"""Verified accounts, session revocation and hashed one-time security tokens."""

from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision = "d94a23e71f58"
down_revision = "c83f12d60e47"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("auth_version", sa.Integer(), nullable=False, server_default="0")
        )
        batch.create_check_constraint("ck_user_auth_version", "auth_version >= 0")
    users = sa.table("users", sa.column("email_verified_at", sa.DateTime(timezone=True)))
    # Grandfather existing accounts without touching credentials or audit timestamps.
    op.get_bind().execute(users.update().values(email_verified_at=datetime.now(timezone.utc)))
    op.create_table(
        "account_tokens",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')", name="ck_account_token_purpose"
        ),
    )
    op.create_index("ix_account_tokens_user_purpose", "account_tokens", ["user_id", "purpose"])
    op.create_index("ix_account_tokens_expires_at", "account_tokens", ["expires_at"])


def downgrade():
    raise RuntimeError(
        "v0.4 security state cannot be downgraded safely. Restore a compatible pre-upgrade backup instead."
    )
