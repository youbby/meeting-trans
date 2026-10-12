import json
import os
from pathlib import Path
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

from meeting_app import runtime_log as monitor


def test_log_whitelist_never_serializes_content_or_exception(tmp_path):
    secret = "기밀 대화 내용 참석자 홍길동 SECRET-TRANSCRIPT"
    class HostileError(ValueError):
        def __str__(self):
            raise AssertionError("Do not stringify exceptions")
    log_path = monitor.start(tmp_path)
    try:
        monitor.event("chunk_processed", source="MIC", duration_seconds=3.5, segments=2,
            text=secret, title=secret, name=secret, path=secret, audio=[1, 2], embedding=[3, 4])
        monitor.event("heartbeat", recording=True, queue_depth=secret, operation=secret,
            lag_seconds=float("nan"), source=secret)
        monitor.event(secret, text=secret)
        monitor.failure("export", HostileError(secret))
        assert monitor.start(tmp_path) == log_path
    finally:
        monitor.finish()
    raw = log_path.read_text(encoding="utf-8")
    assert secret not in raw
    rows = [json.loads(line) for line in raw.splitlines()]
    assert [row["event"] for row in rows] == ["app_started", "chunk_processed", "heartbeat", "operation_failed", "app_stopped"]
    assert rows[1]["source"] == "MIC" and rows[1]["segments"] == 2
    assert rows[3]["error_kind"] == "ValueError"
    assert set(rows[2]) == {"time", "uptime_seconds", "event", "recording"}


def test_concurrent_writes_form_complete_json_lines(tmp_path):
    path = monitor.start(tmp_path)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda i: monitor.event("heartbeat", count=i), range(100)))
    finally:
        monitor.finish()
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 102
    assert sorted(row["count"] for row in rows if "count" in row) == list(range(100))


def test_each_real_launch_has_one_separate_file(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "LOCALAPPDATA": str(tmp_path)}
    for _ in range(2):
        result = subprocess.run([sys.executable, str(root / "main.py"), "--help"],
            env=env, cwd=root, capture_output=True, timeout=20)
        assert result.returncode == 0
    logs = list((tmp_path / "StandaloneMeetingTranscriber/logs").glob("*.log"))
    assert len(logs) == 2 and logs[0].name != logs[1].name
    for path in logs:
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert rows[0]["event"] == "app_started"
        assert rows[-1]["event"] == "app_stopped"


def test_failing_startup_logs_no_exception_text(tmp_path):
    root = Path(__file__).resolve().parents[1]
    code = """
import runpy
from meeting_app import privacy
def fail():
    raise RuntimeError('SECRET-PRIVATE-CONVERSATION')
privacy.install_offline_guard = fail
runpy.run_path('main.py', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=root,
        env={**os.environ, "LOCALAPPDATA": str(tmp_path)}, capture_output=True, timeout=20)
    assert result.returncode == 1
    assert b"SECRET-PRIVATE-CONVERSATION" not in result.stderr
    logs = list(tmp_path.rglob("*.log"))
    assert len(logs) == 1 and logs[0].name.startswith("run_")
    raw = logs[0].read_text(encoding="utf-8")
    assert "SECRET-PRIVATE-CONVERSATION" not in raw
    assert json.loads(raw.splitlines()[-1])["outcome"] == "error"


def test_log_write_failure_does_not_break_processing(tmp_path):
    monitor.start(tmp_path)
    monitor._stream.close()
    try:
        monitor.event("heartbeat", recording=True)
        assert not monitor.healthy()
    finally:
        monitor.finish()
