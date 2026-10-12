from pathlib import Path
import os
import sys


def app_root() -> Path:
    return Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", app_root()))


def data_root() -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "StandaloneMeetingTranscriber"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_models() -> Path:
    return app_root() / "models"
