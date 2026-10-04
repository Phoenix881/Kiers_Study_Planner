from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.profile import utc_now

if TYPE_CHECKING:
    from app.models.plan import Term
    from app.models.requirements import PlanCourseAllocation


class Course(Base):
    __tablename__ = "courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    versions: Mapped[list["CourseVersion"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="CourseVersion.academic_year.desc()",
    )

    @property
    def latest_version(self):
        return max(self.versions, key=lambda v: v.academic_year or "", default=None)

    def __init__(self, **kwargs):
        # Local seed compatibility; metadata is persisted only in version rows.
        fields = set(CourseVersion.__table__.columns.keys()) - {"id", "course_id", "academic_year"}
        metadata = {key: kwargs.pop(key) for key in list(kwargs) if key in fields}
        year = kwargs.pop("source_academic_year", None)
        super().__init__(**kwargs)
        if metadata:
            self.versions.append(CourseVersion(academic_year=year, **metadata))


class CourseVersion(Base):
    __tablename__ = "course_versions"
    __table_args__ = (UniqueConstraint("course_id", "academic_year"), CheckConstraint("units >= 0"))

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    academic_year: Mapped[str | None] = mapped_column(String(9))
    title: Mapped[str] = mapped_column(String(240))
    units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    level: Mapped[int | None]
    department: Mapped[str | None] = mapped_column(String(160))
    prerequisite_text: Mapped[str | None] = mapped_column(Text)
    corequisite_text: Mapped[str | None] = mapped_column(Text)
    antirequisite_text: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(String(500))
    outline_url: Mapped[str | None] = mapped_column(String(500))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    data_status: Mapped[str] = mapped_column(String(30), default="demo_unverified")
    course: Mapped[Course] = relationship(back_populates="versions")

    @property
    def code(self):
        return self.course.code

    @property
    def source_academic_year(self):
        return self.academic_year


def _latest_field(field):
    return property(lambda self: getattr(self.latest_version, field, None))


for _field in (
    "title",
    "units",
    "level",
    "department",
    "prerequisite_text",
    "corequisite_text",
    "antirequisite_text",
    "description",
    "source_url",
    "outline_url",
    "last_checked_at",
    "data_status",
    "source_academic_year",
):
    setattr(Course, _field, _latest_field(_field))


class PlanCourse(Base):
    __tablename__ = "plan_courses"
    __table_args__ = (
        CheckConstraint("units >= 0"),
        CheckConstraint("status IN ('planned', 'in_progress', 'completed', 'withdrawn')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="SET NULL"))
    course_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("course_versions.id", ondelete="SET NULL")
    )
    level_snapshot: Mapped[int | None]
    exceptional_repeat: Mapped[bool] = mapped_column(Boolean, default=False)
    course_code_snapshot: Mapped[str] = mapped_column(String(20))
    course_title_snapshot: Mapped[str] = mapped_column(String(240))
    units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    requirement_group: Mapped[str] = mapped_column(String(100), default="")
    status: Mapped[str] = mapped_column(String(20), default="planned")
    grade: Mapped[str | None] = mapped_column(String(3))
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    term: Mapped["Term"] = relationship(back_populates="courses")
    course: Mapped[Course | None] = relationship()
    course_version: Mapped[CourseVersion | None] = relationship()
    allocations: Mapped[list["PlanCourseAllocation"]] = relationship(
        back_populates="course", cascade="all, delete-orphan", order_by="PlanCourseAllocation.id"
    )
