# Third-party components

The application processes audio locally. Model files are obtained by the separate preparation script; no runtime account or token is used.

| Component | License / source |
| --- | --- |
| faster-whisper | MIT - https://github.com/SYSTRAN/faster-whisper |
| Whisper model, converted by SYSTRAN (base default; small optional) | MIT - https://huggingface.co/Systran/faster-whisper-base |
| CTranslate2 | MIT - https://github.com/OpenNMT/CTranslate2 |
| sherpa-onnx | Apache-2.0 - https://github.com/k2-fsa/sherpa-onnx |
| pyannote segmentation 3.0 (ONNX conversion) | MIT - https://huggingface.co/pyannote/segmentation-3.0 |
| 3D-Speaker ERes2Net speaker embedding | Apache-2.0 - https://github.com/modelscope/3D-Speaker |
| pywebrtc-audio / WebRTC | BSD-style; see installed package license and https://webrtc.googlesource.com/src/+/refs/heads/main/LICENSE |
| PyAudioWPatch / PortAudio | MIT - https://github.com/s0d3s/PyAudioWPatch |
| NumPy | BSD-3-Clause - https://numpy.org/ |
| python-soxr / libsoxr | BSD-3-Clause / LGPL-2.1-or-later - https://github.com/dofuuz/python-soxr |
| ReportLab | BSD license - https://www.reportlab.com/ |
| markdown-it-py | MIT - https://github.com/executablebooks/markdown-it-py |
| Nanum Gothic fonts | SIL Open Font License 1.1; included in assets/fonts/OFL.txt |
| Python / Tcl-Tk / PyInstaller | Their respective distribution licenses apply |

The build includes some wheel-provided license metadata and the bundled font's OFL text. This table is not a complete transitive dependency notice bundle. The source repository excludes downloaded models and packaged binaries. Before publishing an executable release, complete the redistribution audit and notice bundle, including PyAV/FFmpeg, ONNX Runtime, Pillow and other transitive libraries.
