# Build with: .venv\Scripts\python -m PyInstaller --noconfirm MeetingTranscriber.spec
from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs, collect_data_files

root = Path(SPECPATH)
datas = [(str(root / 'assets'), 'assets')]
binaries = []
hiddenimports = ['meeting_app.diagnostics', 'PIL._tkinter_finder']
for package in ['faster_whisper', 'sherpa_onnx', 'pywebrtc_audio', 'soxr', 'pyaudiowpatch', 'ctranslate2']:
    d, b, h = collect_all(package)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files('reportlab')
a = Analysis([str(root / 'main.py')], pathex=[str(root)], binaries=binaries, datas=datas,
    hiddenimports=hiddenimports, hookspath=[], runtime_hooks=[],
    excludes=['pytest', 'pypdfium2', 'torch', 'tensorflow', 'matplotlib', 'IPython'], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name='MeetingTranscriber',
    debug=False, bootloader_ignore_signals=False, strip=False, upx=False, console=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='MeetingTranscriber')
