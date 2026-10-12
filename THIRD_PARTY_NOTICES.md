# Third-party components

The application processes audio locally. Model files are obtained by the separate preparation script; no runtime account or token is used.

| Component | License / source |
| --- | --- |
| faster-whisper | MIT - https://github.com/SYSTRAN/faster-whisper |
| Whisper models, converted by SYSTRAN (small default; base speed mode) | MIT - https://huggingface.co/Systran/faster-whisper-small and https://huggingface.co/Systran/faster-whisper-base |
| CTranslate2 | MIT - https://github.com/OpenNMT/CTranslate2 |
| sherpa-onnx | Apache-2.0 - https://github.com/k2-fsa/sherpa-onnx |
| pyannote segmentation 3.0 (ONNX conversion) | MIT - https://huggingface.co/pyannote/segmentation-3.0 |
| 3D-Speaker ERes2Net speaker embedding | Apache-2.0 - https://github.com/modelscope/3D-Speaker |
| pywebrtc-audio / WebRTC | Apache-2.0 wrapper / BSD-style WebRTC - https://github.com/strands-labs/pywebrtc-audio and https://webrtc.googlesource.com/src/+/refs/heads/main/LICENSE |
| PyAudioWPatch / original PyAudio / PortAudio | Apache-2.0 fork / MIT original bindings / MIT PortAudio - https://github.com/s0d3s/PyAudioWPatch and https://github.com/PortAudio/portaudio |
| NumPy | BSD-3-Clause - https://numpy.org/ |
| python-soxr / libsoxr / PFFFT | LGPL-2.1-or-later; preserve all wheel license texts - https://github.com/dofuuz/python-soxr |
| PyAV | BSD-3-Clause Python bindings - https://github.com/PyAV-Org/PyAV/tree/v16.0.1 |
| FFmpeg and codec DLLs shipped with PyAV | Separate native-library terms; build report and LGPL/GPL texts included - https://github.com/FFmpeg/FFmpeg/tree/n8.0 |
| ONNX Runtime | MIT and bundled third-party notices - https://github.com/microsoft/onnxruntime |
| Pillow | MIT-CMU and bundled notices - https://github.com/python-pillow/Pillow |
| ReportLab | BSD license - https://www.reportlab.com/ |
| markdown-it-py | MIT - https://github.com/executablebooks/markdown-it-py |
| Nanum Gothic fonts | SIL Open Font License 1.1; included in assets/fonts/OFL.txt |
| Python / Tcl-Tk / PyInstaller | Their respective distribution licenses apply |

## Notice bundle in the portable package

This package is prepared for the owner's personal use on their own Windows PCs. It is not being published as a public executable release. It contains original notice texts, including the installed Python distributions' transitive dependencies, ONNX Runtime ThirdPartyNotices, Pillow, PyAV, SoXR/PFFFT, ReportLab fonts, Python/Tk, model notices and supplemental native-library references.

- `licenses/INDEX.md`: installed versions and license-text locations.
- `licenses/inventory.json`: component metadata, model download origins and SHA-256 notice hashes.
- `licenses/python/`: original files copied from installed distributions, including their nested third-party notices.
- `licenses/runtime/`, `licenses/fonts/`: Python/Tk, original PyAudio attribution and Nanum Gothic OFL.
- `licenses/upstream/`: additional upstream texts, including missing wheel licenses, model licenses, FFmpeg and its codec/runtime dependencies. `sources.json` records download URLs, retrieval timestamps and content hashes.
- `licenses/FFMPEG_BUILD.json`: version, license string and configuration reported by the actual bundled FFmpeg DLL, plus codec DLL names and hashes.

The current FFmpeg DLL reports `LGPL version 3 or later`; its configuration and wheel also contain x264/x265 libraries. Both observations are preserved rather than treating the PyAV BSD license as covering all native DLLs. FFmpeg license terms depend on the build and external libraries: https://ffmpeg.org/legal.html. Reference notices without an exact version tag are identified as upstream references, not as an exact corresponding-source match.

`scripts/collect_notices.py` runs offline during packaging. Only the separate maintainer utility `scripts/prepare_notices.py` retrieves notice texts; the application never imports it. The checked-in cache allows subsequent builds without notice-download network calls.

This completes the notice collection and provenance work for the stated personal-PC transfer scope. It does not claim a complete public redistribution audit or provide an exact corresponding-source archive for every native binary. If that scope changes, native source/build matching and applicable source-delivery terms must be checked before publishing. Microsoft runtime DLLs remain Microsoft components; their inclusion is recorded in `PACKAGE_FILES.json`, not relicensed by this document.
