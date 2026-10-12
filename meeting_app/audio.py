"""WASAPI capture, streaming resampling and echo-reference alignment."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import queue
import threading
import time

import numpy as np
import soxr

RATE = 16000
FRAME = 160  # 10 ms


@dataclass
class Device:
    index: int
    name: str
    rate: int
    channels: int
    loopback_index: int | None = None


def list_devices() -> tuple[list[Device], list[Device]]:
    import pyaudiowpatch as pa
    mics, outputs = [], []
    with pa.PyAudio() as p:
        try:
            host = p.get_host_api_info_by_type(pa.paWASAPI)["index"]
        except OSError:
            return mics, outputs
        for i in range(p.get_device_count()):
            d = p.get_device_info_by_index(i)
            if d["hostApi"] != host or d.get("isLoopbackDevice"):
                continue
            if d["maxInputChannels"]:
                mics.append(Device(i, d["name"], int(d["defaultSampleRate"]), int(d["maxInputChannels"])))
            if d["maxOutputChannels"]:
                try:
                    loop = p.get_wasapi_loopback_analogue_by_dict(d)
                    outputs.append(Device(i, d["name"], int(loop["defaultSampleRate"]), int(loop["maxInputChannels"]), int(loop["index"])))
                except (LookupError, OSError):
                    pass
    return mics, outputs


@dataclass
class Frame:
    source: str
    time: float
    samples: np.ndarray


class StreamFramer:
    def __init__(self, rate: int, channels: int, source: str):
        self.rate, self.channels, self.source = rate, channels, source
        self.converter = soxr.ResampleStream(rate, RATE, 1, dtype="float32", quality="LQ") if rate != RATE else None
        self.pending = np.empty(0, dtype=np.float32)
        self.origin = None
        self.count = 0

    def feed(self, data: bytes, start: float) -> list[Frame]:
        if self.origin is None:
            self.origin = start
        mono = np.frombuffer(data, dtype=np.float32).reshape(-1, self.channels).mean(axis=1)
        samples = self.converter.resample_chunk(mono) if self.converter else mono
        self.pending = np.concatenate((self.pending, samples))
        result = []
        while len(self.pending) >= FRAME:
            # Calibrate slowly to callback timestamps, allowing independent device clocks.
            result.append(Frame(self.source, self.origin + self.count / RATE, self.pending[:FRAME].copy()))
            self.pending = self.pending[FRAME:]
            self.count += FRAME
        observed_end = start + len(mono) / self.rate
        estimated_end = self.origin + (self.count + len(self.pending)) / RATE
        if self.converter:
            estimated_end += self.converter.delay() / RATE
        drift = observed_end - estimated_end
        if abs(drift) < .1:
            self.origin += drift * .002
        return result


class ReferenceBuffer:
    def __init__(self):
        self.frames: deque[Frame] = deque(maxlen=600)

    def add(self, frame: Frame):
        self.frames.append(frame)

    def aligned(self, timestamp: float) -> np.ndarray | None:
        if not self.frames:
            return None
        best = min(self.frames, key=lambda f: abs(f.time - timestamp))
        if abs(best.time - timestamp) > .018:
            return None
        return best.samples


class EchoCleaner:
    def __init__(self, delay_ms: int = 60):
        from pywebrtc_audio import AudioProcessor
        self.processor = AudioProcessor(sample_rate=RATE, echo_cancellation=True,
            noise_suppression=True, ns_level=1, auto_gain_control=False,
            stream_delay_ms=delay_ms)

    def process(self, mic: np.ndarray, reference: np.ndarray) -> np.ndarray:
        return np.asarray(self.processor.process(np.ascontiguousarray(mic, dtype=np.float32),
            np.ascontiguousarray(reference, dtype=np.float32)), dtype=np.float32)


class Capture:
    """Opened/closed by the controller worker; callbacks do no model inference."""
    def __init__(self, microphone: Device | None, output: Device | None, epoch: float):
        import pyaudiowpatch as pa
        self.pa = pa
        self.p = pa.PyAudio()
        self.microphone, self.output, self.epoch = microphone, output, epoch
        self.queue: queue.Queue = queue.Queue(maxsize=1000)
        self.streams = []
        self.drops = 0
        self._generation = 0
        self._lock = threading.Lock()

    def _callback(self, source: str, rate: int, generation: int):
        def callback(data, frames, info, status):
            now = time.monotonic()
            adc = info.get("input_buffer_adc_time", 0)
            current = info.get("current_time", 0)
            delta = adc - current
            start = now + delta if adc and current and -.5 < delta < .1 else now - frames / rate
            try:
                self.queue.put_nowait((generation, source, start - self.epoch, data, status))
            except queue.Full:
                self.drops += 1
            return (None, self.pa.paContinue)
        return callback

    def configure(self, mic: bool, system: bool, aec: bool):
        self.close_streams()
        self._generation += 1
        while not self.queue.empty():
            try:
                self.queue.get_nowait()
            except queue.Empty:
                break
        self.framers = {}
        try:
            if system or (mic and aec):
                d = self.output
                if d is None:
                    raise RuntimeError("PC 출력 장치를 선택해 주세요. 에코 제거에도 출력 참조가 필요합니다.")
                # Keep a WASAPI render stream alive with silence so loopback delivers
                # continuous reference frames even when no app is playing sound.
                output_info = self.p.get_device_info_by_index(d.index)
                out_channels = int(output_info["maxOutputChannels"])
                silence = lambda data, n, info, status: (bytes(n * out_channels * 4), self.pa.paContinue)
                keepalive = self.p.open(format=self.pa.paFloat32, channels=out_channels,
                    rate=d.rate, output=True, output_device_index=d.index,
                    frames_per_buffer=int(d.rate * .02), stream_callback=silence)
                self.streams.append(keepalive)
                self._open("SYSTEM", d, d.loopback_index)
            if mic:
                if self.microphone is None:
                    raise RuntimeError("마이크 장치를 선택해 주세요.")
                self._open("MIC", self.microphone, self.microphone.index)
        except Exception:
            self.close_streams()
            raise

    def _open(self, source, device, index):
        self.framers[source] = StreamFramer(device.rate, device.channels, source)
        stream = self.p.open(format=self.pa.paFloat32, channels=device.channels,
            rate=device.rate, input=True, input_device_index=index,
            frames_per_buffer=int(device.rate * .02),
            stream_callback=self._callback(source, device.rate, self._generation))
        self.streams.append(stream)

    def read(self, timeout=.03) -> tuple[list[Frame], int]:
        generation, source, start, data, status = self.queue.get(timeout=timeout)
        if generation != self._generation:
            return [], 0
        return self.framers[source].feed(data, start), status

    def healthy(self):
        return all(stream.is_active() for stream in self.streams)

    def close_streams(self):
        for stream in reversed(self.streams):
            try:
                stream.stop_stream()
            except OSError:
                pass
            try:
                stream.close()
            except OSError:
                pass
        self.streams.clear()

    def close(self):
        self.close_streams()
        self.p.terminate()


@dataclass
class AudioChunk:
    source: str
    start: float
    samples: np.ndarray
    commit_from: float

    @property
    def end(self):
        return self.start + len(self.samples) / RATE


class UtteranceBuffer:
    def __init__(self, source: str, max_seconds=6.0, silence_seconds=.55, minimum_seconds=0.0):
        from pywebrtc_audio import VoiceDetector
        self.source = source
        self.vad = VoiceDetector(sample_rate=RATE)
        # VAD often recognizes speech after its first quiet syllable. Keep enough
        # lead-in audio to restore that onset instead of making ASR guess it.
        self.pre: deque[Frame] = deque(maxlen=80)
        self.active: list[Frame] = []
        self.silence = 0
        self.voiced = 0
        self.max_frames = int(max_seconds * 100)
        self.silence_frames = round(silence_seconds * 100)
        self.minimum_frames = round(minimum_seconds * 100)
        self.committed = 0.0

    def feed(self, frame: Frame) -> AudioChunk | None:
        power = float(np.sqrt(np.mean(frame.samples ** 2)))
        voiced = power > .001 and self.vad.process(frame.samples) > .45
        if not self.active:
            self.pre.append(frame)
            if voiced:
                self.active = list(self.pre)
                self.pre.clear()
                self.voiced = 1
                self.silence = 0
            return None
        self.active.append(frame)
        self.voiced += int(voiced)
        self.silence = 0 if voiced else self.silence + 1
        if (self.silence >= self.silence_frames and len(self.active) >= self.minimum_frames) or len(self.active) >= self.max_frames:
            return self.flush(keep_overlap=self.silence < self.silence_frames)
        return None

    def flush(self, keep_overlap=False) -> AudioChunk | None:
        if not self.active:
            return None
        frames = self.active
        valid = self.voiced >= 12
        self.active = frames[-30:] if keep_overlap else []
        self.voiced = 0
        self.silence = 0
        if not valid:
            return None
        chunk = AudioChunk(self.source, frames[0].time, np.concatenate([f.samples for f in frames]), self.committed)
        self.committed = chunk.end - .15 if keep_overlap else chunk.end
        return chunk
