from __future__ import annotations

import argparse
import json
import multiprocessing
import sys
from pathlib import Path


def main():
    multiprocessing.freeze_support()
    from meeting_app import runtime_log
    runtime_log.start()
    from meeting_app.privacy import install_offline_guard
    install_offline_guard()
    parser = argparse.ArgumentParser(description="Standalone Meeting Transcriber")
    parser.add_argument("--demo", action="store_true", help="Show a UI example without recording")
    parser.add_argument("--devices", action="store_true", help="List WASAPI devices without recording")
    parser.add_argument("--self-check", action="store_true", help="Load local runtime without recording")
    parser.add_argument("--check-ui", action="store_true", help="Also check hidden demo UI and PDF export")
    parser.add_argument("--check-audio", type=Path, help="Optional local audio fixture for self-check")
    parser.add_argument("--report", type=Path, help="Write diagnostic JSON locally")
    args = parser.parse_args()
    if args.self_check:
        from meeting_app.diagnostics import run
        from meeting_app.session import atomic_text
        from meeting_app.models import local_path
        result = run(args.check_audio)
        if args.check_ui:
            from meeting_app.diagnostics import check_ui
            result["ui"] = check_ui()
        if args.report:
            atomic_text(local_path(args.report), json.dumps(result, ensure_ascii=False, indent=2))
        elif sys.stdout:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return
    if args.devices:
        from dataclasses import asdict
        from meeting_app.audio import list_devices
        mics, outputs = list_devices()
        print(json.dumps({"microphones": [asdict(d) for d in mics], "outputs": [asdict(d) for d in outputs]}, ensure_ascii=False, indent=2))
        return
    from meeting_app.ui import App
    App(demo=args.demo).mainloop()


if __name__ == "__main__":
    from meeting_app import runtime_log
    try:
        main()
    except Exception as exc:
        runtime_log.failure("startup", exc)
        error_path = runtime_log.path()
        runtime_log.finish("error")
        if sys.stderr:
            print("Application failed. See the operational log for an error category.", file=sys.stderr)
        elif "--self-check" not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, f"프로그램을 실행할 수 없습니다. 오류 기록: {error_path}", "로컬 회의 기록", 16)
        raise SystemExit(1)
