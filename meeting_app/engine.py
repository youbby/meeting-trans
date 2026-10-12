from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import queue
import threading
import time
import wave

import numpy as np

from .audio import Capture, Device, EchoCleaner, ReferenceBuffer, UtteranceBuffer, Frame, RATE
from .models import LocalModels, ModelPaths, SpeakerRegistry, initial_segments, attributed_segments
from .session import Session
from . import runtime_log as monitor
from .profiles import PROFILES


@dataclass
class EngineConfig:
    model_root: Path
    session_dir: Path
    microphone: Device | None
    output: Device | None
    mic_enabled: bool = True
    system_enabled: bool = True
    aec_enabled: bool = True
    save_audio: bool = False
    language: str = "ko"
    chunk_seconds: float | None = None
    echo_delay_ms: int = 60
    speaker_threshold: float = .62
    profile: str = "accurate"


class AudioArchive:
    def __init__(self, folder: Path):
        self.folder = folder
        self.streams = {}
        self.positions = {}

    def write(self, frame: Frame):
        if frame.source not in self.streams:
            self.folder.mkdir(parents=True, exist_ok=True)
            stream = wave.open(str(self.folder / f"{frame.source.lower()}.wav"), "wb")
            stream.setnchannels(1)
            stream.setsampwidth(2)
            stream.setframerate(RATE)
            self.streams[frame.source] = stream
            self.positions[frame.source] = 0
        stream = self.streams[frame.source]
        position = self.positions[frame.source]
        target = max(0, round(frame.time * RATE))
        while position < target:
            count = min(target - position, RATE)
            stream.writeframes(bytes(count * 2))
            position += count
        skip = max(0, position - target)
        audio = np.clip(frame.samples[skip:], -1, 1)
        stream.writeframes((audio * 32767).astype("<i2").tobytes())
        self.positions[frame.source] = position + len(audio)

    def close(self):
        for stream in self.streams.values():
            stream.close()


