from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    AcademicYear,
    Course,
    CourseVersion,
    ExchangeCourse,
    PlanCourse,
    StudentProfile,
    Term,
    User,
)
from app.services.summary import build_overview
from tests.conftest import create_profile, csrf, register
from tests.test_routes import exchange_form, normal_form


def post(client, url, **values):
    return client.post(url, data={"csrf_token": csrf(client), **values}, follow_redirects=False)


def test_registration_hash_login_logout_and_safe_redirect(anon_client, session):
    client = anon_client
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"
    assert register(client).headers["location"] == "/"
    user = session.scalar(select(User))
    assert user.password_hash.startswith("$argon2id$")
    assert "Test-password-123" not in user.password_hash
    assert post(client, "/logout").headers["location"] == "/login"
    assert client.get("/export/json", follow_redirects=False).headers["location"] == "/login"
    assert post(client, "/login", identifier="student", password="wrong").status_code == 422
    result = post(
        client,
        "/login",
        identifier="STUDENT",
        password="Test-password-123",
        next="https://evil.example/",
    )
    assert result.headers["location"] == "/"


def test_owner_deletion_cannot_disown_a_profile(client, session):
    create_profile(client)
    user = session.get(User, 1)
    assert user.profile.id == 1
    session.delete(user)
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()
    assert session.get(StudentProfile, 1).user_id == 1


def test_claim_not_available_for_ambiguous_legacy_profiles(anon_client, session):
    session.add_all(
        [
            StudentProfile(admission_year="2024/25", programme_name=name, required_total_units=120)
            for name in ("First", "Second")
        ]
    )
    session.commit()
    assert register(anon_client).headers["location"] == "/"
    assert post(anon_client, "/claim", choice="claim").status_code == 409


def test_auth_rotates_csrf_and_rejects_old_forms(anon_client):
    old_token = csrf(anon_client, "/register")
    register(anon_client)
    assert anon_client.post("/logout", data={"csrf_token": old_token}).status_code == 403
    assert post(anon_client, "/logout").status_code == 303


@pytest.mark.parametrize(
    "username,email", [("second", "student@example.com"), ("student", "second@example.com")]
)
def test_unique_accounts(client, session, username, email):
    assert register(client, username, email).status_code == 422
    assert session.scalar(select(func.count(User.id))) == 1


def test_claim_or_new_and_later_users_cannot_claim(anon_client, session):
    profile = StudentProfile(
        admission_year="2024/25", programme_name="Legacy", required_total_units=128
    )
    session.add(profile)
    session.commit()
    assert register(anon_client).headers["location"] == "/claim"
    assert "Claim existing local study plan" in anon_client.get("/claim").text
    assert post(anon_client, "/claim", choice="new").headers["location"] == "/profile"
    session.refresh(profile)
    assert profile.user_id is None
    assert post(anon_client, "/claim", choice="claim").status_code == 303
    session.refresh(profile)
    assert profile.user_id == 1
    post(anon_client, "/logout")
    register(anon_client, "second")
    assert post(anon_client, "/claim", choice="claim").status_code == 409


def test_new_profile_does_not_destroy_unclaimed_plan(anon_client, session):
    legacy = StudentProfile(
        admission_year="2024/25", programme_name="Legacy", required_total_units=120
    )
    session.add(legacy)
    session.commit()
    register(anon_client)
    post(anon_client, "/claim", choice="new")
    create_profile(anon_client)
    session.refresh(legacy)
    assert legacy.user_id is None
    assert session.scalar(select(func.count(StudentProfile.id))) == 2


def test_user_isolation_all_private_surfaces(client, session):
    create_profile(client)
    post(client, "/requirements/groups", name="Private group", required_units="3")
    client.post("/planner/terms/1/courses", data=normal_form(client))
    post(client, "/planner/terms/2/exchange", is_exchange="true")
    client.post("/planner/terms/2/exchange-courses", data=exchange_form(client))
    post(
        client,
        "/requirements/levels",
        label="Private level",
        minimum_level="3",
        required_units="30",
    )
    post(client, "/logout")
    register(client, "second")
    create_profile(client)
    for path in [
        "/planner/terms/1/courses/new",
        "/planner/courses/1/edit",
        "/planner/exchange-courses/1/edit",
        "/planner/terms/2/exchange-courses/new",
        "/courses/MATH3206/add?term_id=1",
    ]:
        assert client.get(path).status_code == 404
    for path in [
        "/planner/courses/1/delete",
        "/planner/exchange-courses/1/delete",
        "/planner/terms/1/delete",
        "/planner/terms/1/rename",
        "/planner/terms/1/move",
        "/planner/terms/1/exchange",
        "/planner/years/1/edit",
        "/planner/years/1/delete",
        "/planner/years/1/move",
        "/planner/years/1/periods",
        "/requirements/groups/1/edit",
        "/requirements/groups/1/delete",
        "/requirements/groups/1/move",
        "/requirements/levels/1/edit",
        "/requirements/levels/1/delete",
        "/requirements/levels/1/move",
    ]:
        assert post(client, path).status_code == 404, path
    assert client.post("/planner/courses/1/edit", data=normal_form(client)).status_code == 404
    assert (
        client.post("/planner/exchange-courses/1/edit", data=exchange_form(client)).status_code
        == 404
    )
    assert client.post("/planner/terms/1/courses", data=normal_form(client)).status_code == 404
    assert (
        client.post("/planner/terms/2/exchange-courses", data=exchange_form(client)).status_code
        == 404
    )
    assert (
        client.post("/planner/terms/9/courses", data=normal_form(client, term_id="1")).status_code
        == 404
    )
    assert (
        client.post(
            "/planner/terms/9/courses",
            data=normal_form(client, allocation_group_id="1", allocated_units="2"),
        ).status_code
        == 422
    )
    assert "Private group" not in client.get("/requirements").text
    payload = client.get("/export/json").json()
    assert payload["profile"]["user_id"] == 2
    assert payload["plan_courses"] == []
    assert "password_hash" not in str(payload)
    assert session.scalar(select(func.count(PlanCourse.id))) == 1
    assert session.scalar(select(func.count(ExchangeCourse.id))) == 1


