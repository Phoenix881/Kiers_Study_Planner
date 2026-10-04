import json
from decimal import Decimal

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.models import (
    Course,
    CourseVersion,
    ExchangeCourse,
    PlanCourse,
    RequirementGroup,
    StudentProfile,
    User,
)
from app.services.audit import evaluate_progress
from app.services.credit import CreditRecord
from app.services.levels import backfill_levels, exchange_level, normal_level
from app.services.summary import build_overview
from tests.conftest import create_profile, register
from tests.test_routes import exchange_form, normal_form
from tests.test_v02 import post


def catalogue(
    session,
    code="COMP3015",
    level=3,
    year="2026-2027",
    title="Data Structures and Algorithms",
    status="official_imported",
):
    course = session.scalar(select(Course).where(Course.code == code)) or Course(code=code)
    version = CourseVersion(
        course=course, academic_year=year, title=title, units=3, level=level, data_status=status
    )
    session.add_all([course, version])
    session.commit()
    return version


def group(client, name, **values):
    response = post(client, "/requirements/groups", name=name, required_units="3", **values)
    assert response.status_code == 303, response.text
    return next(
        g["id"]
        for g in client.get("/export/json").json()["requirement_groups"]
        if g["name"] == name
        and g["parent_id"] == (int(values["parent_id"]) if values.get("parent_id") else None)
    )


def tree_post(client, placements):
    return post(client, "/requirements/tree/reorder", placements=json.dumps(placements))


def test_level_backfill_conservative_idempotent_and_snapshot_preserving(client, session):
    create_profile(client)
    first = catalogue(session)
    ambiguous = catalogue(session, "TEST3001", 3, "2024-2025")
    catalogue(session, "TEST3001", 4)
    catalogue(session, "DEMO3001", 3, status="demo_unverified")
    for code in ["COMP3015", "TEST3001", "DEMO3001", "MANU3999"]:
        client.post("/planner/terms/1/courses", data=normal_form(client, course_code_snapshot=code))
    entries = list(session.scalars(select(PlanCourse).order_by(PlanCourse.id)))
    entries[1].course_version = ambiguous
    entries[3].level_snapshot = 2
    session.commit()
    before = {
        e.id: (
            e.course_title_snapshot,
            e.units,
            e.grade,
            e.status,
            e.notes,
            e.updated_at,
            e.course_version_id,
        )
        for e in entries
    }
    preview = backfill_levels(session)
    assert (
        preview["inspected"],
        preview["filled"],
        preview["unknown"],
        preview["already_known"],
    ) == (4, 2, 1, 1)
    assert entries[0].level_snapshot is None
    result = backfill_levels(session, apply=True)
    session.commit()
    session.expire_all()
    assert result["historical_snapshots_overwritten"] == 0
    assert [e.level_snapshot for e in entries] == [3, 3, None, 2]
    assert {
        e.id: (
            e.course_title_snapshot,
            e.units,
            e.grade,
            e.status,
            e.notes,
            e.updated_at,
            e.course_version_id,
        )
        for e in entries
    } == before
    again = backfill_levels(session, apply=True)
    assert (again["filled"], again["already_known"], again["unknown"]) == (0, 3, 1)
    first.level = 1
    session.commit()
    assert normal_level(entries[0]) == 3


def test_ambiguous_unknown_demo_and_selected_version_precedence(client, session):
    create_profile(client)
    old = catalogue(session, level=2, year="2024-2025")
    catalogue(session, level=4)
    client.post(
        "/planner/terms/1/courses", data=normal_form(client, course_code_snapshot="COMP3015")
    )
    row = session.scalar(select(PlanCourse))
    assert backfill_levels(session)["unknown"] == 1
    row.course_version = old
    assert normal_level(row) == 2
    assert backfill_levels(session, apply=True)["filled"] == 1
    session.commit()
    assert row.level_snapshot == 2
    row.course_version = None
    assert normal_level(row) == 2


