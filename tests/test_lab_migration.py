"""Phase 6D: smoke check that the c3e7f9d2b8a4_add_lab_tables alembic
migration upgrades + downgrades cleanly on a throwaway sqlite DB.

We stamp a fresh DB at the down_revision (a1b2c3d4e5f6) without running
the legacy hedge-fund-flow migrations (some of which fail on fresh
sqlite due to duplicate-index bugs that pre-date Phase 6). Then we
exercise just our migration's up → down → up cycle.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect


REPO_ROOT = Path(__file__).resolve().parents[1]
ALEMBIC_DIR = REPO_ROOT / "app" / "backend" / "alembic"
INI_PATH = REPO_ROOT / "app" / "backend" / "alembic.ini"

DOWN_REVISION = "a1b2c3d4e5f6"
NEW_REVISION = "c3e7f9d2b8a4"


def _build_cfg(db_url: str) -> Config:
    cfg = Config(str(INI_PATH))
    # alembic.ini uses a relative script_location ("alembic"); resolve absolute
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    cfg.set_main_option("sqlalchemy.url", db_url)
    return cfg


def _table_names(db_url: str) -> set[str]:
    engine = create_engine(db_url)
    try:
        return set(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_lab_migration_upgrade_then_downgrade_then_upgrade():
    """Stamp at down_revision, exercise our migration up/down/up."""
    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "test_lab_migration.db"
        db_url = f"sqlite:///{db_path}"
        cfg = _build_cfg(db_url)

        # Stamp DB at our migration's down_revision without actually running
        # the legacy migrations. This lets us test just c3e7f9d2b8a4 in
        # isolation. (Legacy migration 3f9a6b7c8d2e has a duplicate-index
        # bug on fresh sqlite that is unrelated to Phase 6.)
        command.stamp(cfg, DOWN_REVISION)

        # Upgrade just c3e7f9d2b8a4
        command.upgrade(cfg, NEW_REVISION)
        tables = _table_names(db_url)
        assert {"strategies", "lab_chat_messages", "backtests"}.issubset(tables)

        # Downgrade -1 should drop all 3 lab tables
        command.downgrade(cfg, "-1")
        tables_after_down = _table_names(db_url)
        for t in ("strategies", "lab_chat_messages", "backtests"):
            assert t not in tables_after_down, f"{t} still exists after downgrade"

        # Re-apply: must succeed
        command.upgrade(cfg, NEW_REVISION)
        tables_after_reup = _table_names(db_url)
        assert {"strategies", "lab_chat_messages", "backtests"}.issubset(tables_after_reup)


def test_lab_migration_chains_from_a1b2c3d4e5f6():
    """Static check: the new migration's down_revision MUST be the
    pre-Phase-6 head (a1b2c3d4e5f6). If this fails, the chain is broken."""
    from alembic.script import ScriptDirectory

    cfg = Config(str(INI_PATH))
    cfg.set_main_option("script_location", str(ALEMBIC_DIR))
    script = ScriptDirectory.from_config(cfg)
    rev = script.get_revision(NEW_REVISION)
    assert rev is not None, f"revision {NEW_REVISION} not found"
    assert rev.down_revision == DOWN_REVISION, (
        f"down_revision is {rev.down_revision!r}, expected {DOWN_REVISION!r}"
    )
