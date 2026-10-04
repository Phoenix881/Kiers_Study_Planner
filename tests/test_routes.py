from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select

from app.models import Course, ExchangeCourse, PlanCourse, StudentProfile, Term
from app.schemas.inputs import TermInput
from app.services.plans import get_profile
from app.services.seed import seed_demo
from app.services.summary import build_overview
from tests.conftest import create_profile, csrf


@pytest.fixture
def demo(client, session):
    seed_demo(session, with_exchange=True)
    session.get(StudentProfile, 1).user_id = 1
    session.commit()
    return client


@pytest.mark.parametrize(
    "path",
    [
        "/",
        "/planner",
        "/audit",
        "/courses",
        "/courses/MATH3206",
        "/profile",
        "/planner/terms/1/courses/new",
        "/planner/courses/1/edit",
        "/planner/terms/8/exchange-courses/new",
        "/planner/exchange-courses/1/edit",
    ],
)
def test_main_pages(demo, path):
    response = demo.get(path)
    assert response.status_code == 200
    assert "Kier&#39;s Study Planner" in response.text


def test_first_run_redirects(client):
    for path in ["/", "/planner", "/audit", "/export/json"]:
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/profile"
    create_profile(client)
    assert client.get("/planner").text.count('class="study-year"') == 4


def normal_form(client, **changes):
    values = {
        "csrf_token": csrf(client),
        "course_code_snapshot": " math 3206 ",
        "course_title_snapshot": "My historical title",
        "units": "2.5",
        "requirement_group": "Major Core",
        "status": "completed",
        "grade": "a-",
        "notes": "A note",
    }
    return values | changes


def test_normal_course_crud(client, session):
    create_profile(client)
    response = client.post(
        "/planner/terms/1/courses", data=normal_form(client), follow_redirects=False
    )
    assert response.status_code == 303
    entry = session.scalar(select(PlanCourse))
    assert entry.course_code_snapshot == "MATH3206"
    assert entry.units == Decimal("2.5")
    assert entry.grade == "A-"
    assert entry.course_id is None
    response = client.post(
        f"/planner/courses/{entry.id}/edit",
        data=normal_form(client, term_id="2", grade="W", units="3"),
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.expire_all()
    assert entry.term_id == 2
    assert entry.units == 3
    overview = build_overview(get_profile(session, user_id=1))
    assert overview.audit.earned_units == 0
    assert overview.cgpa is None
    response = client.post(
        f"/planner/courses/{entry.id}/delete",
        data={"csrf_token": csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert session.scalar(select(func.count(PlanCourse.id))) == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"units": "-1"},
        {"units": "NaN"},
        {"units": "Infinity"},
        {"units": "0.001"},
        {"course_code_snapshot": "../../../bad"},
        {"grade": "A+"},
        {"status": "finished"},
        {"course_title_snapshot": " "},
        {"allocation_group_id": "999", "allocated_units": "3"},
    ],
)
def test_bad_course_form_does_not_write(client, session, changes):
    create_profile(client)
    response = client.post("/planner/terms/1/courses", data=normal_form(client, **changes))
    assert response.status_code == 422
    assert "Please check" in response.text
    assert session.scalar(select(func.count(PlanCourse.id))) == 0


def test_catalogue_search_and_add_flow(demo, session):
    assert "Scientific Computing I" in demo.get("/courses?q=math%203206&level=all").text
    assert "MATH1005" in demo.get("/courses?q=Calculus&level=all").text
    assert demo.get("/api/courses/search?q=MATH3206").json()[0]["code"] == "MATH3206"
    response = demo.get("/courses/MATH3206/add?term_id=11")
    assert response.status_code == 200
    assert 'value="MATH3206"' in response.text
    assert 'value="Scientific Computing I"' in response.text
    detail = demo.get("/courses/MATH3206").text
    assert "https://arcourseoutline.hkbu.edu.hk/outline/MATH3206.pdf" in detail
    assert "Unknown" in detail
    assert demo.get("/courses?q=%25").text.count('class="course-title-link"') == 0


def exchange_form(client, **changes):
    return {
        "csrf_token": csrf(client),
        "host_course_title": "Exchange topic",
        "host_course_code": "HOST-12",
        "host_units": "7.5",
        "host_grade": "98/100",
        "hkbu_equivalent_code": "",
        "hkbu_equivalent_title": "Free Elective",
        "transferred_units": "3",
        "requirement_group": "Free Elective",
        "transfer_status": "pending_approval",
    } | changes