def test_dynamic_years_periods_summer_reordering_and_deletion(client, session):
    create_profile(client)
    assert session.scalar(select(func.count(Term.id))) == 8
    for year, label in [
        ("2028/2029", "Placement Programme"),
        ("2029/2030", "Academic Leave"),
        ("2030/2031", "Extended Study"),
    ]:
        assert post(client, "/planner/years", academic_year=year, label=label).status_code == 303
    assert session.scalar(select(func.count(AcademicYear.id))) == 7
    assert (
        post(
            client, "/planner/years/5/periods", name="Placement", term_type="placement"
        ).status_code
        == 303
    )
    assert (
        post(client, "/planner/years/1/periods", name="Summer Term", term_type="summer").status_code
        == 303
    )
    summer = session.scalar(select(Term).where(Term.term_type == "summer"))
    assert post(client, f"/planner/terms/{summer.id}/delete").status_code == 303
    client.post("/planner/terms/1/courses", data=normal_form(client))
    assert post(client, "/planner/terms/1/delete").status_code == 409
    assert post(client, "/planner/years/1/delete").status_code == 409
    assert post(client, "/planner/years/5/move", direction="up").status_code == 303
    assert post(client, "/planner/terms/2/move", direction="up").status_code == 303
    session.expire_all()
    assert session.get(AcademicYear, 5).sort_order == 3
    assert session.get(Term, 2).sort_order < session.get(Term, 1).sort_order
    assert post(client, "/planner/years/7/delete").status_code == 303
    assert (
        post(
            client,
            "/planner/years/6/edit",
            academic_year="2031/2032",
            label="Returning",
            notes="Keep this note",
        ).status_code
        == 303
    )
    assert (
        post(
            client, "/planner/terms/9/rename", name="Industry placement", term_type="industry"
        ).status_code
        == 303
    )


def test_allocations_targets_double_count_and_group_deletion(client, session):
    create_profile(client)
    for name in ["Home major", "Second major"]:
        assert (
            post(client, "/requirements/groups", name=name, required_units="75").status_code == 303
        )
    assert (
        post(
            client,
            "/requirements/groups/1/edit",
            name="Home major",
            required_units="100",
            notes="My target",
        ).status_code
        == 303
    )
    assert post(client, "/requirements/groups/2/move", direction="up").status_code == 303
    response = client.post(
        "/planner/terms/1/courses",
        data=normal_form(
            client, units="3", allocation_group_id=["1", "2"], allocated_units=["3", "3"]
        ),
    )
    assert response.status_code == 200
    profile = session.get(StudentProfile, 1)
    overview = build_overview(profile)
    assert overview.audit.earned_units == 3
    assert {g["earned"] for g in overview.groups} == {Decimal(3)}
    assert sum(g.required_units for g in profile.requirement_groups) == 175
    assert post(client, "/requirements/groups/1/delete").status_code == 303
    assert post(client, "/requirements/groups/2/delete").status_code == 303
    session.expire_all()
    assert session.scalar(select(func.count(PlanCourse.id))) == 1
    overview = build_overview(profile)
    assert overview.audit.earned_units == 3
    assert any("Unallocated" in w for w in overview.audit.warnings)


@pytest.mark.parametrize(
    "groups,amounts",
    [
        (["1", "1"], ["1", "1"]),
        (["1"], ["4"]),
        (["1"], ["-1"]),
        (["1"], ["NaN"]),
        (["1"], ["0.001"]),
        (["1"], []),
        (["999"], ["1"]),
    ],
)
def test_invalid_allocations_cannot_write(client, session, groups, amounts):
    create_profile(client)
    post(client, "/requirements/groups", name="Custom", required_units="20")
    assert (
        client.post(
            "/planner/terms/1/courses",
            data=normal_form(
                client, units="3", allocation_group_id=groups, allocated_units=amounts
            ),
        ).status_code
        == 422
    )
    assert session.scalar(select(func.count(PlanCourse.id))) == 0


