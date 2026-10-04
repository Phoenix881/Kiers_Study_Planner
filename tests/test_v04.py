import logging
from dataclasses import replace
from datetime import timedelta
from decimal import Decimal
from email import policy
from email.parser import BytesParser
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.main import app
from app.models import AccountToken, RequirementGroup, User
from app.models.profile import utc_now
from app.services.account_security import digest, hasher
from app.services.audit import evaluate_progress
from app.services.credit import CreditRecord
from app.services.mail import Mailer, MailSettings, deliver
from app.services.rate_limit import RateLimiter
from app.services.security_logging import RedactAccountURLs
from tests.conftest import create_profile, csrf, mail_link, register
from tests.test_v02 import post
from tests.test_v03 import group

PASSWORD = "New-test-password-456"


def submit(client, path, **values):
    return client.post(
        path,
        data={
            "csrf_token": csrf(client, path if path != "/resend-verification" else "/check-email"),
            **values,
        },
        follow_redirects=False,
    )


def login(client, identifier="student", password="Test-password-123"):
    return submit(client, "/login", identifier=identifier, password=password)


def test_registration_verification_is_post_only_hashed_and_single_use(anon_client, session):
    response = register(anon_client, verify=False)
    assert response.headers["location"] == "/check-email"
    user = session.scalar(select(User))
    assert user.email_verified_at is None and user.auth_version == 0
    assert hasher.verify(user.password_hash, "Test-password-123")
    link = mail_link(anon_client, "verify-email")
    raw = parse_qs(urlsplit(link).query)["token"][0]
    token = session.scalar(select(AccountToken))
    assert token.token_hash == digest(raw) and raw not in repr(token.__dict__)
    assert timedelta(hours=23) < token.expires_at - token.created_at <= timedelta(hours=24)
    landing = anon_client.get(link, follow_redirects=False)
    assert landing.status_code == 303 and landing.headers["location"] == "/verify-email"
    assert raw not in landing.headers.get("set-cookie", "")
    form = anon_client.get("/verify-email")
    assert raw not in form.text
    assert form.headers["referrer-policy"] == "no-referrer"
    assert form.headers["cache-control"] == "no-store"
    session.refresh(token)
    session.refresh(user)
    assert token.consumed_at is None and user.email_verified_at is None
    assert anon_client.post("/verify-email").status_code == 403
    assert submit(anon_client, "/verify-email").status_code == 200
    session.refresh(token)
    session.refresh(user)
    assert user.email_verified_at and token.consumed_at
    assert anon_client.get(link).status_code == 400
    assert anon_client.get("/planner", follow_redirects=False).headers["location"] == "/login"
    assert login(anon_client, "STUDENT@EXAMPLE.COM").status_code == 303


def test_unverified_planner_block_and_resend_invalidates_old_link(anon_client, session):
    register(anon_client, verify=False)
    old = mail_link(anon_client, "verify-email")
    for path in ["/planner", "/profile", "/export/json", "/requirements", "/account/security"]:
        assert anon_client.get(path, follow_redirects=False).headers["location"] == "/login"
    assert login(anon_client).headers["location"] == "/check-email"
    for _ in range(3):
        assert submit(anon_client, "/resend-verification").status_code == 200
    assert submit(anon_client, "/resend-verification").status_code == 429
    assert anon_client.get(old).status_code == 400
    assert anon_client.get(mail_link(anon_client, "verify-email")).status_code == 200
    rows = list(session.scalars(select(AccountToken)))
    assert sum(t.consumed_at is None for t in rows) == 1


@pytest.mark.parametrize(
    "purpose,path", [("verify_email", "verify-email"), ("reset_password", "reset-password")]
)
def test_expiry_and_purpose_separation(anon_client, session, purpose, path):
    register(anon_client, verify=purpose == "reset_password")
    if purpose == "reset_password":
        submit(anon_client, "/forgot-password", email="student@example.com")
    link = mail_link(anon_client, path)
    other_path = "reset-password" if path == "verify-email" else "verify-email"
    assert anon_client.get(link.replace(path, other_path)).status_code == 400
    assert anon_client.get(link).status_code == 200
    token = session.scalar(
        select(AccountToken).where(
            AccountToken.purpose == purpose, AccountToken.consumed_at.is_(None)
        )
    )
    token.expires_at = utc_now() - timedelta(seconds=1)
    session.commit()
    assert anon_client.get(link).status_code == 400
    assert (
        submit(
            anon_client, "/" + path, password=PASSWORD, password_confirmation=PASSWORD
        ).status_code
        == 400
    )


