"""PyInstaller entry point. Errors contain no credential values or HTTP payloads."""
import sys
import os

if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

try:
    from loldraft.desktop import main
    main()
except Exception:
    if getattr(sys, "frozen", False):
        if any(flag in sys.argv for flag in ("--serve", "--diagnose", "--verify-runtime", "--no-browser")):
            import traceback
            traceback.print_exc()
            for flag in ("--diagnose", "--verify-runtime"):
                if flag in sys.argv:
                    from pathlib import Path
                    report = Path(sys.argv[sys.argv.index(flag) + 1])
                    report.with_suffix(".error.txt").write_text(traceback.format_exc(), encoding="utf-8")
            raise SystemExit(1) from None
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            None, "League Draft Lab could not start. If an older server is running, close it and retry. "
            "Run Start.cmd from Windows Explorer. Diagnostics are in your private LeagueDraftLab/logs folder.",
            "League Draft Lab", 0x10)
        raise SystemExit(1) from None
    raise
