import re
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.main import app
from app.models import AccountToken, AdminAuditLog, StudentProfile, User
from app.models.profile import utc_now
from app.routers import auth
from app.services.account_security import digest, hasher
from tests.conftest import create_profile, csrf
from tests.test_v04 import login, submit

PASSWORD = "Test-password-123"
HASH = hasher.hash(PASSWORD)


def user(session, name="target", verified=True, **values):
    result = User(
        username=name,
        email=f"{name}@example.com",
        password_hash=HASH,
        email_verified_at=utc_now() if verified else None,
        **values,
    )
    session.add(result)
    session.commit()
    return result


def action(client, target, operation, **values):
    return client.post(
        f"/admin/users/{target}/{operation}",
        data={"csrf_token": csrf(client, "/admin"), "confirmed": "yes", **values},
        follow_redirects=False,
    )


def audit_count(session):
    return session.scalar(select(func.count(AdminAuditLog.id)))


@pytest.mark.parametrize(
    "path",
    [
        "/admin",
        "/admin/users",
        "/admin/audit",
        "/admin/users/1",
        "/admin/users/1/confirm/disable_user",
    ],
)
def test_non_admin_cannot_access_admin(client, path):
    response = client.get(path)
    assert response.status_code == 403
    assert "Administrator access" in response.text


def test_all_admin_mutations_reject_normal_users_and_csrf(admin, session):
    target = user(session)
    for operation in [
        "send_verification",
        "send_password_reset",
        "revoke_sessions",
        "disable_user",
        "enable_user",
        "delete_user",
    ]:
        assert (
            admin.post(
                f"/admin/users/{target.id}/{operation}", data={"confirmed": "yes"}
            ).status_code
            == 403
        )
    actor = session.get(User, 1)
    actor.is_admin = False
    session.commit()
    for operation in [
        "send_verification",
        "send_password_reset",
        "revoke_sessions",
        "disable_user",
        "enable_user",
        "delete_user",
    ]:
        assert action(admin, target.id, operation).status_code == 403
    assert audit_count(session) == 0


@pytest.mark.parametrize("state", ["unverified", "disabled", "stale_version"])
def test_admin_requires_full_valid_account(admin, session, state):
    actor = session.get(User, 1)
    if state == "unverified":
        actor.email_verified_at = None
    elif state == "disabled":
        actor.is_disabled = True
    else:
        actor.auth_version += 1
    session.commit()
    assert admin.get("/admin", follow_redirects=False).headers["location"] == "/login"


def test_admin_metadata_privacy_nav_pagination_and_search(admin, session):
    target = user(session, name="private")
    session.add(
        StudentProfile(
            user_id=target.id,
            admission_year="2024/2025",
            programme_name="PRIVATE ACADEMIC PROGRAMME",
            minor_name="PRIVATE NOTES",
            required_total_units=128,
        )
    )
    session.add_all(
        [
            User(username=f"sample{i:03}", email=f"sample{i:03}@example.com", password_hash=HASH)
            for i in range(60)
        ]
    )
    session.commit()
    assert 'href="/admin"' in admin.get("/profile").text
    for path in ["/admin", "/admin/users", f"/admin/users/{target.id}"]:
        response = admin.get(path)
        assert response.status_code == 200
        for secret in [
            HASH,
            "PRIVATE ACADEMIC PROGRAMME",
            "PRIVATE NOTES",
            "auth_version",
            "token_hash",
        ]:
            assert secret not in response.text
    assert "Page 1 of 2" in admin.get("/admin/users?q=sample").text
    assert (
        len(re.findall(r'<tr><td><a href="/admin/users/', admin.get("/admin/users?q=sample").text))
        == 50
    )
    second = admin.get("/admin/users?q=sample&page=2").text
    assert len(re.findall(r'<tr><td><a href="/admin/users/', second)) == 10
    assert "private@example.com" in admin.get("/admin/users?q=PRIVATE%40EXAMPLE.COM").text
    assert "No accounts found." in admin.get("/admin/users?q=%25_").text
    for state in ["verified", "unverified", "disabled", "active", "has_profile", "no_profile"]:
        assert admin.get(f"/admin/users?state={state}").status_code == 200
    assert "private@example.com" in admin.get("/admin/users?state=has_profile").text
    assert "private@example.com" not in admin.get("/admin/users?state=no_profile").text
    assert admin.get("/admin/users?state=invalid").status_code == 422
    assert admin.get("/admin/users/999999").status_code == 404
    assert action(admin, 999999, "disable_user").status_code == 404
    assert audit_count(session) == 0


