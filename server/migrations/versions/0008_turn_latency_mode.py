"""turn_latency mode

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0008"
down_revision: str | Sequence[str] | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """글 대화 턴의 서버 구간 기록(M5-16): 음성 행과 구분하는 mode 열. 기존 행은 모두 음성이다."""
    with op.batch_alter_table("turn_latency", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("mode", sa.String(length=8), server_default="voice", nullable=False)
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("turn_latency", schema=None) as batch_op:
        batch_op.drop_column("mode")
