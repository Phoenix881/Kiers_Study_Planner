from decimal import Decimal

from app.schemas.audit import AuditResult, CurriculumDefinition, RequirementResult
from app.services.credit import CreditRecord, unique_records
from app.services.gpa import ZERO
from app.services.requirements import tree_rows
from app.sources.hkbu_urls import normalize_course_code


def _matches(rule, record: CreditRecord) -> bool:
    match rule.type:
        case "TOTAL_UNITS":
            return True
        case "GROUP_UNITS":
            return record.requirement_group == rule.group
        case "REQUIRED_COURSE":
            return bool(record.code and normalize_course_code(record.code) == rule.course_code)
        case "MIN_LEVEL_UNITS":
            return record.level is not None and record.level >= rule.minimum_level
        case _:
            raise ValueError(f"Unsupported curriculum rule: {rule.type}")


def _status(earned, active, projected, required):
    if earned >= required:
        return "completed"
    if earned + active >= required:
        return "in_progress"
    if projected >= required:
        return "planned"
    if earned or active:
        return "in_progress"
    if projected:
        return "planned"
    return "missing"


def evaluate_audit(curriculum: CurriculumDefinition, records: list[CreditRecord]) -> AuditResult:
    counted = [r for r in records if r.state != "not_counted"]
    requirements = []
    for rule in curriculum.rules:
        matched = [r for r in counted if _matches(rule, r)]
        is_course = rule.type == "REQUIRED_COURSE"

        def value(states):
            matching = [r for r in matched if r.state in states]
            return Decimal(bool(matching)) if is_course else sum((r.units for r in matching), ZERO)

        earned = value({"earned"})
        active = value({"in_progress"})
        projected = value({"earned", "in_progress", "planned"})
        required = Decimal(1) if is_course else rule.required_units
        status = _status(earned, active, projected, required)
        if status == "completed":
            message = "Current requirement satisfied."
        elif projected >= required:
            message = "Covered by the plan; completion or transfer approval is still required."
        else:
            shortfall = required - projected
            message = (
                f"{shortfall:g} {'course' if is_course else 'units'} still missing from the plan."
            )
        if rule.type == "MIN_LEVEL_UNITS":
            message += " Only known catalogue levels are included."
        requirements.append(
            RequirementResult(
                rule.id,
                rule.label,
                status,
                earned,
                active,
                projected,
                required,
                message,
                "course" if is_course else "units",
            )
        )
    return AuditResult(
        sum((r.units for r in counted if r.state == "earned"), ZERO),
        sum((r.units for r in counted), ZERO),
        curriculum.required_total_units,
        requirements,
    )


def evaluate_progress(profile, records):
    earned = unique_records(records, {"earned"})
    projected = unique_records(records, {"earned", "planned", "in_progress"})
    requirements = []

    def result(identifier, label, required, current, future, message="Your configured target."):
        requirements.append(
            RequirementResult(
                str(identifier),
                label,
                _status(current, ZERO, future, required),
                current,
                ZERO,
                future,
                required,
                message,
            )
        )

    earned_total = sum((r.units for r in earned), ZERO)
    projected_total = sum((r.units for r in projected), ZERO)
    result(
        "total", "Unique degree units", profile.required_total_units, earned_total, projected_total
    )
    tree = tree_rows(profile.requirement_groups)
    group_results = {}
    for node in reversed(tree):
        group = node.group

        def allocated(states):
            # Deduplicate each category independently; cross-category overlap is intentional.
            totals = {}
            for index, record in enumerate(records):
                if record.state not in states:
                    continue
                value = next(
                    (units for identifier, units in record.allocations if identifier == group.id),
                    ZERO,
                )
                key = record.code or f"transfer-{index}"
                totals[key] = max(totals.get(key, ZERO), value)
            return sum(totals.values(), ZERO)

        container = group.aggregation_mode == "sum_children"
        children = [
            group_results[g.id] for g in profile.requirement_groups if g.parent_id == group.id
        ]
        current = (
            sum((c.completed_value for c in children), ZERO) if container else allocated({"earned"})
        )
        future = (
            sum((c.projected_value for c in children), ZERO)
            if container
            else allocated({"earned", "planned", "in_progress"})
        )
        required = (
            sum((c.required_value for c in children), ZERO) if container else group.required_units
        )
        status = _status(current, ZERO, future, required)
        if container:
            # Surplus in one branch must never hide an unfinished sibling.
            status = (
                "completed"
                if children and all(c.status == "completed" for c in children)
                else ("in_progress" if current else "planned" if future else "missing")
            )
        group_results[group.id] = RequirementResult(
            f"group-{group.id}",
            group.name,
            status,
            current,
            ZERO,
            future,
            required,
            "Sum of child targets; each child must be completed."
            if container
            else "Your configured target.",
            depth=node.depth,
            ancestors=node.ancestors,
            is_container=container,
        )
    requirements.extend(group_results[node.group.id] for node in tree)
    for level in profile.level_requirements:

        def level_units(rows):
            return sum(
                (r.units for r in rows if r.level is not None and r.level >= level.minimum_level),
                ZERO,
            )

        result(
            f"level-{level.id}",
            level.label,
            level.required_units,
            level_units(earned),
            level_units(projected),
            f"Known levels {level.minimum_level} and above.",
        )
    return AuditResult(
        earned_total,
        projected_total,
        profile.required_total_units,
        requirements,
        in_progress_units=sum((r.units for r in projected if r.state == "in_progress"), ZERO),
        planned_units=sum((r.units for r in projected if r.state == "planned"), ZERO),
    )