def test_recovery_generic_response_verified_email_only_and_resend(client, session):
    registered = submit(client, "/forgot-password", email="STUDENT@EXAMPLE.COM")
    link = mail_link(client, "reset-password")
    mail_count = len(client.mailer.messages)
    missing = submit(client, "/forgot-password", email="absent@example.com")
    username = submit(client, "/forgot-password", email="student")
    assert registered.status_code == missing.status_code == username.status_code == 200
    assert registered.text == missing.text == username.text
    assert len(client.mailer.messages) == mail_count
    submit(client, "/forgot-password", email="student@example.com")
    assert client.get(link).status_code == 400
    token = session.scalar(
        select(AccountToken).where(
            AccountToken.purpose == "reset_password", AccountToken.consumed_at.is_(None)
        )
    )
    assert timedelta(minutes=29) < token.expires_at - token.created_at <= timedelta(minutes=30)


def test_password_reset_rejects_weak_mismatch_then_revokes_sessions(client, session):
    create_profile(client)
    snapshot = client.get("/export/json").json()
    old_cookie = client.cookies.get("session")
    submit(client, "/forgot-password", email="student@example.com")
    link = mail_link(client, "reset-password")
    client.get(link)
    for password, confirmation in [("short", "short"), (PASSWORD, "different")]:
        assert (
            submit(
                client, "/reset-password", password=password, password_confirmation=confirmation
            ).status_code
            == 422
        )
    assert client.post("/reset-password", data={"password": PASSWORD}).status_code == 403
    assert (
        submit(
            client, "/reset-password", password=PASSWORD, password_confirmation=PASSWORD
        ).status_code
        == 200
    )
    user = session.scalar(select(User))
    assert user.auth_version == 1 and hasher.verify(user.password_hash, PASSWORD)
    assert all(
        t.consumed_at
        for t in session.scalars(
            select(AccountToken).where(AccountToken.purpose == "reset_password")
        )
    )
    assert client.get(link).status_code == 400
    with TestClient(app) as other:
        other.cookies.set("session", old_cookie)
        assert other.get("/export/json", follow_redirects=False).headers["location"] == "/login"
    assert login(client).status_code == 422
    assert login(client, password=PASSWORD).status_code == 303
    after = client.get("/export/json").json()
    after.pop("exported_at")
    snapshot.pop("exported_at")
    assert after == snapshot


def test_change_password_keeps_current_session_revokes_other_sessions_and_tokens(client, session):
    create_profile(client)
    old_cookie = client.cookies.get("session")
    submit(client, "/forgot-password", email="student@example.com")
    reset_link = mail_link(client, "reset-password")
    assert client.post("/account/security").status_code == 403
    assert (
        submit(
            client,
            "/account/security",
            current_password="wrong",
            password=PASSWORD,
            password_confirmation=PASSWORD,
        ).status_code
        == 422
    )
    assert (
        submit(
            client,
            "/account/security",
            current_password="Test-password-123",
            password=PASSWORD,
            password_confirmation=PASSWORD,
        ).status_code
        == 200
    )
    assert client.get("/planner").status_code == 200
    assert client.get(reset_link).status_code == 400
    user = session.scalar(select(User))
    assert user.auth_version == 1 and hasher.verify(user.password_hash, PASSWORD)
    with TestClient(app) as other:
        other.cookies.set("session", old_cookie)
        assert other.get("/profile", follow_redirects=False).headers["location"] == "/login"
    assert "password changed" in client.mailer.messages[-1]["subject"]
    exported = client.get("/export/json").text
    for sensitive in ["password_hash", "auth_version", "account_tokens", "email_verified_at"]:
        assert sensitive not in exported


def test_wrong_login_is_generic_and_limited(anon_client):
    register(anon_client)
    real = login(anon_client, password="incorrect")
    missing = login(anon_client, identifier="absent", password="incorrect")
    # Entered identifier is deliberately preserved; the error itself is identical.
    assert "Email/username or password is incorrect." in real.text
    assert "Email/username or password is incorrect." in missing.text
    for _ in range(8):
        assert login(anon_client, password="incorrect").status_code == 422
    limited = login(anon_client, password="incorrect")
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0


