"""Run real AEC/ASR/diarization/export using fixture capture, never a physical mic."""
from pathlib import Path
import json
import queue
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from meeting_app.privacy import install_offline_guard, blocked_attempts
install_offline_guard()
import numpy as np
from faster_whisper.audio import decode_audio
from meeting_app.audio import Frame, RATE, FRAME
import meeting_app.engine as engine_module
from meeting_app.engine import Engine, EngineConfig
from meeting_app.session import Session
from meeting_app.export import export_session

local = decode_audio(str(ROOT / "tmp/fixtures/korean.wav"), sampling_rate=RATE)
remote = decode_audio(str(ROOT / "tmp/fixtures/jfk.wav"), sampling_rate=RATE)
length = int((max(len(local), len(remote)) / RATE + 2) * RATE)
far = np.pad(remote, (0, length - len(remote)))
near = np.pad(local, (0, length - len(local)))
echo = np.concatenate([np.zeros(960, np.float32), far[:-960]]) * .35
mic_audio = np.clip(near + echo, -.99, .99)


class FixtureCapture:
    def __init__(self, *args):
        self.index = 0
        self.drops = 0
        self.enabled = (True, True, True)

    def configure(self, mic, system, aec):
        self.enabled = mic, system, aec

    def read(self, timeout=.03):
        if self.index + FRAME > length:
            engine.stopping.set()
            raise queue.Empty
        i = self.index
        self.index += FRAME
        mic, system, aec = self.enabled
        frames = []
        if system or (mic and aec):
            frames.append(Frame("SYSTEM", i / RATE, far[i:i+FRAME]))
        if mic:
            frames.append(Frame("MIC", i / RATE, mic_audio[i:i+FRAME]))
        return frames, 0

    def healthy(self):
        return True

    def close(self):
        pass


engine_module.Capture = FixtureCapture
timings = []
for method_name in ("transcribe", "diarize"):
    original = getattr(engine_module.LocalModels, method_name)
    def measured(self, chunk, *args, _method=original, _name=method_name):
        started = time.monotonic()
        result = _method(self, chunk, *args)
        timings.append({"stage": _name, "source": chunk.source, "duration": round(chunk.end-chunk.start, 2),
            "seconds": round(time.monotonic()-started, 2)})
        return result
    setattr(engine_module.LocalModels, method_name, measured)
events = []
folder = ROOT / "output/pipeline-verification"
session = Session("실제 모델 통합 검증 · 합성 입력")
config = EngineConfig(ROOT / "models", folder, None, None, language="", save_audio=False)
engine = Engine(session, config, lambda kind, value: events.append((kind, value)))
start = time.monotonic()
engine.start()
engine.thread.join(timeout=180)
assert not engine.thread.is_alive(), "Pipeline did not finish"
assert not [e for e in events if e[0] == "error"], events
data = session.snapshot()
assert {s["source"] for s in data["segments"]} == {"MIC", "SYSTEM"}
assert {s["source"] for s in data["speakers"]} == {"MIC", "SYSTEM"}
assert not blocked_attempts
assert not list(folder.glob("*.wav")), "Audio retained despite save_audio=False"
md, pdf, error = export_session(data, folder)
assert pdf and not error
report = {"seconds":round(time.monotonic()-start,2),"audio_seconds":round(length/RATE,2),
    "speakers":data["speakers"],"segments":len(data["segments"]),"events":data["events"],
    "network_attempts":len(blocked_attempts),"timings":timings,"md":str(md),"pdf":str(pdf)}
(folder / "verification.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(report,ensure_ascii=False,indent=2))
