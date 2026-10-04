from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import (
    CourseVersion,
    ExchangeCourse,
    ExchangeCourseAllocation,
    PlanCourse,
    PlanCourseAllocation,
    Term,
)
from app.schemas.inputs import CourseInput, ExchangeInput, ExchangeSettingsInput
from app.security import owned_profile, owned_record
from app.services.course_catalog import get_by_code, get_version, latest_year
from app.services.credit import EARNED_GRADES
from app.services.levels import official_level
from app.services.requirements import tree_rows
from app.services.summary import build_overview
from app.sources.hkbu_urls import normalize_course_code
from app.web import form_errors, render

router = APIRouter()


def back_to_term(term_id, saved="course"):
    return RedirectResponse(f"/planner?saved={saved}#term-{term_id}", 303)


def entry_form(
    request, session, term, exchange=False, values=None, entry=None, errors=None, allocations=None
):
    period_year = term.academic_year.academic_year.replace("/", "-") if term.academic_year else None
    catalogue_year = (
        period_year
        if period_year
        and session.scalar(
            select(CourseVersion.id).where(CourseVersion.academic_year == period_year).limit(1)
        )
        else latest_year(session)
    )
    return render(
        request,
        "course_form.html",
        422 if errors else 200,
        profile=term.profile,
        term=term,
        exchange=exchange,
        entry=entry,
        values=values if values is not None else (entry or {}),
        errors=errors or {},
        catalogue_year=catalogue_year,
        allocation_tree=tree_rows(term.profile.requirement_groups),
        terms=sorted(term.profile.terms, key=lambda t: t.sort_order),
        allocation_values=allocations
        if allocations is not None
        else (entry.allocations if entry else []),
    )


def require_term_mode(term, exchange):
    if term.is_exchange != exchange:
        raise HTTPException(
            409, "This course does not match the period type. Check the exchange setting."
        )


@router.get("/planner")
def planner(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session)
    return render(request, "planner.html", profile=profile, overview=build_overview(profile))


@router.get("/planner/terms/{term_id}/courses/new")
def new_course(
    term_id: int,
    request: Request,
    code: str = "",
    version_id: int | None = None,
    session: Session = Depends(get_session),
):
    term = owned_record(request, session, Term, term_id)
    require_term_mode(term, False)
    version = get_version(session, code, version_id) if code else None
    if version_id is not None and version is None:
        raise HTTPException(404, "Catalogue version not found.")
    values = (
        {
            "course_code_snapshot": version.code,
            "course_title_snapshot": version.title,
            "units": version.units,
            "course_version_id": version.id,
            "course_id": version.course_id,
            "level_snapshot": version.level,
            "source_year": version.academic_year,
        }
        if version
        else {}
    )
    return entry_form(request, session, term, values=values)


@router.get("/planner/courses/{entry_id}/edit")
def edit_course(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, PlanCourse, entry_id)
    return entry_form(request, session, entry.term, entry=entry)


def allocation_rows(form, profile, units):
    identifiers = form.getlist("allocation_group_id")
    amounts = form.getlist("allocated_units")
    if len(identifiers) != len(amounts):
        raise ValueError("Each allocation needs a group and units.")
    groups = {g.id: g for g in profile.requirement_groups}
    seen = set()
    rows = []
    for identifier, amount in zip(identifiers, amounts, strict=True):
        if not identifier:
            continue
        try:
            identifier = int(identifier)
            value = Decimal(amount) if amount.strip() else units
        except (ValueError, InvalidOperation):
            raise ValueError("Choose a valid allocation and unit amount.") from None
        if identifier not in groups:
            raise ValueError("Choose a target from your own profile.")
        if groups[identifier].aggregation_mode == "sum_children":
            raise ValueError("Allocate courses to a leaf requirement, not a container.")
        if identifier in seen:
            raise ValueError("A course cannot have duplicate allocations to the same group.")
        if not value.is_finite() or value < 0 or value > units or value.as_tuple().exponent < -2:
            raise ValueError(
                "Each allocation must be between zero and the course units, with at most two decimal places."
            )
        seen.add(identifier)
        rows.append((groups[identifier], value))
    return rows


