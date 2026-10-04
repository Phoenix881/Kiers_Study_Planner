from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.course import Course
    from app.models.plan import Term
    from app.models.requirements import ExchangeCourseAllocation


class ExchangeCourse(Base):
    __tablename__ = "exchange_courses"
    __table_args__ = (
        CheckConstraint("host_units IS NULL OR host_units >= 0"),
        CheckConstraint("transferred_units >= 0"),
        CheckConstraint("transfer_status IN ('planned', 'pending_approval', 'approved')"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    term_id: Mapped[int] = mapped_column(ForeignKey("terms.id", ondelete="CASCADE"), index=True)
    host_course_code: Mapped[str | None] = mapped_column(String(80))
    host_course_title: Mapped[str] = mapped_column(String(240))
    host_units: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    host_grade: Mapped[str | None] = mapped_column(String(40))
    hkbu_equivalent_course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="SET NULL")
    )
    hkbu_equivalent_code: Mapped[str | None] = mapped_column(String(20))
    hkbu_equivalent_title: Mapped[str | None] = mapped_column(String(240))
    level_snapshot: Mapped[int | None]
    transferred_units: Mapped[Decimal] = mapped_column(Numeric(8, 2))
    requirement_group: Mapped[str] = mapped_column(String(100), default="Other")
    transfer_status: Mapped[str] = mapped_column(String(20), default="planned")
    notes: Mapped[str | None] = mapped_column(Text)
    term: Mapped["Term"] = relationship(back_populates="exchange_courses")
    equivalent_course: Mapped["Course | None"] = relationship()
    allocations: Mapped[list["ExchangeCourseAllocation"]] = relationship(
        back_populates="course",
        cascade="all, delete-orphan",
        order_by="ExchangeCourseAllocation.id",
    )
