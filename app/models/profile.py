from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship, synonym

from app.db import Base

if TYPE_CHECKING:
    from app.models.plan import AcademicYear, Term
    from app.models.requirements import LevelRequirement, RequirementGroup
    from app.models.user import User


def utc_now():
    return datetime.now(timezone.utc)


class StudentProfile(Base):
    __tablename__ = "student_profiles"
    __table_args__ = (CheckConstraint("required_total_units > 0"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), unique=True
    )
    admission_year: Mapped[str] = mapped_column(String(9))
    entry_academic_year = synonym("admission_year")
    programme_name: Mapped[str] = mapped_column(String(200))
    minor_name: Mapped[str | None] = mapped_column(String(200))
    required_total_units: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=128)
    curriculum_key: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    terms: Mapped[list["Term"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="Term.sort_order"
    )
    user: Mapped["User | None"] = relationship(back_populates="profile")
    academic_years: Mapped[list["AcademicYear"]] = relationship(
        back_populates="profile", cascade="all, delete-orphan", order_by="AcademicYear.sort_order"
    )
    requirement_groups: Mapped[list["RequirementGroup"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="RequirementGroup.sort_order",
    )
    level_requirements: Mapped[list["LevelRequirement"]] = relationship(
        back_populates="profile",
        cascade="all, delete-orphan",
        order_by="LevelRequirement.sort_order",
    )


AcademicProfile = StudentProfile