async def save_entry(request, session, term, entry=None, exchange=False):
    form = await request.form()
    values = dict(form)
    allocations = [
        {"requirement_group_id": g, "allocated_units": u}
        for g, u in zip(form.getlist("allocation_group_id"), form.getlist("allocated_units"))
    ]
    schema = ExchangeInput if exchange else CourseInput
    try:
        data = schema.model_validate(values)
        target_id = int(values.get("term_id") or term.id)
        target = owned_record(request, session, Term, target_id)
        require_term_mode(target, exchange)
        version = None
        if not exchange and values.get("course_version_id"):
            version = get_version(
                session, data.course_code_snapshot, int(values["course_version_id"])
            )
            if version is None:
                raise ValueError("The catalogue version does not match this code.")
            if values.get("course_id") and int(values["course_id"]) != version.course_id:
                raise ValueError("The catalogue identity does not match this version.")
            if entry is None:
                data.course_title_snapshot = version.title
                data.units = version.units
        units = data.transferred_units if exchange else data.units
        rows = allocation_rows(form, term.profile, units)
        if not exchange and (
            entry is None or data.course_code_snapshot != entry.course_code_snapshot
        ):
            passed = any(
                normalize_course_code(e.course_code_snapshot) == data.course_code_snapshot
                and e.grade in EARNED_GRADES
                and e.status in {"completed", "in_progress"}
                for t in term.profile.terms
                for e in t.courses
                if e is not entry
            )
            if passed and not data.exceptional_repeat:
                raise ValueError(
                    "A passing attempt already exists. A program-required exceptional repeat must be explicitly selected."
                )
    except ValidationError as exc:
        return entry_form(
            request, session, term, exchange, values, entry, form_errors(exc), allocations
        )
    except (ValueError, InvalidOperation) as exc:
        return entry_form(
            request, session, term, exchange, values, entry, {"course": str(exc)}, allocations
        )
    new = entry is None
    old_code = (
        (entry.hkbu_equivalent_code if exchange else entry.course_code_snapshot) if entry else None
    )
    if new:
        entry = ExchangeCourse() if exchange else PlanCourse()
        session.add(entry)
    entry.term = target
    for key, value in data.model_dump(exclude={"requirement_group"}).items():
        setattr(entry, key, value)
    if exchange:
        equivalent = (
            get_by_code(session, data.hkbu_equivalent_code) if data.hkbu_equivalent_code else None
        )
        if (
            new
            or old_code != data.hkbu_equivalent_code
            or entry.hkbu_equivalent_course_id != (equivalent.id if equivalent else None)
        ):
            entry.level_snapshot = official_level(equivalent)
        entry.equivalent_course = equivalent
    else:
        if (
            new
            or old_code != data.course_code_snapshot
            or entry.course_version_id != (version.id if version else None)
        ):
            entry.level_snapshot = version.level if version else None
        entry.course_version = version
        entry.course = version.course if version else None
    if new:
        entry.requirement_group = ""
    entry.allocations.clear()
    session.flush()
    allocation_model = ExchangeCourseAllocation if exchange else PlanCourseAllocation
    for group, amount in rows:
        entry.allocations.append(allocation_model(group=group, allocated_units=amount))
    session.commit()
    return back_to_term(target.id, "exchange" if exchange else "course")


@router.post("/planner/terms/{term_id}/courses")
async def add_course(term_id: int, request: Request, session: Session = Depends(get_session)):
    return await save_entry(request, session, owned_record(request, session, Term, term_id))


@router.post("/planner/courses/{entry_id}/edit")
async def update_course(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, PlanCourse, entry_id)
    return await save_entry(request, session, entry.term, entry)


@router.post("/planner/courses/{entry_id}/delete")
def delete_course(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, PlanCourse, entry_id)
    term_id = entry.term_id
    session.delete(entry)
    session.commit()
    return back_to_term(term_id, "deleted")


@router.post("/planner/terms/{term_id}/exchange/toggle")
@router.post("/planner/terms/{term_id}/exchange")
async def exchange_settings(
    term_id: int, request: Request, session: Session = Depends(get_session)
):
    term = owned_record(request, session, Term, term_id)
    values = dict(await request.form())
    errors = {}
    try:
        data = ExchangeSettingsInput.model_validate(values)
        if data.is_exchange != term.is_exchange and (term.courses or term.exchange_courses):
            errors["is_exchange"] = (
                "Move or remove existing courses before changing this period's type. Your courses have been kept."
            )
    except ValidationError as exc:
        errors = form_errors(exc)
    if errors:
        return render(
            request,
            "planner.html",
            422,
            profile=term.profile,
            overview=build_overview(term.profile),
            errors=errors,
            error_term_id=term.id,
            term_values=values,
        )
    term.is_exchange = data.is_exchange
    term.host_university = data.host_university or None
    term.notes = data.notes or None
    session.commit()
    return back_to_term(term.id, "term")


@router.get("/planner/terms/{term_id}/exchange-courses/new")
def new_exchange(term_id: int, request: Request, session: Session = Depends(get_session)):
    term = owned_record(request, session, Term, term_id)
    require_term_mode(term, True)
    return entry_form(request, session, term, exchange=True)


@router.get("/planner/exchange-courses/{entry_id}/edit")
def edit_exchange(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, ExchangeCourse, entry_id)
    return entry_form(request, session, entry.term, exchange=True, entry=entry)


@router.post("/planner/terms/{term_id}/exchange-courses")
async def add_exchange(term_id: int, request: Request, session: Session = Depends(get_session)):
    return await save_entry(
        request, session, owned_record(request, session, Term, term_id), exchange=True
    )


@router.post("/planner/exchange-courses/{entry_id}/edit")
async def update_exchange(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, ExchangeCourse, entry_id)
    return await save_entry(request, session, entry.term, entry, exchange=True)


@router.post("/planner/exchange-courses/{entry_id}/delete")
def delete_exchange(entry_id: int, request: Request, session: Session = Depends(get_session)):
    entry = owned_record(request, session, ExchangeCourse, entry_id)
    term_id = entry.term_id
    session.delete(entry)
    session.commit()
    return back_to_term(term_id, "deleted")
