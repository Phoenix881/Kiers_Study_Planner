import re
from dataclasses import dataclass

from sqlalchemy import case, func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.models import Course, CourseVersion
from app.sources.hkbu_urls import normalize_course_code


def latest_year(session):
    return session.scalar(
        select(func.max(CourseVersion.academic_year)).where(
            CourseVersion.data_status == "official_imported"
        )
    ) or session.scalar(select(func.max(CourseVersion.academic_year)))


def course_query(session, query="", year=None, level="all", prefix=""):
    statement = select(CourseVersion).join(Course).options(joinedload(CourseVersion.course))
    selected_year = year if year is not None else latest_year(session)
    statement = (
        statement.where(CourseVersion.academic_year == selected_year)
        if selected_year and selected_year != "unknown"
        else statement.where(CourseVersion.academic_year.is_(None))
    )
    if query.strip():
        statement = statement.where(
            or_(
                Course.code.icontains(normalize_course_code(query), autoescape=True),
                CourseVersion.title.icontains(query.strip(), autoescape=True),
            )
        )
    if level == "undergraduate":
        statement = statement.where(CourseVersion.level.between(1, 4))
    elif level == "unknown":
        statement = statement.where(CourseVersion.level.is_(None))
    elif level.isdigit():
        statement = statement.where(CourseVersion.level == int(level))
    if prefix:
        statement = statement.where(
            or_(
                Course.code.istartswith(prefix, autoescape=True), CourseVersion.department == prefix
            )
        )
    return statement


def search_courses(session: Session, query="", limit=100, year=None, level="all", prefix=""):
    statement = course_query(session, query, year, level, prefix)
    return list(session.scalars(statement.order_by(Course.code, CourseVersion.id).limit(limit)))


@dataclass
class CataloguePage:
    rows: list
    total: int
    page: int
    pages: int
    start: int
    end: int


def paginate_courses(session, query="", year=None, level="all", prefix="", page=1, page_size=50):
    statement = course_query(session, query, year, level, prefix)
    total = session.scalar(select(func.count()).select_from(statement.subquery()))
    pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), pages)
    offset = (page - 1) * page_size
    rows = list(
        session.scalars(
            statement.order_by(Course.code, CourseVersion.id).offset(offset).limit(page_size)
        )
    )
    return CataloguePage(
        rows, total, page, pages, offset + 1 if total else 0, min(offset + page_size, total)
    )


def autocomplete_courses(session, query, year=None, limit=12):
    query = " ".join(query.strip().split())[:200]
    if not query:
        return []
    code = re.sub(r"[\s.-]+", "", query).upper()
    title = re.sub(r"[^\w]+", " ", query).strip().lower()
    title_column = func.lower(CourseVersion.title)
    for punctuation in ("-", "/", ":", ",", ".", "(", ")"):
        title_column = func.replace(title_column, punctuation, " ")
    title_prefix = title_column.startswith(title, autoescape=True)
    title_match = title_column.contains(title, autoescape=True)
    code_prefix = Course.code.istartswith(code, autoescape=True)
    code_match = Course.code.icontains(code, autoescape=True)
    statement = course_query(session, year=year).where(or_(code_match, title_match))
    rank = case(
        (Course.code == code, 0), (code_prefix, 1), (code_match, 2), (title_prefix, 3), else_=4
    )
    return list(
        session.scalars(
            statement.order_by(rank, Course.code, CourseVersion.id).limit(min(12, max(1, limit)))
        )
    )


def get_by_code(session: Session, code: str) -> Course | None:
    return session.scalar(select(Course).where(Course.code == normalize_course_code(code)))


def get_version(session, code, version_id=None, year=None):
    course = get_by_code(session, code)
    if course is None:
        return None
    if version_id is not None:
        return next((v for v in course.versions if v.id == version_id), None)
    if year is not None:
        return next((v for v in course.versions if v.academic_year == year), None)
    return course.latest_version
