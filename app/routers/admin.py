from math import ceil

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, load_only

from app.db import get_session
from app.models import AccountToken, AdminAuditLog, StudentProfile, User
from app.models.profile import utc_now
from app.security import require_admin
from app.services.account_security import invalidate_tokens, issue_token
from app.services.accounts import audit_action, delete_account
from app.services.mail import deliver, get_mailer
from app.services.rate_limit import get_limiter
from app.services.readiness import database_readiness, expected_revision
from app.web import render


def authorize(request: Request, session: Session = Depends(get_session)):
    return require_admin(request, session)


router = APIRouter(prefix="/admin", dependencies=[Depends(authorize)])
PAGE_SIZE = 50
ACTIONS = {
    "send_verification": "Send verification email",
    "send_password_reset": "Send password reset email",
    "revoke_sessions": "Revoke all sessions",
    "disable_user": "Disable account",
    "enable_user": "Re-enable account",
    "delete_user": "Delete account and data",
}
SELF_BLOCKED = {"revoke_sessions", "disable_user", "delete_user"}
METADATA = (
    User.id,
    User.username,
    User.email,
    User.email_verified_at,
    User.is_admin,
    User.is_disabled,
    User.created_at,
    User.last_login_at,
    User.disabled_at,
    User.disabled_reason,
)
has_profile = select(StudentProfile.id).where(StudentProfile.user_id == User.id).exists()


def account(session, identifier):
    user = session.scalar(select(User).options(load_only(*METADATA)).where(User.id == identifier))
    if user is None:
        raise HTTPException(404, "That account could not be found.")
    return user


def validate_action(actor, target, action):
    if action not in ACTIONS:
        raise HTTPException(404, "That action could not be found.")
    if actor.id == target.id and action in SELF_BLOCKED:
        raise HTTPException(403, "Use Profile security for your own account.")
    if action in {"send_verification", "send_password_reset"}:
        if target.is_disabled or (action == "send_verification") != (
            target.email_verified_at is None
        ):
            raise HTTPException(409, "Account state does not permit this email.")
    if action == "disable_user" and target.is_disabled:
        raise HTTPException(409, "This account is already disabled.")
    if action == "enable_user" and not target.is_disabled:
        raise HTTPException(409, "This account is already active.")


@router.get("")
def overview(request: Request, session: Session = Depends(get_session)):
    counts = {
        "Users": session.scalar(select(func.count(User.id))),
        "Verified": session.scalar(
            select(func.count(User.id)).where(User.email_verified_at.is_not(None))
        ),
        "Unverified": session.scalar(
            select(func.count(User.id)).where(User.email_verified_at.is_(None))
        ),
        "Disabled": session.scalar(select(func.count(User.id)).where(User.is_disabled.is_(True))),
        "Users with profiles": session.scalar(select(func.count(User.id)).where(has_profile)),
        "Unclaimed local profiles": session.scalar(
            select(func.count(StudentProfile.id)).where(StudentProfile.user_id.is_(None))
        ),
    }
    for purpose, label in [
        ("verify_email", "Outstanding verification links"),
        ("reset_password", "Outstanding reset links"),
    ]:
        counts[label] = session.scalar(
            select(func.count(AccountToken.id)).where(
                AccountToken.purpose == purpose,
                AccountToken.consumed_at.is_(None),
                AccountToken.expires_at > utc_now(),
            )
        )
    ready = database_readiness(session)
    recent = session.execute(
        select(User, has_profile.label("profile_exists"))
        .options(load_only(*METADATA))
        .order_by(User.created_at.desc(), User.id.desc())
        .limit(10)
    ).all()
    return render(
        request,
        "admin.html",
        view="overview",
        heading="Administration",
        counts=counts,
        users=recent,
        ready=ready,
        revision=expected_revision(),
        database=session.get_bind().dialect.name,
    )


