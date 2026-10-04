import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text

from app.main import app
from app.models import (
    AcademicYear,
    AccountToken,
    AdminAuditLog,
    Course,
    ExchangeCourse,
    ExchangeCourseAllocation,
    LevelRequirement,
    PlanCourse,
    PlanCourseAllocation,
    RequirementGroup,
    StudentProfile,
    Term,
    User,
)
from app.models.profile import utc_now
from app.services.accounts import delete_account
from app.services.seed import seed_demo
from tests.conftest import create_profile
from tests.test_v04 import login, submit
from tests.test_v05_admin import PASSWORD, action, user


def rows(session):
    return {
        table: session.execute(text(f'SELECT * FROM "{table}" ORDER BY id')).all()
        for table in [
            "users",
            "student_profiles",
            "academic_years",
            "terms",
            "plan_courses",
            "exchange_courses",
            "requirement_groups",
            "level_requirements",
            "plan_course_allocations",
            "exchange_course_allocations",
            "courses",
            "course_versions",
            "account_tokens",
            "admin_audit_log",
        ]
    }


def rich_graph(session, target_id, depth=3):
    seed_demo(session, with_exchange=True)
    profile = session.get(StudentProfile, 1)
    profile.user_id = target_id
    for i in range(depth):
        session.add(
            RequirementGroup(
                id=10000 + i,
                profile=profile,
                name=f"Nested {i}",
                parent_id=9999 + i if i else None,
                required_units=3,
                aggregation_mode="sum_children" if i < depth - 1 else "own_target",
            )
        )
    session.flush()
    attempt = session.scalar(select(PlanCourse).order_by(PlanCourse.id))
    transfer = session.scalar(select(ExchangeCourse).order_by(ExchangeCourse.id))
    session.add_all(
        [
            PlanCourseAllocation(
                plan_course_id=attempt.id, requirement_group_id=9999 + depth, allocated_units=1
            ),
            ExchangeCourseAllocation(
                exchange_course_id=transfer.id, requirement_group_id=9999 + depth, allocated_units=1
            ),
            LevelRequirement(
                profile=profile, label="Level target", minimum_level=3, required_units=3
            ),
            AccountToken(
                user_id=target_id, purpose="verify_email", token_hash="a" * 64, expires_at=utc_now()
            ),
        ]
    )
    session.commit()
    return profile.id


@pytest.mark.parametrize("with_profile", [False, True])
def test_self_delete_without_or_with_empty_profile(client, session, with_profile):
    if with_profile:
        create_profile(client)
    other = user(session, "other")
    identifier = other.id
    assert client.post("/account/delete").status_code == 403
    assert session.get(User, 1)
    assert (
        submit(
            client, "/account/delete", current_password=PASSWORD, confirmation="DELETE"
        ).status_code
        == 303
    )
    session.expire_all()
    assert session.get(User, 1) is None and session.get(User, identifier)
    assert not list(session.scalars(select(StudentProfile)))
    assert not list(session.scalars(select(AccountToken).where(AccountToken.user_id == 1)))
    assert client.get("/profile", follow_redirects=False).headers["location"] == "/login"
    assert login(client).status_code == 422


@pytest.mark.parametrize(
    "password,confirmation",
    [("wrong", "DELETE"), (PASSWORD, "delete"), (PASSWORD, " DELETE"), (PASSWORD, "")],
)
def test_self_delete_requires_password_and_exact_confirmation(
    client, session, password, confirmation
):
    assert (
        submit(
            client, "/account/delete", current_password=password, confirmation=confirmation
        ).status_code
        == 422
    )
    assert session.get(User, 1)
    assert client.get("/account/delete").status_code == 200


def test_self_delete_full_graph_preserves_other_users_unclaimed_and_catalogue(client, session):
    rich_graph(session, 1, depth=12)
    other = user(session, "other")
    foreign = StudentProfile(
        user_id=other.id,
        admission_year="2026/2027",
        programme_name="Keep other",
        required_total_units=128,
    )
    unclaimed = StudentProfile(
        admission_year="2024/2025", programme_name="Keep legacy", required_total_units=128
    )
    session.add_all([foreign, unclaimed])
    session.flush()
    period = Term(profile=foreign, name="Other period", sort_order=0)
    session.add(period)
    session.flush()
    session.add(
        PlanCourse(
            term=period,
            course_code_snapshot="KEEP1001",
            course_title_snapshot="Keep other course",
            units=3,
        )
    )
    session.commit()
    saved_profiles = {foreign.id, unclaimed.id}
    before = rows(session)
    cookie = client.cookies.get("session")
    assert (
        submit(client, "/account/delete", current_password=PASSWORD, confirmation="DELETE").headers[
            "location"
        ]
        == "/goodbye"
    )
    session.expire_all()
    assert session.get(User, 1) is None
    assert {p.id for p in session.scalars(select(StudentProfile))} == saved_profiles
    assert session.scalar(select(PlanCourse.course_code_snapshot)) == "KEEP1001"
    for model in [
        AcademicYear,
        ExchangeCourse,
        RequirementGroup,
        LevelRequirement,
        PlanCourseAllocation,
        ExchangeCourseAllocation,
        AccountToken,
    ]:
        assert session.scalar(select(func.count()).select_from(model)) == 0
    after = rows(session)
    assert (
        after["courses"] == before["courses"]
        and after["course_versions"] == before["course_versions"]
    )
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert session.execute(text("PRAGMA foreign_key_check")).all() == []
    with TestClient(app) as stale:
        stale.cookies.set("session", cookie)
        assert stale.get("/export/json", follow_redirects=False).headers["location"] == "/login"


