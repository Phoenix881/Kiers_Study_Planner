import re
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import Base, get_session, make_engine
from app.main import app
from app.models import User
from app.services.mail import MailSettings, get_mailer
from app.services.rate_limit import RateLimiter, get_limiter


class FakeMailer:
    settings = MailSettings()

    def __init__(self):
        self.messages = []

    def send(self, recipient, subject, body):
        self.messages.append({"to": recipient, "subject": subject, "body": body})


def mail_link(client, purpose):
    message = next(m for m in reversed(client.mailer.messages) if f"/{purpose}?token=" in m["body"])
    url = re.search(r"https?://\S+", message["body"]).group()
    parsed = urlsplit(url)
    return parsed.path + "?" + parsed.query


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def anon_client(engine):
    def override():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_session] = override
    mailer = FakeMailer()
    limiter = RateLimiter()
    app.dependency_overrides[get_mailer] = lambda: mailer
    app.dependency_overrides[get_limiter] = lambda: limiter
    with TestClient(app) as client:
        client.mailer = mailer
        client.limiter = limiter
        yield client
    app.dependency_overrides.clear()


@pytest.fixture
def client(anon_client):
    register(anon_client)
    return anon_client


@pytest.fixture
def admin(client, session):
    actor = session.scalar(select(User))
    actor.is_admin = True
    session.commit()
    return client


def register(client, username="student", email=None, verify=True):
    response = client.post(
        "/register",
        data={
            "csrf_token": csrf(client, "/register"),
            "email": email or f"{username}@example.com",
            "username": username,
            "password": "Test-password-123",
            "password_confirmation": "Test-password-123",
        },
        follow_redirects=False,
    )
    if response.status_code != 303 or not verify:
        return response
    client.get(mail_link(client, "verify-email"))
    client.post("/verify-email", data={"csrf_token": csrf(client, "/verify-email")})
    return client.post(
        "/login",
        data={
            "csrf_token": csrf(client, "/login"),
            "identifier": username,
            "password": "Test-password-123",
        },
        follow_redirects=False,
    )


def csrf(client, path="/profile"):
    response = client.get(path)
    match = re.search(r'name="csrf_token" value="([^"]+)"', response.text)
    assert match, response.text
    return match.group(1)


def create_profile(client):
    return client.post(
        "/profile",
        data={
            "csrf_token": csrf(client),
            "admission_year": "2024/25",
            "programme_name": "BSc Mathematics",
            "required_total_units": "128",
            "curriculum_key": "demo_math_stats_2024_25",
        },
        follow_redirects=False,
    )
