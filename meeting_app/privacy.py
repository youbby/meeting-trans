"""Fail closed for Python network APIs; native inference uses local files only.

This is a process policy, not an OS firewall. The optional firewall script adds
OS enforcement for the packaged EXE. No remote API is part of the application.
"""
import os
import socket
import sys

_installed = False
blocked_attempts: list[str] = []


def install_offline_guard():
    global _installed
    if _installed:
        return
    for key in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE", "HF_HUB_DISABLE_TELEMETRY", "DO_NOT_TRACK"):
        os.environ[key] = "1"
    os.environ["PYANNOTE_METRICS_ENABLED"] = "0"
    os.environ["HF_HUB_DISABLE_XET"] = "1"
    os.environ["TOKENIZERS_PARALLELISM"] = "false"

    def deny(*args, **kwargs):
        from .runtime_log import event
        event("network_blocked")
        blocked_attempts.append("network API blocked")
        raise PermissionError("이 프로그램은 외부 통신을 허용하지 않습니다. 모델은 별도 준비 도구로 설치해 주세요.")

    def audit(event, args):
        if event in {"socket.connect", "socket.getaddrinfo", "socket.gethostbyname", "socket.sendto", "socket.bind"}:
            deny()

    sys.addaudithook(audit)
    socket.socket.connect = deny
    socket.socket.connect_ex = deny
    socket.socket.sendto = deny
    socket.create_connection = deny
    socket.getaddrinfo = deny
    _installed = True


def configure_onnx_privacy():
    import onnxruntime
    onnxruntime.disable_telemetry_events()
