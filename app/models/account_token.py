from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.models.profile import utc_now

if TYPE_CHECKING:
    from app.models.user import User


class AccountToken(Base):
    __tablename__ = "account_tokens"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')", name="ck_account_token_purpose"
        ),
        Index("ix_account_tokens_user_purpose", "user_id", "purpose"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    purpose: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    user: Mapped["User"] = relationship(back_populates="account_tokens")
