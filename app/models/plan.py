from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.course import PlanCourse
    from app.models.exchange import ExchangeCourse
    from app.models.profile import StudentProfile


class AcademicYear(Base):
    __tablename__ = "academic_years"
    __table_args__ = (UniqueConstraint("profile_id", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"))
    academic_year: Mapped[str] = mapped_column(String(9))
    label: Mapped[str] = mapped_column(String(160))
    sort_order: Mapped[int]
    notes: Mapped[str | None] = mapped_column(Text)
    profile: Mapped["StudentProfile"] = relationship(back_populates="academic_years")
    periods: Mapped[list["Term"]] = relationship(
        back_populates="academic_year", order_by="Term.sort_order", passive_deletes="all"
    )


class Term(Base):
    __tablename__ = "terms"
    __table_args__ = (UniqueConstraint("profile_id", "sort_order"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(ForeignKey("student_profiles.id", ondelete="CASCADE"))
    academic_year_id: Mapped[int | None] = mapped_column(
        ForeignKey("academic_years.id", ondelete="RESTRICT"), index=True
    )
    name: Mapped[str] = mapped_column(String(160), default="Semester 1")
    # Retained for migration provenance; chronology uses sort_order and academic_year_id.
    study_year: Mapped[int | None]
    term_type: Mapped[str] = mapped_column(String(80), default="custom")
    sort_order: Mapped[int]
    is_exchange: Mapped[bool] = mapped_column(Boolean, default=False)
    host_university: Mapped[str | None] = mapped_column(String(200))
    notes: Mapped[str | None] = mapped_column(Text)
    profile: Mapped["StudentProfile"] = relationship(back_populates="terms")
    academic_year: Mapped[AcademicYear | None] = relationship(back_populates="periods")
    courses: Mapped[list["PlanCourse"]] = relationship(
        back_populates="term", cascade="all, delete-orphan", order_by="PlanCourse.id"
    )
    exchange_courses: Mapped[list["ExchangeCourse"]] = relationship(
        back_populates="term", cascade="all, delete-orphan", order_by="ExchangeCourse.id"
    )


StudyPeriod = Term
