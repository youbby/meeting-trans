"""Offline build utility: collect the installed runtime's original notices."""
from __future__ import annotations

import argparse
import ast
import ctypes
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import shutil
import sys

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[1]
NOTICE_NAME = re.compile(r"license|licence|copying|notice|copyright", re.I)
PRIMARY_NAME = re.compile(r"license|licence|copying", re.I)


def digest(path: Path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_distributions():
    names = {Requirement(line).name for line in (ROOT / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.startswith("#")}
    names.update({"setuptools", "pyinstaller"})
    # Also cover optional packages actually collected into the frozen archive.
    toc = ROOT / "build/MeetingTranscriber/PYZ-00.toc"
    if not toc.is_file():
        raise FileNotFoundError("Build the executable before collecting notices.")
    mapping = metadata.packages_distributions()
    for module, *_ in ast.literal_eval(toc.read_text(encoding="utf-8"))[1]:
        names.update(mapping.get(module.split(".")[0], []))
    selected = {}
    pending = list(names)
    while pending:
        name = canonicalize_name(pending.pop())
        if name in selected:
            continue
        distribution = metadata.distribution(name)
        selected[name] = distribution
        for line in distribution.requires or []:
            requirement = Requirement(line)
            if requirement.marker is None or requirement.marker.evaluate({"extra": ""}):
                pending.append(requirement.name)
    return sorted(selected.items())


def copy_text(source: Path, target: Path):
    if not source.is_file():
        raise FileNotFoundError(f"Missing notice: {source.name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def ffmpeg_details(package: Path):
    import av
    dll = next((package / "_internal/av.libs").glob("avutil-*.dll"))
    native = ctypes.CDLL(str(dll))
    result = {"pyav_version": av.__version__, "library_versions": av.library_versions,
        "source_reference": "https://github.com/FFmpeg/FFmpeg/tree/n8.0",
        "wheel_build_source": "https://github.com/PyAV-Org/pyav-ffmpeg"}
    for key, function in (("version", "av_version_info"), ("reported_license", "avutil_license"),
            ("configuration", "avutil_configuration")):
        callback = getattr(native, function)
        callback.restype = ctypes.c_char_p
        result[key] = callback().decode("utf-8")
    result["external_dlls"] = [{"file": p.name, "sha256": digest(p)}
        for p in sorted((package / "_internal/av.libs").glob("*.dll"))]
    result["library_licenses"] = {}
    for prefix in ("avutil", "avcodec", "avformat", "avdevice", "avfilter", "swscale", "swresample"):
        library = ctypes.CDLL(str(next((package / "_internal/av.libs").glob(f"{prefix}-*.dll"))))
        callback = getattr(library, f"{prefix}_license")
        callback.restype = ctypes.c_char_p
        result["library_licenses"][prefix] = callback().decode("utf-8")
    result["scope"] = ("Private PC transfer inventory. Reported license is recorded verbatim; "
        "x264/x265 DLLs and build flags are also present. References are not an exact "
        "corresponding-source bundle or a public redistribution clearance.")
    return result


def collect(package: Path):
    destination = package / "licenses"
    destination.mkdir(parents=True, exist_ok=True)
    upstream = ROOT / "licenses/upstream"
    receipts = json.loads((upstream / "sources.json").read_text(encoding="utf-8"))
    for receipt in receipts:
        source = upstream / receipt["file"]
        if digest(source) != receipt["sha256"]:
            raise ValueError(f"Upstream notice changed: {receipt['file']}")
        copy_text(source, destination / "upstream" / receipt["file"])
    copy_text(upstream / "sources.json", destination / "upstream/sources.json")
    components = []
    for name, distribution in runtime_distributions():
        folder = destination / "python" / f"{name}-{distribution.version}"
        copied = []
        primary = False
        for entry in distribution.files or []:
            if not NOTICE_NAME.search(entry.name) or entry.suffix.lower() in {".py", ".pyc", ".pyd"}:
                continue
            # RECORD paths are provenance only; never allow an absolute/parent destination.
            relative = Path(str(entry))
            if relative.is_absolute() or ".." in relative.parts:
                continue
            source = Path(distribution.locate_file(entry))
            if source.is_file():
                target = folder / relative
                copy_text(source, target)
                copied.append(target.relative_to(destination).as_posix())
                primary |= bool(PRIMARY_NAME.search(entry.name))
        if not primary:
            supplement = upstream / name / "LICENSE"
            if not supplement.is_file():
                raise FileNotFoundError(f"No primary license text for {name} {distribution.version}")
            target = folder / "LICENSE"
            copy_text(supplement, target)
            copied.append(target.relative_to(destination).as_posix())
        license_label = distribution.metadata.get("License-Expression") or distribution.metadata.get("License")
        if not license_label:
            license_label = "; ".join(c.rsplit(" :: ", 1)[-1] for c in
                distribution.metadata.get_all("Classifier", []) if c.startswith("License ::")) or "See original text"
        components.append({"name": distribution.metadata["Name"], "version": distribution.version,
            "declared_license": license_label, "project_urls": distribution.metadata.get_all("Project-URL", []),
            "notices": copied})
    copy_text(Path(sys.base_prefix) / "LICENSE.txt", destination / "runtime/Python-LICENSE.txt")
    copy_text(package / "_internal/_tk_data/license.terms", destination / "runtime/Tk-license.terms")
    copy_text(ROOT / "assets/fonts/OFL.txt", destination / "fonts/NanumGothic-OFL.txt")
    import pyaudiowpatch
    # This fork retains Hubert Pham's MIT notice in the module header.
    header = Path(pyaudiowpatch.__file__).read_text(encoding="utf-8").split("# PyAudioWPatch :", 1)[0]
    target = destination / "runtime/PyAudio-original-MIT.txt"
    target.write_text(header, encoding="utf-8")
    details = ffmpeg_details(package)
    (destination / "FFMPEG_BUILD.json").write_text(json.dumps(details, indent=2) + "\n", encoding="utf-8")
    model_manifest = json.loads((package / "models/manifest.json").read_text(encoding="utf-8"))
    inventory = {"scope": "Personal transfer between the owner's Windows PCs; no public release audit claimed.",
        "python": sys.version.split()[0], "components": components,
        "models": model_manifest, "ffmpeg": details,
        "notice_files": [{"file": p.relative_to(destination).as_posix(), "sha256": digest(p)}
            for p in sorted(destination.rglob("*")) if p.is_file() and p.name not in {"inventory.json", "INDEX.md"}]}
    (destination / "inventory.json").write_text(json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    index = ["# 포함 구성 요소와 라이선스 원문", "", "개인 PC 간 이동용 패키지의 실제 설치 버전을 기록합니다.",
        "`inventory.json`에는 구성 요소·모델 출처와 원문 SHA-256이 있습니다.",
        "`FFMPEG_BUILD.json`에는 DLL이 보고한 버전·라이선스·빌드 옵션과 DLL 해시가 있습니다.",
        "`upstream/sources.json`에는 추가 원문의 다운로드 출처·시점·해시가 있습니다.", "",
        "| 구성 요소 | 버전 | 설치 메타데이터의 라이선스 |", "| --- | --- | --- |"]
    for item in components:
        label = item["declared_license"].replace("|", "\\|").replace("\n", " ")
        index.append(f"| {item['name']} | {item['version']} | {label} |")
    index.extend(["", "원문은 `python/`, `runtime/`, `fonts/`, `upstream/`에 보존합니다.",
        "네이티브 종속성 원문 중 버전 태그가 없는 출처는 참고 원문이며 바이너리와 정확히 일치하는 소스라는 뜻은 아닙니다.",
        "이 묶음은 다른 사람에게 공개 배포하기 위한 전체 소스 제공·라이선스 적합성 검증을 대신하지 않습니다.", ""])
    (destination / "INDEX.md").write_text("\n".join(index), encoding="utf-8")
    return len(components), len(inventory["notice_files"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=ROOT / "dist/MeetingTranscriber")
    args = parser.parse_args()
    components, notices = collect(args.package.resolve())
    print(f"Collected {components} Python components and {notices} notice files (offline).")


if __name__ == "__main__":
    main()
