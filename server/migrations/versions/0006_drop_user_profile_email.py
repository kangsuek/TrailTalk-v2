"""drop user_profile email

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-02 15:59:43.483165

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006"
down_revision: str | Sequence[str] | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """이메일 기능 제거(FR-21, 2026-11-02): 프로필의 본인 주소 열을 지운다."""
    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.drop_column("email")


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("user_profile", schema=None) as batch_op:
        batch_op.add_column(sa.Column("email", sa.String(length=254), nullable=True))
