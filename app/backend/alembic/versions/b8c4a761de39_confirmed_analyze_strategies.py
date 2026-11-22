"""Keep a draft's Analyze origin and the exact revision used by its backtest."""
import sqlalchemy as sa
from alembic import op

revision = "b8c4a761de39"
down_revision = "a419c6de203f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("strategies") as table:
        table.add_column(sa.Column("source_report_id", sa.Integer))
        table.add_column(sa.Column("source_scan_result_id", sa.Integer))
        table.add_column(sa.Column("universe_snapshot_id", sa.Integer))
        table.add_column(sa.Column("draft_report_id", sa.Integer))
        table.create_foreign_key("fk_strategy_universe", "universe_snapshots", ["universe_snapshot_id"], ["id"])
        table.create_foreign_key("fk_strategy_draft_report", "research_reports", ["draft_report_id"], ["id"], ondelete="SET NULL")
        table.create_unique_constraint("uq_strategy_draft_report", ["draft_report_id"])
    op.create_table(
        "confirmed_strategy_revisions",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("strategy_id", sa.Integer, sa.ForeignKey("strategies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("spec_json", sa.JSON, nullable=False),
        sa.Column("source_report_id", sa.Integer, nullable=False),
        sa.Column("source_scan_result_id", sa.Integer, nullable=False),
        sa.Column("universe_snapshot_id", sa.Integer, sa.ForeignKey("universe_snapshots.id"), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("strategy_id", "version", name="uq_confirmed_strategy_version"),
    )
    with op.batch_alter_table("backtests") as table:
        table.add_column(sa.Column("confirmed_revision_id", sa.Integer))
        table.create_foreign_key("fk_backtest_confirmed_revision", "confirmed_strategy_revisions",
                                 ["confirmed_revision_id"], ["id"], ondelete="CASCADE")
        table.create_unique_constraint("uq_backtest_confirmed_revision", ["confirmed_revision_id"])


def downgrade():
    naming = {"fk": "fk_%(table_name)s_%(column_0_name)s", "uq": "uq_%(table_name)s_%(column_0_name)s"}
    with op.batch_alter_table("backtests", naming_convention=naming) as table:
        table.drop_column("confirmed_revision_id")
    op.drop_table("confirmed_strategy_revisions")
    with op.batch_alter_table("strategies", naming_convention=naming) as table:
        for field in ("draft_report_id", "universe_snapshot_id", "source_scan_result_id", "source_report_id"):
            table.drop_column(field)