def test_deep_tree_deletion_uses_no_recursive_python_or_fk_disabling(client, session):
    rich_graph(session, 1, depth=1050)
    target = session.get(User, 1)
    delete_account(session, target)
    session.commit()
    assert session.scalar(select(func.count(RequirementGroup.id))) == 0
    assert session.scalar(select(func.count(Course.id))) > 0
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
    assert session.execute(text("PRAGMA foreign_key_check")).all() == []


@pytest.mark.parametrize("exchange", [False, True])
def test_cross_profile_external_allocation_fails_closed_and_rolls_back(client, session, exchange):
    rich_graph(session, 1)
    foreign = StudentProfile(admission_year="2024/2025", programme_name="Unclaimed keep")
    session.add(foreign)
    session.flush()
    period = Term(profile=foreign, name="Keep", sort_order=0, is_exchange=exchange)
    session.add(period)
    session.flush()
    if exchange:
        course = ExchangeCourse(
            term=period, host_course_title="Keep foreign transfer", transferred_units=3
        )
        session.add(course)
        session.flush()
        allocation = ExchangeCourseAllocation(
            exchange_course_id=course.id, requirement_group_id=10002, allocated_units=1
        )
    else:
        course = PlanCourse(
            term=period,
            course_code_snapshot="KEEP1001",
            course_title_snapshot="Keep foreign attempt",
            units=3,
        )
        session.add(course)
        session.flush()
        allocation = PlanCourseAllocation(
            plan_course_id=course.id, requirement_group_id=10002, allocated_units=1
        )
    session.add(allocation)
    session.commit()
    before = rows(session)
    assert (
        submit(
            client, "/account/delete", current_password=PASSWORD, confirmation="DELETE"
        ).status_code
        == 409
    )
    session.expire_all()
    assert rows(session) == before
    assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1


def test_deletion_failure_rolls_back_every_personal_row_and_session_version(
    client, session, engine, caplog
):
    rich_graph(session, 1)
    before = rows(session)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("DELETE FROM academic_years"):
            raise RuntimeError("PRIVATE-password-token-invite-confirmation")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = submit(
            client, "/account/delete", current_password=PASSWORD, confirmation="DELETE"
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 500
    assert "Something went wrong" in response.text and "Request ID:" in response.text
    assert "PRIVATE-password" not in response.text + caplog.text
    assert "RuntimeError" in caplog.text and "route=/account/delete" in caplog.text
    session.expire_all()
    assert rows(session) == before
    assert client.get("/account/delete").status_code == 200


def test_admin_delete_full_graph_and_audit_survives_both_accounts(admin, session):
    target = user(session)
    identifier = target.id
    rich_graph(session, identifier)
    catalogue_count = session.scalar(select(func.count(Course.id)))
    assert action(admin, identifier, "delete_user", confirmation="DELETE").status_code == 303
    session.expire_all()
    log = session.scalar(select(AdminAuditLog).where(AdminAuditLog.action == "delete_user"))
    log_id = log.id
    assert log.target_user_id is None and log.target_username_snapshot == "target"
    assert session.scalar(select(func.count(PlanCourse.id))) == 0
    assert session.scalar(select(func.count(Course.id))) == catalogue_count
    actor = session.get(User, 1)
    delete_account(session, actor)
    session.commit()
    session.expire_all()
    log = session.get(AdminAuditLog, log_id)
    assert log.admin_user_id is None and log.admin_username_snapshot == "student"
    assert log.target_username_snapshot == "target"


def test_admin_delete_failure_rolls_back_success_audit(admin, session, engine):
    target = user(session)
    rich_graph(session, target.id)
    before = rows(session)

    def fail(connection, cursor, statement, parameters, context, many):
        if statement.startswith("DELETE FROM academic_years"):
            raise RuntimeError("failure")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = action(admin, target.id, "delete_user", confirmation="DELETE")
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 500
    session.expire_all()
    assert rows(session) == before


def test_user_ids_never_reused_after_deletion(client, session):
    cookie = client.cookies.get("session")
    submit(client, "/account/delete", current_password=PASSWORD, confirmation="DELETE")
    replacement = user(session, "replacement")
    assert replacement.id > 1
    with TestClient(app) as stale:
        stale.cookies.set("session", cookie)
        assert stale.get("/profile", follow_redirects=False).headers["location"] == "/login"
