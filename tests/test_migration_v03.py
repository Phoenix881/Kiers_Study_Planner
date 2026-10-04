import sqlite3

import pytest

from tests.test_migration_v02 import migrate


def test_populated_v02_migration_preserves_every_existing_column(tmp_path):
    path = tmp_path / "v02.sqlite3"
    migrate(path, "b72e91a40c26")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute(
            "INSERT INTO users VALUES (7,'test@example.com','student','keep-hash','2024-01-01','2024-01-02')"
        )
        db.execute(
            "INSERT INTO student_profiles (id,user_id,admission_year,programme_name,required_total_units,created_at,updated_at) VALUES (8,7,'2024/2025','Keep programme',128,'2024-01-01','2024-01-02')"
        )
        db.execute(
            "INSERT INTO academic_years VALUES (9,8,'2024/2025','Year 1',0,'Keep year note')"
        )
        db.execute(
            "INSERT INTO terms (id,profile_id,academic_year_id,name,term_type,sort_order,is_exchange,notes) VALUES (11,8,9,'Custom term','custom',0,0,'Keep term note'), (12,8,9,'Exchange','custom',1,1,'Keep exchange term')"
        )
        db.execute("INSERT INTO courses VALUES (15,'COMP3015')")
        db.execute(
            "INSERT INTO course_versions (id,course_id,academic_year,title,units,level,data_status) VALUES (16,15,'2024-2025','Historical course',3,3,'official_imported')"
        )
        db.execute(
            "INSERT INTO requirement_groups VALUES (20,8,'Core',30,4,'Keep requirement note','2024-01-01','2024-01-02')"
        )
        db.execute("INSERT INTO level_requirements VALUES (21,8,'Advanced',3,36,0)")
        db.execute(
            "INSERT INTO plan_courses (id,term_id,course_id,course_version_id,level_snapshot,exceptional_repeat,course_code_snapshot,course_title_snapshot,units,requirement_group,status,grade,notes,created_at,updated_at) VALUES (25,11,15,16,NULL,0,'COMP3015','Keep snapshot',2,'Core','completed','B','Keep attempt note','2024-01-01','2024-01-02')"
        )
        db.execute(
            "INSERT INTO exchange_courses (id,term_id,host_course_title,hkbu_equivalent_course_id,hkbu_equivalent_code,hkbu_equivalent_title,level_snapshot,transferred_units,requirement_group,transfer_status,notes) VALUES (26,12,'Host snapshot',15,'COMP3015','Equivalent snapshot',NULL,3,'Core','approved','Keep transfer note')"
        )
        db.execute("INSERT INTO plan_course_allocations VALUES (28,25,20,2)")
        db.execute("INSERT INTO exchange_course_allocations VALUES (29,26,20,3)")
        tables = [
            r[0]
            for r in db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name != 'alembic_version' AND name NOT LIKE 'sqlite_%'"
            )
        ]
        columns = {t: [r[1] for r in db.execute(f'PRAGMA table_info("{t}")')] for t in tables}
        before = {t: db.execute(f'SELECT * FROM "{t}" ORDER BY id').fetchall() for t in tables}
    migrate(path, "head")
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys=ON")
        for table in tables:
            selected = ",".join(columns[table])
            assert (
                db.execute(f'SELECT {selected} FROM "{table}" ORDER BY id').fetchall()
                == before[table]
            )
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("e05b34f82a69",)
        assert db.execute("SELECT theme_preference FROM users").fetchone() == ("system",)
        assert db.execute(
            "SELECT parent_id,aggregation_mode FROM requirement_groups"
        ).fetchone() == (None, "own_target")
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "INSERT INTO requirement_groups (profile_id,name,required_units,sort_order,created_at,updated_at) VALUES (8,'Core',3,0,'2024-01-01','2024-01-01')"
            )
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE requirement_groups SET parent_id=id")
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE users SET theme_preference='other'")
