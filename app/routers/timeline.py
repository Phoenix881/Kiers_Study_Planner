from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import Field, ValidationError, field_validator
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import AcademicYear, Term
from app.schemas.inputs import FormInput, ProfileInput
from app.security import owned_profile, owned_record
from app.services.plans import order_periods, reorder

router = APIRouter()


class YearInput(FormInput):
    academic_year: str
    label: str = Field(min_length=1, max_length=160)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("academic_year")
    @classmethod
    def validate_year(cls, value):
        return ProfileInput.academic_year(value)


class PeriodInput(FormInput):
    name: str = Field(min_length=1, max_length=160)
    term_type: str = Field(default="custom", min_length=1, max_length=80)


def validated(schema, form):
    try:
        return schema.model_validate(dict(form))
    except ValidationError as exc:
        raise HTTPException(422, "; ".join(e["msg"] for e in exc.errors())) from exc


@router.post("/planner/years")
@router.post("/planner/years/{year_id}/edit")
async def save_year(
    request: Request, year_id: int | None = None, session: Session = Depends(get_session)
):
    profile = owned_profile(request, session)
    year = owned_record(request, session, AcademicYear, year_id) if year_id is not None else None
    values = validated(YearInput, await request.form())
    if year is None:
        year = AcademicYear(
            profile=profile,
            sort_order=max((y.sort_order for y in profile.academic_years), default=-1) + 1,
        )
        session.add(year)
    for key, value in values.model_dump().items():
        setattr(year, key, value)
    session.commit()
    return RedirectResponse(f"/planner#year-{year.id}", 303)


@router.post("/planner/years/{year_id}/periods")
async def add_period(year_id: int, request: Request, session: Session = Depends(get_session)):
    year = owned_record(request, session, AcademicYear, year_id)
    values = validated(PeriodInput, await request.form())
    term = Term(
        profile=year.profile,
        academic_year=year,
        sort_order=max((t.sort_order for t in year.profile.terms), default=-1) + 1,
        **values.model_dump(),
    )
    session.add(term)
    session.flush()
    order_periods(session, year.profile)
    session.commit()
    return RedirectResponse(f"/planner#term-{term.id}", 303)


@router.post("/planner/terms/{term_id}/rename")
async def rename_period(term_id: int, request: Request, session: Session = Depends(get_session)):
    term = owned_record(request, session, Term, term_id)
    values = validated(PeriodInput, await request.form())
    term.name = values.name
    term.term_type = values.term_type
    session.commit()
    return RedirectResponse(f"/planner#term-{term.id}", 303)


@router.post("/planner/years/{identifier}/delete")
@router.post("/planner/terms/{identifier}/delete")
def delete_timeline(identifier: int, request: Request, session: Session = Depends(get_session)):
    is_year = "/years/" in request.url.path
    row = owned_record(request, session, AcademicYear if is_year else Term, identifier)
    periods = list(row.periods) if is_year else [row]
    if any(t.courses or t.exchange_courses for t in periods):
        raise HTTPException(
            409, "Move or explicitly delete the study records before deleting this year or period."
        )
    for term in periods:
        session.delete(term)
    session.flush()
    if is_year:
        session.delete(row)
    session.commit()
    return RedirectResponse("/planner", 303)


@router.post("/planner/years/{identifier}/move")
@router.post("/planner/terms/{identifier}/move")
async def move_timeline(identifier: int, request: Request, session: Session = Depends(get_session)):
    is_year = "/years/" in request.url.path
    row = owned_record(request, session, AcademicYear if is_year else Term, identifier)
    rows = sorted(
        row.profile.academic_years if is_year else row.academic_year.periods,
        key=lambda r: r.sort_order,
    )
    direction = (await request.form()).get("direction")
    if direction not in {"up", "down"}:
        raise HTTPException(422, "Choose up or down.")
    index = rows.index(row)
    target = index + (-1 if direction == "up" else 1)
    if 0 <= target < len(rows):
        rows[index], rows[target] = rows[target], rows[index]
        if is_year:
            reorder(session, rows)
            order_periods(session, row.profile)
        else:
            all_periods = []
            for year in sorted(row.profile.academic_years, key=lambda y: y.sort_order):
                all_periods.extend(
                    rows
                    if year.id == row.academic_year_id
                    else sorted(year.periods, key=lambda t: t.sort_order)
                )
            reorder(session, all_periods)
        session.commit()
    return RedirectResponse("/planner", 303)
