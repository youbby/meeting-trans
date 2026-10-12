import numpy as np

from meeting_app.audio import Frame, EchoCleaner, ReferenceBuffer, StreamFramer, RATE, FRAME
from meeting_app.models import SpeakerRegistry, attributed_segments
from meeting_app.session import Session


def test_stereo_resampling_keeps_duration():
    framer = StreamFramer(48000, 2, "MIC")
    rng = np.random.default_rng(1)
    frames = []
    for i in range(100):
        block = rng.normal(0, .05, (960, 2)).astype(np.float32)
        frames.extend(framer.feed(block.tobytes(), i * .02))
    assert 197 <= len(frames) <= 200
    assert all(f.samples.shape == (FRAME,) for f in frames)
    assert abs(frames[-1].time - 1.98) < .05


def test_reference_missing_is_not_silently_used():
    reference = ReferenceBuffer()
    assert reference.aligned(0) is None
    reference.add(Frame("SYSTEM", 1, np.ones(FRAME, np.float32)))
    assert reference.aligned(1.005) is not None
    assert reference.aligned(1.1) is None


def test_aec_reduces_echo_and_keeps_local_speech():
    rng = np.random.default_rng(9)
    far = rng.normal(0, .1, RATE * 10).astype(np.float32)
    mic = np.concatenate([np.zeros(960, np.float32), .6 * far[:-960]])
    cleaner = EchoCleaner(60)
    cleaned = np.concatenate([cleaner.process(mic[i:i+FRAME], far[i:i+FRAME]) for i in range(0, len(mic), FRAME)])
    ratio = np.mean(cleaned[-RATE*3:]**2) / np.mean(mic[-RATE*3:]**2)
    assert ratio < .35, f"Echo not reduced: power ratio={ratio}"
    # With no render reference, real near-end audio must not be globally muted.
    cleaner = EchoCleaner(60)
    local = (.15 * np.sin(2*np.pi*240*np.arange(RATE*2)/RATE)).astype(np.float32)
    cleaned = np.concatenate([cleaner.process(local[i:i+FRAME], np.zeros(FRAME, np.float32)) for i in range(0,len(local),FRAME)])
    assert np.sqrt(np.mean(cleaned[-RATE:]**2)) > .005


def test_same_voice_stays_source_scoped():
    session = Session()
    registry = SpeakerRegistry(session)
    a = np.array([1., 0, 0], np.float32)
    b = np.array([0., 1, 0], np.float32)
    s1 = registry.match("MIC", a, 3)
    s2 = registry.match("MIC", b, 3)
    s3 = registry.match("SYSTEM", a, 3)
    assert len({s1, s2, s3}) == 3
    session.rename(s1, "현장 참석자")
    assert registry.match("MIC", a, 2) == s1
    assert session.speakers[s1].name == "현장 참석자"
    assert registry.match("MIC", b, .2) is None


def test_words_split_at_speaker_boundary_and_overlap_is_explicit():
    rows = [{"id":"test", "words":[{"start":0.,"end":1.,"text":"첫 발언"},{"start":1.1,"end":2.,"text":" 다음 발언"}]}]
    turns = [{"start":0.,"end":1.,"speaker_id":"a"},{"start":1.,"end":2.,"speaker_id":"b"}]
    segments = attributed_segments(rows, turns, "MIC")
    assert [s.speaker_id for s in segments] == ["a", "b"]
    turns.append({"start":1.,"end":2.,"speaker_id":"c"})
    assert attributed_segments(rows, turns, "MIC")[-1].overlap