@pytest.mark.parametrize(
    "status,grade,earned,projected",
    [
        ("completed", "A", 3, 3),
        ("completed", "S", 3, 3),
        ("completed", "DT", 3, 3),
        ("completed", "F", 0, 0),
        ("withdrawn", "W", 0, 0),
        ("planned", None, 0, 3),
        ("in_progress", None, 0, 3),
        ("completed", "E", 0, 0),
    ],
)
def test_known_level_progress_preserves_grade_semantics(
    client, session, status, grade, earned, projected
):
    create_profile(client)
    version = catalogue(session)
    post(client, "/requirements/levels", label="Advanced", minimum_level="3", required_units="36")
    client.post(
        "/planner/terms/1/courses",
        data=normal_form(
            client,
            course_code_snapshot="COMP3015",
            course_version_id=str(version.id),
            status=status,
            grade=grade or "",
        ),
    )
    result = build_overview(session.get(StudentProfile, 1)).audit.requirements[-1]
    assert (result.completed_value, result.projected_value) == (earned, projected)


@pytest.mark.parametrize(
    "status,current,projected", [("approved", 3, 3), ("pending_approval", 0, 3), ("planned", 0, 3)]
)
def test_specific_exchange_levels_and_generic_exclusion(
    client, session, status, current, projected
):
    create_profile(client)
    catalogue(session)
    post(client, "/planner/terms/2/exchange", is_exchange="true")
    post(client, "/requirements/levels", label="Advanced", minimum_level="3", required_units="36")
    client.post(
        "/planner/terms/2/exchange-courses",
        data=exchange_form(client, hkbu_equivalent_code="COMP3015", transfer_status=status),
    )
    client.post(
        "/planner/terms/2/exchange-courses",
        data=exchange_form(client, hkbu_equivalent_code="", transfer_status="approved"),
    )
    entries = list(session.scalars(select(ExchangeCourse).order_by(ExchangeCourse.id)))
    entries[0].level_snapshot = None
    entries[1].level_snapshot = 4
    session.commit()
    assert exchange_level(entries[0]) == 3
    assert exchange_level(entries[1]) is None
    overview = build_overview(session.get(StudentProfile, 1))
    assert overview.cgpa is None
    result = overview.audit.requirements[-1]
    assert (result.completed_value, result.projected_value) == (current, projected)
    assert backfill_levels(session, apply=True)["filled"] == 1


def test_nested_targets_progress_surplus_overlap_and_physical_units(client, session):
    create_profile(client)
    root = group(client, "Degree categories", aggregation_mode="sum_children")
    major = group(client, "Major", parent_id=str(root), aggregation_mode="sum_children")
    core = group(client, "Core", parent_id=str(major))
    elective = group(client, "Elective", parent_id=str(major))
    minor = group(client, "Minor", parent_id=str(root), aggregation_mode="sum_children")
    minor_core = group(client, "Core", parent_id=str(minor))
    profile = session.get(StudentProfile, 1)
    record = CreditRecord(
        "hkbu_course",
        "COMP3015",
        "Snapshot",
        Decimal(6),
        3,
        "",
        "earned",
        1,
        ((core, Decimal(6)), (minor_core, Decimal(6))),
    )
    report = evaluate_progress(profile, [record])
    rows = {r.id: r for r in report.requirements}
    assert report.earned_units == 6
    assert rows[f"group-{major}"].required_value == 6
    assert rows[f"group-{major}"].completed_value == 6
    assert rows[f"group-{major}"].status != "completed"
    assert rows[f"group-{root}"].required_value == 9
    assert rows[f"group-{root}"].completed_value == 12
    assert rows[f"group-{root}"].status != "completed"
    assert rows[f"group-{elective}"].depth == 2
    assert rows[f"group-{minor_core}"].ancestors == (root, minor)
    assert report.requirements[1].id == f"group-{root}"
    form = client.get("/planner/terms/1/courses/new").text
    assert "Degree categories / Major / Core" in form
    assert f'value="{root}" disabled' in form


