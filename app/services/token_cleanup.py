from datetime import timedelta

from sqlalchemy import delete, func, or_, select

from app.models import AccountToken
from app.models.profile import utc_now


def cleanup_tokens(session, days=30, apply=False):
    if days < 0:
        raise ValueError("Retention days cannot be negative.")
    cutoff = utc_now() - timedelta(days=days)
    eligible = or_(AccountToken.expires_at < cutoff, AccountToken.consumed_at < cutoff)
    count = session.scalar(select(func.count(AccountToken.id)).where(eligible))
    removed = (
        session.execute(
            delete(AccountToken).where(eligible).execution_options(synchronize_session=False)
        ).rowcount
        if apply
        else 0
    )
    return {"eligible": count, "removed": removed}
