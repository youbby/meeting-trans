"""ONLINE maintainer utility: cache upstream notices, never imported by the app.

Builds use the checked-in cache offline. Receipts retain the URL, retrieval time
and content hash. Native references do not assert an exact wheel source match.
"""
from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "licenses" / "upstream"
RAW = "https://raw.githubusercontent.com/"
SOURCES = {
    "ctranslate2/LICENSE": RAW + "OpenNMT/CTranslate2/v4.8.2/LICENSE",
    "flatbuffers/LICENSE": RAW + "google/flatbuffers/v25.12.19/LICENSE",
    "tokenizers/LICENSE": RAW + "huggingface/tokenizers/v0.23.3/LICENSE",
    "sherpa-onnx-core/LICENSE": RAW + "k2-fsa/sherpa-onnx/v1.13.8/LICENSE",
    "models/whisper/LICENSE": RAW + "openai/whisper/main/LICENSE",
    "models/pyannote/LICENSE": "https://huggingface.co/pyannote/segmentation-3.0/resolve/main/LICENSE",
    "models/3d-speaker/LICENSE": RAW + "modelscope/3D-Speaker/main/LICENSE",
    "webrtc/LICENSE": "https://webrtc.googlesource.com/src/+/refs/heads/main/LICENSE?format=TEXT",
    "webrtc/PATENTS": "https://webrtc.googlesource.com/src/+/refs/heads/main/PATENTS?format=TEXT",
    "portaudio/LICENSE.txt": RAW + "PortAudio/portaudio/v19.7.0/LICENSE.txt",
    "ffmpeg/LICENSE.md": RAW + "FFmpeg/FFmpeg/n8.0/LICENSE.md",
    "ffmpeg/COPYING.LGPLv2.1": RAW + "FFmpeg/FFmpeg/n8.0/COPYING.LGPLv2.1",
    "ffmpeg/COPYING.LGPLv3": RAW + "FFmpeg/FFmpeg/n8.0/COPYING.LGPLv3",
    "ffmpeg/COPYING.GPLv2": RAW + "FFmpeg/FFmpeg/n8.0/COPYING.GPLv2",
    "ffmpeg/COPYING.GPLv3": RAW + "FFmpeg/FFmpeg/n8.0/COPYING.GPLv3",
    "ffmpeg-dependencies/aom/LICENSE": "https://aomedia.googlesource.com/aom/+/refs/heads/main/LICENSE?format=TEXT",
    "ffmpeg-dependencies/aom/PATENTS": "https://aomedia.googlesource.com/aom/+/refs/heads/main/PATENTS?format=TEXT",
    "ffmpeg-dependencies/dav1d/COPYING": RAW + "videolan/dav1d/master/COPYING",
    "ffmpeg-dependencies/openh264/LICENSE": RAW + "cisco/openh264/master/LICENSE",
    "ffmpeg-dependencies/opus/COPYING": RAW + "xiph/opus/main/COPYING",
    "ffmpeg-dependencies/speex/COPYING": RAW + "xiph/speex/master/COPYING",
    "ffmpeg-dependencies/ogg/COPYING": RAW + "xiph/ogg/main/COPYING",
    "ffmpeg-dependencies/vorbis/COPYING": RAW + "xiph/vorbis/master/COPYING",
    "ffmpeg-dependencies/libvpx/LICENSE": RAW + "webmproject/libvpx/main/LICENSE",
    "ffmpeg-dependencies/libvpx/PATENTS": RAW + "webmproject/libvpx/main/PATENTS",
    "ffmpeg-dependencies/libwebp/COPYING": RAW + "webmproject/libwebp/main/COPYING",
    "ffmpeg-dependencies/libwebp/PATENTS": RAW + "webmproject/libwebp/main/PATENTS",
    "ffmpeg-dependencies/x264/COPYING": RAW + "mirror/x264/master/COPYING",
    "ffmpeg-dependencies/x265/COPYING": RAW + "videolan/x265/master/COPYING",
    "ffmpeg-dependencies/lame/COPYING": RAW + "lameproject/lame/master/COPYING",
    "ffmpeg-dependencies/twolame/COPYING": RAW + "njh/twolame/main/COPYING",
    "ffmpeg-dependencies/opencore-amr/LICENSE": RAW + "BelledonneCommunications/opencore-amr/master/LICENSE",
    "ffmpeg-dependencies/svt-av1/LICENSE.md": "https://gitlab.com/AOMediaCodec/SVT-AV1/-/raw/master/LICENSE.md",
    "ffmpeg-dependencies/gmp/COPYING.LESSERv3": "https://gmplib.org/repo/gmp/raw-file/tip/COPYING.LESSERv3",
    "ffmpeg-dependencies/iconv/COPYING.LIB": "https://www.gnu.org/licenses/old-licenses/lgpl-2.1.txt",
    "ffmpeg-dependencies/gcc/COPYING.RUNTIME": RAW + "gcc-mirror/gcc/master/COPYING.RUNTIME",
    "ffmpeg-dependencies/mingw-w64/COPYING": RAW + "mingw-w64/mingw-w64/master/COPYING",
    "zlib/LICENSE": RAW + "madler/zlib/v1.3.1/LICENSE",
    "openssl/LICENSE.txt": RAW + "openssl/openssl/openssl-3.5.7/LICENSE.txt",
    "tcl/license.terms": RAW + "tcltk/tcl/core-8-6-branch/license.terms",
    "libffi/LICENSE": RAW + "libffi/libffi/master/LICENSE",
    "expat/COPYING": RAW + "libexpat/libexpat/master/expat/COPYING",
    "bzip2/LICENSE": "https://sourceware.org/git/?p=bzip2.git;a=blob_plain;f=LICENSE;hb=bzip2-1.0.8",
    "xz/COPYING": RAW + "tukaani-project/xz/master/COPYING",
    "xz/COPYING.0BSD": RAW + "tukaani-project/xz/master/COPYING.0BSD",
    "apache/LICENSE-2.0.txt": "https://www.apache.org/licenses/LICENSE-2.0.txt",
}


def fetch(item):
    name, url = item
    request = urllib.request.Request(url, headers={"User-Agent": "MeetingTranscriber-NoticeSetup/0.1.3"})
    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(2_000_000)
        final_url = response.url
    if "format=TEXT" in url:
        content = base64.b64decode(content)
    if len(content) < 30 or b"<html" in content.lower() or b"<!doctype html" in content.lower():
        raise ValueError(f"Not a license text: {name}")
    destination = CACHE / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(content)
    return {"file": name, "url": url, "resolved_url": final_url,
        "retrieved_utc": datetime.now(timezone.utc).isoformat(),
        "sha256": hashlib.sha256(content).hexdigest()}


def main():
    receipt_path = CACHE / "sources.json"
    old = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else []
    receipts = {r["file"]: r for r in old}
    errors = []
    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = [(name, pool.submit(fetch, (name, url))) for name, url in SOURCES.items()]
        for name, future in futures:
            try:
                receipts[name] = future.result()
                print(f"Cached: {name}", flush=True)
            except Exception as exc:
                errors.append(name)
                print(f"Failed: {name}: {exc}", flush=True)
    CACHE.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(list(receipts.values()), indent=2) + "\n", encoding="utf-8")
    if errors:
        raise SystemExit("Missing notices: " + ", ".join(errors))


if __name__ == "__main__":
    main()
