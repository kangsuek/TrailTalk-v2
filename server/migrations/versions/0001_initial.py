"""initial

Revision ID: 0001
Revises:
Create Date: 2026-10-22 17:16:01.206845

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "persona",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("yaml_path", sa.String(length=500), nullable=False),
        sa.Column("version", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_persona")),
    )
    op.create_table(
        "user_profile",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("nickname", sa.String(length=50), nullable=True),
        sa.Column("email", sa.String(length=254), nullable=True),
        sa.Column("interests", sa.JSON(), nullable=False),
        sa.Column("persona_id", sa.String(length=64), nullable=True),
        sa.Column("voice", sa.String(length=100), nullable=True),
        sa.Column("speaking_rate", sa.Float(), nullable=True),
        sa.Column("ack_enabled", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "chat_model",
            sa.Enum(
                "haiku",
                "sonnet",
                "opus",
                name="chat_model",
                native_enum=False,
                create_constraint=True,
                length=16,
            ),
            nullable=True,
        ),
        sa.Column("keep_audio", sa.Boolean(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name=op.f("ck_user_profile_single_row")),
        sa.ForeignKeyConstraint(
            ["persona_id"],
            ["persona.id"],
            name=op.f("fk_user_profile_persona_id_persona"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_profile")),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table("user_profile")
    op.drop_table("persona")
