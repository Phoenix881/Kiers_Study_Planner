import re
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.sources.hkbu_urls import normalize_course_code, valid_course_code

Units = Annotated[
    Decimal, Field(ge=0, le=9999, max_digits=6, decimal_places=2, allow_inf_nan=False)
]
CourseStatus = Literal["planned", "in_progress", "completed", "withdrawn"]
TransferStatus = Literal["planned", "pending_approval", "approved"]
VALID_GRADES = (
    "A",
    "A-",
    "B+",
    "B",
    "B-",
    "C+",
    "C",
    "C-",
    "D",
    "E",
    "F",
    "DT",
    "I",
    "S",
    "U",
    "W",
    "YR",
    "NR",
    "PR",
)


class FormInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    @field_validator("*", mode="before")
    @classmethod
    def strip_strings(cls, value):
        return value.strip() if isinstance(value, str) else value


class ProfileInput(FormInput):
    admission_year: str
    programme_name: str = Field(min_length=1, max_length=200)
    minor_name: str | None = Field(default=None, max_length=200)
    required_total_units: Units = Field(default=Decimal(128), gt=0)
    curriculum_key: str | None = Field(default=None, max_length=100)

    @field_validator("admission_year")
    @classmethod
    def academic_year(cls, value):
        if (
            not re.fullmatch(r"20\d{2}/(?:\d{2}|20\d{2})", value)
            or int(value[-2:]) != (int(value[:4]) + 1) % 100
        ):
            raise ValueError("Enter a consecutive academic year, for example 2024/25.")
        return f"{value[:4]}/{int(value[:4]) + 1}"

    @field_validator("minor_name", "curriculum_key")
    @classmethod
    def optional_text(cls, value):
        return value or None


class CourseInput(FormInput):
    course_code_snapshot: str = Field(max_length=30)
    course_title_snapshot: str = Field(min_length=1, max_length=240)
    units: Units
    requirement_group: str = Field(default="", max_length=100)
    exceptional_repeat: bool = False
    status: CourseStatus = "planned"
    grade: str | None = None
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("course_code_snapshot")
    @classmethod
    def code(cls, value):
        value = normalize_course_code(value)
        if not valid_course_code(value):
            raise ValueError("Enter a course code such as MATH3206.")
        return value

    @field_validator("grade")
    @classmethod
    def valid_grade(cls, value):
        value = value.upper() if value else None
        if value is not None and value not in VALID_GRADES:
            raise ValueError("Choose a recognised HKBU grade, or leave the grade blank.")
        return value

    @field_validator("requirement_group")
    @classmethod
    def valid_group(cls, value):
        return value


class ExchangeInput(FormInput):
    host_course_code: str | None = Field(default=None, max_length=80)
    host_course_title: str = Field(min_length=1, max_length=240)
    host_units: Units | None = None
    host_grade: str | None = Field(default=None, max_length=40)
    hkbu_equivalent_code: str | None = Field(default=None, max_length=30)
    hkbu_equivalent_title: str | None = Field(default=None, max_length=240)
    transferred_units: Units
    requirement_group: str = Field(default="", max_length=100)
    transfer_status: TransferStatus = "planned"
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("host_units", mode="before")
    @classmethod
    def optional_units(cls, value):
        return None if value == "" else value

    @field_validator("hkbu_equivalent_code")
    @classmethod
    def equivalent(cls, value):
        return CourseInput.code(value) if value else None

    @field_validator("requirement_group")
    @classmethod
    def group(cls, value):
        return CourseInput.valid_group(value)


class TermInput(FormInput):
    study_year: int = Field(ge=1)
    term_type: str = Field(min_length=1, max_length=80)


class ExchangeSettingsInput(FormInput):
    is_exchange: bool = False
    host_university: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=4000)
