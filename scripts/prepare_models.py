"""Explicit ONLINE setup utility. Never imported by the transcription application."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import tarfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"User-Agent": "StandaloneMeetingTranscriber-Setup/0.1"}


def request(url: str):
    return urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=90)


def fetch(url: str, path: Path) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        print(f"Download: {path.name}", flush=True)
        part = path.with_suffix(path.suffix + ".part")
        with request(url) as source, part.open("wb") as target:
            while block := source.read(1024 * 1024):
                target.write(block)
        os.replace(part, path)
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    return {"url": url, "sha256": digest, "bytes": path.stat().st_size}


def main():
    parser = argparse.ArgumentParser(description="Download local models before running the offline app")
    parser.add_argument("--destination", type=Path, default=ROOT / "models")
    parser.add_argument("--whisper", choices=["base", "small"], default="base")
    args = parser.parse_args()
    base = args.destination.resolve()
    records = {}
    repo = f"Systran/faster-whisper-{args.whisper}"
    with request(f"https://huggingface.co/api/models/{repo}") as response:
        metadata = json.load(response)
    revision = metadata["sha"]
    available = {item["rfilename"] for item in metadata["siblings"]}
    for name in ["config.json", "model.bin", "tokenizer.json", "vocabulary.json", "vocabulary.txt", "preprocessor_config.json"]:
        if name in available:
            relative = f"whisper-{args.whisper}/{name}"
            records[relative] = fetch(f"https://huggingface.co/{repo}/resolve/{revision}/{name}", base / relative)
    assets = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
    relative = "speaker/embedding-3dspeaker.onnx"
    records[relative] = fetch(f"{assets}/speaker-recongition-models/3dspeaker_speech_eres2net_base_200k_sv_zh-cn_16k-common.onnx", base / relative)
    archive = base / "speaker/segmentation.tar.bz2"
    archive_record = fetch(f"{assets}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2", archive)
    with tarfile.open(archive, "r:bz2") as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith("/model.onnx"))
        # Extract one known regular file without accepting archive paths.
        stream = tar.extractfile(member)
        if stream is None:
            raise RuntimeError("Segmentation model missing")
        destination = base / "speaker/segmentation.onnx"
        with stream, destination.open("wb") as target:
            while block := stream.read(1024 * 1024):
                target.write(block)
    with destination.open("rb") as stream:
        records["speaker/segmentation.onnx"] = {"url": archive_record["url"], "sha256": hashlib.file_digest(stream, "sha256").hexdigest(), "bytes": destination.stat().st_size}
    font_root = ROOT / "assets/fonts"
    for name in ["NanumGothic-Regular.ttf", "NanumGothic-Bold.ttf", "OFL.txt"]:
        fetch(f"https://raw.githubusercontent.com/google/fonts/main/ofl/nanumgothic/{name}", font_root / name)
    manifest = {"whisper": f"whisper-{args.whisper}", "embedding": "speaker/embedding-3dspeaker.onnx", "revision": revision, "files": records}
    (base / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Ready: {base}", flush=True)
    print("The meeting application runs offline; this setup utility is the only downloader.", flush=True)


if __name__ == "__main__":
    main()
