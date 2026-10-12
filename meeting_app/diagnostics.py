"""Explicit command-line runtime verification, without physical capture."""
from pathlib import Path
import time


def run(audio_path: Path | None = None) -> dict:
    import numpy as np
    from .audio import AudioChunk, EchoCleaner, FRAME, RATE, list_devices
    from .models import LocalModels, ModelPaths, SpeakerRegistry
    from .paths import default_models
    from .privacy import blocked_attempts
    from .session import Session
    start = time.monotonic()
    models = LocalModels(ModelPaths.resolve(default_models()))
    zeros = np.zeros(FRAME, np.float32)
    assert EchoCleaner().process(zeros, zeros).shape == zeros.shape
    report = {"models_loaded": True, "aec_loaded": True, "model_load_seconds": round(time.monotonic() - start, 2)}
    mics, outputs = list_devices()
    report.update({"microphones": len(mics), "outputs": len(outputs)})
    if audio_path:
        from faster_whisper.audio import decode_audio
        from .models import local_path
        audio = decode_audio(str(local_path(audio_path)), sampling_rate=RATE)
        chunk = AudioChunk("SYSTEM", 0, audio, 0)
        rows = models.transcribe(chunk, "")
        turns = models.diarize(chunk, SpeakerRegistry(Session("검증")))
        report["text"] = ["".join(w["text"] for w in r["words"]).strip() for r in rows]
        report["speaker_count"] = len({t["speaker_id"] for t in turns if t["speaker_id"]})
    report["blocked_network_attempts"] = len(blocked_attempts)
    report["total_seconds"] = round(time.monotonic() - start, 2)
    return report


def check_ui() -> dict:
    """Check bundled Tcl/Tk and document assets using a hidden demo, no capture."""
    import tempfile
    from .ui import App
    with tempfile.TemporaryDirectory(prefix="meeting-check-") as folder:
        app = App(demo=True)
        app.withdraw()
        try:
            app.session_path = Path(folder) / "session.json"
            app.session.finish()
            app.save_export()
            deadline = time.monotonic() + 30
            while app.exporting and time.monotonic() < deadline:
                app.update()
                time.sleep(.02)
            if app.exporting or not app.export_paths or not app.export_paths[1]:
                raise RuntimeError(f"UI document check failed: {app.status.get()}")
            md, pdf = app.export_paths
            assert "MIC" in md.read_text(encoding="utf-8")
            assert pdf.read_bytes().startswith(b"%PDF")
            return {"transcript_rows": len(app.transcript.get_children()),
                "speaker_rows": len(app.speaker_tree.get_children()),
                "markdown_bytes": md.stat().st_size, "pdf_bytes": pdf.stat().st_size}
        finally:
            app.destroy()