def test_tree_reorder_indent_outdent_delete_and_export(client, session):
    create_profile(client)
    a, b, c = [group(client, name) for name in ["A", "B", "C"]]
    assert (
        tree_post(
            client,
            [{"id": c, "parent_id": None}, {"id": a, "parent_id": None}, {"id": b, "parent_id": a}],
        ).status_code
        == 200
    )
    session.expire_all()
    assert session.get(RequirementGroup, a).aggregation_mode == "sum_children"
    assert post(client, f"/requirements/groups/{a}/delete").status_code == 409
    assert post(client, f"/requirements/groups/{b}/move", direction="outdent").status_code == 303
    assert post(client, f"/requirements/groups/{b}/move", direction="indent").status_code == 303
    session.expire_all()
    assert session.get(RequirementGroup, b).parent_id == a
    assert post(client, f"/requirements/groups/{b}/delete").status_code == 303
    assert post(client, f"/requirements/groups/{a}/delete").status_code == 303
    data = client.get("/export/json").json()
    assert data["requirement_groups"][0]["id"] == c
    assert data["requirement_groups"][0]["aggregation_mode"] == "own_target"


@pytest.mark.parametrize(
    "placements",
    [
        [{"id": 1, "parent_id": 1}, {"id": 2, "parent_id": None}],
        [{"id": 1, "parent_id": 2}, {"id": 2, "parent_id": 1}],
        [{"id": 1, "parent_id": 2}, {"id": 2, "parent_id": 999}],
        [{"id": 1, "parent_id": None}],
        [{"id": 1, "parent_id": None}, {"id": 1, "parent_id": None}],
        [{"id": 1, "parent_id": None}, {"id": 999, "parent_id": None}],
        [{"id": True, "parent_id": None}, {"id": 2, "parent_id": None}],
    ],
)
def test_forged_or_cyclic_reorder_is_atomic(client, session, placements):
    create_profile(client)
    group(client, "A")
    group(client, "B")
    before = client.get("/export/json").json()["requirement_groups"]
    assert tree_post(client, placements).status_code == 422
    assert client.get("/export/json").json()["requirement_groups"] == before


def test_allocated_leaf_cannot_become_container_or_receive_children(client, session):
    create_profile(client)
    a, b = group(client, "A"), group(client, "B")
    client.post(
        "/planner/terms/1/courses",
        data=normal_form(client, units="3", allocation_group_id=str(a), allocated_units="3"),
    )
    assert (
        post(
            client,
            f"/requirements/groups/{a}/edit",
            name="A",
            required_units="3",
            aggregation_mode="sum_children",
        ).status_code
        == 422
    )
    assert (
        tree_post(client, [{"id": a, "parent_id": None}, {"id": b, "parent_id": a}]).status_code
        == 422
    )
    container = group(client, "Container", aggregation_mode="sum_children")
    assert (
        client.post(
            "/planner/terms/2/courses",
            data=normal_form(
                client,
                course_code_snapshot="MANU3001",
                allocation_group_id=str(container),
                allocated_units="3",
            ),
        ).status_code
        == 422
    )
    assert len(client.get("/export/json").json()["plan_course_allocations"]) == 1


def test_sibling_name_uniqueness_and_cross_account_tree(client, session):
    create_profile(client)
    a = group(client, "A", aggregation_mode="sum_children")
    b = group(client, "B", aggregation_mode="sum_children")
    core = group(client, "Core", parent_id=str(a))
    group(client, "Core", parent_id=str(b))
    assert post(client, "/requirements/groups", name="a", required_units="3").status_code == 422
    assert (
        post(
            client, "/requirements/groups", name="Core", required_units="3", parent_id=str(a)
        ).status_code
        == 422
    )
    assert (
        post(
            client,
            f"/requirements/groups/{a}/edit",
            name="A",
            required_units="3",
            parent_id=str(core),
            aggregation_mode="sum_children",
        ).status_code
        == 422
    )
    post(client, "/logout")
    register(client, "second")
    create_profile(client)
    own = group(client, "Mine")
    assert tree_post(client, [{"id": own, "parent_id": a}]).status_code == 422
    assert (
        post(
            client, "/requirements/groups", name="Forged", required_units="3", parent_id=str(a)
        ).status_code
        == 422
    )
    assert client.post("/requirements/tree/reorder", data={"placements": "[]"}).status_code == 403


def test_empty_container_is_not_completed(client, session):
    create_profile(client)
    group(client, "Empty", aggregation_mode="sum_children")
    result = build_overview(session.get(StudentProfile, 1)).audit.requirements[-1]
    assert result.status == "missing"
    assert result.required_value == 0