@pytest.mark.parametrize(
    "grade,status,allowed",
    [
        ("W", "withdrawn", True),
        ("F", "completed", True),
        ("B", "completed", False),
        ("S", "completed", False),
    ],
)
def test_retakes_and_exceptional_override(client, session, grade, status, allowed):
    create_profile(client)
    client.post(
        "/planner/terms/1/courses", data=normal_form(client, units="3", grade=grade, status=status)
    )
    response = client.post(
        "/planner/terms/2/courses",
        data=normal_form(client, units="3", grade="A"),
        follow_redirects=False,
    )
    assert response.status_code == (303 if allowed else 422)
    if not allowed:
        assert (
            client.post(
                "/planner/terms/2/courses",
                data=normal_form(client, units="3", grade="A", exceptional_repeat="true"),
                follow_redirects=False,
            ).status_code
            == 303
        )
    assert build_overview(session.get(StudentProfile, 1)).audit.earned_units == 3


def test_catalogue_versions_snapshot_and_known_level_progress(client, session):
    create_profile(client)
    course = Course(code="MATH3206")
    first = CourseVersion(
        course=course,
        academic_year="2024-2025",
        title="Historical",
        units=3,
        level=3,
        department="MATH",
        data_status="official_imported",
        source_url="https://handbook.ar.hkbu.edu.hk/2024-2025/course/MATH3206",
    )
    second = CourseVersion(
        course=course,
        academic_year="2026-2027",
        title="Current",
        units=4,
        level=4,
        data_status="official_imported",
    )
    postgraduate = Course(
        code="COMP7001",
        title="Postgraduate",
        units=3,
        level=7,
        source_academic_year="2026-2027",
        data_status="official_imported",
    )
    session.add_all([course, first, second, postgraduate])
    session.commit()
    assert "Current" in client.get("/courses").text
    assert "Postgraduate" not in client.get("/courses").text
    assert "Postgraduate" in client.get("/courses?level=all").text
    assert "Historical" in client.get("/courses?year=2024-2025&q=historical&prefix=MATH").text
    assert first.source_url in client.get(f"/courses/MATH3206?version_id={first.id}").text
    assert (
        client.get(f"/courses/MATH3206/add?term_id=1&version_id={first.id}", follow_redirects=False)
        .headers["location"]
        .endswith(f"version_id={first.id}")
    )
    post(client, "/requirements/levels", label="Advanced", minimum_level="3", required_units="36")
    response = client.post(
        "/planner/terms/1/courses",
        data=normal_form(
            client, course_version_id=str(first.id), units="99", course_title_snapshot="Tampered"
        ),
        follow_redirects=False,
    )
    assert response.status_code == 303
    entry = session.scalar(select(PlanCourse))
    assert (entry.course_title_snapshot, entry.units, entry.level_snapshot) == ("Historical", 3, 3)
    first.title, first.units, first.level = "Refreshed", 5, 1
    session.commit()
    client.post(
        "/planner/terms/1/courses",
        data=normal_form(client, course_code_snapshot="TEST4999", units="3"),
    )
    client.post(
        "/planner/terms/1/courses",
        data=normal_form(client, course_code_snapshot="TEST1999", units="3", status="planned"),
    )
    session.expire_all()
    overview = build_overview(session.get(StudentProfile, 1))
    assert overview.audit.requirements[-1].completed_value == 3
    assert any("no verified catalogue level" in w for w in overview.audit.warnings)
    assert entry.course_title_snapshot == "Historical"
    assert entry.units == 3


def test_pending_equivalents_soft_warning_and_final_allocations(client, session):
    create_profile(client)
    post(client, "/requirements/groups", name="Minor", required_units="6")
    post(client, "/requirements/groups", name="Free Elective", required_units="20")
    client.post("/planner/terms/1/courses", data=normal_form(client, grade="B", units="3"))
    post(client, "/planner/terms/2/exchange", is_exchange="true")
    for title in ["Host A", "Host B"]:
        response = client.post(
            "/planner/terms/2/exchange-courses",
            data=exchange_form(
                client,
                host_course_title=title,
                hkbu_equivalent_code="COMP2015",
                allocation_group_id="1",
                allocated_units="3",
            ),
        )
        assert response.status_code == 200
    assert "Duplicate HKBU equivalent COMP2015" in response.text
    assert session.scalar(select(func.count(ExchangeCourse.id))) == 2
    assert build_overview(session.get(StudentProfile, 1)).audit.projected_units == 6
    client.post(
        "/planner/exchange-courses/1/edit",
        data=exchange_form(
            client,
            host_course_title="Host A",
            hkbu_equivalent_code="COMP2015",
            transfer_status="approved",
            allocation_group_id="1",
            allocated_units="3",
        ),
    )
    client.post(
        "/planner/exchange-courses/2/edit",
        data=exchange_form(
            client,
            host_course_title="Host B",
            hkbu_equivalent_code="",
            transfer_status="approved",
            host_grade="F",
            allocation_group_id="2",
            allocated_units="3",
        ),
    )
    session.expire_all()
    overview = build_overview(session.get(StudentProfile, 1))
    assert overview.cgpa == 3
    assert overview.audit.earned_units == 9
    assert all(g["earned"] == 3 for g in overview.groups)
