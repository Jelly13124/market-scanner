"""Preserve Screener selections, Scanner executions and report provenance."""
import sqlalchemy as sa
from alembic import op

revision = 'a419c6de203f'
down_revision = 'd7e3f901b625'
branch_labels = None
depends_on = None

# Fresh ORM installs and incrementally migrated installs can have different
# names for the original scanner_configs → user_watchlists constraint.
_NAMING = {'fk': 'fk_%(table_name)s_%(column_0_name)s'}


def replace_watchlist_fk(ondelete):
    keys = sa.inspect(op.get_bind()).get_foreign_keys('scanner_configs')
    old = next(key for key in keys if key['constrained_columns'] == ['user_watchlist_id'])
    with op.batch_alter_table('scanner_configs', naming_convention=_NAMING) as table:
        table.drop_constraint(old['name'] or 'fk_scanner_configs_user_watchlist_id', type_='foreignkey')
        table.create_foreign_key('fk_scanner_configs_user_watchlist', 'user_watchlists',
                                 ['user_watchlist_id'], ['id'], ondelete=ondelete)


def upgrade():
    op.create_table(
        'universe_snapshots',
        sa.Column('id', sa.Integer, primary_key=True),
        sa.Column('user_id', sa.BigInteger().with_variant(sa.Integer, 'sqlite'), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('origin', sa.String(20), nullable=False),
        sa.Column('market', sa.String(12), nullable=False),
        sa.Column('tickers', sa.JSON, nullable=False),
        sa.Column('filters', sa.JSON),
        sa.Column('filter_version', sa.String(32)),
        sa.Column('screener_snapshot_date', sa.Date),
        sa.Column('selected_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('source_watchlist_id', sa.Integer, sa.ForeignKey('user_watchlists.id', ondelete='SET NULL')),
        sa.Column('source_snapshot_id', sa.Integer, sa.ForeignKey('universe_snapshots.id')),
    )
    for field in ('user_id', 'source_watchlist_id', 'source_snapshot_id'):
        op.create_index(f'ix_universe_snapshots_{field}', 'universe_snapshots', [field])
    with op.batch_alter_table('user_watchlists') as table:
        table.add_column(sa.Column('latest_selection_id', sa.Integer))
        table.create_foreign_key('fk_watchlist_selection', 'universe_snapshots', ['latest_selection_id'], ['id'])
    with op.batch_alter_table('scan_runs') as table:
        table.add_column(sa.Column('universe_snapshot_id', sa.Integer))
        table.create_foreign_key('fk_run_universe', 'universe_snapshots', ['universe_snapshot_id'], ['id'])
        table.create_index('ix_scan_runs_universe_snapshot_id', ['universe_snapshot_id'])
        table.add_column(sa.Column('detector_config', sa.JSON))
        table.add_column(sa.Column('outcomes', sa.JSON))
    with op.batch_alter_table('research_reports') as table:
        table.add_column(sa.Column('source_scan_result_id', sa.Integer))
        table.create_foreign_key('fk_report_scan_result', 'watchlist_entries', ['source_scan_result_id'], ['id'], ondelete='SET NULL')
        table.create_index('ix_research_reports_source_scan_result_id', ['source_scan_result_id'])
    op.add_column('scanner_configs', sa.Column('archived_at', sa.DateTime(timezone=True)))
    replace_watchlist_fk('SET NULL')


def downgrade():
    replace_watchlist_fk(None)
    op.drop_column('scanner_configs', 'archived_at')
    with op.batch_alter_table('research_reports') as table:
        table.drop_index('ix_research_reports_source_scan_result_id')
        table.drop_constraint('fk_report_scan_result', type_='foreignkey')
        table.drop_column('source_scan_result_id')
    with op.batch_alter_table('scan_runs') as table:
        table.drop_index('ix_scan_runs_universe_snapshot_id')
        table.drop_constraint('fk_run_universe', type_='foreignkey')
        for field in ('outcomes', 'detector_config', 'universe_snapshot_id'):
            table.drop_column(field)
    with op.batch_alter_table('user_watchlists') as table:
        table.drop_constraint('fk_watchlist_selection', type_='foreignkey')
        table.drop_column('latest_selection_id')
    op.drop_table('universe_snapshots')