@pytest.mark.parametrize(
    "action,limit",
    [
        ("login", 10),
        ("register", 5),
        ("resend", 3),
        ("reset_request", 3),
        ("reset_submit", 8),
        ("verify_submit", 8),
        ("password_change", 8),
    ],
)
def test_rate_limits_normalized_keys_and_expiry(action, limit):
    clock = [0]
    limiter = RateLimiter(clock=lambda: clock[0])
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    for _ in range(limit):
        limiter.protect(request, action, " USER@EXAMPLE.COM ")
    with pytest.raises(HTTPException) as exc:
        limiter.protect(request, action, "user@example.com")
    assert exc.value.status_code == 429
    assert all("example" not in key for _, key in limiter.buckets)
    clock[0] = 4000
    limiter.protect(request, action, "user@example.com")


def test_ip_limit_and_capacity_are_bounded():
    limiter = RateLimiter(clock=lambda: 0)
    request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
    for i in range(30):
        limiter.protect(request, "reset_request", f"{i}@example.com")
    with pytest.raises(HTTPException):
        limiter.protect(request, "reset_request", "other@example.com")
    for i in range(10000 - len(limiter.buckets)):
        limiter.check("capacity", str(i), 1, 100)
    with pytest.raises(HTTPException):
        limiter.check("new", "key", 1, 100)
    assert len(limiter.buckets) == 10000


def test_file_mail_private_and_smtp_tls(monkeypatch, tmp_path):
    settings = replace(MailSettings(), directory=tmp_path / "mail")
    Mailer(settings).send("student@example.com", "Verify account", "Private link")
    path = next(settings.directory.glob("*.eml"))
    assert path.stat().st_mode & 0o777 == 0o600
    assert settings.directory.stat().st_mode & 0o777 == 0o700
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    assert message["To"] == "student@example.com" and "Private link" in message.get_content()
    from unittest.mock import MagicMock

    smtp = MagicMock()
    monkeypatch.setattr("app.services.mail.smtplib.SMTP", smtp)
    settings = replace(
        settings, backend="smtp", host="smtp.example.com", username="user", password="secret"
    )
    Mailer(settings).send("student@example.com", "Verify account", "Private link")
    transport = smtp.return_value.__enter__.return_value
    transport.starttls.assert_called_once()
    transport.login.assert_called_once_with("user", "secret")
    transport.send_message.assert_called_once()
    assert transport.method_calls[0][0] == "ehlo"
    assert [c[0] for c in transport.method_calls] == [
        "ehlo",
        "starttls",
        "ehlo",
        "login",
        "send_message",
    ]


def test_mail_failures_and_access_logs_do_not_disclose_secrets(caplog):
    class BrokenMailer:
        def send(self, *args):
            raise RuntimeError("secret-token smtp-password")

    with caplog.at_level(logging.ERROR):
        deliver(BrokenMailer(), "student@example.com", "Subject", "secret-token")
    assert "secret-token" not in caplog.text and "smtp-password" not in caplog.text
    for route in ["verify-email", "reset-password"]:
        record = logging.LogRecord(
            "uvicorn.access",
            logging.INFO,
            "",
            0,
            '%s - "%s %s HTTP/%s" %d',
            ("client", "GET", f"/{route}?token=secret-token", "1.1", 303),
            None,
        )
        assert RedactAccountURLs().filter(record)
        assert "secret-token" not in record.getMessage()


def test_production_mail_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("SECRET_KEY", "s" * 40)
    good = replace(
        MailSettings(),
        environment="production",
        backend="smtp",
        base_url="https://planner.example.com",
        host="smtp.example.com",
        from_address="planner@example.com",
    )
    good.validate()
    for fields in [
        {"backend": "file"},
        {"host": ""},
        {"use_tls": False},
        {"base_url": "http://planner.example.com"},
        {"base_url": "https://localhost"},
        {"base_url": "https://127.0.0.1"},
        {"base_url": "https://planner.example.com/path"},
        {"username": "user"},
        {"from_address": "planner@localhost"},
        {"from_name": "bad\r\nheader"},
    ]:
        with pytest.raises(RuntimeError):
            replace(good, **fields).validate()
    monkeypatch.delenv("SECRET_KEY")
    with pytest.raises(RuntimeError):
        good.validate()
    MailSettings().validate()