def test_pagination_all_rows_filters_and_out_of_range(client, session):
    for index in range(125):
        session.add(
            Course(
                code=f"COMP{1000 + index}",
                title=f"Search row {index}",
                units=3,
                level=1,
                source_academic_year="2026-2027",
                data_status="official_imported",
            )
        )
    session.commit()
    pages = [
        client.get(f"/courses?year=2026-2027&level=1&prefix=COMP&q=Search&page={i}").text
        for i in range(1, 4)
    ]
    from bs4 import BeautifulSoup

    codes = [[a.text for a in BeautifulSoup(p, "html.parser").select("td.code a")] for p in pages]
    assert list(map(len, codes)) == [50, 50, 25]
    assert len(set(sum(codes, []))) == 125
    assert "Showing 1&ndash;50 of 125" in pages[0]
    assert "page=2" in pages[0] and "prefix=COMP" in pages[0]
    assert "Showing 101&ndash;125 of 125" in client.get("/courses?page=9999").text
    assert "Showing 1&ndash;50 of 125" in client.get("/courses?page=-2").text
    assert "Showing 0&ndash;0 of 0" in client.get("/courses?q=notfound").text


def test_autocomplete_ranking_year_cap_title_and_auth(client, session):
    catalogue(session, "COMP2015", 2)
    catalogue(session, "ABCD1001", 1, title="Computer Studies")
    catalogue(session, "ACOMP1001", 1, title="Other")
    catalogue(session, "COMP2015", 1, "2024-2025", "Old historical title")
    for index in range(20):
        catalogue(session, f"COMP{4000 + index}", 4)
    result = client.get("/api/catalogue/search?q=comp&limit=500").json()
    assert len(result) == 12 and all(r["code"].startswith("COMP") for r in result)
    assert client.get("/api/catalogue/search?q=comp%202015").json()[0]["code"] == "COMP2015"
    assert (
        client.get("/api/catalogue/search?q=data%20str").json()[0]["title"]
        == "Data Structures and Algorithms"
    )
    assert (
        client.get("/api/catalogue/search?q=comp2015&academic_year=2024-2025").json()[0]["title"]
        == "Old historical title"
    )
    assert client.get("/api/catalogue/search?q=").json() == []
    assert client.get("/api/catalogue/search?q=unknown").json() == []
    post(client, "/logout")
    assert client.get("/api/catalogue/search?q=comp", follow_redirects=False).status_code == 303


def test_manual_entry_and_stale_catalogue_selection_validation(client, session):
    create_profile(client)
    version = catalogue(session)
    assert (
        client.post(
            "/planner/terms/1/courses",
            data=normal_form(
                client, course_code_snapshot="TEST3999", course_version_id=str(version.id)
            ),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/planner/terms/1/courses",
            data=normal_form(
                client,
                course_code_snapshot="COMP3015",
                course_version_id=str(version.id),
                course_id="999",
            ),
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/planner/terms/1/courses",
            data=normal_form(
                client,
                course_code_snapshot="COMP3015",
                course_title_snapshot="My manual title",
                units="2",
            ),
        ).status_code
        == 200
    )
    row = session.scalar(select(PlanCourse))
    assert (row.course_id, row.course_version_id, row.level_snapshot) == (None, None, None)
    assert (row.course_title_snapshot, row.units) == ("My manual title", 2)


def test_theme_default_validation_csrf_account_isolation_and_login(client, session):
    assert session.get(User, 1).theme_preference == "system"
    assert client.post("/account/theme", data={"theme_preference": "dark"}).status_code == 403
    assert post(client, "/account/theme", theme_preference="invalid").status_code == 422
    assert post(client, "/account/theme", theme_preference="dark").json() == {
        "theme_preference": "dark"
    }
    session.expire_all()
    assert session.get(User, 1).theme_preference == "dark"
    post(client, "/logout")
    register(client, "second")
    assert session.get(User, 2).theme_preference == "system"
    assert post(client, "/account/theme", theme_preference="light", user_id="1").status_code == 200
    session.expire_all()
    assert session.get(User, 1).theme_preference == "dark"
    post(client, "/logout")
    post(client, "/login", identifier="student", password="Test-password-123")
    assert 'let preference = "dark"' in client.get("/profile").text
    user = session.get(User, 1)
    user.theme_preference = "invalid"
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_requirement_tree_render_queries_do_not_scale_per_node(client, session, engine):
    create_profile(client)
    counts = []

    def record(*args):
        counts.append(args[2])

    event.listen(engine, "before_cursor_execute", record)
    try:
        client.get("/requirements")
        baseline = len(counts)
        session.add_all(
            [
                RequirementGroup(profile_id=1, name=f"Node {i}", sort_order=i, required_units=3)
                for i in range(100)
            ]
        )
        session.commit()
        counts.clear()
        assert client.get("/requirements").status_code == 200
        assert len(counts) <= baseline + 1
    finally:
        event.remove(engine, "before_cursor_execute", record)


