"""Exercise the desktop UI and export without opening audio input streams."""
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
from meeting_app.privacy import install_offline_guard
install_offline_guard()
from meeting_app.ui import App
from PIL import ImageGrab
from pypdf import PdfReader

folder = ROOT / "output/verification"
folder.mkdir(parents=True, exist_ok=True)
app = App(demo=True)
app.geometry("1220x720+20+20")
app.session_path = folder / "session.json"
app.session.finish()
app.session.rename("speaker_0002", "현장 참석자 김대리")
app.refresh_session()
app.update()
app.lift()
app.save_export()
deadline = time.monotonic() + 20
while app.exporting and time.monotonic() < deadline:
    app.update()
    time.sleep(.03)
assert not app.exporting and app.export_paths and app.export_paths[1]
app.update()
ImageGrab.grab(bbox=(app.winfo_rootx(), app.winfo_rooty(), app.winfo_rootx()+app.winfo_width(), app.winfo_rooty()+app.winfo_height())).save(folder / "ui.png")
md, pdf = app.export_paths
assert "현장 참석자 김대리" in md.read_text(encoding="utf-8")
assert "현장 참석자 김대리" in "".join(p.extract_text() for p in PdfReader(pdf).pages)
print(f"UI / export verified: {folder}")
app.destroy()
