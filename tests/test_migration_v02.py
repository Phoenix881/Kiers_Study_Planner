import os
import sqlite3
import subprocess
import sys

from app.config import ROOT


def migrate(path, revision):
    return subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", revision],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{path}"},
        capture_output=True,
        text=True,
        check=True,
    )


def test_lossless_v01_upgrade_preserves_ids_snapshots_allocations_and_chronology(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    migrate(path, "8884a9a3ad86")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO student_profiles VALUES (1,'2024/25','Legacy programme','Minor',128,'legacy-key','2024-01-01','2024-01-02')"
        )
        db.execute(
            "INSERT INTO courses (id,code,title,units,level,data_status,source_academic_year,source_url) VALUES (17,'TEST3001','Old catalogue',3,3,'official_imported','2024-2025','https://handbook.ar.hkbu.edu.hk/2024-2025/course/TEST3001')"
        )
        db.execute(
            "INSERT INTO courses (id,code,title,units,data_status) VALUES (19,'DEMO1001','Unverified',3,'demo_unverified')"
        )
        for identifier, year, kind, order, exchange in [
            (11, 1, "semester_1", 0, 0),
            (24, 2, "semester_2", 4, 0),
            (53, 4, "semester_2", 10, 1),
        ]:
            db.execute(
                "INSERT INTO terms VALUES (?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    1,
                    year,
                    kind,
                    order,
                    exchange,
                    "Host University" if exchange else None,
                    f"Term note {identifier}",
                ),
            )
        for identifier, term, grade, status, group in [
            (21, 11, "S", "completed", "Custom legacy"),
            (23, 11, "W", "withdrawn", "Major"),
            (29, 24, "B", "completed", "Major"),
            (32, 24, "F", "completed", "Retake"),
        ]:
            db.execute(
                "INSERT INTO plan_courses VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    identifier,
                    term,
                    17,
                    "TEST3001" if grade != "S" else "DEMO1001",
                    f"Snapshot {identifier}",
                    3,
                    group,
                    status,
                    grade,
                    "Keep note",
                    "2024-01-01",
                    "2024-01-02",
                ),
            )
        db.execute(
            "INSERT INTO exchange_courses VALUES (9,53,'HOST-101','Host course',6,'A',17,'TEST3001','Equivalent snapshot',3,'Exchange custom','approved','Keep exchange note')"
        )
        before = {
            table: db.execute(f"SELECT * FROM {table} ORDER BY id").fetchall()
            for table in [
                "student_profiles",
                "terms",
                "courses",
                "plan_courses",
                "exchange_courses",
            ]
        }
        columns = {
            table: [c[1] for c in db.execute(f"PRAGMA table_info({table})")] for table in before
        }
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        for table in before:
            if table == "courses":
                continue
            selected = ",".join(columns[table])
            assert (
                db.execute(f"SELECT {selected} FROM {table} ORDER BY id").fetchall()
                == before[table]
            )
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        assert db.execute("SELECT version_num FROM alembic_version").fetchone()[0] == "e05b34f82a69"
        assert db.execute(
            "SELECT academic_year,label FROM academic_years ORDER BY sort_order"
        ).fetchall() == [("2024/2025", "Year 1"), ("2025/2026", "Year 2"), ("2027/2028", "Year 4")]
        assert db.execute(
            "SELECT t.id,y.academic_year FROM terms t JOIN academic_years y ON y.id=t.academic_year_id ORDER BY t.sort_order"
        ).fetchall() == [(11, "2024/2025"), (24, "2025/2026"), (53, "2027/2028")]
        assert db.execute(
            "SELECT c.requirement_group,g.name,a.allocated_units,c.units FROM plan_courses c JOIN plan_course_allocations a ON a.plan_course_id=c.id JOIN requirement_groups g ON g.id=a.requirement_group_id ORDER BY c.id"
        ).fetchall() == [(r[6], r[6], r[5], r[5]) for r in before["plan_courses"]]
        assert db.execute(
            "SELECT g.name,a.allocated_units FROM exchange_course_allocations a JOIN requirement_groups g ON g.id=a.requirement_group_id"
        ).fetchall() == [("Exchange custom", 3)]
        assert db.execute(
            "SELECT course_id,academic_year,title,level,data_status FROM course_versions ORDER BY course_id"
        ).fetchall() == [
            (17, "2024-2025", "Old catalogue", 3, "official_imported"),
            (19, None, "Unverified", None, "demo_unverified"),
        ]
        for column in columns["courses"]:
            if column in {"id", "code"}:
                assert db.execute(f"SELECT {column} FROM courses ORDER BY id").fetchall() == [
                    (r[columns["courses"].index(column)],) for r in before["courses"]
                ]
            else:
                target = "academic_year" if column == "source_academic_year" else column
                assert db.execute(
                    f"SELECT {target} FROM course_versions ORDER BY course_id"
                ).fetchall() == [(r[columns["courses"].index(column)],) for r in before["courses"]]
        assert db.execute("SELECT user_id FROM student_profiles").fetchone() == (None,)
        assert db.execute("SELECT DISTINCT required_units FROM requirement_groups").fetchall() == [
            (0,)
        ]
        db.execute(
            "INSERT INTO student_profiles (id,admission_year,programme_name,required_total_units,created_at,updated_at) VALUES (2,'2026/2027','Second',120,'2026-01-01','2026-01-01')"
        )
        db.execute(
            "INSERT INTO terms (id,profile_id,academic_year_id,name,study_year,term_type,sort_order,is_exchange) VALUES (60,1,1,'Custom placement',6,'placement',11,0)"
        )
    check = subprocess.run(
        [sys.executable, "-m", "alembic", "check"],
        cwd=ROOT,
        env={**os.environ, "DATABASE_URL": f"sqlite:///{path}"},
        capture_output=True,
        text=True,
    )
    assert check.returncode == 0, check.stdout + check.stderr
