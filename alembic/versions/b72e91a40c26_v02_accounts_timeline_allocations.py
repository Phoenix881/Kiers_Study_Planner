"""Accounts, flexible timeline, manual targets and versioned catalogue.

Revision ID: b72e91a40c26
Revises: 8884a9a3ad86
"""

from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision = "b72e91a40c26"
down_revision = "8884a9a3ad86"
branch_labels = None
depends_on = None


def pk():
    return sa.Column("id", sa.Integer(), primary_key=True)


def fk(name, target, delete="CASCADE", nullable=False):
    return sa.Column(name, sa.Integer(), sa.ForeignKey(target, ondelete=delete), nullable=nullable)


def col(name, type_, nullable=False):
    return sa.Column(name, type_, nullable=nullable)


def timestamps():
    return [
        col("created_at", sa.DateTime(timezone=True)),
        col("updated_at", sa.DateTime(timezone=True)),
    ]


def reflected(name):
    table = sa.Table(name, sa.MetaData(), autoload_with=op.get_bind())
    for index, constraint in enumerate(
        sorted(table.constraints, key=lambda c: str(getattr(c, "sqltext", "")))
    ):
        if isinstance(constraint, sa.CheckConstraint) and constraint.name is None:
            constraint.name = f"ck_{name}_{index}"
    return table


