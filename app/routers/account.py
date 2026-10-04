import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import SITE_NAME
from app.db import get_session
from app.models import User
from app.models.profile import utc_now
from app.routers.auth import sign_in
from app.security import current_user
from app.services.account_security import (
    consume_token,
    find_token,
    hasher,
    invalidate_tokens,
    issue_token,
    password_errors,
    valid_password,
)
from app.services.mail import deliver, get_mailer
from app.services.rate_limit import get_limiter
from app.web import render

router = APIRouter()
RESET_MESSAGE = "If an account exists for that email, a password-reset link has been sent."
INVALID_MESSAGE = "This link is invalid, expired or already used. Request a new link."


@router.get("/check-email")
def check_email(request: Request, session: Session = Depends(get_session)):
    user = (
        session.get(User, request.session.get("pending_user_id"))
        if request.session.get("pending_user_id")
        else None
    )
    if user is None or user.is_disabled or user.email_verified_at is not None:
        return RedirectResponse("/login", 303)
    return render(
        request,
        "account.html",
        mode="check",
        heading="Check your email",
        message="Verify your email address to continue.",
    )


@router.post("/resend-verification")
def resend(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    user = (
        session.get(User, request.session.get("pending_user_id"))
        if request.session.get("pending_user_id")
        else None
    )
    limiter.protect(request, "resend", user.email if user else "")
    if user and not user.is_disabled and user.email_verified_at is None:
        subject, body = issue_token(session, user, "verify_email", mailer.settings.base_url)
        session.commit()
        background.add_task(deliver, mailer, user.email, subject, body)
    return render(
        request,
        "account.html",
        mode="check",
        heading="Check your email",
        message="If verification is needed, a new link has been sent.",
    )


@router.get("/verify-email")
@router.get("/reset-password")
def token_page(request: Request, token: str | None = None, session: Session = Depends(get_session)):
    purpose = "verify_email" if request.url.path == "/verify-email" else "reset_password"
    row = find_token(session, purpose, raw=token, context=request.session.get("account_token"))
    if row is None:
        request.session.pop("account_token", None)
        return render(
            request,
            "account.html",
            400,
            mode="invalid",
            heading="Link unavailable",
            message=INVALID_MESSAGE,
        )
    if token is not None:
        # Strip the secret query before displaying the form; only signed, purpose-bound context remains.
        request.session["account_token"] = {"purpose": purpose, "hash": row.token_hash}
        return RedirectResponse(request.url.path, 303)
    return render(
        request,
        "account.html",
        mode="verify" if purpose == "verify_email" else "reset",
        heading="Verify your email" if purpose == "verify_email" else "Reset password",
        message="",
    )


@router.post("/verify-email")
def verify(request: Request, session: Session = Depends(get_session), limiter=Depends(get_limiter)):
    context = request.session.get("account_token")
    limiter.protect(request, "verify_submit", str((context or {}).get("hash", "")))
    token = find_token(session, "verify_email", context=context)
    if token is None or not consume_token(session, token):
        session.rollback()
        raise HTTPException(400, INVALID_MESSAGE)
    session.execute(
        update(User).where(User.id == token.user_id).values(email_verified_at=utc_now())
    )
    invalidate_tokens(session, token.user_id, "verify_email")
    session.commit()
    request.session.clear()
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return render(
        request,
        "account.html",
        mode="success",
        heading="Email verified",
        message="Your email is verified. Sign in to continue.",
    )


@router.get("/forgot-password")
def forgot_page(request: Request):
    return render(
        request, "account.html", mode="forgot", heading="Forgot your password?", message=""
    )


@router.post("/forgot-password")
async def forgot(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    email = str((await request.form()).get("email", "")).strip().lower()[:254]
    limiter.protect(request, "reset_request", email)
    user = session.scalar(
        select(User).where(
            User.email == email, User.email_verified_at.is_not(None), User.is_disabled.is_(False)
        )
    )
    if user:
        subject, body = issue_token(session, user, "reset_password", mailer.settings.base_url)
        session.commit()
        background.add_task(deliver, mailer, user.email, subject, body)
    # Delivery runs after the response; SMTP latency does not disclose account existence.
    return render(
        request, "account.html", mode="sent", heading="Check your email", message=RESET_MESSAGE
    )


@router.post("/reset-password")
async def reset(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    context = request.session.get("account_token")
    limiter.protect(request, "reset_submit", str((context or {}).get("hash", "")))
    token = find_token(session, "reset_password", context=context)
    if token is None:
        raise HTTPException(400, INVALID_MESSAGE)
    form = await request.form()
    password = str(form.get("password", ""))
    errors = password_errors(password, form.get("password_confirmation"))
    if errors:
        return render(
            request,
            "account.html",
            422,
            mode="reset",
            heading="Reset password",
            message="",
            errors=errors,
        )
    password_hash = hasher.hash(password)
    if not consume_token(session, token):
        session.rollback()
        raise HTTPException(400, INVALID_MESSAGE)
    user = session.get(User, token.user_id)
    session.execute(
        update(User)
        .where(User.id == user.id)
        .values(password_hash=password_hash, auth_version=User.auth_version + 1)
    )
    invalidate_tokens(session, user.id, "reset_password")
    session.commit()
    request.session.clear()
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    background.add_task(
        deliver,
        mailer,
        user.email,
        f"Your {SITE_NAME} password changed",
        "Your password was reset. All previous signed-in sessions have been signed out. If this was not you, recover your account immediately.",
    )
    return render(
        request,
        "account.html",
        mode="success",
        heading="Password reset",
        message="Your password has been changed. Sign in with your new password.",
    )


@router.get("/account/security")
def security_page(request: Request, session: Session = Depends(get_session)):
    current_user(request, session)
    return render(request, "account.html", mode="change", heading="Change password", message="")


@router.post("/account/security")
async def change_password(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    user = current_user(request, session)
    limiter.protect(request, "password_change", str(user.id))
    form = await request.form()
    password = str(form.get("password", ""))
    errors = password_errors(password, form.get("password_confirmation"))
    if not valid_password(str(form.get("current_password", "")), user.password_hash):
        errors["current_password"] = "Current password is incorrect."
    if errors:
        return render(
            request,
            "account.html",
            422,
            mode="change",
            heading="Change password",
            message="",
            errors=errors,
        )
    next_version = user.auth_version + 1
    changed = session.execute(
        update(User)
        .where(User.id == user.id, User.auth_version == user.auth_version)
        .values(password_hash=hasher.hash(password), auth_version=User.auth_version + 1)
    )
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "Account security changed. Sign in again.")
    invalidate_tokens(session, user.id, "reset_password")
    session.commit()
    session.refresh(user)
    sign_in(request, user, auth_version=next_version)
    background.add_task(
        deliver,
        mailer,
        user.email,
        f"Your {SITE_NAME} password changed",
        "Your password was changed. Other signed-in sessions have been signed out. If this was not you, recover your account immediately.",
    )
    return render(
        request,
        "account.html",
        mode="changed",
        heading="Password changed",
        message="Your password is updated. Other sessions have been signed out.",
    )
