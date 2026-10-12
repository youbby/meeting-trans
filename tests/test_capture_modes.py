"""Privacy-critical routing tests using real capture controller, no devices."""
import queue
import numpy as np
import pytest

from meeting_app.audio import Frame, FRAME, AudioChunk
from meeting_app.engine import Engine, EngineConfig
from meeting_app.session import Session
import meeting_app.engine as module


@pytest.mark.parametrize("mic,system,aec,expected", [
    (True, False, True, {"MIC"}),
    (False, True, True, {"SYSTEM"}),
    (True, True, True, {"MIC", "SYSTEM"}),
    (False, False, True, set()),
])
def test_capture_routing_and_archive(tmp_path, monkeypatch, mic, system, aec, expected):
    archived = []
    cleaned = []

    class Capture:
        drops = 0
        def __init__(self, *args):
            self.count = 0
        def configure(self, m, s, a):
            assert (m, s, a) == (mic, system, aec)
        def read(self, timeout):
            self.count += 1
            if self.count > 1:
                engine.stop()
                raise queue.Empty
            frames = []
            if system or (mic and aec):
                frames.append(Frame("SYSTEM", 0, np.ones(FRAME, np.float32)))
            if mic:
                frames.append(Frame("MIC", 0, np.full(FRAME, 2, np.float32)))
            return frames, 0
        def healthy(self):
            return True
        def close(self):
            pass

    class Cleaner:
        def __init__(self, *args):
            pass
        def process(self, audio, reference):
            cleaned.append(True)
            return audio * .1

    class Buffer:
        def __init__(self, source, *args):
            self.source = source
        def feed(self, frame):
            return AudioChunk(frame.source, frame.time, frame.samples, 0)
        def flush(self):
            return None

    class Archive:
        def __init__(self, *args):
            pass
        def write(self, frame):
            archived.append(frame)
        def close(self):
            pass

    for name, fake in [("Capture", Capture), ("EchoCleaner", Cleaner), ("UtteranceBuffer", Buffer), ("AudioArchive", Archive)]:
        monkeypatch.setattr(module, name, fake)
    engine = Engine(Session(), EngineConfig(tmp_path, tmp_path, None, None,
        mic_enabled=mic, system_enabled=system, aec_enabled=aec, save_audio=True), lambda *args: None)
    engine._capture()
    chunks = list(engine.chunks.queue)
    assert chunks[-1] is None
    assert {chunk.source for chunk in chunks[:-1]} == expected
    assert {frame.source for frame in archived} == expected
    assert bool(cleaned) == mic
    for frame in archived:
        if frame.source == "MIC":
            assert np.allclose(frame.samples, .2), "Raw microphone audio was archived"
