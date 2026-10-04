"""Account lifecycle writes. Callers commit once, or roll back the whole operation."""

from sqlalchemy import delete, select, update

from app.models import (
    AcademicYear,
    AccountToken,
    AdminAuditLog,
    ExchangeCourse,
    ExchangeCourseAllocation,
    LevelRequirement,
    PlanCourse,
    PlanCourseAllocation,
    RequirementGroup,
    StudentProfile,
    Term,
    User,
)


def audit_action(session, actor, target, action, details=None):
    row = AdminAuditLog(
        admin_user_id=actor.id if actor else None,
        admin_username_snapshot=actor.username if actor else "operator CLI",
        target_user_id=target.id,
        target_username_snapshot=target.username,
        action=action,
        details=details,
    )
    session.add(row)
    session.flush()
    return row


def delete_account(session, user):
    """Erase only the owned graph, with FKs enabled and no intermediate commits."""
    claimed = session.execute(
        update(User)
        .where(User.id == user.id, User.auth_version == user.auth_version)
        .values(auth_version=User.auth_version + 1)
        .execution_options(synchronize_session=False)
    )
    if claimed.rowcount != 1:
        raise ValueError("Account security changed. Reload and try again.")
    profiles = list(
        session.scalars(select(StudentProfile.id).where(StudentProfile.user_id == user.id))
    )
    if profiles:
        # External SQL can bypass ownership validation. Refuse cross-profile cascades.
        groups = select(RequirementGroup.id).where(RequirementGroup.profile_id.in_(profiles))
        for allocation, course, course_key in [
            (PlanCourseAllocation, PlanCourse, PlanCourseAllocation.plan_course_id),
            (ExchangeCourseAllocation, ExchangeCourse, ExchangeCourseAllocation.exchange_course_id),
        ]:
            foreign_allocation = session.scalar(
                select(allocation.id)
                .join(course, course.id == course_key)
                .join(Term, Term.id == course.term_id)
                .where(
                    allocation.requirement_group_id.in_(groups), Term.profile_id.not_in(profiles)
                )
                .limit(1)
            )
            if foreign_allocation is not None:
                raise ValueError(
                    "Cross-profile allocations require repair before account deletion."
                )
        # Term deletion cascades to normal/exchange attempts and their allocations.
        session.execute(
            delete(Term)
            .where(Term.profile_id.in_(profiles))
            .execution_options(synchronize_session=False)
        )
        session.execute(
            delete(AcademicYear)
            .where(AcademicYear.profile_id.in_(profiles))
            .execution_options(synchronize_session=False)
        )
        parents = dict(
            session.execute(
                select(RequirementGroup.id, RequirementGroup.parent_id).where(
                    RequirementGroup.profile_id.in_(profiles)
                )
            ).all()
        )
        while parents:
            leaves = set(parents) - set(parents.values())
            if not leaves:
                raise ValueError(
                    "The target hierarchy needs repair before this account can be deleted."
                )
            session.execute(
                delete(RequirementGroup)
                .where(RequirementGroup.id.in_(leaves))
                .execution_options(synchronize_session=False)
            )
            for identifier in leaves:
                del parents[identifier]
        session.execute(
            delete(LevelRequirement)
            .where(LevelRequirement.profile_id.in_(profiles))
            .execution_options(synchronize_session=False)
        )
        session.execute(
            delete(StudentProfile)
            .where(StudentProfile.id.in_(profiles))
            .execution_options(synchronize_session=False)
        )
    session.execute(
        delete(AccountToken)
        .where(AccountToken.user_id == user.id)
        .execution_options(synchronize_session=False)
    )
    # Audit FKs become NULL; username snapshots survive. Shared catalogue is untouched.
    session.execute(
        delete(User).where(User.id == user.id).execution_options(synchronize_session=False)
    )
