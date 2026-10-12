from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, asdict, field
from datetime import datetime
import json
import os
from pathlib import Path
import threading
import uuid

SOURCES = {"MIC": "마이크", "SYSTEM": "PC 출력"}


@dataclass
class Speaker:
    id: str
    name: str
    source: str


@dataclass
class Segment:
    id: str
    start: float
    end: float
    source: str
    text: str
    speaker_id: str | None = None
    status: str = "발화자 확인 중"
    overlap: bool = False
    manual: bool = False


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temp.open("w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


class Session:
    def __init__(self, title="새 회의"):
        self.id = uuid.uuid4().hex
        self.title = title.strip() or "새 회의"
        self.started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.ended_at: str | None = None
        self.speakers: dict[str, Speaker] = {}
        self.segments: dict[str, Segment] = {}
        self.events: list[dict] = []
        self.revision = 0
        self._lock = threading.RLock()

    def add_speaker(self, source: str) -> str:
        if source not in SOURCES:
            raise ValueError("Unknown source")
        with self._lock:
            n = 1
            while f"speaker_{n:04d}" in self.speakers:
                n += 1
            sid = f"speaker_{n:04d}"
            self.speakers[sid] = Speaker(sid, f"발화자 {n}", source)
            self.revision += 1
            return sid

    def rename(self, sid: str, name: str):
        name = name.strip()
        if not name or len(name) > 80:
            raise ValueError("이름은 1~80자로 입력해 주세요.")
        with self._lock:
            self.speakers[sid].name = name
            self.revision += 1

    def add_segment(self, segment: Segment):
        if segment.source not in SOURCES or segment.end < segment.start:
            raise ValueError("Invalid segment")
        with self._lock:
            self.segments[segment.id] = segment
            self.revision += 1

    def replace_segments(self, original_ids: list[str], segments: list[Segment]):
        with self._lock:
            # User corrections made while diarization ran take precedence.
            if any(self.segments.get(sid) and self.segments[sid].manual for sid in original_ids):
                return
            for sid in original_ids:
                self.segments.pop(sid, None)
            for segment in segments:
                self.segments[segment.id] = segment
            self.revision += 1

    def edit_segment(self, sid: str, text: str, speaker_id: str | None):
        with self._lock:
            segment = self.segments[sid]
            if speaker_id is not None and self.speakers[speaker_id].source != segment.source:
                raise ValueError("같은 입력 출처의 발화자를 선택해 주세요.")
            segment.text = text.strip()
            segment.speaker_id = speaker_id
            segment.manual = True
            segment.status = "수동 수정" if speaker_id else "발화자 미지정"
            self.revision += 1

    def event(self, seconds: float, message: str, source: str = ""):
        with self._lock:
            self.events.append({"time": round(seconds, 3), "source": source, "message": message})
            self.revision += 1

    def finish(self):
        with self._lock:
            self.ended_at = datetime.now().astimezone().isoformat(timespec="seconds")
            self.revision += 1

    def snapshot(self) -> dict:
        with self._lock:
            return deepcopy({"schema": 1, "id": self.id, "title": self.title,
                "started_at": self.started_at, "ended_at": self.ended_at, "revision": self.revision,
                "speakers": [asdict(s) for s in self.speakers.values()],
                "segments": [asdict(s) for s in sorted(self.segments.values(), key=lambda s: (s.start, s.source, s.id))],
                "events": self.events})

    def save(self, path: Path):
        with self._lock:
            atomic_text(path, json.dumps(self.snapshot(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: Path) -> "Session":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("schema") != 1:
            raise ValueError("지원하지 않는 세션 형식입니다.")
        obj = cls(data["title"])
        obj.id = data["id"]
        obj.started_at = data["started_at"]
        obj.ended_at = data.get("ended_at")
        for value in data["speakers"]:
            speaker = Speaker(**value)
            if speaker.source not in SOURCES or speaker.id in obj.speakers:
                raise ValueError("잘못된 발화자 정보입니다.")
            obj.speakers[speaker.id] = speaker
        for value in data["segments"]:
            segment = Segment(**value)
            if segment.speaker_id and (segment.speaker_id not in obj.speakers or obj.speakers[segment.speaker_id].source != segment.source):
                raise ValueError("발화자와 입력 출처가 일치하지 않습니다.")
            obj.add_segment(segment)
        obj.events = data.get("events", [])
        obj.revision = data.get("revision", 0)
        return obj


def timestamp(seconds: float) -> str:
    whole = max(0, int(seconds))
    return f"{whole // 3600:02}:{whole // 60 % 60:02}:{whole % 60:02}"
