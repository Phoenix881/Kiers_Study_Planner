from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.config import GROUPS
from app.schemas.inputs import Units
from app.sources.hkbu_urls import normalize_course_code, valid_course_code


class CurriculumRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    type: Literal["TOTAL_UNITS", "GROUP_UNITS", "REQUIRED_COURSE", "MIN_LEVEL_UNITS"]
    label: str
    required_units: Units | None = None
    group: str | None = None
    course_code: str | None = None
    minimum_level: int | None = Field(default=None, ge=1, le=4)

    @model_validator(mode="after")
    def rule_fields(self):
        if self.type != "REQUIRED_COURSE" and self.required_units is None:
            raise ValueError("Unit rules need required_units.")
        if self.type == "GROUP_UNITS" and self.group not in GROUPS:
            raise ValueError("Group rules need a recognised group.")
        if self.type == "MIN_LEVEL_UNITS" and self.minimum_level is None:
            raise ValueError("Level rules need minimum_level.")
        if self.type == "REQUIRED_COURSE":
            self.course_code = normalize_course_code(self.course_code or "")
            if not valid_course_code(self.course_code):
                raise ValueError("Required-course rules need a valid course code.")
        return self


class CurriculumDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    name: str
    admission_year: str | None = None
    version: int = Field(default=1, ge=1)
    is_demo: bool = True
    required_total_units: Units = Decimal(128)
    source_urls: list[str] = Field(default_factory=list)
    notes: str = ""
    rules: list[CurriculumRule]

    @model_validator(mode="after")
    def unique_ids(self):
        if len({rule.id for rule in self.rules}) != len(self.rules):
            raise ValueError("Curriculum rule IDs must be unique.")
        return self


@dataclass(frozen=True)
class RequirementResult:
    id: str
    label: str
    status: str
    completed_value: Decimal
    in_progress_value: Decimal
    projected_value: Decimal
    required_value: Decimal
    message: str
    measure: str = "units"
    depth: int = 0
    ancestors: tuple[int, ...] = ()
    is_container: bool = False


@dataclass
class AuditResult:
    earned_units: Decimal
    projected_units: Decimal
    required_units: Decimal
    requirements: list[RequirementResult]
    warnings: list[str] = field(default_factory=list)
    in_progress_units: Decimal = Decimal(0)
    planned_units: Decimal = Decimal(0)

    @property
    def segments(self):
        remaining = max(Decimal(0), self.required_units)
        result = []
        for key, label, units in [
            ("earned", "Earned", self.earned_units),
            ("active", "In progress", self.in_progress_units),
            ("planned", "Planned", self.planned_units),
            ("remaining", "Remaining", self.unplanned_units),
        ]:
            visible = min(remaining, max(Decimal(0), units))
            width = visible / self.required_units * 100 if self.required_units > 0 else Decimal(0)
            result.append({"key": key, "label": label, "units": units, "width": width})
            remaining -= visible
        return result

    @property
    def completed_count(self):
        return sum(row.status == "completed" for row in self.requirements)

    @property
    def remaining_units(self):
        return max(Decimal(0), self.required_units - self.earned_units)

    @property
    def unplanned_units(self):
        return max(Decimal(0), self.required_units - self.projected_units)

    @property
    def earned_percent(self):
        return min(100, self.earned_units / self.required_units * 100) if self.required_units else 0

    @property
    def projected_percent(self):
        return (
            min(100, self.projected_units / self.required_units * 100) if self.required_units else 0
        )
