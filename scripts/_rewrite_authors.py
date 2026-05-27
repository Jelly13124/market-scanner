"""One-off rewrite: collapse all commit authors to Jelly13124 and strip
the 'Co-Authored-By:' trailers so the GitHub Contributors sidebar shows
only the repo owner.

Run from repo root:
    C:/Users/Jerry/anaconda3/python.exe scripts/_rewrite_authors.py

After this finishes:
    git remote add origin https://github.com/Jelly13124/market-scanner.git
    git push origin main --force
"""
from __future__ import annotations

import re
import sys

from git_filter_repo import FilteringOptions, RepoFilter


NAME = b"Jelly13124"
EMAIL = b"ruizheyuan3487@gmail.com"

_COAUTHOR_RE = re.compile(rb"^\s*Co-Authored-By:.*\r?\n?", re.MULTILINE | re.IGNORECASE)
_TRAILING_BLANKS_RE = re.compile(rb"\n{3,}$")


def commit_cb(commit, _metadata):
    commit.author_name = NAME
    commit.author_email = EMAIL
    commit.committer_name = NAME
    commit.committer_email = EMAIL
    msg = _COAUTHOR_RE.sub(b"", commit.message)
    msg = _TRAILING_BLANKS_RE.sub(b"\n", msg)
    commit.message = msg.rstrip(b"\n") + b"\n"


def main() -> int:
    args = FilteringOptions.parse_args(["--force"])
    RepoFilter(args, commit_callback=commit_cb).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
