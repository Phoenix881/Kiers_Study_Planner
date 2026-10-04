from app.config import APP_DIR
from app.schemas.audit import CurriculumDefinition, CurriculumRule


def available_curricula() -> list[CurriculumDefinition]:
    return [
        CurriculumDefinition.model_validate_json(path.read_text())
        for path in sorted((APP_DIR / "curricula").glob("*.json"))
    ]


def load_curriculum(profile) -> tuple[CurriculumDefinition, list[str]]:
    warnings = []
    selected = next((c for c in available_curricula() if c.key == profile.curriculum_key), None)
    if selected and selected.admission_year != profile.admission_year:
        warnings.append(
            "The selected curriculum does not match your admission cohort. Only your manual total-unit target is being evaluated."
        )
        selected = None
    elif profile.curriculum_key and selected is None:
        warnings.append(
            "The selected curriculum definition is unavailable. Only your manual total-unit target is being evaluated."
        )
    if selected is None:
        selected = CurriculumDefinition(
            key="manual", name="Manual targets", is_demo=False, rules=[]
        )
    else:
        selected = selected.model_copy(deep=True)
    selected.required_total_units = profile.required_total_units
    selected.rules = [rule for rule in selected.rules if rule.type != "TOTAL_UNITS"]
    selected.rules.insert(
        0,
        CurriculumRule(
            id="total_units",
            type="TOTAL_UNITS",
            label="Total degree units",
            required_units=profile.required_total_units,
        ),
    )
    return selected, warnings
