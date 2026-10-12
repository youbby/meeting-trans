from dataclasses import dataclass


@dataclass(frozen=True)
class RecognitionProfile:
    label: str
    model_size: str
    beam_size: int
    chunk_seconds: float
    silence_seconds: float
    minimum_seconds: float


PROFILES = {
    "accurate": RecognitionProfile("정확도 우선", "small", 5, 12.0, .8, 3.0),
    "fast": RecognitionProfile("속도 우선", "base", 1, 6.0, .55, 0.0),
}
