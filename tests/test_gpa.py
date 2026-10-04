from decimal import Decimal

import pytest

from app.services.gpa import (
    CourseAttemptDTO,
    cumulative_gpa,
    format_gpa,
    gpa_totals,
    select_cumulative_attempts,
    semester_gpa,
)


def attempt(code="TEST1001", grade="B", units=3, order=0, status="completed", identifier=1):
    return CourseAttemptDTO(identifier, code, Decimal(str(units)), grade, status, order)


def test_spreadsheet_example_a():
    rows = [attempt(f"TEST100{i}", grade) for i, grade in enumerate(["B+", "B+", "A-", "B+", "A-"])]
    assert format_gpa(semester_gpa(rows)) == "3.47"
    assert gpa_totals(rows).units == 15


def test_spreadsheet_example_b():
    rows = [
        attempt(f"TEST100{i}", grade, units)
        for i, (units, grade) in enumerate(
            [(2, "B+"), (2, "A-"), (3, "A"), (3, "B-"), (3, "B"), (1, "A")]
        )
    ]
    assert format_gpa(semester_gpa(rows)) == "3.36"
    assert gpa_totals(rows).units == 14


@pytest.mark.parametrize("grade", ["DT", "S", "U", "W", "I", "YR", "NR", "PR", "", None])
def test_non_gpa_grades(grade):
    assert semester_gpa([attempt(grade=grade)]) is None
    assert semester_gpa([attempt(), attempt("TEST1002", grade)]) == Decimal("3")


def test_failure_and_conditional_grade_keep_denominator():
    totals = gpa_totals([attempt(grade="A"), attempt("TEST1002", "F"), attempt("TEST1003", "E")])
    assert totals.units == 9
    assert totals.points == 12
    assert format_gpa(totals.gpa) == "1.33"


def test_repeat_does_not_change_past_semester_gpa():
    rows = [attempt(" math 1005 ", "F"), attempt("MATH1005", "B+", order=3, identifier=2)]
    assert semester_gpa(rows[:1]) == 0
    assert cumulative_gpa(rows, through_sort_order=0) == 0
    assert cumulative_gpa(rows) == Decimal("3.33")


def test_highest_repeat_wins_even_if_latest_grade_is_lower():
    rows = [attempt(grade="A"), attempt(grade="C", order=1), attempt(grade="W", order=2)]
    assert cumulative_gpa(rows) == Decimal(4)


def test_tied_repeat_uses_latest_units_and_id():
    rows = [attempt(units=2), attempt(units=3, order=1, identifier=2)]
    assert select_cumulative_attempts(rows)[0].id == 2
    assert gpa_totals(select_cumulative_attempts(rows)).units == 3


def test_future_and_withdrawn_grades_never_count():
    rows = [
        attempt(),
        attempt("TEST1002", "A", status="planned"),
        attempt("TEST1003", "F", status="withdrawn"),
    ]
    assert cumulative_gpa(rows) == 3
    assert semester_gpa([attempt(status="in_progress", grade="A")]) == 4
    assert format_gpa(None) == "\u2014"


def test_decimal_precision():
    rows = [attempt(units="0.5", grade="A-"), attempt("TEST1002", "B+", units="1.25")]
    assert gpa_totals(rows).points == Decimal("5.9975")
    assert format_gpa(semester_gpa(rows)) == "3.43"
