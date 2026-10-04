from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import Field, TypeAdapter, ValidationError
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import LevelRequirement, RequirementGroup
from app.schemas.inputs import FormInput, Units
from app.security import owned_profile, owned_record
from app.services.audit import evaluate_progress
from app.services.plans import reorder
from app.services.requirements import (
    allocated_group_ids,
    apply_tree_order,
    tree_rows,
    validate_tree,
)
from app.web import render

router = APIRouter()


class GroupInput(FormInput):
    name: str = Field(min_length=1, max_length=100)
    required_units: Units = 0
    notes: str | None = Field(default=None, max_length=4000)
    parent_id: int | None = None
    aggregation_mode: Literal["own_target", "sum_children"] = "own_target"


class Placement(FormInput):
    id: int = Field(strict=True, gt=0)
    parent_id: int | None = Field(default=None, strict=True, gt=0)


class LevelInput(FormInput):
    label: str = Field(min_length=1, max_length=160)
    minimum_level: int = Field(ge=1, le=99)
    required_units: Units


@router.get("/requirements")
def requirements(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session)
    targets = {row.id: row.required_value for row in evaluate_progress(profile, []).requirements}
    return render(
        request,
        "requirements.html",
        profile=profile,
        tree=tree_rows(profile.requirement_groups),
        targets=targets,
    )


@router.post("/requirements/tree/reorder")
async def reorder_tree(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session)
    try:
        payload = str((await request.form()).get("placements", ""))
        placements = TypeAdapter(list[Placement]).validate_json(payload)
        apply_tree_order(
            session, list(profile.requirement_groups), [p.model_dump() for p in placements]
        )
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(
            422, str(exc) if isinstance(exc, ValueError) else "Conflicting sibling names."
        ) from exc
    return {"saved": True}


@router.post("/requirements/{kind}")
@router.post("/requirements/{kind}/{identifier}/edit")
async def save_requirement(
    kind: str,
    request: Request,
    identifier: int | None = None,
    session: Session = Depends(get_session),
):
    profile = owned_profile(request, session)
    model, schema = select_kind(kind)
    row = owned_record(request, session, model, identifier) if identifier is not None else None
    try:
        form = dict(await request.form())
        if kind == "groups":
            form["parent_id"] = form.get("parent_id") or None
            if row:
                form.setdefault("aggregation_mode", row.aggregation_mode)
                if "parent_id" not in (await request.form()):
                    form["parent_id"] = row.parent_id
        values = schema.model_validate(form)
        rows = list(profile.requirement_groups if kind == "groups" else profile.level_requirements)
        if kind == "groups":
            parent = next((g for g in rows if g.id == values.parent_id), None)
            if values.parent_id is not None and parent is None:
                raise ValueError("Choose a parent from your own profile.")
            if (
                row
                and values.aggregation_mode == "own_target"
                and any(g.parent_id == row.id for g in rows)
            ):
                raise ValueError(
                    "Move the child requirements before changing this container to a leaf."
                )
            occupied = allocated_group_ids(session, rows)
            if (row and row.id in occupied and values.aggregation_mode == "sum_children") or (
                parent and parent.id in occupied
            ):
                raise ValueError(
                    "Move direct course allocations to a leaf before making this target a container."
                )
        if row is None:
            row = model(
                profile=profile,
                profile_id=profile.id,
                sort_order=max(
                    (
                        r.sort_order
                        for r in rows
                        if kind != "groups" or r.parent_id == values.parent_id
                    ),
                    default=-1,
                )
                + 1,
            )
            rows.append(row)
            session.add(row)
        elif kind == "groups" and row.parent_id != values.parent_id:
            row.sort_order = (
                max((g.sort_order for g in rows if g.parent_id == values.parent_id), default=-1) + 1
            )
        for key, value in values.model_dump().items():
            setattr(row, key, value)
        if kind == "groups":
            validate_tree(rows)
            if parent:
                parent.aggregation_mode = "sum_children"
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        message = (
            "; ".join(e["msg"] for e in exc.errors())
            if isinstance(exc, ValidationError)
            else str(exc)
        )
        raise HTTPException(
            422,
            "A requirement with that sibling name already exists."
            if isinstance(exc, IntegrityError)
            else message,
        ) from exc
    return RedirectResponse("/requirements", 303)


