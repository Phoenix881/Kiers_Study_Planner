import hashlib
import re
import secrets
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from sqlalchemy import select, update

from app.config import SITE_NAME
from app.models import AccountToken, User
from app.models.profile import utc_now

hasher = PasswordHasher()
dummy_hash = hasher.hash(secrets.token_urlsafe(32))


def valid_password(password, stored_hash=None):
    try:
        if len(password) > 1024:
            return False
        hasher.verify(stored_hash or dummy_hash, password)
        return stored_hash is not None
    except (InvalidHashError, VerificationError):
        return False


def password_errors(password, confirmation):
    errors = {}
    if not 12 <= len(password) <= 1024:
        errors["password"] = "Use a password of 12-1024 characters."
    if password != confirmation:
        errors["password_confirmation"] = "Passwords do not match."
    return errors


def digest(raw):
    return hashlib.sha256(raw.encode()).hexdigest()


def invalidate_tokens(session, user_id, purpose=None):
    statement = update(AccountToken).where(
        AccountToken.user_id == user_id, AccountToken.consumed_at.is_(None)
    )
    if purpose:
        statement = statement.where(AccountToken.purpose == purpose)
    session.execute(statement.values(consumed_at=utc_now()))


def issue_token(session, user, purpose, base_url):
    if user.is_disabled:
        raise ValueError("Account mail is unavailable.")
    invalidate_tokens(session, user.id, purpose)
    raw = secrets.token_urlsafe(32)
    duration = timedelta(hours=24) if purpose == "verify_email" else timedelta(minutes=30)
    session.add(
        AccountToken(
            user_id=user.id,
            purpose=purpose,
            token_hash=digest(raw),
            expires_at=utc_now() + duration,
        )
    )
    verification = purpose == "verify_email"
    action = "verify-email" if verification else "reset-password"
    subject = (
        f"Verify your {SITE_NAME} account" if verification else f"Reset your {SITE_NAME} password"
    )
    lead = (
        f"Verify your email address to finish setting up {SITE_NAME}:"
        if verification
        else "A password reset was requested for your account:"
    )
    expiry = "24 hours" if verification else "30 minutes"
    body = f"Hi {user.username},\n\n{lead}\n\n{base_url}/{action}?token={raw}\n\nThis link expires in {expiry}.\n\nIf you did not request this, you can ignore this email.\n"
    return subject, body


def find_token(session, purpose, raw=None, context=None):
    if raw is not None:
        if not re.fullmatch(r"[A-Za-z0-9_-]{43}", raw):
            return None
        token_hash = digest(raw)
    elif context and context.get("purpose") == purpose:
        token_hash = context.get("hash", "")
    else:
        return None
    return session.scalar(
        select(AccountToken)
        .join(User)
        .where(
            User.is_disabled.is_(False),
            AccountToken.purpose == purpose,
            AccountToken.token_hash == token_hash,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > utc_now(),
        )
    )


def consume_token(session, token):
    result = session.execute(
        update(AccountToken)
        .where(
            AccountToken.id == token.id,
            AccountToken.consumed_at.is_(None),
            AccountToken.expires_at > utc_now(),
            AccountToken.user_id.in_(select(User.id).where(User.is_disabled.is_(False))),
        )
        .values(consumed_at=utc_now())
        .execution_options(synchronize_session=False)
    )
    return result.rowcount == 1
