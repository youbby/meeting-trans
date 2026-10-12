"""Offline integration check with public or locally synthesized test fixtures."""
from pathlib import Path
import sys
import time
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from meeting_app.privacy import install_offline_guard, blocked_attempts
install_offline_guard()
from meeting_app.models import LocalModels, ModelPaths, SpeakerRegistry, initial_segments, attributed_segments
from meeting_app.audio import AudioChunk, RATE
from meeting_app.session import Session
from faster_whisper.audio import decode_audio

start = time.monotonic()
models = LocalModels(ModelPaths.resolve(ROOT / "models"), print)
report = {"load_seconds": round(time.monotonic() - start, 2), "cases": []}
session = Session("오프라인 모델 검증")
registry = SpeakerRegistry(session)
for name, language, source in [("jfk.wav", "en", "SYSTEM"), ("korean.wav", "ko", "MIC"), ("four-speakers.wav", "zh", "SYSTEM")]:
    path = ROOT / "tmp/fixtures" / name
    if not path.exists():
        continue
    audio = decode_audio(str(path), sampling_rate=RATE)
    # Longer sample is used for diarization; avoid unnecessary ASR on it.
    chunk = AudioChunk(source, 0, audio, 0)
    begin = time.monotonic()
    rows = [] if name == "four-speakers.wav" else models.transcribe(chunk, language)
    turns = models.diarize(chunk, registry)
    texts = [s.text for s in attributed_segments(rows, turns, source)]
    result = {"file":name,"duration":round(len(audio)/RATE,2),"processing_seconds":round(time.monotonic()-begin,2),
        "text":texts,"speaker_ids":sorted({t['speaker_id'] for t in turns if t['speaker_id']}),"turns":len(turns)}
    report["cases"].append(result)
    print(json.dumps(result, ensure_ascii=False), flush=True)
report["blocked_network_attempts"] = blocked_attempts
(ROOT / "tmp/model-verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
assert not blocked_attempts
assert report["cases"] and report["cases"][0]["text"]
print("Offline integration check completed.")
