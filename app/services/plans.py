from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AcademicYear, StudentProfile, Term


def get_profile(session: Session, user_id=None) -> StudentProfile | None:
    """Administrative helper. HTTP routes use owned_profile."""
    query = select(StudentProfile)
    query = (
        query.where(StudentProfile.user_id == user_id)
        if user_id is not None
        else query.where(StudentProfile.user_id.is_(None))
    )
    return session.scalar(query.order_by(StudentProfile.id))


def ensure_terms(session: Session, profile: StudentProfile):
    if profile.academic_years or profile.terms:
        return
    start = int(profile.admission_year[:4])
    for index in range(4):
        year = AcademicYear(
            profile=profile,
            academic_year=f"{start + index}/{start + index + 1}",
            label=f"Year {index + 1}",
            sort_order=index,
        )
        session.add(year)
        for semester in range(2):
            session.add(
                Term(
                    profile=profile,
                    academic_year=year,
                    study_year=index + 1,
                    name=f"Semester {semester + 1}",
                    term_type=f"semester_{semester + 1}",
                    sort_order=index * 2 + semester,
                )
            )


def academic_year(profile, year: int) -> str:
    start = int(profile.admission_year[:4]) + year - 1
    return f"{start}/{start + 1}"


def reorder(session, items):
    """Temporary negative positions avoid transient uniqueness collisions."""
    for index, item in enumerate(items):
        item.sort_order = -index - 1
    session.flush()
    for index, item in enumerate(items):
        item.sort_order = index
    session.flush()


def order_periods(session, profile):
    years = sorted(profile.academic_years, key=lambda y: (y.sort_order, y.id or 0))
    periods = [
        t
        for y in years
        for t in sorted(y.periods, key=lambda t: (t.sort_order, t.id or 0))
        if t not in session.deleted
    ]
    reorder(session, periods)
