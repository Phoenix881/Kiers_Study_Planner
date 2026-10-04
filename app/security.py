import secrets

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.models import Course, CourseVersion, ExchangeCourse, PlanCourse, StudentProfile, Term, User


def current_user(request, session):
    request.state.admin_access = False
    user_id = request.session.get("user_id")
    user = session.get(User, user_id) if isinstance(user_id, int) else None
    if (
        user is None
        or user.is_disabled
        or user.email_verified_at is None
        or request.session.get("auth_version") != user.auth_version
    ):
        request.session.clear()
        raise HTTPException(303, "Please sign in.", headers={"Location": "/login"})
    request.state.user = user
    request.state.admin_access = user.is_admin
    request.session["theme_preference"] = user.theme_preference
    return user


def require_admin(request, session):
    user = current_user(request, session)
    if not user.is_admin:
        raise HTTPException(403, "Administrator access is required.")
    return user


def owned_profile(request, session, required=True):
    user = current_user(request, session)
    profile = session.scalar(
        select(StudentProfile)
        .where(StudentProfile.user_id == user.id)
        .options(
            selectinload(StudentProfile.requirement_groups),
            selectinload(StudentProfile.level_requirements),
            selectinload(StudentProfile.academic_years),
            selectinload(StudentProfile.terms).joinedload(Term.academic_year),
            selectinload(StudentProfile.terms)
            .selectinload(Term.courses)
            .selectinload(PlanCourse.allocations),
            selectinload(StudentProfile.terms)
            .selectinload(Term.courses)
            .joinedload(PlanCourse.course_version)
            .joinedload(CourseVersion.course),
            selectinload(StudentProfile.terms)
            .selectinload(Term.exchange_courses)
            .selectinload(ExchangeCourse.allocations),
            selectinload(StudentProfile.terms)
            .selectinload(Term.exchange_courses)
            .joinedload(ExchangeCourse.equivalent_course)
            .selectinload(Course.versions),
        )
    )
    if required and profile is None:
        raise HTTPException(303, "Set up your academic profile.", headers={"Location": "/profile"})
    return profile


def owned_record(request, session, model, identifier):
    profile = owned_profile(request, session)
    item = session.get(model, identifier)
    owner = getattr(item, "profile_id", None)
    if item is not None and hasattr(item, "term"):
        owner = item.term.profile_id
    if item is None or owner != profile.id:
        raise HTTPException(404, "That record could not be found.")
    return item


async def csrf_protect(request: Request):
    if "csrf_token" not in request.session:
        request.session["csrf_token"] = secrets.token_urlsafe(32)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        form = await request.form()
        provided = str(form.get("csrf_token", ""))
        if not secrets.compare_digest(provided, request.session["csrf_token"]):
            raise HTTPException(403, "This form expired. Reload the page and try again.")
