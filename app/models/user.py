from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.profile import utc_now

if TYPE_CHECKING:
    from app.models.account_token import AccountToken
    from app.models.profile import StudentProfile


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("theme_preference IN ('system', 'light', 'dark')", name="ck_user_theme"),
        CheckConstraint("auth_version >= 0", name="ck_user_auth_version"),
        CheckConstraint("is_admin IN (0, 1)", name="ck_user_admin"),
        CheckConstraint("is_disabled IN (0, 1)", name="ck_user_disabled"),
        CheckConstraint(
            "disabled_reason IS NULL OR length(disabled_reason) <= 500",
            name="ck_user_disabled_reason",
        ),
        {"sqlite_autoincrement": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    auth_version: Mapped[int] = mapped_column(default=0, server_default="0")
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_reason: Mapped[str | None] = mapped_column(String(500))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    theme_preference: Mapped[str] = mapped_column(
        String(10), default="system", server_default="system"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    profile: Mapped["StudentProfile | None"] = relationship(
        back_populates="user", passive_deletes="all"
    )
    account_tokens: Mapped[list["AccountToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan", passive_deletes=True
    )
