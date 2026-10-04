import os
import subprocess
import sys

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.config import ROOT
from app.db import make_engine
from app.models import Course, ExchangeCourse, PlanCourse, StudentProfile, Term
from app.services.gpa import format_gpa
from app.services.plans import get_profile
from app.services.summary import build_overview


def test_documented_setup_migrations_and_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration.sqlite3'}"
    env = {**os.environ, "DATABASE_URL": url}

    def run(*args):
        subprocess.run(
            [sys.executable, *args], env=env, cwd=ROOT, check=True, capture_output=True, text=True
        )

    run("scripts/init_db.py")
    run("scripts/seed_demo.py", "--with-exchange")
    run("scripts/seed_demo.py", "--with-exchange")
    first = make_engine(url)
    with Session(first) as session:
        assert session.scalar(select(func.count(StudentProfile.id))) == 1
        assert session.scalar(select(func.count(Term.id))) == 11
        assert session.scalar(select(func.count(Course.id))) == 21
        assert session.scalar(select(func.count(PlanCourse.id))) == 23
        assert session.scalar(select(func.count(ExchangeCourse.id))) == 2
        before = build_overview(get_profile(session))
    first.dispose()
    reopened = make_engine(url)
    with Session(reopened) as session:
        after = build_overview(get_profile(session))
        assert before.cgpa == after.cgpa
        assert after.audit.earned_units == 44
        assert after.audit.projected_units == 68
        assert format_gpa(after.terms[0].semester_gpa) == "3.47"
    reopened.dispose()
    run("-m", "alembic", "check")
    blocked = subprocess.run(
        [sys.executable, "-m", "alembic", "downgrade", "base"],
        env=env,
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert blocked.returncode != 0
    assert "cannot be downgraded safely" in blocked.stderr
    intact = make_engine(url)
    assert "plan_courses" in inspect(intact).get_table_names()
    intact.dispose()