def select_kind(kind):
    if kind == "groups":
        return RequirementGroup, GroupInput
    if kind == "levels":
        return LevelRequirement, LevelInput
    raise HTTPException(404, "Unknown requirement type.")


@router.post("/requirements/{kind}/{identifier}/delete")
def delete_requirement(
    kind: str, identifier: int, request: Request, session: Session = Depends(get_session)
):
    model, _ = select_kind(kind)
    row = owned_record(request, session, model, identifier)
    if kind == "groups" and any(g.parent_id == row.id for g in row.profile.requirement_groups):
        raise HTTPException(
            409, "Move or delete this target's children first. Courses and targets have been kept."
        )
    session.delete(row)
    session.commit()
    return RedirectResponse("/requirements", 303)


@router.post("/requirements/groups/{identifier}/parent")
async def move_to_group(identifier: int, request: Request, session: Session = Depends(get_session)):
    row = owned_record(request, session, RequirementGroup, identifier)
    groups = list(row.profile.requirement_groups)
    try:
        raw = (await request.form()).get("parent_id")
        parent = int(raw) if raw else None
        if parent is not None and not any(
            g.id == parent and g.aggregation_mode == "sum_children" for g in groups
        ):
            raise ValueError("Choose a group of targets from your own profile.")
        ordered = [n.group for n in tree_rows(groups) if n.group.id != row.id] + [row]
        apply_tree_order(
            session,
            groups,
            [{"id": g.id, "parent_id": parent if g.id == row.id else g.parent_id} for g in ordered],
        )
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(
            422, str(exc) if isinstance(exc, ValueError) else "Conflicting target names."
        ) from exc
    return RedirectResponse("/requirements", 303)


@router.post("/requirements/{kind}/{identifier}/move")
async def move_requirement(
    kind: str, identifier: int, request: Request, session: Session = Depends(get_session)
):
    model, _ = select_kind(kind)
    row = owned_record(request, session, model, identifier)
    direction = (await request.form()).get("direction")
    if kind == "groups":
        groups = list(row.profile.requirement_groups)
        siblings = sorted(
            (g for g in groups if g.parent_id == row.parent_id), key=lambda g: (g.sort_order, g.id)
        )
        index = siblings.index(row)
        parent = row.parent_id
        if direction in {"up", "down"}:
            target = index + (-1 if direction == "up" else 1)
            if 0 <= target < len(siblings):
                siblings[index], siblings[target] = siblings[target], siblings[index]
        elif direction == "indent":
            if index == 0:
                raise HTTPException(422, "There is no preceding sibling to contain this target.")
            parent = siblings[index - 1].id
        elif direction == "outdent":
            if parent is not None:
                parent = next(g.parent_id for g in groups if g.id == parent)
        else:
            raise HTTPException(422, "Choose up, down, indent or outdent.")
        ordered = [n.group for n in tree_rows(groups)]
        if direction in {"up", "down"}:
            positions = [i for i, g in enumerate(ordered) if g.parent_id == row.parent_id]
            for position, sibling in zip(positions, siblings, strict=True):
                ordered[position] = sibling
        else:
            ordered.remove(row)
            ordered.append(row)
        try:
            apply_tree_order(
                session,
                groups,
                [{"id": g.id, "parent_id": parent if g is row else g.parent_id} for g in ordered],
            )
            session.commit()
        except (ValueError, IntegrityError) as exc:
            session.rollback()
            raise HTTPException(
                422, str(exc) if isinstance(exc, ValueError) else "Conflicting sibling names."
            ) from exc
    else:
        rows = list(row.profile.level_requirements)
        if direction not in {"up", "down"}:
            raise HTTPException(422, "Choose up or down.")
        index = rows.index(row)
        target = index + (-1 if direction == "up" else 1)
        if 0 <= target < len(rows):
            rows[index], rows[target] = rows[target], rows[index]
            reorder(session, rows)
            session.commit()
    return RedirectResponse("/requirements", 303)
