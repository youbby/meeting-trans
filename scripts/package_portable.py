"""Validate and archive the whole portable folder, excluding user data by policy."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re
import zipfile

ROOT = Path(__file__).resolve().parents[1]
DIRECTORIES = {"_internal", "models", "docs", "licenses"}
FILES = {"MeetingTranscriber.exe", "readme.md", "THIRD_PARTY_NOTICES.md",
    "enable_firewall.ps1", "check_package.ps1", "PACKAGE_FILES.json"}


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def contained(root: Path, name: str):
    relative = PureWindowsPath(name)
    if relative.is_absolute() or relative.drive or ".." in relative.parts:
        raise ValueError("Package path escapes its folder")
    path = (root / name).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Package path escapes its folder")
    return path


def validate(package: Path):
    for name in FILES - {"PACKAGE_FILES.json"}:
        if not (package / name).is_file():
            raise FileNotFoundError(f"Missing package file: {name}")
    for name in ("_internal/python312.dll", "_internal/base_library.zip", "licenses/INDEX.md", "licenses/inventory.json"):
        if not (package / name).is_file():
            raise FileNotFoundError(f"Missing runtime or notice file: {name}")
    manifest = json.loads((package / "models/manifest.json").read_text(encoding="utf-8"))
    for name, record in manifest["files"].items():
        path = contained(package / "models", name)
        if not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError(f"Model file missing or changed: {name}")
    for name in manifest.get("whisper_models", {}).values():
        if not contained(package / "models", name).is_dir():
            raise FileNotFoundError("Missing recognition model directory")
    inventory = json.loads((package / "licenses/inventory.json").read_text(encoding="utf-8"))
    for record in inventory["notice_files"]:
        path = contained(package / "licenses", record["file"])
        if not path.is_file() or digest(path) != record["sha256"]:
            raise ValueError("Notice file missing or changed")
    files = []
    model_files = {Path(name).as_posix() for name in manifest["files"]} | {"manifest.json"}
    for path in sorted(package.rglob("*")):
        if path.is_symlink() or not path.resolve().is_relative_to(package.resolve()):
            raise ValueError("Linked paths are not allowed in the portable package")
        relative = path.relative_to(package)
        if any(part.casefold() in {"sessions", "logs", "recordings", "output", "tmp"} for part in relative.parts):
            raise ValueError("Unexpected package item; user data must not be bundled")
        if path.name.casefold() == "settings.json" or path.name.casefold().startswith(".env") or path.suffix.casefold() == ".log":
            raise ValueError("Unexpected package item; user data must not be bundled")
        if relative.parts[0] not in DIRECTORIES and relative.as_posix() not in FILES:
            raise ValueError(f"Unexpected package item; user data must not be bundled: {relative}")
        if path.is_file() and path.name != "PACKAGE_FILES.json":
            if relative.parts[0] == "models" and path.relative_to(package / "models").as_posix() not in model_files:
                raise ValueError("Unlisted file in model folder; user data must not be bundled")
            files.append(path)
    return files


def package_portable(package: Path, destination: Path, version: str):
    if not re.fullmatch(r"\d+\.\d+\.\d+", version):
        raise ValueError("Invalid package version")
    if destination.resolve().is_relative_to(package.resolve()):
        raise ValueError("Archive destination must be outside the package")
    files = validate(package)
    records = [{"file": p.relative_to(package).as_posix(), "bytes": p.stat().st_size,
        "sha256": digest(p)} for p in files]
    manifest_path = package / "PACKAGE_FILES.json"
    manifest_path.write_text(json.dumps({"version": version, "platform": "Windows x64",
        "files": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".zip.part")
    with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in [*files, manifest_path]:
            archive.write(path, f"MeetingTranscriber/{path.relative_to(package).as_posix()}")
    with zipfile.ZipFile(temporary) as archive:
        damaged = archive.testzip()
        if damaged:
            raise ValueError(f"Archive validation failed: {damaged}")
    temporary.replace(destination)
    checksum = destination.with_suffix(".zip.sha256")
    checksum.write_text(f"{digest(destination)}  {destination.name}\n", encoding="ascii")
    return len(files) + 1, destination.stat().st_size


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "dist/MeetingTranscriber")
    parser.add_argument("--destination", type=Path)
    args = parser.parse_args()
    version = re.search(r'__version__\s*=\s*"([^"]+)"',
        (ROOT / "meeting_app/__init__.py").read_text(encoding="utf-8")).group(1)
    target = args.destination or ROOT / f"dist/MeetingTranscriber-v{version}-win-x64.zip"
    count, size = package_portable(args.package.resolve(), target.resolve(), version)
    print(f"Portable ZIP: {target.name} ({size / 1024**2:.1f} MiB, {count} files)")
    print(f"SHA-256: {target.name}.sha256")


if __name__ == "__main__":
    main()
