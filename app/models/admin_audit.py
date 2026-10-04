from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.profile import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class AdminAuditLog(Base):
    __tablename__ = "admin_audit_log"
    __table_args__ = (
        CheckConstraint(
            "action IN ('send_verification', 'send_password_reset', 'revoke_sessions', 'disable_user', 'enable_user', 'delete_user', 'grant_admin', 'revoke_admin')",
            name="ck_admin_audit_action",
        ),
        CheckConstraint("details IS NULL OR length(details) <= 500", name="ck_admin_audit_details"),
        Index("ix_admin_audit_created_id", "created_at", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    admin_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    admin_username_snapshot: Mapped[str] = mapped_column(String(80))
    target_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    target_username_snapshot: Mapped[str] = mapped_column(String(80))
    action: Mapped[str] = mapped_column(String(30))
    details: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    admin: Mapped["User | None"] = relationship(foreign_keys=[admin_user_id])
    target: Mapped["User | None"] = relationship(foreign_keys=[target_user_id])
