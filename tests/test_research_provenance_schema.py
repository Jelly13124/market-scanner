"""Upgrade an existing installation and keep its original rows and evidence."""
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.backend.database.models import Base


def test_upgrade_keeps_legacy_rows_and_selection_when_watchlist_is_deleted():
    engine = sa.create_engine('sqlite://')
    scripts = ScriptDirectory('app/backend/alembic')
    with engine.begin() as conn:
        for table in ('users', 'user_watchlists', 'watchlist_entries', 'scan_runs', 'research_reports'):
            conn.exec_driver_sql(f'CREATE TABLE {table} (id INTEGER PRIMARY KEY)')
            conn.exec_driver_sql(f'INSERT INTO {table} VALUES (1)')
        conn.exec_driver_sql('CREATE TABLE scanner_configs (id INTEGER PRIMARY KEY, user_watchlist_id INTEGER REFERENCES user_watchlists(id))')
        conn.exec_driver_sql('INSERT INTO scanner_configs VALUES (1,1)')
        revisions = list(reversed(list(scripts.iterate_revisions('a419c6de203f', 'd7e3f901b625'))))
        with Operations.context(MigrationContext.configure(conn)):
            for revision in revisions:
                revision.module.upgrade()
        assert 'universe_snapshots' in sa.inspect(conn).get_table_names()
        assert conn.exec_driver_sql('SELECT source_scan_result_id FROM research_reports WHERE id=1').scalar_one() is None
        assert conn.exec_driver_sql('SELECT universe_snapshot_id FROM scan_runs WHERE id=1').scalar_one() is None
        assert conn.exec_driver_sql('SELECT latest_selection_id FROM user_watchlists WHERE id=1').scalar_one() is None

    with engine.begin() as conn:
        conn.exec_driver_sql('PRAGMA foreign_keys=ON')
        conn.exec_driver_sql("""INSERT INTO universe_snapshots (id,user_id,origin,market,tickers,source_watchlist_id)
                             VALUES (1,1,'screener','us','["AAPL"]',1)""")
        conn.exec_driver_sql('UPDATE user_watchlists SET latest_selection_id=1 WHERE id=1')
        conn.exec_driver_sql('DELETE FROM user_watchlists WHERE id=1')
        assert conn.exec_driver_sql('SELECT tickers,source_watchlist_id FROM universe_snapshots').one() == ('["AAPL"]', None)
        assert conn.exec_driver_sql('SELECT user_watchlist_id FROM scanner_configs').scalar_one() is None


def test_new_database_has_same_links_as_upgraded_database():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    inspector = sa.inspect(engine)
    assert 'universe_snapshots' in inspector.get_table_names()
    for table, column, target in [
        ('research_reports','source_scan_result_id','watchlist_entries'),
        ('scan_runs','universe_snapshot_id','universe_snapshots'),
        ('user_watchlists','latest_selection_id','universe_snapshots'),
        ('universe_snapshots','source_snapshot_id','universe_snapshots'),
    ]:
        assert any(key['constrained_columns'] == [column] and key['referred_table'] == target
                   for key in inspector.get_foreign_keys(table))


def test_fresh_schema_can_downgrade_like_a_migrated_installation():
    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    scripts = ScriptDirectory('app/backend/alembic')
    with engine.begin() as conn, Operations.context(MigrationContext.configure(conn)):
        scripts.get_revision('a419c6de203f').module.downgrade()
        assert 'universe_snapshots' not in sa.inspect(conn).get_table_names()


def test_run_status_query_does_not_read_full_universe_evidence():
    from sqlalchemy.orm import Session
    from app.backend.database.models import ScanRun
    from app.backend.repositories.scanner_repository import ScanRunRepository

    engine = sa.create_engine('sqlite://')
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ScanRun(config_id=1, status='COMPLETE', outcomes={'AAPL': {'selected': True}}))
        db.commit()
        row = ScanRunRepository(db).get_latest_for_config(1)
        assert 'outcomes' in sa.inspect(row).unloaded
        assert row.outcomes['AAPL']['selected']
