import json
import os
import sqlite3
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import ROOT
from app.db import get_session
from app.main import app
from app.models import AccountToken, AdminAuditLog, User
from app.models.profile import utc_now
from app.services.backups import backup_database, verify_backup
from app.services.readiness import expected_revision
from app.services.registration import RegistrationSettings
from app.services.token_cleanup import cleanup_tokens
from scripts.set_admin import set_admin
from tests.conftest import csrf, register
from tests.test_v04 import login, submit
from tests.test_v05_admin import user


def cli(engine, script, *args):
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script), *map(str, args)],
        env={**os.environ, "DATABASE_URL": str(engine.url)},
        capture_output=True,
        text=True,
    )


def test_readiness_success_mismatch_and_absent_revision(client, session):
    assert client.get("/health").json() == {"status": "ok", "version": "0.5.0"}
    assert client.get("/ready").status_code == 503
    session.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) PRIMARY KEY)"))
    session.execute(
        text("INSERT INTO alembic_version VALUES (:revision)"), {"revision": expected_revision()}
    )
    session.commit()
    ready = client.get("/ready")
    assert ready.status_code == 200 and ready.json() == {"status": "ready", "version": "0.5.0"}
    session.execute(text("UPDATE alembic_version SET version_num='outdated'"))
    session.commit()
    assert client.get("/ready").json() == {"status": "not_ready", "version": "0.5.0"}
    assert client.get("/ready").status_code == 503


def test_readiness_failure_is_generic_and_does_not_need_network(client):
    class FailingSession:
        def execute(self, *args):
            raise RuntimeError("private/path/database-password")

        def rollback(self):
            pass

    original = app.dependency_overrides[get_session]
    app.dependency_overrides[get_session] = lambda: FailingSession()
    try:
        response = client.get("/ready")
    finally:
        app.dependency_overrides[get_session] = original
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "version": "0.5.0"}
    assert "private" not in response.text


def test_request_ids_and_generic_errors_do_not_log_bodies(client, engine, caplog):
    from sqlalchemy import event

    def fail(connection, cursor, statement, parameters, context, many):
        raise RuntimeError("secret-key smtp-password token-hash CSRF invite-code")

    event.listen(engine, "before_cursor_execute", fail)
    try:
        response = client.post(
            "/login?token=secret-query",
            headers={"X-Request-ID": "untrusted-id"},
            data={
                "csrf_token": csrf(client, "/login"),
                "identifier": "student",
                "password": "secret-body",
            },
        )
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert response.status_code == 500
    assert len(response.headers["x-request-id"]) == 32
    assert "untrusted-id" not in response.headers["x-request-id"]
    for secret in [
        "secret-key",
        "smtp-password",
        "token-hash",
        "invite-code",
        "secret-query",
        "secret-body",
    ]:
        assert secret not in response.text + caplog.text
    assert "route=/login" in caplog.text and "exception=RuntimeError" in caplog.text
    assert response.headers["x-request-id"] in response.text


def test_set_admin_exact_cli_lookup_last_admin_and_session_revocation(client, session, engine):
    response = cli(engine, "set_admin.py", "  STUDENT@EXAMPLE.COM  ", "--grant")
    assert response.returncode == 0 and "student: admin granted" in response.stdout
    session.expire_all()
    actor = session.get(User, 1)
    assert actor.is_admin and actor.auth_version == 1
    assert client.get("/admin", follow_redirects=False).headers["location"] == "/login"
    assert cli(engine, "set_admin.py", "student", "--revoke").returncode != 0
    assert cli(engine, "set_admin.py", "stu", "--grant").returncode != 0
    assert cli(engine, "set_admin.py", "new", "--grant").returncode != 0
    assert cli(engine, "set_admin.py", "student", "--revoke", "--force").returncode == 0
    session.expire_all()
    assert not session.get(User, 1).is_admin and session.get(User, 1).auth_version == 2
    assert len(list(session.scalars(select(User)))) == 1
    assert [
        a.action for a in session.scalars(select(AdminAuditLog).order_by(AdminAuditLog.id))
    ] == ["grant_admin", "revoke_admin"]
    assert actor.password_hash not in response.stdout + response.stderr


def test_admin_cli_idempotence_and_multiple_admins(session):
    first = user(session, "first")
    second = user(session, "second")
    assert set_admin(session, "first", True) == ("first", True)
    assert set_admin(session, "first", True) == ("first", False)
    assert set_admin(session, "second", True) == ("second", True)
    session.commit()
    assert set_admin(session, "first", False) == ("first", True)
    session.commit()
    assert not first.is_admin and second.is_admin


def test_backup_consistency_privacy_and_retention(tmp_path):
    source = tmp_path / "source.sqlite3"
    db = sqlite3.connect(source)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("CREATE TABLE example (id INTEGER PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO example VALUES (1,'private test row')")
    db.commit()
    directory = tmp_path / "backups"
    result = backup_database(f"sqlite:///{source}", directory, verify=True)
    path = Path(result["file"])
    assert result["verified"] and result["bytes"] > 0
    assert path.stat().st_mode & 0o777 == 0o600
    assert directory.stat().st_mode & 0o777 == 0o700
    with sqlite3.connect(path) as backup:
        assert backup.execute("SELECT * FROM example").fetchall() == [(1, "private test row")]
    assert db.execute("SELECT * FROM example").fetchall() == [(1, "private test row")]
    unrelated = directory / "do-not-delete.sqlite3"
    unrelated.write_text("unrelated")
    symlink = directory / "kiers-study-planner-20000101T000000000000Z.sqlite3"
    symlink.symlink_to(unrelated)
    for _ in range(3):
        result = backup_database(f"sqlite:///{source}", directory, keep=2)
    assert result["verified"]
    assert (
        len([p for p in directory.glob("kiers-study-planner-*.sqlite3") if not p.is_symlink()]) == 2
    )
    assert unrelated.read_text() == "unrelated" and symlink.is_symlink()
    assert verify_backup(result["file"])
    db.close()


