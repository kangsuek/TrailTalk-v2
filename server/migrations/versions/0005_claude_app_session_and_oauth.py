"""claude app session and oauth

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-30 13:40:09.593413

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005"
down_revision: str | Sequence[str] | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        "oauth_client",
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("info", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("client_id", name=op.f("pk_oauth_client")),
    )
    op.create_table(
        "oauth_code",
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("data", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("code_hash", name=op.f("pk_oauth_code")),
    )
    op.create_table(
        "oauth_pending",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("params", sa.Text(), nullable=False),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_pending")),
    )
    op.create_table(
        "oauth_token",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("family_id", sa.String(length=32), nullable=False),
        sa.Column("client_id", sa.String(length=64), nullable=False),
        sa.Column("scopes", sa.String(length=200), nullable=False),
        sa.Column("resource", sa.String(length=300), nullable=True),
        sa.Column("expires_at", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("token_hash", name=op.f("pk_oauth_token")),
    )
    with op.batch_alter_table("oauth_token", schema=None) as batch_op:
        batch_op.create_index("ix_oauth_token_family_id", ["family_id"], unique=False)

    with op.batch_alter_table("conversation_session", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "app_kind",
                sa.Enum(
                    "journal",
                    "memo",
                    name="app_kind",
                    native_enum=False,
                    create_constraint=True,
                    length=16,
                ),
                nullable=True,
            )
        )
        batch_op.add_column(sa.Column("app_day", sa.Date(), nullable=True))
        # mode의 열거 CHECK에 claude_app을 더한다(열거 CHECK 변경은 batch로 직접 교체한다)
        batch_op.drop_constraint("session_mode", type_="check")
        batch_op.create_check_constraint(
            "session_mode",
            "mode IN ('text', 'voice', 'claude_app')",
        )
        batch_op.create_index(
            "uq_app_journal_day_title",
            ["app_day", "title"],
            unique=True,
            sqlite_where=sa.text("app_kind = 'journal'"),
        )
        batch_op.create_index(
            "uq_app_memo_day", ["app_day"], unique=True, sqlite_where=sa.text("app_kind = 'memo'")
        )


def downgrade() -> None:
    """Downgrade schema."""
    # claude_app 세션은 옛 열거값에 없으므로 먼저 지운다(노트·턴은 외래 키 CASCADE)
    op.execute("DELETE FROM conversation_session WHERE mode = 'claude_app'")
    # 부분 인덱스가 app_kind를 참조하므로 열을 지우기 전에 먼저 지운다
    op.drop_index("uq_app_memo_day", table_name="conversation_session")
    op.drop_index("uq_app_journal_day_title", table_name="conversation_session")
    with op.batch_alter_table("conversation_session", schema=None) as batch_op:
        batch_op.drop_constraint("session_mode", type_="check")
        batch_op.create_check_constraint("session_mode", "mode IN ('text', 'voice')")
        batch_op.drop_constraint("app_kind", type_="check")
        batch_op.drop_column("app_day")
        batch_op.drop_column("app_kind")

    with op.batch_alter_table("oauth_token", schema=None) as batch_op:
        batch_op.drop_index("ix_oauth_token_family_id")

    op.drop_table("oauth_token")
    op.drop_table("oauth_pending")
    op.drop_table("oauth_code")
    op.drop_table("oauth_client")