def upgrade():
    db = op.get_bind()
    if db.dialect.name == "sqlite" and db.exec_driver_sql("PRAGMA foreign_keys").scalar():
        raise RuntimeError(
            "SQLite batch migration requires foreign_keys=OFF before the transaction."
        )
    before = {
        name: db.execute(sa.text(f"SELECT id FROM {name} ORDER BY id")).scalars().all()
        for name in ("student_profiles", "terms", "courses", "plan_courses", "exchange_courses")
    }
    op.create_table(
        "users",
        pk(),
        col("email", sa.String(254)),
        col("username", sa.String(80)),
        col("password_hash", sa.String(255)),
        *timestamps(),
        sa.UniqueConstraint("email"),
        sa.UniqueConstraint("username"),
    )
    old = reflected("student_profiles")
    old.constraints = {c for c in old.constraints if c.name != "single_active_profile"}
    with op.batch_alter_table("student_profiles", copy_from=old, recreate="always") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_profile_user", "users", ["user_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_unique_constraint("uq_profile_user", ["user_id"])
        batch.alter_column("admission_year", type_=sa.String(9))
    op.create_table(
        "academic_years",
        pk(),
        fk("profile_id", "student_profiles.id"),
        col("academic_year", sa.String(9)),
        col("label", sa.String(160)),
        col("sort_order", sa.Integer()),
        col("notes", sa.Text(), True),
        sa.UniqueConstraint("profile_id", "sort_order"),
    )
    old = reflected("terms")
    old.constraints = {
        c
        for c in old.constraints
        if not isinstance(c, sa.CheckConstraint)
        and not (isinstance(c, sa.UniqueConstraint) and "study_year" in c.columns)
    }
    with op.batch_alter_table("terms", copy_from=old, recreate="always") as batch:
        batch.add_column(sa.Column("academic_year_id", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("name", sa.String(160), nullable=False, server_default="Semester 1")
        )
        batch.create_foreign_key(
            "fk_term_year", "academic_years", ["academic_year_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_terms_academic_year_id", ["academic_year_id"])
        batch.alter_column("study_year", nullable=True)
        batch.alter_column("term_type", type_=sa.String(80))
    profiles = (
        db.execute(sa.text("SELECT id, admission_year FROM student_profiles")).mappings().all()
    )
    years = reflected("academic_years")
    for profile in profiles:
        start = int(profile["admission_year"][:4])
        for study_year in db.execute(
            sa.text(
                "SELECT DISTINCT study_year FROM terms WHERE profile_id=:id ORDER BY study_year"
            ),
            {"id": profile["id"]},
        ).scalars():
            year = start + study_year - 1
            year_id = db.execute(
                years.insert().values(
                    profile_id=profile["id"],
                    academic_year=f"{year}/{year + 1}",
                    label=f"Year {study_year}",
                    sort_order=study_year - 1,
                )
            ).inserted_primary_key[0]
            db.execute(
                sa.text(
                    "UPDATE terms SET academic_year_id=:year, name=CASE term_type WHEN 'semester_1' THEN 'Semester 1' WHEN 'semester_2' THEN 'Semester 2' ELSE 'Summer Term' END WHERE profile_id=:profile AND study_year=:study"
                ),
                {"year": year_id, "profile": profile["id"], "study": study_year},
            )
    with op.batch_alter_table("terms") as batch:
        batch.alter_column("name", server_default=None)
    op.create_table(
        "requirement_groups",
        pk(),
        fk("profile_id", "student_profiles.id"),
        col("name", sa.String(100)),
        col("required_units", sa.Numeric(8, 2)),
        col("sort_order", sa.Integer()),
        col("notes", sa.Text(), True),
        *timestamps(),
        sa.UniqueConstraint("profile_id", "name"),
        sa.CheckConstraint("required_units >= 0"),
    )
    op.create_index("ix_requirement_groups_profile_id", "requirement_groups", ["profile_id"])
    op.create_table(
        "level_requirements",
        pk(),
        fk("profile_id", "student_profiles.id"),
        col("label", sa.String(160)),
        col("minimum_level", sa.Integer()),
        col("required_units", sa.Numeric(8, 2)),
        col("sort_order", sa.Integer()),
        sa.CheckConstraint("minimum_level >= 1"),
        sa.CheckConstraint("required_units >= 0"),
    )
    op.create_index("ix_level_requirements_profile_id", "level_requirements", ["profile_id"])
    for table, parent, key in [
        ("plan_course_allocations", "plan_courses", "plan_course_id"),
        ("exchange_course_allocations", "exchange_courses", "exchange_course_id"),
    ]:
        op.create_table(
            table,
            pk(),
            fk(key, f"{parent}.id"),
            fk("requirement_group_id", "requirement_groups.id"),
            col("allocated_units", sa.Numeric(8, 2)),
            sa.UniqueConstraint(key, "requirement_group_id"),
            sa.CheckConstraint("allocated_units >= 0"),
        )
        op.create_index(f"ix_{table}_requirement_group_id", table, ["requirement_group_id"])
    groups = reflected("requirement_groups")
    now = datetime.now(timezone.utc)
    for profile in profiles:
        group_ids = {}
        for table, allocations, key, units in [
            ("plan_courses", "plan_course_allocations", "plan_course_id", "units"),
            (
                "exchange_courses",
                "exchange_course_allocations",
                "exchange_course_id",
                "transferred_units",
            ),
        ]:
            rows = db.execute(
                sa.text(
                    f"SELECT c.id, c.requirement_group, c.{units} AS units FROM {table} c JOIN terms t ON c.term_id=t.id WHERE t.profile_id=:id ORDER BY c.id"
                ),
                {"id": profile["id"]},
            ).mappings()
            target = reflected(allocations)
            for row in rows:
                name = row["requirement_group"]
                if name not in group_ids:
                    group_ids[name] = db.execute(
                        groups.insert().values(
                            profile_id=profile["id"],
                            name=name,
                            required_units=0,
                            sort_order=len(group_ids),
                            notes="Migrated allocation name. Set your own target; legacy curriculum targets were not assumed.",
                            created_at=now,
                            updated_at=now,
                        )
                    ).inserted_primary_key[0]
                db.execute(
                    target.insert().values(
                        **{
                            key: row["id"],
                            "requirement_group_id": group_ids[name],
                            "allocated_units": row["units"],
                        }
                    )
                )
    op.create_table(
        "course_versions",
        pk(),
        fk("course_id", "courses.id"),
        col("academic_year", sa.String(9), True),
        col("title", sa.String(240)),
        col("units", sa.Numeric(8, 2)),
        col("level", sa.Integer(), True),
        col("department", sa.String(160), True),
        col("prerequisite_text", sa.Text(), True),
        col("corequisite_text", sa.Text(), True),
        col("antirequisite_text", sa.Text(), True),
        col("description", sa.Text(), True),
        col("source_url", sa.String(500), True),
        col("outline_url", sa.String(500), True),
        col("last_checked_at", sa.DateTime(timezone=True), True),
        col("data_status", sa.String(30)),
        sa.UniqueConstraint("course_id", "academic_year"),
        sa.CheckConstraint("units >= 0"),
    )
    columns = "title, units, level, department, prerequisite_text, corequisite_text, antirequisite_text, description, source_url, outline_url, last_checked_at, data_status"
    db.execute(
        sa.text(
            f"INSERT INTO course_versions (id, course_id, academic_year, {columns}) SELECT id, id, source_academic_year, {columns} FROM courses"
        )
    )
    with op.batch_alter_table("plan_courses", copy_from=reflected("plan_courses")) as batch:
        batch.add_column(sa.Column("course_version_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("level_snapshot", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column("exceptional_repeat", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch.create_foreign_key(
            "fk_attempt_version",
            "course_versions",
            ["course_version_id"],
            ["id"],
            ondelete="SET NULL",
        )
    with op.batch_alter_table("exchange_courses", copy_from=reflected("exchange_courses")) as batch:
        batch.add_column(sa.Column("level_snapshot", sa.Integer(), nullable=True))
    db.execute(
        sa.text(
            "UPDATE plan_courses SET course_version_id=course_id, level_snapshot=(SELECT level FROM courses WHERE courses.id=plan_courses.course_id)"
        )
    )
    db.execute(
        sa.text(
            "UPDATE exchange_courses SET level_snapshot=(SELECT level FROM courses WHERE courses.id=exchange_courses.hkbu_equivalent_course_id)"
        )
    )
    with op.batch_alter_table("plan_courses") as batch:
        batch.alter_column("exceptional_repeat", server_default=None)
    old = reflected("courses")
    old.constraints = {c for c in old.constraints if not isinstance(c, sa.CheckConstraint)}
    with op.batch_alter_table("courses", copy_from=old, recreate="always") as batch:
        for column in list(old.columns):
            if column.name not in {"id", "code"}:
                batch.drop_column(column.name)
    for name, ids in before.items():
        if db.execute(sa.text(f"SELECT id FROM {name} ORDER BY id")).scalars().all() != ids:
            raise RuntimeError(f"Migration changed record IDs in {name}")
    for table, parent in [
        ("plan_course_allocations", "plan_courses"),
        ("exchange_course_allocations", "exchange_courses"),
    ]:
        if db.execute(sa.text(f"SELECT count(*) FROM {table}")).scalar() != len(before[parent]):
            raise RuntimeError(f"Missing migrated allocations for {parent}")
    if db.dialect.name == "sqlite" and db.exec_driver_sql("PRAGMA foreign_key_check").all():
        raise RuntimeError("Migration failed foreign-key validation")


def downgrade():
    raise RuntimeError(
        "v0.2 cannot be downgraded losslessly: restore the pre-upgrade SQLite backup instead. No data was changed."
    )
