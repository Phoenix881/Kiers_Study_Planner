from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.profile import utc_now

if TYPE_CHECKING:
    from app.models.course import PlanCourse
    from app.models.exchange import ExchangeCourse
    from app.models.profile import StudentProfile


class RequirementGroup(Base):
    __tablename__ = "requirement_groups"
    __table_args__ = (
        Index(
            "uq_requirement_root_name",
            "profile_id",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NULL"),
        ),
        Index(
            "uq_requirement_child_name",
            "profile_id",
            "parent_id",
            "name",
            unique=True,
            sqlite_where=text("parent_id IS NOT NULL"),
        ),
        CheckConstraint("required_units >= 0"),
        CheckConstraint("parent_id IS NULL OR parent_id != id", name="ck_requirement_not_self"),
        CheckConstraint(
            "aggregation_mode IN ('own_target', 'sum_children')", name="ck_requirement_aggregation"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(100))
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="RESTRICT"), index=True
    )
    aggregation_mode: Mapped[str] = mapped_column(
        String(20), default="own_target", server_default="own_target"
    )
    required_units: Mapped[Decimal] = mapped_column(Numeric(8, 2), default=0)
    sort_order: Mapped[int] = mapped_column(default=0)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    profile: Mapped["StudentProfile"] = relationship(back_populates="requirement_groups")
    parent: Mapped["RequirementGroup | None"] = relationship(
        back_populates="children", remote_side="RequirementGroup.id"
    )
    children: Mapped[list["RequirementGroup"]] = relationship(
        back_populates="parent",
        order_by="RequirementGroup.sort_order, RequirementGroup.id",
        passive_deletes="all",
    )


class LevelRequirement(Base):
    __tablename__ = "level_requirements"
    __table_args__ = (CheckConstraint("minimum_level >= 1"), CheckConstraint("required_units >= 0"))

    id: Mapped[int] = mapped_column(primary_key=True)
    profile_id: Mapped[int] = mapped_column(
        ForeignKey("student_profiles.id", ondelete="CASCADE"), index=True
    )
    label: Mapped[str] = mapped_column(String(160))
    minimum_level: Mapped[int]
    required_units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    sort_order: Mapped[int] = mapped_column(default=0)
    profile: Mapped["StudentProfile"] = relationship(back_populates="level_requirements")


class PlanCourseAllocation(Base):
    __tablename__ = "plan_course_allocations"
    __table_args__ = (
        UniqueConstraint("plan_course_id", "requirement_group_id"),
        CheckConstraint("allocated_units >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    plan_course_id: Mapped[int] = mapped_column(ForeignKey("plan_courses.id", ondelete="CASCADE"))
    requirement_group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE"), index=True
    )
    allocated_units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    course: Mapped["PlanCourse"] = relationship(back_populates="allocations")
    group: Mapped[RequirementGroup] = relationship()


class ExchangeCourseAllocation(Base):
    __tablename__ = "exchange_course_allocations"
    __table_args__ = (
        UniqueConstraint("exchange_course_id", "requirement_group_id"),
        CheckConstraint("allocated_units >= 0"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exchange_course_id: Mapped[int] = mapped_column(
        ForeignKey("exchange_courses.id", ondelete="CASCADE")
    )
    requirement_group_id: Mapped[int] = mapped_column(
        ForeignKey("requirement_groups.id", ondelete="CASCADE"), index=True
    )
    allocated_units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    course: Mapped["ExchangeCourse"] = relationship(back_populates="allocations")
    group: Mapped[RequirementGroup] = relationship()
