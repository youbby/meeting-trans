import subprocess
import sys

from meeting_app.models import local_path
import pytest


def test_offline_guard_blocks_network_in_fresh_process():
    code = '''
from meeting_app.privacy import install_offline_guard, blocked_attempts
install_offline_guard()
import socket
for operation in [lambda: socket.getaddrinfo('example.com',443), lambda: socket.socket().connect(('1.1.1.1',443))]:
    try:
        operation()
        raise AssertionError('Network call was allowed')
    except PermissionError:
        pass
assert len(blocked_attempts) == 2
'''
    subprocess.run([sys.executable, "-c", code], check=True)


def test_remote_paths_rejected():
    for path in ["https://example.com/model", "\\\\server\\share\\model", "//server/share"]:
        with pytest.raises(ValueError):
            local_path(path)
