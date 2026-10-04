"""Initial study planner schema"""

import sqlalchemy as sa

from alembic import op

revision = "8884a9a3ad86"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("units", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("department", sa.String(length=160), nullable=True),
        sa.Column("prerequisite_text", sa.Text(), nullable=True),
        sa.Column("corequisite_text", sa.Text(), nullable=True),
        sa.Column("antirequisite_text", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=500), nullable=True),
        sa.Column("outline_url", sa.String(length=500), nullable=True),
        sa.Column("source_academic_year", sa.String(length=9), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("data_status", sa.String(length=30), nullable=False),
        sa.CheckConstraint("units >= 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_courses_code"), ["code"], unique=True)

    op.create_table(
        "student_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("admission_year", sa.String(length=7), nullable=False),
        sa.Column("programme_name", sa.String(length=200), nullable=False),
        sa.Column("minor_name", sa.String(length=200), nullable=True),
        sa.Column("required_total_units", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("curriculum_key", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("id = 1", name="single_active_profile"),
        sa.CheckConstraint("required_total_units > 0"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "terms",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("study_year", sa.Integer(), nullable=False),
        sa.Column("term_type", sa.String(length=20), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_exchange", sa.Boolean(), nullable=False),
        sa.Column("host_university", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("term_type IN ('semester_1', 'semester_2', 'summer')"),
        sa.CheckConstraint("study_year BETWEEN 1 AND 4"),
        sa.ForeignKeyConstraint(["profile_id"], ["student_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("profile_id", "sort_order"),
        sa.UniqueConstraint("profile_id", "study_year", "term_type"),
    )
    op.create_table(
        "exchange_courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.Column("host_course_code", sa.String(length=80), nullable=True),
        sa.Column("host_course_title", sa.String(length=240), nullable=False),
        sa.Column("host_units", sa.Numeric(precision=8, scale=2), nullable=True),
        sa.Column("host_grade", sa.String(length=40), nullable=True),
        sa.Column("hkbu_equivalent_course_id", sa.Integer(), nullable=True),
        sa.Column("hkbu_equivalent_code", sa.String(length=20), nullable=True),
        sa.Column("hkbu_equivalent_title", sa.String(length=240), nullable=True),
        sa.Column("transferred_units", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("requirement_group", sa.String(length=100), nullable=False),
        sa.Column("transfer_status", sa.String(length=20), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("transfer_status IN ('planned', 'pending_approval', 'approved')"),
        sa.CheckConstraint("host_units IS NULL OR host_units >= 0"),
        sa.CheckConstraint("transferred_units >= 0"),
        sa.ForeignKeyConstraint(["hkbu_equivalent_course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("exchange_courses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_exchange_courses_term_id"), ["term_id"], unique=False)

    op.create_table(
        "plan_courses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("term_id", sa.Integer(), nullable=False),
        sa.Column("course_id", sa.Integer(), nullable=True),
        sa.Column("course_code_snapshot", sa.String(length=20), nullable=False),
        sa.Column("course_title_snapshot", sa.String(length=240), nullable=False),
        sa.Column("units", sa.Numeric(precision=8, scale=2), nullable=False),
        sa.Column("requirement_group", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("grade", sa.String(length=3), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'withdrawn')"),
        sa.CheckConstraint("units >= 0"),
        sa.ForeignKeyConstraint(["course_id"], ["courses.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["term_id"], ["terms.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("plan_courses", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_plan_courses_term_id"), ["term_id"], unique=False)


def downgrade():
    with op.batch_alter_table("plan_courses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_plan_courses_term_id"))

    op.drop_table("plan_courses")
    with op.batch_alter_table("exchange_courses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_exchange_courses_term_id"))

    op.drop_table("exchange_courses")
    op.drop_table("terms")
    op.drop_table("student_profiles")
    with op.batch_alter_table("courses", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_courses_code"))

    op.drop_table("courses")
