"""Per-launch operational JSON logs. Never accepts free-form messages or payloads."""
from __future__ import annotations

import atexit
from datetime import datetime
import json
import math
import os
from pathlib import Path
import threading
import time
import uuid

EVENTS = frozenset({
    "app_started", "app_stopped", "ui_ready", "heartbeat", "session_started",
    "session_stopped", "session_opened", "stop_requested", "models_loading",
    "models_ready", "capture_state", "capture_warning", "chunk_processed",
    "operation_failed", "export_started", "export_completed", "network_blocked",
    "recognition_retry", "recognition_rejected",
})
ENUMS = {
    "profile": {"accurate", "fast"},
    "source": {"MIC", "SYSTEM"},
    "outcome": {"normal", "error"},
    "operation": {"startup", "ui_callback", "worker", "devices", "session_start",
        "models", "capture", "transcribe", "diarize", "session_save", "session_open",
        "export", "export_path", "settings", "folder_open"},
    "error_kind": {"PermissionError", "FileNotFoundError", "OSError", "ValueError",
        "TypeError", "KeyError", "RuntimeError", "MemoryError", "Exception"},
    "reason": {"queue_full", "audio_status", "reference_missing", "capture_dropped"},
}
BOOLS = {"packaged", "recording", "paused", "mic", "system", "reference", "audio_saved", "md", "pdf"}
NUMBERS = {"duration_seconds", "elapsed_seconds", "queue_depth", "lag_seconds", "count", "status", "segments"}
_lock = threading.RLock()
_stream = None
_path: Path | None = None
_started = 0.0
_failed = False
_hooks_installed = False


def start(folder: Path | None = None) -> Path:
    """Called once by the entry point; repeated calls in this process reuse the file."""
    global _stream, _path, _started, _failed, _hooks_installed
    with _lock:
        if _stream is not None:
            return _path
        if folder is None:
            from .paths import data_root
            folder = data_root() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S_%f")
        _path = folder / f"run_{stamp}_{os.getpid()}_{uuid.uuid4().hex[:8]}.log"
        _stream = _path.open("x", encoding="utf-8", newline="\n")
        _started, _failed = time.monotonic(), False
        if not _hooks_installed:
            atexit.register(finish)
            threading.excepthook = lambda args: failure("worker", args.exc_value)
            _hooks_installed = True
        import sys
        event("app_started", packaged=bool(getattr(sys, "frozen", False)))
        return _path


def event(name: str, /, **fields):
    """Whitelist names and scalar fields; discard everything else, including paths."""
    global _failed
    if type(name) is not str or name not in EVENTS:
        return
    with _lock:
        if _stream is None:
            return
        record = {"time": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "uptime_seconds": round(time.monotonic() - _started, 3), "event": name}
        for key, value in fields.items():
            if key in ENUMS and type(value) is str and value in ENUMS[key]:
                record[key] = value
            elif key in BOOLS and type(value) is bool:
                record[key] = value
            elif key in NUMBERS and type(value) in (int, float) and math.isfinite(value) and 0 <= value < 1e12:
                record[key] = round(value, 3)
        try:
            _stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            _stream.flush()
        except (OSError, ValueError):
            # Logging storage trouble must not interrupt capture or transcription.
            _failed = True


def failure(operation: str, exc: BaseException):
    # Never call str/repr(exc), format a traceback, or inspect exception arguments.
    # Some PDF/ASR exceptions contain the very transcript we must not log.
    kinds = (PermissionError, FileNotFoundError, MemoryError, OSError, ValueError,
        TypeError, KeyError, RuntimeError)
    kind = next((cls.__name__ for cls in kinds if isinstance(exc, cls)), "Exception")
    event("operation_failed", operation=operation, error_kind=kind)


def path() -> Path | None:
    return _path


def healthy() -> bool:
    return not _failed


def finish(outcome="normal"):
    global _stream
    with _lock:
        if _stream is None:
            return
        event("app_stopped", outcome=outcome)
        try:
            _stream.close()
        except OSError:
            pass
        _stream = None
