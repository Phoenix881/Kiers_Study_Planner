from dataclasses import dataclass
from decimal import Decimal

from app.schemas.audit import AuditResult
from app.services.audit import evaluate_progress
from app.services.credit import build_credit_records, unique_records
from app.services.gpa import ZERO, CourseAttemptDTO, cumulative_gpa, gpa_totals


@dataclass
class TermSummary:
    term: object
    catalogue_units: Decimal
    earned_units: Decimal
    projected_units: Decimal
    gpa_units: Decimal
    semester_gpa: Decimal | None
    cumulative_gpa: Decimal | None
    approved_transfer: Decimal
    projected_transfer: Decimal


@dataclass
class Overview:
    terms: list[TermSummary]
    audit: AuditResult
    cgpa: Decimal | None
    groups: list[dict]
    current_term: TermSummary | None
    pending_transfers: int


def attempts_for_profile(profile) -> list[CourseAttemptDTO]:
    return [
        CourseAttemptDTO(
            entry.id or 0,
            entry.course_code_snapshot,
            Decimal(str(entry.units)),
            entry.grade,
            entry.status,
            term.sort_order,
        )
        for term in profile.terms
        for entry in term.courses
    ]


def build_term_summaries(profile) -> list[TermSummary]:
    attempts = attempts_for_profile(profile)
    summaries = []
    for term in sorted(profile.terms, key=lambda t: t.sort_order):
        term_attempts = [a for a in attempts if a.sort_order == term.sort_order]
        totals = gpa_totals(term_attempts)
        # Degree units are allocated to the selected repeat attempt as of this term.
        records, _ = build_credit_records(profile, through_sort_order=term.sort_order)
        term_records = [
            r
            for r in unique_records(records, {"earned", "planned", "in_progress"})
            if r.term_id == term.id
        ]
        summaries.append(
            TermSummary(
                term,
                sum((Decimal(str(e.units)) for e in term.courses), ZERO),
                sum((r.units for r in term_records if r.state == "earned"), ZERO),
                sum((r.units for r in term_records if r.state != "not_counted"), ZERO),
                totals.units,
                totals.gpa,
                cumulative_gpa(attempts, term.sort_order),
                sum(
                    (
                        Decimal(str(e.transferred_units))
                        for e in term.exchange_courses
                        if e.transfer_status == "approved"
                    ),
                    ZERO,
                ),
                sum((Decimal(str(e.transferred_units)) for e in term.exchange_courses), ZERO),
            )
        )
    return summaries


def build_overview(profile) -> Overview:
    records, credit_warnings = build_credit_records(profile)
    audit = evaluate_progress(profile, records)
    audit.warnings = credit_warnings
    unknown = sum(1 for r in records if r.state != "not_counted" and r.level is None)
    if unknown and profile.level_requirements:
        audit.warnings.append(
            f"{unknown} entries have no verified catalogue level and are excluded from level-based requirements."
        )
        audit.warnings.append(
            "Unknown levels: "
            + "; ".join(
                f"{r.code or 'Unmapped transfer'}: {r.title}"
                for r in records
                if r.state != "not_counted" and r.level is None
            )
        )
    if any(e.grade == "E" for t in profile.terms for e in t.courses):
        audit.warnings.append(
            "Grade E is treated as temporary: zero GPA points, no earned or projected degree units until the final grade is recorded."
        )
    groups = [
        {
            "name": r.label,
            "earned": r.completed_value,
            "projected": r.projected_value,
            "required": r.required_value,
        }
        for r in audit.requirements
        if r.id.startswith("group-")
    ]
    if not profile.requirement_groups:
        audit.warnings.append("No targets configured. Your total-unit target still applies.")
    unallocated = sum(not r.allocations for r in records if r.state != "not_counted")
    if unallocated:
        audit.warnings.append(
            f"Unallocated: {unallocated} courses have no target allocation; overall units still count."
        )
    if any(
        e.course_version and e.course_version.data_status != "official_imported"
        for t in profile.terms
        for e in t.courses
    ):
        audit.warnings.append(
            "Some catalogue versions are demo/unverified. Check the linked academic records."
        )
    terms = build_term_summaries(profile)
    current = next(
        (s for s in terms if any(c.status == "in_progress" for c in s.term.courses)), None
    )
    if current is None:
        current = next(
            (
                s
                for s in terms
                if any(c.status == "planned" for c in s.term.courses)
                or any(c.transfer_status != "approved" for c in s.term.exchange_courses)
            ),
            next(
                (s for s in reversed(terms) if s.term.courses or s.term.exchange_courses),
                terms[0] if terms else None,
            ),
        )
    return Overview(
        terms,
        audit,
        cumulative_gpa(attempts_for_profile(profile)),
        groups,
        current,
        sum(
            e.transfer_status == "pending_approval"
            for t in profile.terms
            for e in t.exchange_courses
        ),
    )
