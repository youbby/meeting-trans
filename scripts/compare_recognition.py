"""Compare profiles on a local synthetic fixture; no meeting data or network."""
from pathlib import Path
import json
import sys
import time
import re

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from meeting_app.privacy import install_offline_guard, blocked_attempts
install_offline_guard()
from meeting_app.audio import UtteranceBuffer, Frame, RATE, FRAME
from meeting_app.models import LocalModels, ModelPaths
from meeting_app.profiles import PROFILES
from faster_whisper.audio import decode_audio
import numpy as np

REFERENCE = "안녕하세요. 오늘 회의에서는 개발 일정과 검증 결과를 확인하겠습니다. 마이크와 컴퓨터 출력의 음성을 구분하고 회의 기록은 마크다운과 PDF로 저장합니다. 모든 음성 처리는 이 컴퓨터 안에서 이루어집니다."


def cer(reference, predicted):
    norm = lambda s: re.sub(r"[^\w]", "", s).lower()
    a, b = norm(reference), norm(predicted)
    row = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        nxt = [i]
        for j, y in enumerate(b, 1):
            nxt.append(min(nxt[-1] + 1, row[j] + 1, row[j - 1] + (x != y)))
        row = nxt
    return round(row[-1] / max(1, len(a)), 4)


audio = decode_audio(str(ROOT / "tmp/fixtures/korean.wav"), sampling_rate=RATE)
audio = np.pad(audio, (0, RATE))
report = {}
for key in ("fast", "accurate"):
    profile = PROFILES[key]
    model = LocalModels(ModelPaths.resolve(ROOT / "models", profile.model_size), profile=key)
    buffer = UtteranceBuffer("SYSTEM", profile.chunk_seconds, profile.silence_seconds, profile.minimum_seconds)
    chunks = []
    for i in range(0, len(audio) - FRAME + 1, FRAME):
        chunk = buffer.feed(Frame("SYSTEM", i / RATE, audio[i:i+FRAME]))
        if chunk:
            chunks.append(chunk)
    last = buffer.flush()
    if last:
        chunks.append(last)
    start = time.monotonic()
    texts = []
    per_chunk = []
    for chunk in chunks:
        t = time.monotonic()
        rows = model.transcribe(chunk, "ko")
        texts.extend("".join(w["text"] for w in row["words"]).strip() for row in rows)
        per_chunk.append({"start": round(chunk.start, 2), "audio_seconds": round(chunk.end-chunk.start, 2), "processing_seconds": round(time.monotonic()-t, 2)})
    output = " ".join(texts)
    report[key] = {"text": output, "cer": cer(REFERENCE, output), "processing_seconds": round(time.monotonic()-start, 2), "chunks": per_chunk}
    print(json.dumps({key: report[key]}, ensure_ascii=False), flush=True)
    del model
assert not blocked_attempts
folder = ROOT / "output/recognition-comparison"
folder.mkdir(parents=True, exist_ok=True)
(folder / "comparison.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