def test_exchange_crud_and_gpa_exclusion(client, session):
    create_profile(client)
    client.post("/planner/terms/1/courses", data=normal_form(client, units="3", grade="B"))
    response = client.post(
        "/planner/terms/2/exchange/toggle",
        data={
            "csrf_token": csrf(client),
            "is_exchange": "true",
            "host_university": "Test University",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    response = client.post(
        "/planner/terms/2/exchange-courses", data=exchange_form(client), follow_redirects=False
    )
    assert response.status_code == 303
    profile = get_profile(session, user_id=1)
    overview = build_overview(profile)
    assert overview.cgpa == 3
    assert overview.audit.earned_units == 3
    assert overview.audit.projected_units == 6
    entry = session.scalar(select(ExchangeCourse))
    response = client.post(
        f"/planner/exchange-courses/{entry.id}/edit",
        data=exchange_form(client, transfer_status="approved", host_grade="F"),
        follow_redirects=False,
    )
    assert response.status_code == 303
    session.expire_all()
    overview = build_overview(get_profile(session, user_id=1))
    assert overview.audit.earned_units == 6
    assert overview.cgpa == 3
    assert "GPA units" in client.get("/planner").text
    response = client.post(
        "/planner/terms/2/exchange", data={"csrf_token": csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 422
    session.expire_all()
    assert session.get(Term, 2).is_exchange
    response = client.post(
        f"/planner/exchange-courses/{entry.id}/delete",
        data={"csrf_token": csrf(client)},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert session.scalar(select(func.count(ExchangeCourse.id))) == 0
    response = client.post(
        "/planner/terms/2/exchange", data={"csrf_token": csrf(client)}, follow_redirects=False
    )
    assert response.status_code == 303
    session.expire_all()
    assert not session.get(Term, 2).is_exchange


@pytest.mark.parametrize(
    "changes",
    [
        {"host_course_title": ""},
        {"transferred_units": "-1"},
        {"host_units": "-5"},
        {"transfer_status": "accepted"},
        {"hkbu_equivalent_code": "bad-code"},
    ],
)
def test_exchange_validation(demo, session, changes):
    count = session.scalar(select(func.count(ExchangeCourse.id)))
    response = demo.post("/planner/terms/8/exchange-courses", data=exchange_form(demo, **changes))
    assert response.status_code == 422
    assert session.scalar(select(func.count(ExchangeCourse.id))) == count


def test_term_mode_guards_preserve_data(demo, session):
    count = session.scalar(select(func.count(PlanCourse.id)))
    response = demo.post(
        "/planner/terms/1/exchange/toggle", data={"csrf_token": csrf(demo), "is_exchange": "true"}
    )
    assert response.status_code == 422
    assert "Move or remove existing courses" in response.text
    assert session.scalar(select(func.count(PlanCourse.id))) == count
    assert demo.post("/planner/terms/8/courses", data=normal_form(demo)).status_code == 409
    assert (
        demo.post("/planner/terms/1/exchange-courses", data=exchange_form(demo)).status_code == 409
    )


def test_missing_records_are_friendly(demo):
    for path in [
        "/courses/FAKE1001",
        "/planner/courses/99999/edit",
        "/planner/exchange-courses/99999/edit",
        "/planner/terms/99999/courses/new",
    ]:
        response = demo.get(path)
        assert response.status_code == 404
        assert "Page not found" in response.text


def test_optional_catalogue_can_be_removed(demo, session):
    session.execute(delete(Course))
    session.commit()
    assert demo.get("/planner").status_code == 200
    assert demo.get("/audit").status_code == 200
    assert (
        "My historical title" in demo.post("/planner/terms/11/courses", data=normal_form(demo)).text
    )


def test_user_content_is_escaped(client):
    create_profile(client)
    response = client.post(
        "/planner/terms/1/courses",
        data=normal_form(client, course_title_snapshot='<script>alert("x")</script>'),
    )
    assert response.status_code == 200
    assert '<script>alert("x")</script>' not in response.text
    assert "&lt;script&gt;" in response.text


def test_json_export_keeps_snapshots_and_exchange(demo):
    response = demo.get("/export/json")
    assert response.status_code == 200
    assert "attachment;" in response.headers["content-disposition"]
    payload = response.json()
    assert payload["version"] == 2
    assert len(payload["terms"]) == 11
    assert len(payload["exchange_courses"]) == 2
    assert payload["profile"]["required_total_units"] == "128.00"
    assert payload["plan_courses"][0]["course_title_snapshot"]


def test_seed_idempotence(demo, session):
    counts = [
        session.scalar(select(func.count(model.id)))
        for model in [StudentProfile, Term, Course, PlanCourse, ExchangeCourse]
    ]
    assert not seed_demo(session, with_exchange=True)
    assert counts == [
        session.scalar(select(func.count(model.id)))
        for model in [StudentProfile, Term, Course, PlanCourse, ExchangeCourse]
    ]


@pytest.mark.parametrize("year,kind", [(0, "semester_1"), (-1, "semester_1"), (1, "")])
def test_term_validation(year, kind):
    with pytest.raises(ValueError):
        TermInput(study_year=year, term_type=kind)


def test_profile_target_overrides_curriculum(demo, session):
    profile = session.get(StudentProfile, 1)
    profile.required_total_units = Decimal(140)
    session.commit()
    overview = build_overview(get_profile(session, user_id=1))
    assert overview.audit.required_units == 140
    assert overview.audit.requirements[0].required_value == 140
