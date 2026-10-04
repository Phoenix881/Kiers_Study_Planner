import json
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from app.db import get_session
from app.security import owned_profile

router = APIRouter()


def serialize_row(row):
    result = {}
    for column in inspect(row).mapper.column_attrs:
        value = getattr(row, column.key)
        result[column.key] = (
            str(value)
            if isinstance(value, Decimal)
            else value.isoformat()
            if isinstance(value, datetime)
            else value
        )
    return result


@router.get("/export/json")
def export_json(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session)
    if profile is None:
        return RedirectResponse("/profile", status_code=303)
    courses = {e.course.id: e.course for t in profile.terms for e in t.courses if e.course}
    courses.update(
        {
            e.equivalent_course.id: e.equivalent_course
            for t in profile.terms
            for e in t.exchange_courses
            if e.equivalent_course
        }
    )
    payload = {
        "format": "hkbu-study-companion",
        "version": 2,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "profile": serialize_row(profile),
        "terms": [serialize_row(t) for t in profile.terms],
        "plan_courses": [serialize_row(e) for t in profile.terms for e in t.courses],
        "exchange_courses": [serialize_row(e) for t in profile.terms for e in t.exchange_courses],
        "catalogue_courses": [serialize_row(c) for c in courses.values()],
        "course_versions": [serialize_row(v) for c in courses.values() for v in c.versions],
        "academic_years": [serialize_row(y) for y in profile.academic_years],
        "requirement_groups": [serialize_row(g) for g in profile.requirement_groups],
        "level_requirements": [serialize_row(r) for r in profile.level_requirements],
        "plan_course_allocations": [
            serialize_row(a) for t in profile.terms for e in t.courses for a in e.allocations
        ],
        "exchange_course_allocations": [
            serialize_row(a)
            for t in profile.terms
            for e in t.exchange_courses
            for a in e.allocations
        ],
    }
    return Response(
        json.dumps(payload, indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": 'attachment; filename="hkbu-study-plan.json"',
            "Cache-Control": "no-store",
        },
    )