def test_admin_mail_uses_existing_services_without_exposing_tokens(admin, session):
    target = user(session, verified=False)
    assert action(admin, target.id, "send_verification").status_code == 303
    first = session.scalar(select(AccountToken).where(AccountToken.user_id == target.id))
    assert first.purpose == "verify_email" and first.consumed_at is None
    assert action(admin, target.id, "send_verification").status_code == 303
    session.refresh(first)
    assert first.consumed_at
    assert action(admin, target.id, "send_password_reset").status_code == 409
    target.email_verified_at = utc_now()
    session.commit()
    assert action(admin, target.id, "send_password_reset").status_code == 303
    assert audit_count(session) == 3
    html = admin.get(f"/admin/users/{target.id}").text + admin.get("/admin/audit").text
    for token in session.scalars(select(AccountToken)):
        assert token.token_hash not in html
    assert all(
        "Delivery requested" in row.details for row in session.scalars(select(AdminAuditLog))
    )
    assert all(m["to"] == target.email for m in admin.mailer.messages[-3:])
    assert action(admin, target.id, "send_verification").status_code == 409
    assert audit_count(session) == 3


def test_admin_confirmation_required_and_self_actions_blocked(admin, session):
    target = user(session)
    response = admin.post(
        f"/admin/users/{target.id}/disable_user", data={"csrf_token": csrf(admin, "/admin")}
    )
    assert response.status_code == 422
    for operation in ["disable_user", "delete_user", "revoke_sessions"]:
        assert action(admin, 1, operation, confirmation="DELETE").status_code == 403
        assert admin.get(f"/admin/users/1/confirm/{operation}").status_code == 403
    assert action(admin, target.id, "delete_user", confirmation="wrong").status_code == 422
    assert action(admin, target.id, "disable_user", reason="x" * 501).status_code == 422
    assert audit_count(session) == 0
    assert session.get(User, target.id)


def test_disable_reenable_blocks_login_mail_tokens_and_sessions(admin, session):
    target = user(session)
    with TestClient(app) as browser:
        assert login(browser, target.username).status_code == 303
        old_cookie = browser.cookies.get("session")
        initial_login = session.get(User, target.id).last_login_at
        session.refresh(target)
        initial_login = target.last_login_at
        assert initial_login
        session.add(
            AccountToken(
                user_id=target.id,
                purpose="reset_password",
                token_hash=digest("x"),
                expires_at=utc_now() + timedelta(minutes=30),
            )
        )
        session.commit()
        before_mail = len(admin.mailer.messages)
        assert action(admin, target.id, "disable_user", reason="Operator note").status_code == 303
        session.refresh(target)
        assert target.is_disabled and target.disabled_at and target.auth_version == 1
        assert all(
            t.consumed_at
            for t in session.scalars(select(AccountToken).where(AccountToken.user_id == target.id))
        )
        for path in ["/planner", "/export/json", "/account/security", "/account/delete"]:
            browser.cookies.clear()
            browser.cookies.set("session", old_cookie)
            assert browser.get(path, follow_redirects=False).headers["location"] == "/login"
        wrong = login(browser, target.username, "wrong")
        assert wrong.status_code == 422 and "currently unavailable" not in wrong.text
        correct = login(browser, target.username)
        assert correct.status_code == 403 and "currently unavailable" in correct.text
        public = submit(browser, "/forgot-password", email=target.email)
        missing = submit(browser, "/forgot-password", email="missing@example.com")
        assert public.text == missing.text
        assert len(admin.mailer.messages) == before_mail
        assert action(admin, target.id, "send_password_reset").status_code == 409
        assert action(admin, target.id, "send_verification").status_code == 409
        session.refresh(target)
        assert target.last_login_at == initial_login
        assert action(admin, target.id, "enable_user").status_code == 303
        session.refresh(target)
        assert (
            not target.is_disabled and target.disabled_at is None and target.disabled_reason is None
        )
        assert target.auth_version == 1
        assert login(browser, target.username).status_code == 303
        session.refresh(target)
        assert target.last_login_at > initial_login
    assert audit_count(session) == 2


