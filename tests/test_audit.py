from decimal import Decimal

import pytest

from app.schemas.audit import CurriculumDefinition
from app.services.audit import evaluate_audit
from app.services.credit import CreditRecord


@pytest.fixture
def curriculum():
    return CurriculumDefinition.model_validate(
        {
            "key": "test",
            "name": "Test",
            "required_total_units": 12,
            "rules": [
                {"id": "total", "type": "TOTAL_UNITS", "label": "Total", "required_units": 12},
                {
                    "id": "major",
                    "type": "GROUP_UNITS",
                    "label": "Major",
                    "group": "Major Core",
                    "required_units": 6,
                },
                {
                    "id": "required",
                    "type": "REQUIRED_COURSE",
                    "label": "Required",
                    "course_code": "TEST1001",
                },
                {
                    "id": "level",
                    "type": "MIN_LEVEL_UNITS",
                    "label": "Advanced",
                    "minimum_level": 3,
                    "required_units": 3,
                },
            ],
        }
    )


def record(code, units, state, group="Major Core", level=1):
    return CreditRecord("hkbu_course", code, code, Decimal(units), level, group, state)


@pytest.mark.parametrize(
    "state,status",
    [("planned", "planned"), ("in_progress", "in_progress"), ("earned", "completed")],
)
def test_audit_states(curriculum, state, status):
    rows = [record("TEST1001", 6, state), record("TEST3001", 6, state, "Free Elective", 3)]
    audit = evaluate_audit(curriculum, rows)
    assert all(row.status == status for row in audit.requirements)
    assert audit.projected_units == 12
    assert audit.earned_units == (12 if state == "earned" else 0)


def test_missing_and_partial_progress(curriculum):
    audit = evaluate_audit(curriculum, [record("TEST1001", 3, "earned")])
    assert [r.status for r in audit.requirements] == [
        "in_progress",
        "in_progress",
        "completed",
        "missing",
    ]
    assert audit.remaining_units == 9


def test_earned_and_projected_are_separate(curriculum):
    rows = [
        record("TEST1001", 6, "earned"),
        record("TEST3001", 6, "planned", level=3),
        record("TEST4001", 9, "not_counted", level=4),
    ]
    audit = evaluate_audit(curriculum, rows)
    assert audit.earned_units == 6
    assert audit.projected_units == 12
    assert audit.requirements[0].status == "planned"
    assert audit.requirements[1].status == "completed"


def test_unknown_level_not_guessed(curriculum):
    audit = evaluate_audit(curriculum, [record("TEST4001", 12, "earned", level=None)])
    assert audit.requirements[-1].completed_value == 0


def test_required_course_is_boolean_not_units(curriculum):
    audit = evaluate_audit(
        curriculum, [record("TEST1001", 3, "earned"), record("TEST1001", 3, "earned")]
    )
    assert audit.requirements[2].completed_value == 1
