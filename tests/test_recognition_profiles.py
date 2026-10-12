import json
import numpy as np
import pytest

from meeting_app.audio import Frame, FRAME, UtteranceBuffer
from meeting_app.models import ModelPaths


@pytest.fixture
def voice_detector(monkeypatch):
    import pywebrtc_audio
    class Detector:
        def __init__(self, **kwargs):
            pass
        def process(self, samples):
            return .9 if samples[0] > .01 else 0
    monkeypatch.setattr(pywebrtc_audio, "VoiceDetector", Detector)


def test_short_pause_keeps_sentence_context(voice_detector):
    buffer = UtteranceBuffer("SYSTEM", 12, .8, 3)
    # 0.5s voice, 0.6s pause, 0.5s continuation, 1.5s silence.
    chunks = []
    for i in range(310):
        voiced = i < 50 or 110 <= i < 160
        chunk = buffer.feed(Frame("SYSTEM", i / 100, np.full(FRAME, .1 if voiced else 0, np.float32)))
        if chunk:
            chunks.append(chunk)
    assert len(chunks) == 1
    assert chunks[0].start == 0
    assert chunks[0].end >= 3
    assert np.count_nonzero(chunks[0].samples) == 100 * FRAME


def test_end_of_recording_preserves_short_utterance(voice_detector):
    buffer = UtteranceBuffer("SYSTEM", 12, .8, 3)
    for i in range(40):
        assert buffer.feed(Frame("SYSTEM", i / 100, np.full(FRAME, .1, np.float32))) is None
    chunk = buffer.flush()
    assert chunk is not None and chunk.end == pytest.approx(.4)
    assert buffer.flush() is None


def test_late_voice_detection_preserves_initial_syllables(monkeypatch):
    import pywebrtc_audio
    class LateDetector:
        def __init__(self, **kwargs):
            self.frames = 0
        def process(self, samples):
            self.frames += 1
            return .9 if self.frames > 70 else 0
    monkeypatch.setattr(pywebrtc_audio, "VoiceDetector", LateDetector)
    buffer = UtteranceBuffer("SYSTEM", 12, .8, 3)
    for i in range(150):
        buffer.feed(Frame("SYSTEM", i / 100, np.full(FRAME, .1, np.float32)))
    chunk = buffer.flush()
    assert chunk.start == 0
    assert len(chunk.samples) == 150 * FRAME


def test_continuous_speech_still_has_bounded_latency(voice_detector):
    buffer = UtteranceBuffer("SYSTEM", 12, .8, 3)
    chunks = []
    for i in range(1300):
        chunk = buffer.feed(Frame("SYSTEM", i / 100, np.full(FRAME, .1, np.float32)))
        if chunk:
            chunks.append(chunk)
    assert len(chunks) == 1 and chunks[0].end == pytest.approx(12)
    last = buffer.flush()
    assert last.start < chunks[0].end and last.end == pytest.approx(13)


def test_accuracy_model_missing_never_silently_uses_fast_model(tmp_path):
    (tmp_path / "manifest.json").write_text(json.dumps({"whisper": "whisper-base"}), encoding="utf-8")
    (tmp_path / "whisper-base").mkdir()
    for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
        (tmp_path / "whisper-base" / name).write_text("fixture", encoding="utf-8")
    (tmp_path / "speaker").mkdir()
    for name in ("segmentation.onnx", "embedding.onnx"):
        (tmp_path / "speaker" / name).write_text("fixture", encoding="utf-8")
    assert ModelPaths.resolve(tmp_path, "base").whisper.name == "whisper-base"
    with pytest.raises(FileNotFoundError):
        ModelPaths.resolve(tmp_path, "small")
