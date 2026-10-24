"""On-disk version store + optimization-path log for the self-evolve loop.

Each iteration of the loop produces a candidate config; this module persists the
full record (config-as-dict, train/val metrics, hypothesis, kept flag,
attribution, …) under ``<base_dir>/versions/<v_id>/version.json`` and appends a
compact one-line summary to ``<base_dir>/versions/path_log.jsonl`` so the
*optimization path* (which hypotheses were tried, their validation Sharpe, and
whether they were kept) is replayable end-to-end.

Design:

* **Writes create dirs and are atomic-ish enough** for a single-process loop —
  plain ``json.dump`` with ``indent=2``.
* **Reads are best-effort.** A missing ``base_dir`` (or a missing version / a
  truncated log line) never crashes: the reader returns the empty value
  (``[]`` / ``{}``) so the loop can bootstrap on a fresh directory.

Pure stdlib — no network, no pandas, no LLM.
"""

from __future__ import annotations

import json
from pathlib import Path


def _versions_dir(base_dir) -> Path:
    """``<base_dir>/versions`` as a :class:`Path` (not created here)."""
    return Path(base_dir) / "versions"


def write_version(base_dir, v_id: str, record: dict) -> str:
    """Write ``record`` as JSON to ``<base_dir>/versions/<v_id>/version.json``.

    Creates intermediate directories. ``record`` is whatever the loop wants to
    persist for this candidate (config-as-dict, ``train_metrics``,
    ``val_metrics``, ``hypothesis``, ``kept``, ``attribution``, …). Returns the
    absolute path of the written file as a string.
    """
    out_dir = _versions_dir(base_dir) / str(v_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "version.json"
    path.write_text(json.dumps(record, indent=2, sort_keys=False), encoding="utf-8")
    return str(path)


def read_version(base_dir, v_id) -> dict:
    """Read back the record written by :func:`write_version`.

    Best-effort: a missing dir / file / unreadable JSON returns ``{}`` rather
    than raising, so a caller probing a not-yet-written version degrades cleanly.
    """
    path = _versions_dir(base_dir) / str(v_id) / "version.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, NotADirectoryError, OSError, ValueError):
        return {}


def append_path_log(base_dir, entry: dict) -> None:
    """Append one ``entry`` (as a single JSON line) to ``path_log.jsonl``.

    The log records the optimization path — typically ``{v_id, hypothesis,
    val_sharpe, kept}`` — one object per line so it streams and tails cleanly.
    Creates the ``versions`` directory if needed.
    """
    vdir = _versions_dir(base_dir)
    vdir.mkdir(parents=True, exist_ok=True)
    line = json.dumps(entry, sort_keys=False)
    with (vdir / "path_log.jsonl").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def read_path_log(base_dir) -> list[dict]:
    """Return every :func:`append_path_log` entry, in append order.

    Best-effort: a missing log returns ``[]``; a blank or unparseable line is
    skipped rather than crashing the whole read.
    """
    path = _versions_dir(base_dir) / "path_log.jsonl"
    try:
        raw = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []
    out: list[dict] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def list_versions(base_dir) -> list[str]:
    """Return the sorted ids of versions present under ``<base_dir>/versions``.

    A version id is any immediate sub-directory that holds a ``version.json``.
    A missing ``base_dir`` returns ``[]``.
    """
    vdir = _versions_dir(base_dir)
    try:
        children = list(vdir.iterdir())
    except (FileNotFoundError, NotADirectoryError, OSError):
        return []
    ids = [c.name for c in children if c.is_dir() and (c / "version.json").is_file()]
    return sorted(ids)