def test_backup_and_verification_cli_errors_and_no_row_contents(client, engine, tmp_path):
    response = cli(
        engine, "backup_db.py", "--output-dir", tmp_path / "backups", "--verify", "--keep", "2"
    )
    assert response.returncode == 0, response.stderr
    result = json.loads(response.stdout)
    assert cli(engine, "verify_backup.py", result["file"]).returncode == 0
    assert "student@example.com" not in response.stdout
    assert cli(engine, "backup_db.py", "--output-dir", engine.url.database).returncode != 0
    assert cli(engine, "backup_db.py", "--keep", "0").returncode != 0
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"invalid database")
    assert cli(engine, "verify_backup.py", corrupt).returncode != 0
    with pytest.raises(ValueError):
        backup_database("sqlite:///:memory:", tmp_path)
    with pytest.raises(ValueError):
        backup_database(f"sqlite:///{tmp_path / 'missing.sqlite3'}", tmp_path)


def test_backup_verification_rejects_foreign_key_violations(tmp_path):
    path = tmp_path / "invalid-fk.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))"
        )
        db.execute("INSERT INTO child VALUES (1,42)")
    with pytest.raises(ValueError, match="foreign-key"):
        verify_backup(path)


def test_token_cleanup_retention_dry_run_apply_and_cli(client, session, engine):
    now = utc_now()
    states = [
        (now + timedelta(days=3), None),
        (now - timedelta(days=2), None),
        (now - timedelta(days=40), None),
        (now + timedelta(days=10), now - timedelta(days=40)),
        (now - timedelta(days=1), now - timedelta(days=1)),
    ]
    ids = []
    for i, (expiry, consumed) in enumerate(states):
        token = AccountToken(
            user_id=1,
            purpose="reset_password",
            token_hash=f"{i:064x}",
            created_at=now - timedelta(days=60),
            expires_at=expiry,
            consumed_at=consumed,
        )
        session.add(token)
        session.flush()
        ids.append(token.id)
    session.commit()
    assert cleanup_tokens(session) == {"eligible": 2, "removed": 0}
    assert all(session.get(AccountToken, identifier) for identifier in ids)
    preview = cli(engine, "cleanup_account_tokens.py", "--older-than-days", 30)
    assert json.loads(preview.stdout) == {"eligible": 2, "removed": 0}
    applied = cli(engine, "cleanup_account_tokens.py", "--older-than-days", 30, "--apply")
    assert applied.returncode == 0 and json.loads(applied.stdout) == {"eligible": 2, "removed": 2}
    session.expire_all()
    for i, identifier in enumerate(ids):
        assert (session.get(AccountToken, identifier) is None) == (i in {2, 3})
    assert "token_hash" not in preview.stdout + applied.stdout
    assert cli(engine, "cleanup_account_tokens.py", "--older-than-days", -1).returncode != 0


def test_invite_registration_never_echoes_or_logs_code(anon_client, session, monkeypatch, caplog):
    monkeypatch.setenv("REGISTRATION_MODE", "invite")
    monkeypatch.setenv("BETA_INVITE_CODE", "correct-private-code")
    assert "Beta access code" in anon_client.get("/register").text
    data = {
        "email": "beta@example.com",
        "username": "beta",
        "password": "Test-password-123",
        "password_confirmation": "Test-password-123",
    }
    rejected = submit(anon_client, "/register", **data, invite_code="wrong-private-code")
    assert rejected.status_code == 422
    assert "wrong-private-code" not in rejected.text + caplog.text
    assert not list(session.scalars(select(User)))
    accepted = submit(anon_client, "/register", **data, invite_code="correct-private-code")
    assert accepted.status_code == 303
    assert "correct-private-code" not in accepted.text + caplog.text
    assert len(list(session.scalars(select(User)))) == 1


def test_closed_registration_preserves_login_recovery(client, session, monkeypatch):
    monkeypatch.setenv("REGISTRATION_MODE", "closed")
    assert client.get("/register").status_code == 403
    assert register(client, "other").status_code == 403
    assert len(list(session.scalars(select(User)))) == 1
    assert login(client).status_code == 303
    assert submit(client, "/forgot-password", email="student@example.com").status_code == 200


def test_gate_configuration_fails_closed_and_constant_time_compatible(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    for settings in [
        RegistrationSettings("invalid"),
        RegistrationSettings("invite"),
        RegistrationSettings("invite", "x" * 257),
    ]:
        with pytest.raises(RuntimeError):
            settings.validate()
    assert RegistrationSettings().accepts("")
    assert not RegistrationSettings("closed").accepts("anything")
    gate = RegistrationSettings("invite", "valid")
    gate.validate()
    assert gate.accepts("valid") and not gate.accepts("invalid")
    monkeypatch.setenv("REGISTRATION_MODE", "invite")
    monkeypatch.delenv("BETA_INVITE_CODE", raising=False)
    with pytest.raises(RuntimeError, match="BETA_INVITE_CODE"):
        with TestClient(app):
            pass