def test_level_threshold_is_generic_and_repeats_are_unique(client, session):
    create_profile(client)
    post(client, "/requirements/levels", label="Advanced", minimum_level="3", required_units="36")
    for code, level in [("COMP2015", 2), ("COMP3015", 3), ("COMP7001", 7)]:
        version = catalogue(session, code, level)
        client.post(
            "/planner/terms/1/courses",
            data=normal_form(client, course_code_snapshot=code, course_version_id=str(version.id)),
        )
    client.post(
        "/planner/terms/2/courses",
        data=normal_form(
            client,
            course_code_snapshot="COMP3015",
            course_version_id="2",
            exceptional_repeat="true",
        ),
    )
    overview = build_overview(session.get(StudentProfile, 1))
    assert overview.audit.requirements[-1].completed_value == 6
    assert overview.audit.earned_units == 9


def test_nested_container_completion_and_unchanged_sibling_branch(client, session):
    create_profile(client)
    a, b = (
        group(client, "A", aggregation_mode="sum_children"),
        group(client, "B", aggregation_mode="sum_children"),
    )
    first, second = (
        group(client, "First", parent_id=str(a)),
        group(client, "Second", parent_id=str(a)),
    )
    third, fourth = (
        group(client, "Third", parent_id=str(b)),
        group(client, "Fourth", parent_id=str(b)),
    )
    assert post(client, f"/requirements/groups/{second}/move", direction="up").status_code == 303
    session.expire_all()
    assert (
        session.get(RequirementGroup, second).sort_order
        < session.get(RequirementGroup, first).sort_order
    )
    assert (
        session.get(RequirementGroup, third).sort_order
        < session.get(RequirementGroup, fourth).sort_order
    )
    records = [
        CreditRecord(
            "hkbu_course",
            f"COMP{3000 + i}",
            "Known",
            Decimal(3),
            3,
            "",
            "earned",
            1,
            ((target, Decimal(3)),),
        )
        for i, target in enumerate([first, second])
    ]
    result = evaluate_progress(session.get(StudentProfile, 1), records)
    assert next(r for r in result.requirements if r.id == f"group-{a}").status == "completed"
    assert next(r for r in result.requirements if r.id == f"group-{b}").status == "missing"


def test_course_form_prefers_period_year_and_retains_historical_snapshot(client, session):
    create_profile(client)
    old = catalogue(session, year="2024-2025", level=2)
    current = catalogue(session, year="2026-2027", level=4)
    assert 'data-year="2024-2025"' in client.get("/planner/terms/1/courses/new").text
    assert 'data-year="2026-2027"' in client.get("/planner/terms/3/courses/new").text
    client.post(
        "/planner/terms/1/courses",
        data=normal_form(client, course_code_snapshot="COMP3015", course_version_id=str(old.id)),
    )
    old.level, old.title, old.units = 1, "Refreshed title", 4
    session.commit()
    response = client.post(
        "/planner/courses/1/edit",
        data=normal_form(
            client,
            course_code_snapshot="COMP3015",
            course_version_id=str(old.id),
            course_title_snapshot="Data Structures and Algorithms",
            units="3",
            notes="New note",
        ),
    )
    assert response.status_code == 200
    entry = session.get(PlanCourse, 1)
    assert (entry.level_snapshot, entry.units, entry.course_title_snapshot) == (
        2,
        3,
        "Data Structures and Algorithms",
    )
    assert current.level == 4
