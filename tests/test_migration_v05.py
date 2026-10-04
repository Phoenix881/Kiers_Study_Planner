import sqlite3

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import make_engine
from app.models import RequirementGroup, StudentProfile
from app.services.seed import seed_demo
from tests.test_migration_v02 import migrate
from tests.test_migration_v04 import assert_preserved, snapshot, totals


def test_populated_v04_upgrade_preserves_every_old_column_and_academic_total(tmp_path):
    path = tmp_path / "v04.sqlite3"
    migrate(path, "d94a23e71f58")
    engine = make_engine(f"sqlite:///{path}")
    with Session(engine) as session:
        seed_demo(session, with_exchange=True)
        profile = session.get(StudentProfile, 1)
        parent = RequirementGroup(
            profile=profile,
            name="Preserved parent",
            required_units=0,
            aggregation_mode="sum_children",
            sort_order=99,
            notes="Private fixture note",
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
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO users (id,email,username,password_hash,created_at,updated_at,"
            "theme_preference,email_verified_at,auth_version) VALUES "
            "(7,'student@example.com','student','unchanged-fixture','2024-01-01',"
            "'2024-01-02','dark','2024-01-03',8)"
        )
        db.execute("UPDATE student_profiles SET user_id=7 WHERE id=1")
        db.execute(
            "INSERT INTO account_tokens (id,user_id,purpose,token_hash,created_at,expires_at,consumed_at) "
            "VALUES (9,7,'reset_password',?,'2024-01-02','2024-01-03','2024-01-02')",
            ("a" * 64,),
        )
    columns, before = snapshot(path)
    academic_before = totals(path)
    migrate(path, "head")
    assert_preserved(path, columns, before)
    assert totals(path) == academic_before
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("e05b34f82a69",)
        assert db.execute(
            "SELECT is_admin,is_disabled,disabled_at,disabled_reason,last_login_at FROM users"
        ).fetchall() == [(0, 0, None, None, None)]
        assert db.execute("SELECT COUNT(*) FROM admin_audit_log").fetchone() == (0,)
        assert (
            "AUTOINCREMENT"
            in db.execute("SELECT sql FROM sqlite_master WHERE name='users'").fetchone()[0]
        )
        assert db.execute("SELECT seq FROM sqlite_sequence WHERE name='users'").fetchone() == (7,)
