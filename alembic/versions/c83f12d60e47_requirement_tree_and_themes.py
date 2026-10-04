"""Requirement hierarchy and per-account themes; no network or snapshot changes."""

import sqlalchemy as sa

from alembic import op

revision = "c83f12d60e47"
down_revision = "b72e91a40c26"
branch_labels = None
depends_on = None


def upgrade():
    old = sa.Table("requirement_groups", sa.MetaData(), autoload_with=op.get_bind())
    # SQLite's original unnamed UNIQUE must be removed during batch reconstruction.
    old.constraints = {c for c in old.constraints if not isinstance(c, sa.UniqueConstraint)}
    for constraint in old.constraints:
        if isinstance(constraint, sa.CheckConstraint) and constraint.name is None:
            constraint.name = "ck_requirement_units"
    with op.batch_alter_table("requirement_groups", copy_from=old, recreate="always") as batch:
        batch.add_column(sa.Column("parent_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "aggregation_mode", sa.String(20), nullable=False, server_default="own_target"
            )
        )
        batch.create_foreign_key(
            "fk_requirement_parent",
            "requirement_groups",
            ["parent_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_check_constraint(
            "ck_requirement_not_self", "parent_id IS NULL OR parent_id != id"
        )
        batch.create_check_constraint(
            "ck_requirement_aggregation", "aggregation_mode IN ('own_target', 'sum_children')"
        )
        batch.create_index("ix_requirement_groups_parent_id", ["parent_id"])
        batch.create_index(
            "uq_requirement_root_name",
            ["profile_id", "name"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NULL"),
        )
        batch.create_index(
            "uq_requirement_child_name",
            ["profile_id", "parent_id", "name"],
            unique=True,
            sqlite_where=sa.text("parent_id IS NOT NULL"),
        )
    with op.batch_alter_table("users") as batch:
        batch.add_column(
            sa.Column("theme_preference", sa.String(10), nullable=False, server_default="system")
        )
        batch.create_check_constraint(
            "ck_user_theme", "theme_preference IN ('system', 'light', 'dark')"
        )


def downgrade():
    raise RuntimeError(
        "v0.3 cannot be downgraded losslessly. Restore the pre-upgrade backup instead; no data was changed."
    )
