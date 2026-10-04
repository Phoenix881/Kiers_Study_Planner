from sqlalchemy import func, select

from app.models import StudentProfile, Term
from tests.conftest import create_profile, csrf


def test_profile_setup_creates_eight_optional_periods(client, session):
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/profile").status_code == 200
    assert create_profile(client).status_code == 303
    assert session.scalar(select(func.count(Term.id))) == 8
    assert session.get(StudentProfile, 1).admission_year == "2024/2025"
    assert not session.scalar(select(Term).where(Term.term_type == "summer"))
    create_profile(client)
    assert session.scalar(select(func.count(Term.id))) == 8


def test_profile_errors_preserve_input(client):
    response = client.post(
        "/profile",
        data={
            "csrf_token": csrf(client),
            "admission_year": "2024/27",
            "programme_name": "My Programme",
            "required_total_units": "-1",
        },
    )
    assert response.status_code == 422
    assert "My Programme" in response.text
    assert "consecutive academic year" in response.text


def test_csrf_blocks_mutation(client):
    assert client.post("/profile", data={}).status_code == 403


def test_curriculum_is_not_an_authority(client, session):
    response = client.post(
        "/profile",
        data={
            "csrf_token": csrf(client),
            "admission_year": "2025/26",
            "programme_name": "My Programme",
            "curriculum_key": "demo_math_stats_2024_25",
        },
    )
    assert response.status_code == 200
    assert session.get(StudentProfile, 1).curriculum_key is None
