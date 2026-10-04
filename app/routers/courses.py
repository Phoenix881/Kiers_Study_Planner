from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Course, CourseVersion, Term
from app.security import current_user, owned_profile, owned_record
from app.services.course_catalog import (
    autocomplete_courses,
    get_version,
    latest_year,
    paginate_courses,
)
from app.sources.hkbu_urls import course_outline_url
from app.web import render

router = APIRouter()


@router.get("/courses")
def courses(
    request: Request,
    q: str = "",
    year: str | None = None,
    level: str = "undergraduate",
    prefix: str = "",
    page: int = 1,
    session: Session = Depends(get_session),
):
    profile = owned_profile(request, session, required=False)
    selected = year if year is not None else latest_year(session)
    years = list(
        session.scalars(
            select(CourseVersion.academic_year)
            .distinct()
            .order_by(CourseVersion.academic_year.desc())
        )
    )
    prefixes = sorted(
        {"".join(c for c in code if c.isalpha()) for code in session.scalars(select(Course.code))}
    )
    result = paginate_courses(
        session, q[:200], year=selected, level=level, prefix=prefix, page=page
    )

    def page_url(number):
        return str(request.url.include_query_params(page=number))

    return render(
        request,
        "courses.html",
        profile=profile,
        courses=result.rows,
        pagination=result,
        page_url=page_url,
        page_numbers=range(max(1, result.page - 2), min(result.pages, result.page + 2) + 1),
        q=q[:200],
        selected_year=selected,
        years=years,
        level=level,
        prefix=prefix,
        prefixes=prefixes,
        latest_year=latest_year(session),
    )


@router.get("/api/courses/search")
@router.get("/api/catalogue/search")
def search(
    request: Request,
    q: str = "",
    year: str | None = None,
    academic_year: str | None = None,
    limit: int = 12,
    session: Session = Depends(get_session),
):
    current_user(request, session)
    return [
        {
            "course_id": c.course_id,
            "version_id": c.id,
            "code": c.code,
            "title": c.title,
            "units": str(c.units),
            "level": c.level,
            "academic_year": c.academic_year,
            "data_status": c.data_status,
        }
        for c in autocomplete_courses(session, q[:200], limit=limit, year=academic_year or year)
    ]


@router.get("/courses/{course_code}")
def course_detail(
    course_code: str,
    request: Request,
    version_id: int | None = None,
    session: Session = Depends(get_session),
):
    profile = owned_profile(request, session, required=False)
    version = get_version(session, course_code, version_id)
    if version is None:
        raise HTTPException(
            404, "This course version is not in the local catalogue. You can still add it manually."
        )
    return render(
        request,
        "course_detail.html",
        profile=profile,
        course=version,
        outline_url=version.outline_url or course_outline_url(version.code),
        latest_year=latest_year(session),
    )


@router.get("/courses/{course_code}/add")
def choose_term(
    course_code: str,
    term_id: int,
    request: Request,
    version_id: int | None = None,
    session: Session = Depends(get_session),
):
    term = owned_record(request, session, Term, term_id)
    version = get_version(session, course_code, version_id)
    if version is None:
        raise HTTPException(404, "This course version is not in the local catalogue.")
    if term.is_exchange:
        raise HTTPException(
            409, "Choose a normal HKBU period. Exchange equivalents are entered separately."
        )
    return RedirectResponse(
        f"/planner/terms/{term.id}/courses/new?code={version.code}&version_id={version.id}", 303
    )
