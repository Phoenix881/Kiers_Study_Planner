"""Conservative local level resolution. Never derive a level from code digits."""

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload, selectinload

from app.models import Course, CourseVersion, ExchangeCourse, PlanCourse
from app.sources.hkbu_urls import normalize_course_code, valid_course_code


def official_level(course):
    if course is None:
        return None
    levels = {
        v.level
        for v in course.versions
        if v.data_status == "official_imported" and v.level is not None
    }
    return next(iter(levels)) if len(levels) == 1 else None


def normal_level(entry):
    if entry.level_snapshot is not None:
        return entry.level_snapshot
    version = entry.course_version
    if version and normalize_course_code(version.code) == normalize_course_code(
        entry.course_code_snapshot
    ):
        return version.level
    return None


def exchange_level(entry):
    code = normalize_course_code(entry.hkbu_equivalent_code or "")
    if not valid_course_code(code):
        return None
    if entry.level_snapshot is not None:
        return entry.level_snapshot
    course = entry.equivalent_course
    return official_level(course) if course and course.code == code else None


def backfill_levels(session, apply=False):
    catalogue = {}
    for course in session.scalars(select(Course).options(selectinload(Course.versions))):
        catalogue.setdefault(normalize_course_code(course.code), []).append(course)
    report = {
        "inspected": 0,
        "filled": 0,
        "already_known": 0,
        "unknown": 0,
        "historical_snapshots_overwritten": 0,
        "unresolved": [],
        "apply": apply,
    }
    for model in (PlanCourse, ExchangeCourse):
        statement = select(model).order_by(model.id)
        if model is PlanCourse:
            statement = statement.options(
                joinedload(PlanCourse.course_version).joinedload(CourseVersion.course)
            )
        for entry in session.scalars(statement):
            report["inspected"] += 1
            if entry.level_snapshot is not None:
                report["already_known"] += 1
                continue
            code = normalize_course_code(
                entry.course_code_snapshot
                if model is PlanCourse
                else entry.hkbu_equivalent_code or ""
            )
            level = normal_level(entry) if model is PlanCourse else None
            matches = catalogue.get(code, []) if valid_course_code(code) else []
            if level is None and len(matches) == 1:
                level = official_level(matches[0])
            if level is None:
                report["unknown"] += 1
                report["unresolved"].append(
                    {
                        "table": model.__tablename__,
                        "id": entry.id,
                        "code": code or None,
                        "reason": "No unambiguous known official level",
                    }
                )
                continue
            report["filled"] += 1
            if apply:
                values = {"level_snapshot": level}
                if model is PlanCourse:
                    values["updated_at"] = entry.updated_at
                # Only the missing level changes, including preservation of record timestamps.
                session.execute(
                    update(model)
                    .where(model.id == entry.id, model.level_snapshot.is_(None))
                    .values(**values)
                )
    return report
