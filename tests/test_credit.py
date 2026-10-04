from decimal import Decimal

import pytest

from app.models import ExchangeCourse, PlanCourse, StudentProfile, Term
from app.services.credit import build_credit_records, earned_units_for_grade
from app.services.gpa import cumulative_gpa
from app.services.summary import attempts_for_profile


@pytest.mark.parametrize("grade", ["A", "A-", "B+", "B", "B-", "C+", "C", "C-", "D", "S", "DT"])
def test_earned_grades(grade):
    assert earned_units_for_grade(grade, Decimal(3), "completed") == 3
    assert earned_units_for_grade(grade, Decimal(3), "in_progress") == 3
    assert earned_units_for_grade(grade, Decimal(3), "planned") == 0


@pytest.mark.parametrize("grade", ["E", "F", "U", "W", "I", "YR", "NR", "PR", None, ""])
def test_no_earned_units(grade):
    assert earned_units_for_grade(grade, Decimal(3), "completed") == 0


def test_exchange_is_credit_only():
    profile = StudentProfile(id=1, admission_year="2024/25", programme_name="Test")
    term = Term(id=1, study_year=1, term_type="semester_1", sort_order=0, profile=profile)
    Term(
        id=2,
        study_year=1,
        term_type="semester_2",
        sort_order=1,
        profile=profile,
        is_exchange=True,
        exchange_courses=[
            ExchangeCourse(
                id=1,
                host_course_title="Host",
                host_grade="A+",
                transferred_units=Decimal(3),
                transfer_status="approved",
                requirement_group="Free Elective",
            ),
            ExchangeCourse(
                id=2,
                host_course_title="Pending",
                transferred_units=Decimal(4),
                transfer_status="pending_approval",
                requirement_group="Free Elective",
            ),
        ],
    )
    term.courses.append(
        PlanCourse(
            id=1,
            course_code_snapshot="TEST1001",
            course_title_snapshot="Test",
            units=Decimal(3),
            status="completed",
            grade="B",
            requirement_group="Major Core",
        )
    )
    records, _ = build_credit_records(profile)
    assert sum(r.units for r in records if r.state == "earned") == 6
    assert sum(r.units for r in records if r.state != "not_counted") == 10
    assert cumulative_gpa(attempts_for_profile(profile)) == 3


def test_normal_repeat_counts_degree_units_once():
    profile = StudentProfile(id=1, admission_year="2024/25", programme_name="Test")
    for index, (grade, status) in enumerate(
        [("F", "completed"), ("B", "completed"), (None, "planned")]
    ):
        Term(
            id=index + 1,
            study_year=1,
            term_type="semester_1",
            sort_order=index,
            profile=profile,
            courses=[
                PlanCourse(
                    id=index + 1,
                    course_code_snapshot="TEST1001",
                    course_title_snapshot="Repeated",
                    units=Decimal(3),
                    grade=grade,
                    status=status,
                    requirement_group="Major Core",
                )
            ],
        )
    records, warnings = build_credit_records(profile)
    assert sum(r.units for r in records if r.state == "earned") == 3
    assert sum(r.units for r in records if r.state != "not_counted") == 3
    assert any("repeat" in w.lower() for w in warnings)


def test_exchange_duplicate_equivalent_is_flagged():
    profile = StudentProfile(id=1, admission_year="2024/25", programme_name="Test")
    Term(
        id=1,
        study_year=1,
        term_type="semester_1",
        sort_order=0,
        profile=profile,
        courses=[
            PlanCourse(
                id=1,
                course_code_snapshot="TEST1001",
                course_title_snapshot="Local",
                units=Decimal(3),
                grade="B",
                status="completed",
                requirement_group="Major Core",
            )
        ],
        exchange_courses=[
            ExchangeCourse(
                id=2,
                host_course_title="Host",
                hkbu_equivalent_code="TEST1001",
                transferred_units=Decimal(3),
                transfer_status="approved",
                requirement_group="Major Core",
            )
        ],
    )
    records, warnings = build_credit_records(profile)
    assert any("TEST1001" in w and "duplicate" in w.lower() for w in warnings)
    assert len(records) == 2