def test_token_constraints_and_cascade(client, session):
    user = session.scalar(select(User))
    token = session.scalar(select(AccountToken))
    for fields in [
        {"purpose": "other", "token_hash": "a" * 64},
        {"purpose": "verify_email", "token_hash": token.token_hash},
    ]:
        session.add(AccountToken(user_id=user.id, expires_at=utc_now(), **fields))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    session.delete(user)
    session.commit()
    assert not list(session.scalars(select(AccountToken)))


def test_four_segments_deduplicate_physical_codes_and_preserve_totals():
    def record(code, state, units=3):
        return CreditRecord(
            "hkbu_course",
            code,
            "Course",
            Decimal(units),
            3,
            None,
            state,
            allocations=((1, Decimal(units)), (2, Decimal(units))),
        )

    records = [
        record("CORE1001", "earned"),
        record("CORE1001", "in_progress"),
        record("CORE1001", "planned"),
        record("CORE1002", "in_progress"),
        record("CORE1002", "planned"),
        record("CORE1003", "planned"),
        record(None, "earned"),
        record(None, "planned"),
    ]
    profile = SimpleNamespace(
        required_total_units=Decimal(20), requirement_groups=[], level_requirements=[]
    )
    audit = evaluate_progress(profile, records)
    assert (
        audit.earned_units,
        audit.in_progress_units,
        audit.planned_units,
        audit.projected_units,
    ) == (6, 3, 6, 15)
    assert [s["units"] for s in audit.segments] == [6, 3, 6, 5]
    assert sum(s["width"] for s in audit.segments) == 100
    profile.required_total_units = Decimal(7)
    over = evaluate_progress(profile, records)
    assert over.projected_units == 15 and over.unplanned_units == 0
    assert sum(s["width"] for s in over.segments) == 100
    assert all(s["width"] >= 0 for s in over.segments)
    profile.required_total_units = Decimal(0)
    assert all(s["width"] == 0 for s in evaluate_progress(profile, records).segments)


def test_move_dialog_endpoint_validation_and_compact_labels(client, session):
    create_profile(client)
    parent = group(client, "Major", aggregation_mode="sum_children")
    child = group(client, "Core")
    other = group(client, "Other")
    assert (
        post(client, f"/requirements/groups/{child}/parent", parent_id=str(parent)).status_code
        == 303
    )
    assert (
        post(client, f"/requirements/groups/{child}/parent", parent_id=str(other)).status_code
        == 422
    )
    assert (
        post(client, f"/requirements/groups/{parent}/parent", parent_id=str(parent)).status_code
        == 422
    )
    assert (
        post(client, f"/requirements/groups/{child}/parent", parent_id="not-an-id").status_code
        == 422
    )
    nested = group(client, "Nested", parent_id=str(parent), aggregation_mode="sum_children")
    assert (
        post(client, f"/requirements/groups/{parent}/parent", parent_id=str(nested)).status_code
        == 422
    )
    assert post(client, f"/requirements/groups/{child}/parent", parent_id="").status_code == 303
    session.expire_all()
    assert session.get(RequirementGroup, child).parent_id is None
    html = client.get("/requirements").text
    assert "Single target" in html and "Group of targets" in html
    assert "Move to group" in html and "target-dialog" in html
    assert "Indent " not in html and "Outdent " not in html
    assert "Counts toward" in client.get("/planner/terms/1/courses/new").text


@pytest.mark.parametrize(
    "status,grade,segment",
    [
        ("completed", "A", "earned"),
        ("completed", "S", "earned"),
        ("completed", "DT", "earned"),
        ("completed", "F", None),
        ("completed", "E", None),
        ("withdrawn", "W", None),
        ("in_progress", None, "active"),
        ("in_progress", "S", "earned"),
        ("planned", None, "planned"),
        ("planned", "W", None),
    ],
)
def test_progress_segments_use_retained_normal_credit_semantics(status, grade, segment):
    from app.models import PlanCourse, StudentProfile, Term
    from app.services.credit import build_credit_records

    entry = PlanCourse(
        id=1,
        course_code_snapshot="TEST1001",
        course_title_snapshot="Test",
        units=3,
        status=status,
        grade=grade,
    )
    term = Term(id=1, sort_order=0, courses=[entry])
    profile = StudentProfile(required_total_units=128, terms=[term])
    records, _ = build_credit_records(profile)
    audit = evaluate_progress(profile, records)
    values = {s["key"]: s["units"] for s in audit.segments}
    for key in ["earned", "active", "planned"]:
        assert values[key] == (3 if key == segment else 0)


