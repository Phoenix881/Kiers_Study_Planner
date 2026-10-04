from collections import Counter
from dataclasses import dataclass
from decimal import Decimal

from app.services.gpa import GRADE_POINTS, ZERO
from app.services.levels import exchange_level, normal_level
from app.sources.hkbu_urls import normalize_course_code

EARNED_GRADES = frozenset({"A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "S", "DT"})


@dataclass(frozen=True)
class CreditRecord:
    source_type: str
    code: str | None
    title: str
    units: Decimal
    level: int | None
    requirement_group: str | None
    state: str
    term_id: int | None = None
    allocations: tuple[tuple[int, Decimal], ...] = ()


def earned_units_for_grade(grade: str | None, units: Decimal, status: str) -> Decimal:
    if status in {"completed", "in_progress"} and grade in EARNED_GRADES:
        return Decimal(str(units))
    return ZERO


def course_state(entry) -> str:
    if entry.status == "withdrawn" or entry.grade == "W":
        return "not_counted"
    if entry.status == "planned":
        return "planned"
    if entry.grade in EARNED_GRADES and entry.status in {"completed", "in_progress"}:
        return "earned"
    if entry.status == "in_progress" and entry.grade not in {"E", "F", "U"}:
        return "in_progress"
    return "not_counted"


def build_credit_records(
    profile, through_sort_order: int | None = None
) -> tuple[list[CreditRecord], list[str]]:
    normal = {}
    exchange = []
    repeats = Counter()
    warnings = []
    priority = {"not_counted": 0, "planned": 1, "in_progress": 2, "earned": 3}
    for term in sorted(profile.terms, key=lambda t: t.sort_order):
        if through_sort_order is not None and term.sort_order > through_sort_order:
            continue
        for entry in term.courses:
            code = normalize_course_code(entry.course_code_snapshot)
            state = course_state(entry)
            record = CreditRecord(
                "hkbu_course",
                code,
                entry.course_title_snapshot,
                Decimal(str(entry.units)),
                normal_level(entry),
                entry.requirement_group,
                state,
                term.id,
                tuple(
                    (a.requirement_group_id, Decimal(str(a.allocated_units)))
                    for a in entry.allocations
                ),
            )
            rank = (
                priority[state],
                GRADE_POINTS.get(entry.grade, Decimal(-1)) if state == "earned" else ZERO,
                term.sort_order,
                entry.id or 0,
            )
            repeats[code] += 1
            if code not in normal or rank > normal[code][0]:
                normal[code] = (rank, record)
        for entry in term.exchange_courses:
            code = (
                normalize_course_code(entry.hkbu_equivalent_code)
                if entry.hkbu_equivalent_code
                else None
            )
            exchange.append(
                CreditRecord(
                    "exchange",
                    code,
                    entry.host_course_title,
                    Decimal(str(entry.transferred_units)),
                    exchange_level(entry),
                    entry.requirement_group,
                    "earned" if entry.transfer_status == "approved" else "planned",
                    term.id,
                    tuple(
                        (a.requirement_group_id, Decimal(str(a.allocated_units)))
                        for a in entry.allocations
                    ),
                )
            )
    for code, count in repeats.items():
        if count > 1:
            warnings.append(
                f"{code}: {count} normal attempts. Repeat-course degree units are counted once; semester GPAs retain each attempt."
            )
    records = [record for _, record in normal.values()] + exchange
    counted = Counter(
        record.code for record in records if record.code and record.state != "not_counted"
    )
    for code, count in counted.items():
        if count > 1:
            warnings.append(
                f"Duplicate HKBU equivalent {code}: {count} entries include exchange transfer. Proposed equivalents may coexist; overall units count the code once. Confirm final equivalents and allocations."
            )
    return records, warnings


def unique_records(records, states):
    selected = {}
    priority = {"planned": 1, "in_progress": 2, "earned": 3}
    for index, record in enumerate(records):
        if record.state not in states:
            continue
        key = record.code or f"unmapped-transfer-{index}"
        rank = (priority[record.state], record.units, index)
        if key not in selected or rank > selected[key][0]:
            selected[key] = (rank, record)
    return [r for _, r in selected.values()]
