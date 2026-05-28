"""PreToolUse guard for Bash/PowerShell commands.

Blocks two things the project explicitly forbids (see CLAUDE.md):
  1. --no-verify  (skipping pre-commit / commit hooks)
  2. Co-Authored-By: trailers in git commits (project strips these via
     filter-repo; new commits must not reintroduce them)

Exit code 2 = block the tool call and surface stderr to Claude.
Any parse error or unexpected shape -> exit 0 (fail open, never wedge the agent).
"""

import json
import sys


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    cmd = (data.get("tool_input") or {}).get("command", "") or ""
    if not isinstance(cmd, str):
        return 0

    violations = []
    if "--no-verify" in cmd:
        violations.append(
            "--no-verify is forbidden (CLAUDE.md: never skip pre-commit hooks). "
            "Fix the underlying hook failure instead."
        )
    if "Co-Authored-By:" in cmd and "git commit" in cmd:
        violations.append(
            "Co-Authored-By: trailer is forbidden. The project strips these via "
            "filter-repo; commit with subject + body only."
        )

    if violations:
        sys.stderr.write(
            "BLOCKED by .claude/hooks/block_dangerous_git.py:\n"
            + "\n".join(f"  - {v}" for v in violations)
            + "\n"
        )
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