@pytest.mark.parametrize(
    "status,segment",
    [("approved", "earned"), ("pending_approval", "planned"), ("planned", "planned")],
)
def test_progress_segments_use_retained_exchange_semantics(status, segment):
    from app.models import ExchangeCourse, StudentProfile, Term
    from app.services.credit import build_credit_records

    entry = ExchangeCourse(
        host_course_title="Host", transferred_units=3, transfer_status=status, host_grade="F"
    )
    profile = StudentProfile(
        required_total_units=128, terms=[Term(id=1, sort_order=0, exchange_courses=[entry])]
    )
    records, _ = build_credit_records(profile)
    audit = evaluate_progress(profile, records)
    assert next(s["units"] for s in audit.segments if s["key"] == segment) == 3


def test_atomic_token_consumption_and_reset_cancels_all_outstanding(client, session):
    from app.services.account_security import consume_token

    submit(client, "/forgot-password", email="student@example.com")
    link = mail_link(client, "reset-password")
    raw = parse_qs(urlsplit(link).query)["token"][0]
    original = session.scalar(select(AccountToken).where(AccountToken.token_hash == digest(raw)))
    assert original and original.token_hash != raw
    extra = AccountToken(
        user_id=original.user_id,
        purpose="reset_password",
        token_hash=digest("other-test-token"),
        expires_at=utc_now() + timedelta(minutes=30),
    )
    session.add(extra)
    session.commit()
    client.get(link)
    assert (
        submit(
            client, "/reset-password", password=PASSWORD, password_confirmation=PASSWORD
        ).status_code
        == 200
    )
    session.expire_all()
    assert session.get(AccountToken, extra.id).consumed_at
    assert not consume_token(session, original)
    session.rollback()


def test_recovery_rate_limits_enforced_at_routes(client):
    for _ in range(3):
        assert submit(client, "/forgot-password", email="absent@example.com").status_code == 200
    assert submit(client, "/forgot-password", email="absent@example.com").status_code == 429
    for _ in range(30):
        assert (
            submit(
                client, "/reset-password", password=PASSWORD, password_confirmation=PASSWORD
            ).status_code
            == 400
        )
    assert (
        submit(
            client, "/reset-password", password=PASSWORD, password_confirmation=PASSWORD
        ).status_code
        == 429
    )


def test_registration_rate_limit_and_unverified_recovery(anon_client):
    register(anon_client, verify=False)
    count = len(anon_client.mailer.messages)
    assert submit(anon_client, "/forgot-password", email="student@example.com").status_code == 200
    assert len(anon_client.mailer.messages) == count
    for _ in range(4):
        assert register(anon_client, verify=False).status_code == 422
    assert register(anon_client, verify=False).status_code == 429


def test_move_to_group_rejects_foreign_ownership_and_sibling_collision(client, session):
    from app.models import StudentProfile

    create_profile(client)
    parent = group(client, "Major", aggregation_mode="sum_children")
    child = group(client, "Core", parent_id=str(parent))
    second = group(client, "Minor", aggregation_mode="sum_children")
    group(client, "Core", parent_id=str(second))
    foreign = StudentProfile(
        admission_year="2024/2025", programme_name="Other", required_total_units=128
    )
    target = RequirementGroup(
        profile=foreign, name="Foreign", required_units=3, aggregation_mode="sum_children"
    )
    session.add_all([foreign, target])
    session.commit()
    before = client.get("/export/json").json()["requirement_groups"]
    assert (
        post(client, f"/requirements/groups/{child}/parent", parent_id=str(target.id)).status_code
        == 422
    )
    assert (
        post(client, f"/requirements/groups/{target.id}/parent", parent_id=str(parent)).status_code
        == 404
    )
    assert (
        post(client, f"/requirements/groups/{child}/parent", parent_id=str(second)).status_code
        == 422
    )
    assert client.get("/export/json").json()["requirement_groups"] == before
