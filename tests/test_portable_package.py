import hashlib
import json
from pathlib import Path
import zipfile

import pytest

from scripts.package_portable import package_portable, validate


def write(root, name, content=b"fixture"):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


@pytest.fixture
def portable(tmp_path):
    folder = tmp_path / "MeetingTranscriber"
    for name in ("MeetingTranscriber.exe", "readme.md", "THIRD_PARTY_NOTICES.md", "enable_firewall.ps1",
            "check_package.ps1", "_internal/python312.dll", "_internal/base_library.zip", "licenses/INDEX.md"):
        write(folder, name)
    model = write(folder, "models/whisper-small/model.bin")
    write(folder, "models/manifest.json", json.dumps({"whisper_models": {"small": "whisper-small"},
        "files": {"whisper-small/model.bin": {"sha256": hashlib.sha256(model.read_bytes()).hexdigest()}}}).encode())
    notice = write(folder, "licenses/original-LICENSE.txt", b"Original notice")
    write(folder, "licenses/inventory.json", json.dumps({"notice_files": [{"file": notice.name,
        "sha256": hashlib.sha256(notice.read_bytes()).hexdigest()}]}).encode())
    return folder


def test_complete_zip_roundtrip_and_checksums(portable, tmp_path):
    target = tmp_path / "package.zip"
    count, size = package_portable(portable, target, "0.1.2")
    assert count > 0 and size > 0
    with zipfile.ZipFile(target) as archive:
        archive.extractall(tmp_path / "unpacked")
        assert archive.testzip() is None
    unpacked = tmp_path / "unpacked/MeetingTranscriber"
    manifest = json.loads((unpacked / "PACKAGE_FILES.json").read_text())
    assert len(manifest["files"]) + 1 == count
    for record in manifest["files"]:
        assert hashlib.sha256((unpacked / record["file"]).read_bytes()).hexdigest() == record["sha256"]
    assert target.with_suffix(".zip.sha256").read_text().split()[0] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert validate(unpacked)


def test_corrupt_model_does_not_produce_zip(portable, tmp_path):
    (portable / "models/whisper-small/model.bin").write_bytes(b"changed")
    target = tmp_path / "package.zip"
    with pytest.raises(ValueError, match="Model"):
        package_portable(portable, target, "0.1.2")
    assert not target.exists()


@pytest.mark.parametrize("name", ["sessions/private-meeting.json", "models/private.wav", "docs/logs/run.log", "settings.json"])
def test_personal_data_is_rejected(portable, tmp_path, name):
    write(portable, name, b"private transcript")
    target = tmp_path / "package.zip"
    with pytest.raises(ValueError, match="user data"):
        package_portable(portable, target, "0.1.2")
    assert not target.exists()


def test_notice_corruption_is_rejected(portable):
    (portable / "licenses/original-LICENSE.txt").write_bytes(b"missing attribution")
    with pytest.raises(ValueError, match="Notice"):
        validate(portable)


@pytest.mark.parametrize("name", ["../outside.bin", "C:/outside.bin", "..\\outside.bin"])
def test_model_manifest_cannot_escape_folder(portable, name):
    manifest = json.loads((portable / "models/manifest.json").read_text())
    manifest["files"] = {name: {"sha256": "0" * 64}}
    (portable / "models/manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="escapes"):
        validate(portable)
