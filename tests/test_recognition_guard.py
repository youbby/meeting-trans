import json
from types import SimpleNamespace as Obj

import numpy as np
import pytest

from meeting_app.audio import AudioChunk, RATE
from meeting_app.models import LocalModels, initial_segments, attributed_segments
from meeting_app.profiles import PROFILES
from meeting_app.recognition_guard import has_repetition_loop, REVIEW_TEXT, REVIEW_STATUS
from meeting_app.session import Session
from meeting_app.export import markdown, export_session
from meeting_app import runtime_log


@pytest.mark.parametrize("text", ["자, " * 100, "다음 항목 " * 15, "안내입니다. " + "자, " * 20,
    "가나다라마바사 " * 12, "자" * 70])
def test_detects_extended_loops(text):
    assert has_repetition_loop(text)


@pytest.mark.parametrize("text", ["자, 자, 자, 이제 시작합시다.", "네, 네, 네, 알겠습니다.",
    "다시 확인하고 다시 검토하고 다시 정리하겠습니다.", "", "이 회의는 다음 주에도 계속됩니다."])
def test_preserves_ordinary_repetition(text):
    assert not has_repetition_loop(text)


def segment(text, start=0, end=4, confidence=-.2):
    return Obj(text=text, start=start, end=end, avg_logprob=confidence, no_speech_prob=.05,
        words=[Obj(start=start, end=end, word=text)])


class StubRecognizer:
    def __init__(self, batches):
        self.batches = iter(batches)
        self.calls = []
    def transcribe(self, samples, **kwargs):
        self.calls.append(kwargs)
        result = next(self.batches)
        if isinstance(result, Exception):
            raise result
        return iter(result), None


def model(batches):
    obj = LocalModels.__new__(LocalModels)
    obj.profile = PROFILES["accurate"]
    obj.asr = StubRecognizer(batches)
    return obj


def chunk():
    return AudioChunk("SYSTEM", 10, np.zeros(RATE * 12, np.float32), 10)


def test_retry_recovers_and_preserves_good_original_segment():
    recognizer = model([[segment("정상 발언", 0, 3), segment("자, " * 50, 4, 8)],
        [segment("재시도로 바뀐 다른 발언", 0, 3), segment("일정을 확인하겠습니다.", 4, 8)]])
    rows = recognizer.transcribe(chunk())
    assert rows[0]["words"][0]["text"] == "정상 발언"
    assert rows[1]["words"][0]["text"] == "일정을 확인하겠습니다."
    assert rows[1]["reprocessed"]
    assert len(recognizer.asr.calls) == 2
    assert recognizer.asr.calls[1]["no_repeat_ngram_size"] > 0
    segments = attributed_segments(rows, [{"start": 10, "end": 22, "speaker_id": "a"}], "SYSTEM")
    assert segments[-1].status.startswith("재인식")


@pytest.mark.parametrize("retry", [[segment("자, " * 40)], [],
    [segment("검증되지 않은 문장", confidence=-1.8)], RuntimeError("PRIVATE-CONVERSATION")])
def test_retry_failure_is_visible_and_never_attributed_to_speaker(retry):
    recognizer = model([[segment("자, " * 50)], retry])
    rows = recognizer.transcribe(chunk())
    assert len(recognizer.asr.calls) == 2
    segments = attributed_segments(rows, [{"start": 10, "end": 22, "speaker_id": "a"}], "SYSTEM")
    assert len(segments) == 1
    assert segments[0].status == REVIEW_STATUS
    assert segments[0].speaker_id is None
    assert segments[0].text == REVIEW_TEXT
    assert segments[0].source == "SYSTEM"
    assert segments[0].start == 10 and segments[0].end == 14
    session = Session()
    session.add_segment(segments[0])
    assert REVIEW_STATUS in markdown(session.snapshot())


def test_good_result_has_no_retry():
    recognizer = model([[segment("자, 자, 시작하겠습니다.")]])
    rows = recognizer.transcribe(chunk())
    assert len(recognizer.asr.calls) == 1
    assert initial_segments(rows, "SYSTEM")[0].text == "자, 자, 시작하겠습니다."


def test_repetition_across_decoder_segments_is_rejected():
    repeated = [segment("자, ", i * .3, (i + 1) * .3) for i in range(20)]
    recognizer = model([repeated, repeated])
    rows = recognizer.transcribe(chunk())
    assert all(row.get("review_required") for row in rows)
    assert len(rows) == 1


def test_review_marker_survives_session_and_pdf_export(tmp_path):
    from pypdf import PdfReader
    recognizer = model([[segment("자, " * 40)], []])
    session = Session("반복 출력 검증")
    session.add_segment(initial_segments(recognizer.transcribe(chunk()), "SYSTEM")[0])
    session.save(tmp_path / "session.json")
    loaded = Session.load(tmp_path / "session.json")
    md, pdf, error = export_session(loaded.snapshot(), tmp_path)
    assert not error and pdf
    assert REVIEW_STATUS in md.read_text(encoding="utf-8")
    text = "".join(page.extract_text() for page in PdfReader(pdf).pages)
    assert REVIEW_STATUS in text and "SYSTEM" in text
    assert "자, 자, 자" not in text


def test_retry_logs_only_status_not_candidate_text(tmp_path):
    secret = "고객기밀"
    log = runtime_log.start(tmp_path)
    try:
        recognizer = model([[segment((secret + ", ") * 30)], [segment((secret + ", ") * 30)]])
        recognizer.transcribe(chunk())
    finally:
        runtime_log.finish()
    raw = log.read_text(encoding="utf-8")
    assert secret not in raw and "text" not in raw
    events = [json.loads(line)["event"] for line in raw.splitlines()]
    assert "recognition_retry" in events and "recognition_rejected" in events
