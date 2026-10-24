"""PostToolUse hook: auto-format edited Python files with black.

Runs after Edit/Write. Reads the tool_input.file_path, and if it's a .py
file under this repo, runs `python -m black --quiet` on it. Best-effort:
any failure is logged to stderr but never blocks (exit 0 always).

Uses the Anaconda interpreter explicitly because poetry/python are not on
PATH in this environment (see CLAUDE.md).
"""

import json
import os
import subprocess
import sys

PYTHON = r"C:\Users\Jerry\anaconda3\python.exe"


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    file_path = (data.get("tool_input") or {}).get("file_path", "") or ""
    if not isinstance(file_path, str) or not file_path.endswith(".py"):
        return 0
    if not os.path.isfile(file_path):
        return 0

    try:
        subprocess.run(
            [PYTHON, "-m", "black", "--quiet", file_path],
            timeout=30,
            capture_output=True,
        )
    except Exception as e:  # noqa: BLE001 - best-effort, never wedge
        sys.stderr.write(f"format_python: black skipped for {file_path}: {e}\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
