from collections import defaultdict
from dataclasses import dataclass
from uuid import uuid4

from sqlalchemy import select

from app.models import ExchangeCourseAllocation, PlanCourseAllocation


@dataclass
class TreeRow:
    group: object
    depth: int
    ancestors: tuple[int, ...]
    path: str


def tree_rows(groups):
    children = defaultdict(list)
    for group in groups:
        children[group.parent_id].append(group)
    for siblings in children.values():
        siblings.sort(key=lambda g: (g.sort_order, g.id or 0))
    stack = [(g, (), ()) for g in reversed(children[None])]
    result = []
    while stack:
        group, ancestors, names = stack.pop()
        result.append(TreeRow(group, len(ancestors), ancestors, " / ".join((*names, group.name))))
        stack.extend(
            (c, (*ancestors, group.id), (*names, group.name)) for c in reversed(children[group.id])
        )
    return result


def allocated_group_ids(session, groups):
    ids = [g.id for g in groups if g.id is not None]
    result = set()
    for model in (PlanCourseAllocation, ExchangeCourseAllocation):
        result.update(
            session.scalars(
                select(model.requirement_group_id).where(model.requirement_group_id.in_(ids))
            )
        )
    return result


def validate_tree(groups, parents=None, names=None):
    by_id = {g.id: g for g in groups}
    parents = parents if parents is not None else {g.id: g.parent_id for g in groups}
    names = names or {g.id: g.name for g in groups}
    seen_names = set()
    for identifier, parent in parents.items():
        if parent is not None and (
            parent not in by_id or by_id[parent].profile_id != by_id[identifier].profile_id
        ):
            raise ValueError("Choose a parent from your own profile.")
    for identifier, parent in parents.items():
        seen = {identifier}
        ancestor = parent
        while ancestor is not None:
            if ancestor in seen:
                raise ValueError("A requirement cannot contain itself or one of its ancestors.")
            seen.add(ancestor)
            ancestor = parents[ancestor]
        key = (parent, names[identifier].strip().casefold())
        if key in seen_names:
            raise ValueError("A requirement with that name already exists under this parent.")
        seen_names.add(key)


def apply_tree_order(session, groups, placements):
    """Validate a complete tree snapshot, then atomically persist parent and sibling order."""
    by_id = {g.id: g for g in groups}
    if len(placements) != len(groups) or {p["id"] for p in placements} != set(by_id):
        raise ValueError("The requirement list changed. Reload it before moving a target.")
    parents = {p["id"]: p["parent_id"] for p in placements}
    validate_tree(groups, parents)
    containers = set(parents.values()) - {None}
    occupied = allocated_group_ids(session, groups)
    if containers & occupied:
        raise ValueError(
            "Move direct course allocations to a leaf before making this target a container."
        )
    # Temporarily rename moved nodes so valid same-name branch swaps cannot collide mid-flush.
    moved_names = {g.id: g.name for g in groups if g.parent_id != parents[g.id]}
    for identifier in moved_names:
        by_id[identifier].name = f"__moving_{uuid4().hex}"
    session.flush()
    orders = defaultdict(int)
    for placement in placements:
        row = by_id[placement["id"]]
        parent = placement["parent_id"]
        row.parent_id = parent
        row.sort_order = orders[parent]
        orders[parent] += 1
        if row.id in containers:
            row.aggregation_mode = "sum_children"
    session.flush()
    for identifier, name in moved_names.items():
        by_id[identifier].name = name
    session.flush()