@router.get("/users")
def users(
    request: Request,
    q: str = "",
    state: str = "all",
    page: int = 1,
    session: Session = Depends(get_session),
):
    filters = {
        "all": None,
        "verified": User.email_verified_at.is_not(None),
        "unverified": User.email_verified_at.is_(None),
        "disabled": User.is_disabled.is_(True),
        "active": User.is_disabled.is_(False),
        "has_profile": has_profile,
        "no_profile": ~has_profile,
    }
    if state not in filters:
        raise HTTPException(422, "Choose a valid account filter.")
    query = select(User, has_profile.label("profile_exists")).options(load_only(*METADATA))
    q = q.strip().lower()[:254]
    if q:
        query = query.where(
            User.username.contains(q, autoescape=True) | User.email.contains(q, autoescape=True)
        )
    if filters[state] is not None:
        query = query.where(filters[state])
    total = session.scalar(select(func.count()).select_from(query.subquery()))
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = session.execute(
        query.order_by(User.created_at.desc(), User.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    return render(
        request,
        "admin.html",
        view="users",
        heading="Users",
        users=rows,
        q=q,
        state=state,
        page=page,
        pages=pages,
        total=total,
    )


@router.get("/audit")
def audit(request: Request, page: int = 1, session: Session = Depends(get_session)):
    total = session.scalar(select(func.count(AdminAuditLog.id)))
    pages = max(1, ceil(total / PAGE_SIZE))
    page = min(max(1, page), pages)
    rows = list(
        session.scalars(
            select(AdminAuditLog)
            .order_by(AdminAuditLog.created_at.desc(), AdminAuditLog.id.desc())
            .offset((page - 1) * PAGE_SIZE)
            .limit(PAGE_SIZE)
        )
    )
    return render(
        request,
        "admin.html",
        view="audit",
        heading="Admin audit log",
        events=rows,
        actions=ACTIONS,
        page=page,
        pages=pages,
        total=total,
    )


@router.get("/users/{identifier}")
def detail(identifier: int, request: Request, session: Session = Depends(get_session)):
    target = account(session, identifier)
    profile_exists = session.scalar(
        select(has_profile).select_from(User).where(User.id == identifier)
    )
    return render(
        request,
        "admin.html",
        view="detail",
        heading=f"User: {target.username}",
        target=target,
        profile_exists=profile_exists,
        actions=ACTIONS,
    )


@router.get("/users/{identifier}/confirm/{action}")
def confirm(
    identifier: int, action: str, request: Request, session: Session = Depends(get_session)
):
    target = account(session, identifier)
    validate_action(request.state.user, target, action)
    return render(
        request, "admin.html", view="confirm", heading=ACTIONS[action], target=target, action=action
    )


@router.post("/users/{identifier}/{action}")
async def perform(
    identifier: int,
    action: str,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
    mailer=Depends(get_mailer),
    limiter=Depends(get_limiter),
):
    actor = request.state.user
    target = account(session, identifier)
    validate_action(actor, target, action)
    limiter.protect(request, "admin_action", str(actor.id))
    form = await request.form()
    if form.get("confirmed") != "yes":
        raise HTTPException(422, "Confirm this account action first.")
    if action == "delete_user" and str(form.get("confirmation", "")) not in {
        "DELETE",
        target.username,
    }:
        raise HTTPException(422, "Type the target username or DELETE to confirm.")
    reason = str(form.get("reason", "")).strip()
    if action == "disable_user" and len(reason) > 500:
        raise HTTPException(422, "Keep the internal reason within 500 characters.")
    mail = None
    try:
        if action in {"send_verification", "send_password_reset"}:
            verification = action == "send_verification"
            limiter.protect(request, "resend" if verification else "reset_request", target.email)
            subject, body = issue_token(
                session,
                target,
                "verify_email" if verification else "reset_password",
                mailer.settings.base_url,
            )
            mail = (target.email, subject, body)
        elif action == "revoke_sessions":
            session.execute(
                update(User).where(User.id == target.id).values(auth_version=User.auth_version + 1)
            )
            invalidate_tokens(session, target.id, "reset_password")
        elif action == "disable_user":
            session.execute(
                update(User)
                .where(User.id == target.id)
                .values(
                    is_disabled=True,
                    disabled_at=utc_now(),
                    disabled_reason=reason or None,
                    auth_version=User.auth_version + 1,
                )
            )
            invalidate_tokens(session, target.id)
        elif action == "enable_user":
            session.execute(
                update(User)
                .where(User.id == target.id)
                .values(is_disabled=False, disabled_at=None, disabled_reason=None)
            )
        audit_action(
            session,
            actor,
            target,
            action,
            "Delivery requested; not confirmation of delivery." if mail else None,
        )
        if action == "delete_user":
            delete_account(session, target)
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(
            409, "The account action could not be completed. Reload and try again."
        ) from exc
    if mail:
        background.add_task(deliver, mailer, *mail)
    return RedirectResponse(
        "/admin/users?done=delete_user"
        if action == "delete_user"
        else f"/admin/users/{identifier}?done={action}",
        303,
    )
