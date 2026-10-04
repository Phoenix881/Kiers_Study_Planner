import re
import secrets

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import StudentProfile, User
from app.models.profile import utc_now
from app.security import current_user
from app.services.account_security import hasher, issue_token, password_errors, valid_password
from app.services.mail import deliver, get_mailer
from app.services.rate_limit import get_limiter
from app.services.registration import RegistrationSettings
from app.web import render

router = APIRouter()


def sign_in(request, user, *, auth_version):
    request.session.clear()
    request.session.update(
        user_id=user.id,
        auth_version=auth_version,
        username=user.username,
        theme_preference=user.theme_preference,
        csrf_token=secrets.token_urlsafe(32),
    )


def claimable(session, user):
    first_id = session.scalar(select(func.min(User.id)))
    rows = list(session.scalars(select(StudentProfile).where(StudentProfile.user_id.is_(None))))
    return rows[0] if user.id == first_id and user.profile is None and len(rows) == 1 else None


@router.get("/register")
@router.get("/login")
def auth_page(request: Request):
    registering = request.url.path == "/register"
    closed = registering and RegistrationSettings.from_env().mode == "closed"
    return render(request, "auth.html", 403 if closed else 200, register=registering, values={})


@router.post("/register")
async def register(
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    form = await request.form()
    email = str(form.get("email", "")).strip().lower()
    username = str(form.get("username", "")).strip().lower()
    password = str(form.get("password", ""))
    limiter.protect(request, "register", email)
    gate = RegistrationSettings.from_env()
    if gate.mode == "closed":
        return render(request, "auth.html", 403, register=True, values={})
    errors = password_errors(password, form.get("password_confirmation"))
    if not gate.accepts(str(form.get("invite_code", ""))):
        errors["invite_code"] = "Enter a valid beta access code."
    if len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
        errors["email"] = "Enter a valid email address."
    if not re.fullmatch(r"[a-z0-9_.-]{3,80}", username):
        errors["username"] = "Use 3-80 letters, numbers, dots, hyphens or underscores."
    for field, value in [("email", email), ("username", username)]:
        if session.scalar(select(User.id).where(getattr(User, field) == value)):
            errors["account"] = (
                "Unable to create an account with those details. Try signing in or recovering your password."
            )
    if errors:
        return render(
            request,
            "auth.html",
            422,
            register=True,
            values={"email": email, "username": username},
            errors=errors,
        )
    user = User(email=email, username=username, password_hash=hasher.hash(password))
    session.add(user)
    try:
        session.flush()
        subject, body = issue_token(session, user, "verify_email", mailer.settings.base_url)
        session.commit()
    except IntegrityError:
        session.rollback()
        return render(
            request,
            "auth.html",
            422,
            register=True,
            values={},
            errors={"account": "Unable to create an account with those details."},
        )
    background.add_task(deliver, mailer, user.email, subject, body)
    request.session.clear()
    request.session.update(pending_user_id=user.id, csrf_token=secrets.token_urlsafe(32))
    return RedirectResponse("/check-email", 303)


@router.post("/login")
async def login(
    request: Request, session: Session = Depends(get_session), limiter=Depends(get_limiter)
):
    form = await request.form()
    identifier = str(form.get("identifier", "")).strip().lower()
    password = str(form.get("password", ""))
    limiter.protect(request, "login", identifier)
    user = session.scalar(
        select(User).where((User.email == identifier) | (User.username == identifier))
    )
    if not valid_password(password, user.password_hash if user else None):
        return render(
            request,
            "auth.html",
            422,
            register=False,
            values={"identifier": identifier},
            errors={"account": "Email/username or password is incorrect."},
        )
    if user.is_disabled:
        return render(
            request,
            "auth.html",
            403,
            register=False,
            values={"identifier": identifier},
            errors={
                "account": "This account is currently unavailable. Contact the site administrator."
            },
        )
    if user.email_verified_at is None:
        request.session.clear()
        request.session.update(pending_user_id=user.id, csrf_token=secrets.token_urlsafe(32))
        return RedirectResponse("/check-email", 303)
    authenticated_version = user.auth_version
    values = {"last_login_at": utc_now()}
    if hasher.check_needs_rehash(user.password_hash):
        values["password_hash"] = hasher.hash(password)
    changed = session.execute(
        update(User)
        .where(
            User.id == user.id,
            User.auth_version == authenticated_version,
            User.password_hash == user.password_hash,
            User.is_disabled.is_(False),
            User.email_verified_at.is_not(None),
        )
        .values(**values)
        .execution_options(synchronize_session=False)
    )
    if changed.rowcount != 1:
        session.rollback()
        request.session.clear()
        raise HTTPException(409, "Account security changed. Sign in again.")
    session.commit()
    sign_in(request, user, auth_version=authenticated_version)
    return RedirectResponse("/claim" if claimable(session, user) else "/", 303)


@router.post("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", 303)


@router.post("/account/theme")
async def theme(request: Request, session: Session = Depends(get_session)):
    user = current_user(request, session)
    preference = (await request.form()).get("theme_preference")
    if preference not in {"system", "light", "dark"}:
        raise HTTPException(422, "Choose System, Light or Dark.")
    user.theme_preference = preference
    session.commit()
    request.session["theme_preference"] = preference
    return {"theme_preference": preference}


@router.get("/claim")
def claim_page(request: Request, session: Session = Depends(get_session)):
    user = current_user(request, session)
    profile = claimable(session, user)
    if profile is None:
        return RedirectResponse("/profile", 303)
    return render(request, "claim.html", legacy=profile)


@router.post("/claim")
async def claim(request: Request, session: Session = Depends(get_session)):
    user = current_user(request, session)
    profile = claimable(session, user)
    if profile is None:
        raise HTTPException(409, "No local plan is available to claim.")
    choice = (await request.form()).get("choice")
    if choice == "claim":
        result = session.execute(
            update(StudentProfile)
            .where(StudentProfile.id == profile.id, StudentProfile.user_id.is_(None))
            .values(user_id=user.id)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "This plan has already been claimed.")
        session.commit()
        return RedirectResponse("/profile", 303)
    if choice != "new":
        raise HTTPException(422, "Choose an existing or new plan.")
    return RedirectResponse("/profile", 303)
