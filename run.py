from __future__ import annotations

import subprocess
import sys
import time
import webbrowser


def main() -> int:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "main:app", "--port", "8000"],
        stdout=None,
        stderr=None,
    )
    try:
        time.sleep(1.5)
        webbrowser.open("http://127.0.0.1:8000")
        return proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