class Engine:
    def __init__(self, session: Session, config: EngineConfig, emit):
        self.session, self.config, self.emit = session, config, emit
        self.stopping = threading.Event()
        self.changed = threading.Event()
        self._control = threading.Lock()
        self._modes = (config.mic_enabled, config.system_enabled, False)
        self.chunks: queue.Queue = queue.Queue(maxsize=120)
        self.epoch = time.monotonic()
        self.thread = None
        self.profile = PROFILES[config.profile]

    def _utterance_buffer(self, source):
        return UtteranceBuffer(source, self.config.chunk_seconds or self.profile.chunk_seconds,
            self.profile.silence_seconds, self.profile.minimum_seconds)

    def start(self):
        monitor.event("session_started", mic=self.config.mic_enabled, system=self.config.system_enabled,
            reference=self.config.aec_enabled, audio_saved=self.config.save_audio, profile=self.config.profile)
        self.thread = threading.Thread(target=self._run, name="local-inference", daemon=False)
        self.thread.start()

    def stop(self):
        monitor.event("stop_requested")
        self.stopping.set()

    def set_modes(self, mic: bool, system: bool, paused: bool):
        with self._control:
            self._modes = (mic, system, paused)
        self.changed.set()

    def modes(self):
        with self._control:
            return self._modes

    def log_event(self, message: str, source=""):
        self.session.event(time.monotonic() - self.epoch, message, source)
        self.emit("notice", message)

    def _enqueue(self, chunk):
        if chunk is None:
            return
        try:
            self.chunks.put_nowait(chunk)
        except queue.Full:
            monitor.event("capture_warning", reason="queue_full", source=chunk.source, queue_depth=self.chunks.qsize())
            self.log_event(f"{chunk.source}: 처리 대기 용량 초과, {chunk.start:.1f}~{chunk.end:.1f}초 전사 누락", chunk.source)

    def _capture(self):
        cap = None
        archive = AudioArchive(self.config.session_dir) if self.config.save_audio else None
        buffers = {}
        pending = deque()
        reference = ReferenceBuffer()
        cleaner = None
        last_levels = 0
        last_health = 0
        last_reference_error = 0
        dropped = 0
        levels = {"MIC": 0.0, "SYSTEM": 0.0}

        def consume(frame):
            if archive:
                archive.write(frame)
            self._enqueue(buffers[frame.source].feed(frame))

        try:
            cap = Capture(self.config.microphone, self.config.output, self.epoch)
            self.changed.set()
            while not self.stopping.is_set():
                if self.changed.is_set():
                    self.changed.clear()
                    for buffer in buffers.values():
                        self._enqueue(buffer.flush())
                    mic, system, paused = self.modes()
                    mic, system = mic and not paused, system and not paused
                    cap.configure(mic, system, self.config.aec_enabled)
                    reference = ReferenceBuffer()
                    pending.clear()
                    cleaner = EchoCleaner(self.config.echo_delay_ms) if mic and self.config.aec_enabled else None
                    buffers = {s: self._utterance_buffer(s) for s in ("MIC", "SYSTEM")}
                    self.log_event("수집 일시정지" if paused else f"수집 설정: 마이크 {'켜짐' if mic else '꺼짐'}, PC 출력 전사 {'켜짐' if system else '꺼짐'}")
                    self.emit("capture", {"mic": mic, "system": system, "reference": bool(cleaner)})
                    monitor.event("capture_state", mic=mic, system=system, reference=bool(cleaner), paused=paused)
                try:
                    frames, status = cap.read(.03)
                except queue.Empty:
                    frames, status = [], 0
                if status:
                    monitor.event("capture_warning", reason="audio_status", status=status)
                    self.log_event(f"오디오 입력 상태 {status}: 일부 구간 손실 가능")
                now = time.monotonic()
                for frame in frames:
                    levels[frame.source] = min(1.0, float(np.sqrt(np.mean(frame.samples ** 2))) * 8)
                    if frame.source == "SYSTEM":
                        if cleaner:
                            reference.add(frame)
                        if system:
                            consume(frame)
                    elif mic:
                        if cleaner:
                            pending.append((frame, now))
                        else:
                            consume(frame)
                while pending:
                    frame, arrived = pending[0]
                    ref = reference.aligned(frame.time)
                    if ref is not None:
                        pending.popleft()
                        consume(Frame("MIC", frame.time, cleaner.process(frame.samples, ref)))
                    elif now - arrived > .35:
                        pending.popleft()
                        if now - last_reference_error > 2:
                            monitor.event("capture_warning", reason="reference_missing", source="MIC")
                            self._enqueue(buffers["MIC"].flush())
                            buffers["MIC"] = self._utterance_buffer("MIC")
                            self.log_event("마이크 처리 공백: 에코 참조 시간 불일치. 장치 선택을 확인해 주세요.", "MIC")
                            self.emit("aec", "출력 참조 확인 필요")
                            last_reference_error = now
                    else:
                        break
                if now - last_levels > .15:
                    self.emit("levels", levels.copy())
                    last_levels = now
                if now - last_health > .5:
                    if not cap.healthy():
                        raise RuntimeError("오디오 장치가 연결 해제되었습니다. 세션을 종료한 뒤 장치를 다시 선택해 주세요.")
                    if cap.drops > dropped:
                        monitor.event("capture_warning", reason="capture_dropped", count=cap.drops - dropped)
                        self.log_event(f"오디오 수집 버퍼 초과: {cap.drops - dropped}블록 손실")
                        dropped = cap.drops
                    last_health = now
            # References arriving before stop are already in the buffer. Never bypass AEC.
            for frame, _ in pending:
                ref = reference.aligned(frame.time)
                if ref is not None and cleaner:
                    consume(Frame("MIC", frame.time, cleaner.process(frame.samples, ref)))
            for buffer in buffers.values():
                self._enqueue(buffer.flush())
        except Exception as exc:
            monitor.failure("capture", exc)
            for buffer in buffers.values():
                self._enqueue(buffer.flush())
            self.log_event(f"수집 오류: {exc}")
            self.emit("error", str(exc))
            self.stopping.set()
        finally:
            if cap:
                cap.close()
            if archive:
                archive.close()
            self.chunks.put(None)

    def _run(self):
        capture_thread = None
        try:
            monitor.event("models_loading")
            model_started = time.monotonic()
            models = LocalModels(ModelPaths.resolve(self.config.model_root, self.profile.model_size),
                lambda message: self.emit("status", message), profile=self.config.profile)
            monitor.event("models_ready", elapsed_seconds=time.monotonic() - model_started)
            if self.stopping.is_set():
                return
            registry = SpeakerRegistry(self.session, self.config.speaker_threshold)
            self.epoch = time.monotonic()
            self.emit("state", "running")
            capture_thread = threading.Thread(target=self._capture, name="audio-capture", daemon=False)
            capture_thread.start()
            while True:
                chunk = self.chunks.get()
                if chunk is None:
                    break
                delay = max(0, time.monotonic() - self.epoch - chunk.end)
                self.emit("lag", {"seconds": delay, "queued": self.chunks.qsize()})
                try:
                    processing_started = time.monotonic()
                    rows = models.transcribe(chunk, self.config.language)
                    for segment in initial_segments(rows, chunk.source):
                        self.session.add_segment(segment)
                    self.emit("updated", None)
                    self.emit("lag", {"seconds": max(0, time.monotonic() - self.epoch - chunk.end),
                        "queued": self.chunks.qsize()})
                    if any(not row.get("review_required") for row in rows):
                        try:
                            turns = models.diarize(chunk, registry)
                            self.session.replace_segments([r["id"] for r in rows], attributed_segments(rows, turns, chunk.source))
                        except Exception as exc:
                            monitor.failure("diarize", exc)
                            self.log_event(f"발화자 분석 실패({chunk.source}): {exc}", chunk.source)
                    self.session.save(self.config.session_dir / "session.json")
                    self.emit("updated", None)
                    monitor.event("chunk_processed", source=chunk.source,
                        duration_seconds=chunk.end - chunk.start,
                        elapsed_seconds=time.monotonic() - processing_started,
                        queue_depth=self.chunks.qsize(), segments=len(rows),
                        lag_seconds=max(0, time.monotonic() - self.epoch - chunk.end))
                except Exception as exc:
                    monitor.failure("transcribe", exc)
                    self.log_event(f"전사 실패({chunk.source}, {chunk.start:.1f}~{chunk.end:.1f}초): {exc}", chunk.source)
        except Exception as exc:
            monitor.failure("models", exc)
            self.emit("error", str(exc))
        finally:
            self.stopping.set()
            if capture_thread:
                # On an inference failure, let capture finish even if its final
                # sentinel is waiting for room in the bounded queue.
                while capture_thread.is_alive():
                    capture_thread.join(timeout=.1)
                    if capture_thread.is_alive():
                        try:
                            self.chunks.get_nowait()
                        except queue.Empty:
                            pass
            self.session.finish()
            try:
                self.session.save(self.config.session_dir / "session.json")
            except Exception as exc:
                monitor.failure("session_save", exc)
                self.emit("error", f"세션 저장 실패: {exc}")
            self.emit("state", "stopped")
            monitor.event("session_stopped")
