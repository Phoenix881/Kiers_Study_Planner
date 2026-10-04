from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

from app.sources.hkbu_urls import normalize_course_code

GRADE_POINTS = {
    grade: Decimal(points)
    for grade, points in {
        "A": "4.00",
        "A-": "3.67",
        "B+": "3.33",
        "B": "3.00",
        "B-": "2.67",
        "C+": "2.33",
        "C": "2.00",
        "C-": "1.67",
        "D": "1.00",
        "E": "0.00",
        "F": "0.00",
    }.items()
}
NON_GPA_GRADES = frozenset({"DT", "I", "S", "U", "W", "YR", "NR", "PR"})
ZERO = Decimal(0)


@dataclass(frozen=True)
class CourseAttemptDTO:
    id: int
    code: str
    units: Decimal
    grade: str | None
    status: str
    sort_order: int


@dataclass(frozen=True)
class GPATotals:
    units: Decimal
    points: Decimal

    @property
    def gpa(self) -> Decimal | None:
        return self.points / self.units if self.units else None


def is_gpa_bearing(attempt: CourseAttemptDTO) -> bool:
    return attempt.status in {"completed", "in_progress"} and attempt.grade in GRADE_POINTS


def gpa_totals(attempts: Iterable[CourseAttemptDTO]) -> GPATotals:
    eligible = [attempt for attempt in attempts if is_gpa_bearing(attempt)]
    return GPATotals(
        sum((Decimal(str(a.units)) for a in eligible), ZERO),
        sum((Decimal(str(a.units)) * GRADE_POINTS[a.grade] for a in eligible), ZERO),
    )


def semester_gpa(attempts: Iterable[CourseAttemptDTO]) -> Decimal | None:
    return gpa_totals(attempts).gpa


def select_cumulative_attempts(
    attempts: Iterable[CourseAttemptDTO], through_sort_order: int | None = None
) -> list[CourseAttemptDTO]:
    def rank(attempt):
        return GRADE_POINTS[attempt.grade], attempt.sort_order, attempt.id

    selected: dict[str, CourseAttemptDTO] = {}
    for attempt in attempts:
        if not is_gpa_bearing(attempt) or (
            through_sort_order is not None and attempt.sort_order > through_sort_order
        ):
            continue
        code = normalize_course_code(attempt.code)
        prior = selected.get(code)
        if prior is None or rank(attempt) > rank(prior):
            selected[code] = attempt
    return list(selected.values())


def cumulative_gpa(
    attempts: Iterable[CourseAttemptDTO], through_sort_order: int | None = None
) -> Decimal | None:
    return gpa_totals(select_cumulative_attempts(attempts, through_sort_order)).gpa


def format_gpa(value: Decimal | None) -> str:
    return (
        "\u2014" if value is None else str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    )
