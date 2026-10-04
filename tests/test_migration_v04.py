import sqlite3

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import RequirementGroup, StudentProfile, User
from app.services.seed import seed_demo
from app.services.summary import build_overview
from tests.test_migration_v02 import migrate


def totals(path):
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        result = {}
        for profile in session.scalars(select(StudentProfile)):
            overview = build_overview(profile)
            result[profile.id] = (
                overview.cgpa,
                overview.audit.earned_units,
                overview.audit.projected_units,
            )
    engine.dispose()
    return result


def snapshot(path):
    with sqlite3.connect(path) as db:
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        columns = {t: [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        rows = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY id').fetchall() for t in tables}
    return columns, rows


def assert_preserved(path, columns, before):
    with sqlite3.connect(path) as db:
        for table, names in columns.items():
            selected = ",".join(f'"{name}"' for name in names)
            assert (
                db.execute(f'SELECT {selected} FROM "{table}" ORDER BY id').fetchall()
                == before[table]
            ), table
        assert db.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_populated_v03_upgrade_is_lossless_and_grandfathers_accounts(tmp_path):
    path = tmp_path / "v03.sqlite3"
    migrate(path, "c83f12d60e47")
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        seed_demo(session, with_exchange=True)
        profile = session.get(StudentProfile, 1)
        parent = RequirementGroup(
            profile=profile,
            name="Degree group",
            required_units=0,
            aggregation_mode="sum_children",
            sort_order=99,
            notes="Keep container note",
        )
        session.add(parent)
        session.flush()
        child = session.scalar(
            select(RequirementGroup).where(RequirementGroup.name == "Major Core")
        )
        child.parent_id = parent.id
        session.commit()
    engine.dispose()
    with sqlite3.connect(path) as db:
        db.execute(
            "INSERT INTO users (id,email,username,password_hash,created_at,updated_at,theme_preference) VALUES (7,'student@example.com','student','unchanged-hash','2024-01-01','2024-01-02','dark')"
        )
        db.execute("UPDATE student_profiles SET user_id=7 WHERE id=1")
    columns, before = snapshot(path)
    academic_before = totals(path)
    migrate(path, "head")
    assert_preserved(path, columns, before)
    assert totals(path) == academic_before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("e05b34f82a69",)
        assert db.execute("SELECT email_verified_at, auth_version FROM users").fetchone()[0]
        assert db.execute("SELECT auth_version FROM users").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM account_tokens").fetchone() == (0,)
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        user = User(email="new@example.com", username="new", password_hash="test-hash")
        session.add(user)
        session.commit()
        assert user.email_verified_at is None and user.auth_version == 0
    engine.dispose()
