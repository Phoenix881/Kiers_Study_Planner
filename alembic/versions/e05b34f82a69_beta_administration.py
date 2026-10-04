"""Private administration, account state and deletion-safe user identities."""

import sqlalchemy as sa

from alembic import op

revision = "e05b34f82a69"
down_revision = "d94a23e71f58"
branch_labels = None
depends_on = None


def upgrade():
    # Never reuse a deleted user's ID: old signed cookies must not match a new account.
    with op.batch_alter_table(
        "users", recreate="always", table_kwargs={"sqlite_autoincrement": True}
    ) as batch:
        batch.add_column(sa.Column("is_admin", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("disabled_reason", sa.String(500), nullable=True))
        batch.add_column(sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
        batch.create_check_constraint("ck_user_admin", "is_admin IN (0, 1)")
        batch.create_check_constraint("ck_user_disabled", "is_disabled IN (0, 1)")
        batch.create_check_constraint(
            "ck_user_disabled_reason", "disabled_reason IS NULL OR length(disabled_reason) <= 500"
        )
    op.create_table(
        "admin_audit_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "admin_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("admin_username_snapshot", sa.String(80), nullable=False),
        sa.Column(
            "target_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("target_username_snapshot", sa.String(80), nullable=False),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("details", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('send_verification', 'send_password_reset', 'revoke_sessions', 'disable_user', 'enable_user', 'delete_user', 'grant_admin', 'revoke_admin')",
            name="ck_admin_audit_action",
        ),
        sa.CheckConstraint(
            "details IS NULL OR length(details) <= 500", name="ck_admin_audit_details"
        ),
    )
    op.create_index("ix_admin_audit_log_admin_user_id", "admin_audit_log", ["admin_user_id"])
    op.create_index("ix_admin_audit_log_target_user_id", "admin_audit_log", ["target_user_id"])
    op.create_index("ix_admin_audit_created_id", "admin_audit_log", ["created_at", "id"])


def downgrade():
    raise RuntimeError(
        "v0.5 account state and audit history cannot be downgraded safely. Restore a compatible backup and application version."
    )
