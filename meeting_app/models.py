from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import uuid

import numpy as np

from .audio import AudioChunk, RATE
from .privacy import configure_onnx_privacy
from .session import Session, Segment


def local_path(value: str | Path) -> Path:
    value = str(value)
    if value.startswith(("\\\\", "//")) or "://" in value:
        raise ValueError("네트워크 경로 대신 PC의 로컬 폴더를 선택해 주세요.")
    path = Path(value).expanduser().resolve()
    if os.name == "nt":
        import ctypes
        if ctypes.windll.kernel32.GetDriveTypeW(str(path.anchor)) == 4:
            raise ValueError("네트워크 드라이브는 사용할 수 없습니다.")
    return path


@dataclass
class ModelPaths:
    root: Path
    whisper: Path
    segmentation: Path
    embedding: Path

    @classmethod
    def resolve(cls, root: Path):
        root = local_path(root)
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            raise FileNotFoundError("로컬 모델이 없습니다. 먼저 모델 준비 도구를 실행하거나 준비된 models 폴더를 선택해 주세요.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        whisper = local_path(root / manifest["whisper"])
        if not whisper.is_relative_to(root):
            raise ValueError("모델 경로가 models 폴더 밖에 있습니다.")
        embedding = local_path(root / manifest.get("embedding", "speaker/embedding.onnx"))
        if not embedding.is_relative_to(root):
            raise ValueError("발화자 모델이 models 폴더 밖에 있습니다.")
        result = cls(root, whisper, root / "speaker/segmentation.onnx", embedding)
        if not any((whisper / name).is_file() for name in ("vocabulary.txt", "vocabulary.json")):
            raise FileNotFoundError("음성 인식 어휘 파일이 없습니다. 모델 준비 도구를 다시 실행해 주세요.")
        for path in (whisper / "model.bin", whisper / "config.json", whisper / "tokenizer.json", result.segmentation, result.embedding):
            if not path.is_file() or path.stat().st_size == 0:
                raise FileNotFoundError(f"모델 파일이 없습니다: {path.name}")
            item = manifest.get("files", {}).get(path.relative_to(root).as_posix())
            if item and path.stat().st_size != item["bytes"]:
                raise ValueError(f"불완전한 모델 파일입니다: {path.name}")
        return result


class SpeakerRegistry:
    """Source-scoped online centroids; names belong to Session, not clusters."""
    def __init__(self, session: Session, threshold=.62):
        self.session, self.threshold = session, threshold
        self.centroids: dict[str, np.ndarray] = {}

    def match(self, source: str, embedding: np.ndarray, duration: float, exclude=()) -> str | None:
        embedding = np.asarray(embedding, dtype=np.float32)
        norm = np.linalg.norm(embedding)
        if duration < .8 or norm < 1e-6 or not np.isfinite(embedding).all():
            return None
        embedding = embedding / norm
        candidates = [(float(np.dot(embedding, center)), sid) for sid, center in self.centroids.items()
            if self.session.speakers[sid].source == source and sid not in exclude]
        candidates.sort(reverse=True)
        if candidates and candidates[0][0] >= self.threshold:
            if len(candidates) > 1 and candidates[0][0] - candidates[1][0] < .035:
                return None
            score, sid = candidates[0]
            if duration >= 1.5 and score >= self.threshold + .04:
                center = .9 * self.centroids[sid] + .1 * embedding
                self.centroids[sid] = center / np.linalg.norm(center)
            return sid
        if duration < 1.25:
            return None
        sid = self.session.add_speaker(source)
        self.centroids[sid] = embedding
        return sid


class LocalModels:
    def __init__(self, paths: ModelPaths, notify=lambda _: None, threads=4):
        configure_onnx_privacy()
        notify("음성 인식 모델을 불러오는 중")
        from faster_whisper import WhisperModel
        self.asr = WhisperModel(str(paths.whisper), device="cpu", compute_type="int8",
            cpu_threads=threads, num_workers=1, local_files_only=True)
        notify("발화자 모델을 불러오는 중")
        import sherpa_onnx as s
        ec = s.SpeakerEmbeddingExtractorConfig(model=str(paths.embedding), num_threads=2, provider="cpu")
        dc = s.OfflineSpeakerDiarizationConfig(
            segmentation=s.OfflineSpeakerSegmentationModelConfig(
                pyannote=s.OfflineSpeakerSegmentationPyannoteModelConfig(model=str(paths.segmentation), window_shift_ratio=.5),
                num_threads=2, provider="cpu"),
            embedding=ec,
            clustering=s.FastClusteringConfig(num_clusters=-1, threshold=.65),
            min_duration_on=.2, min_duration_off=.3)
        if not ec.validate() or not dc.validate():
            raise ValueError("발화자 모델을 확인해 주세요.")
        self.diarizer = s.OfflineSpeakerDiarization(dc)
        self.extractor = s.SpeakerEmbeddingExtractor(ec)
        notify("로컬 모델 준비 완료")

    def transcribe(self, chunk: AudioChunk, language="ko") -> list[dict]:
        result, _ = self.asr.transcribe(chunk.samples, language=language or None,
            beam_size=1, best_of=1, word_timestamps=True, condition_on_previous_text=False,
            temperature=0.0,
            vad_filter=True, vad_parameters={"min_silence_duration_ms": 300},
            no_speech_threshold=.6, compression_ratio_threshold=2.4)
        rows = []
        for segment in result:
            words = [{"start": chunk.start + w.start, "end": chunk.start + w.end, "text": w.word}
                for w in (segment.words or []) if chunk.start + (w.start + w.end) / 2 >= chunk.commit_from]
            if not words and chunk.start + (segment.start + segment.end) / 2 >= chunk.commit_from:
                words = [{"start": chunk.start + segment.start, "end": chunk.start + segment.end, "text": segment.text}]
            if not words or not "".join(w["text"] for w in words).strip():
                continue
            rows.append({"id": uuid.uuid4().hex, "words": words})
        return rows

    def diarize(self, chunk: AudioChunk, registry: SpeakerRegistry) -> list[dict]:
        turns = self.diarizer.process(np.ascontiguousarray(chunk.samples)).sort_by_start_time()
        local_speakers = sorted({turn.speaker for turn in turns})
        mapping, used = {}, set()
        for speaker in local_speakers:
            # Exclude overlap when building the voice reference.
            pieces = []
            for turn in turns:
                if turn.speaker != speaker:
                    continue
                if any(other.speaker != speaker and min(turn.end, other.end) > max(turn.start, other.start) for other in turns):
                    continue
                pieces.append(chunk.samples[int(turn.start * RATE):int(turn.end * RATE)])
            audio = np.concatenate(pieces) if pieces else np.empty(0, np.float32)
            sid = None
            if len(audio) >= int(.8 * RATE):
                stream = self.extractor.create_stream()
                stream.accept_waveform(sample_rate=RATE, waveform=audio)
                stream.input_finished()
                if self.extractor.is_ready(stream):
                    sid = registry.match(chunk.source, np.array(self.extractor.compute(stream)), len(audio) / RATE, used)
            mapping[speaker] = sid
            if sid:
                used.add(sid)
        return [{"start": chunk.start + t.start, "end": chunk.start + t.end, "speaker_id": mapping[t.speaker]} for t in turns]


def initial_segments(rows: list[dict], source: str) -> list[Segment]:
    return [Segment(r["id"], r["words"][0]["start"], r["words"][-1]["end"], source,
        "".join(w["text"] for w in r["words"]).strip()) for r in rows]


def attributed_segments(rows: list[dict], turns: list[dict], source: str) -> list[Segment]:
    output = []
    for row in rows:
        groups = []
        for word in row["words"]:
            mid = (word["start"] + word["end"]) / 2
            active = [t for t in turns if t["start"] <= mid <= t["end"]]
            # Boundaries in diarization and ASR differ slightly; only a close turn is usable.
            if not active and turns:
                nearest = min(turns, key=lambda t: min(abs(mid - t["start"]), abs(mid - t["end"])))
                if min(abs(mid - nearest["start"]), abs(mid - nearest["end"])) < .25:
                    active = [nearest]
            overlap = len(active) > 1
            sid = active[0]["speaker_id"] if len(active) == 1 else None
            key = (sid, overlap)
            if groups and groups[-1][0] == key:
                groups[-1][1].append(word)
            else:
                groups.append((key, [word]))
        for i, ((sid, overlap), words) in enumerate(groups):
            status = "겹친 발언" if overlap else ("분류됨" if sid else "발화자 미확정")
            output.append(Segment(f"{row['id']}_{i}", words[0]["start"], words[-1]["end"], source,
                "".join(w["text"] for w in words).strip(), sid, status, overlap))
    return output
