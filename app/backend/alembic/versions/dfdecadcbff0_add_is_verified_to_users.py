"""add is_verified to users

deploy P2-B1: password signups must verify their email before using the app
(gated by REQUIRE_EMAIL_VERIFICATION). Adds ``users.is_verified`` (bool, NOT
NULL, server_default false) so existing rows backfill to unverified; OAuth
users are set True by the callback. Additive + SQLite/Postgres safe via
batch_alter_table.

Revision ID: dfdecadcbff0
Revises: 58ae3db295eb
Create Date: 2026-06-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "dfdecadcbff0"
down_revision: Union[str, None] = "58ae3db295eb"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add users.is_verified (NOT NULL, server_default false)."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(
            sa.Column(
                "is_verified",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            )
        )


def downgrade() -> None:
    """Drop users.is_verified."""
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("is_verified")