def test_revoke_preserves_account_fields_but_invalidates_reset_and_session(admin, session):
    target = user(session)
    with TestClient(app) as browser:
        login(browser, target.username)
        cookie = browser.cookies.get("session")
        submit(browser, "/forgot-password", email=target.email)
        assert action(admin, target.id, "revoke_sessions").status_code == 303
        session.refresh(target)
        assert (
            target.auth_version == 1 and target.password_hash == HASH and target.email_verified_at
        )
        assert all(
            t.consumed_at
            for t in session.scalars(select(AccountToken).where(AccountToken.user_id == target.id))
        )
        browser.cookies.clear()
        browser.cookies.set("session", cookie)
        assert browser.get("/profile", follow_redirects=False).headers["location"] == "/login"
    assert audit_count(session) == 1


def test_disabled_unverified_user_cannot_resend_or_use_old_token(anon_client, session):
    from tests.conftest import mail_link, register

    register(anon_client, verify=False)
    link = mail_link(anon_client, "verify-email")
    target = session.scalar(select(User))
    target.is_disabled = True
    session.commit()
    # Even a direct disable outside the admin action blocks unconsumed links.
    assert anon_client.get(link).status_code == 400
    assert (
        anon_client.post(
            "/resend-verification", data={"csrf_token": csrf(anon_client, "/login")}
        ).status_code
        == 200
    )
    assert len(anon_client.mailer.messages) == 1


def test_last_login_only_full_login_and_no_admin_nav(client, session):
    create_profile(client)
    target = session.get(User, 1)
    first = target.last_login_at
    assert first is not None
    for path in ["/profile", "/", "/account/security"]:
        assert 'href="/admin"' not in client.get(path).text
    assert login(client, password="wrong").status_code == 422
    session.refresh(target)
    assert target.last_login_at == first
    assert login(client).status_code == 303
    session.refresh(target)
    assert target.last_login_at > first


@pytest.mark.parametrize("operation", ["disable", "reset", "revoke"])
def test_concurrent_security_change_rejects_login_before_last_login_write(
    client, session, engine, monkeypatch, operation
):
    target = user(session, name="concurrent")
    identifier = target.id
    original = auth.valid_password

    def concurrent_change(password, stored):
        accepted = original(password, stored)
        with Session(engine) as writer:
            values = {"auth_version": User.auth_version + 1}
            if operation == "disable":
                values["is_disabled"] = True
            elif operation == "reset":
                values["password_hash"] = "different-test-hash"
            writer.execute(update(User).where(User.id == identifier).values(**values))
            writer.commit()
        return accepted

    monkeypatch.setattr(auth, "valid_password", concurrent_change)
    assert login(client, "concurrent").status_code == 409
    session.expire_all()
    assert session.get(User, identifier).last_login_at is None
    assert client.get("/profile", follow_redirects=False).headers["location"] == "/login"


def test_login_never_borrows_a_new_session_version_after_commit(
    client, session, engine, monkeypatch
):
    target = user(session, name="concurrent")
    identifier = target.id
    original = auth.sign_in

    def concurrent_revoke(request, account, *, auth_version):
        with Session(engine) as writer:
            writer.execute(
                update(User).where(User.id == identifier).values(auth_version=User.auth_version + 1)
            )
            writer.commit()
        original(request, account, auth_version=auth_version)

    monkeypatch.setattr(auth, "sign_in", concurrent_revoke)
    assert login(client, "concurrent").status_code == 303
    assert client.get("/profile", follow_redirects=False).headers["location"] == "/login"


def test_audit_paginated_and_user_fk_snapshots_survive(admin, session):
    target = user(session)
    target_id = target.id
    session.add_all(
        [
            AdminAuditLog(
                admin_user_id=1,
                admin_username_snapshot="student",
                target_user_id=target.id,
                target_username_snapshot=target.username,
                action="revoke_sessions",
            )
            for _ in range(55)
        ]
    )
    session.commit()
    assert "Page 1 of 2" in admin.get("/admin/audit").text
    assert "Page 2 of 2" in admin.get("/admin/audit?page=2").text
    assert action(admin, target.id, "delete_user", confirmation=target.username).status_code == 303
    session.expire_all()
    rows = list(session.scalars(select(AdminAuditLog)))
    assert len(rows) == 56 and all(
        r.target_user_id is None and r.target_username_snapshot == "target" for r in rows
    )
    assert all(r.admin_user_id == 1 for r in rows)
    assert session.get(User, target_id) is None
    assert session.execute(text("PRAGMA foreign_key_check")).all() == []
