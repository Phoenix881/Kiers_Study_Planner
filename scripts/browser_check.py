"""Exercise v0.5 workflows in an isolated database and capture responsive themes."""

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from email import policy
from email.parser import BytesParser
from pathlib import Path

import httpx
from playwright.sync_api import expect, sync_playwright
from sqlalchemy.orm import Session

from app.config import ROOT
from app.db import make_engine
from app.models import Course
from app.sources.handbook import ImportReport, parse_courses, upsert_courses
from scripts.browser_admin_check import admin_workflows


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def check_page(page, base_url, path):
    response = page.goto(base_url + path)
    assert response.status == 200, (path, response.status)
    expect(page.locator("h1")).to_be_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
        path,
        page.viewport_size,
    )
    assert page.locator("main").bounding_box()["height"] > 100


def upgrade_workflows(page, base, artifacts):
    check_page(page, base, "/requirements")

    def add(name, parent="", container=False):
        page.locator("#new-group").fill(name)
        page.locator("#new-group-parent").select_option(parent)
        page.locator("#new-group-mode").select_option("sum_children" if container else "own_target")
        if not container:
            page.locator("#new-group-units").fill("3")
        page.get_by_role("button", name="Add target", exact=True).click()
        return page.locator(f'[data-node-name="{name}"]').get_attribute("data-node-id")

    ge = add("General Education", container=True)
    foundation = add("Foundational Courses", ge, True)
    history = add("History and Civilization", foundation)
    quantitative = add("Quantitative Reasoning", foundation)
    capstone = add("GE Capstone")

    def row(identifier):
        return page.locator(f'[data-node-id="{identifier}"]')

    def drag(identifier, target, ratio=0.5):
        handle = row(identifier).locator(".drag-handle")
        handle.scroll_into_view_if_needed()
        target.scroll_into_view_if_needed()
        source, bounds = handle.bounding_box(), target.bounding_box()
        x, y = source["x"] + source["width"] / 2, source["y"] + source["height"] / 2
        target_x, target_y = bounds["x"] + 45, bounds["y"] + bounds["height"] * ratio
        with page.expect_navigation():
            page.mouse.move(x, y)
            page.mouse.down()
            page.mouse.move(x + 8, y + 8, steps=4)
            page.mouse.move(target_x, target_y, steps=12)
            page.mouse.move(target_x + 1, target_y + 1)
            page.mouse.up()

    drag(capstone, row(ge))
    expect(row(capstone)).to_have_attribute("data-parent", ge)
    drag(quantitative, row(ge))
    expect(row(quantitative)).to_have_attribute("data-parent", ge)
    drag(capstone, row(quantitative), 0.95)
    data = page.request.get(base + "/export/json").json()
    by_id = {str(g["id"]): g for g in data["requirement_groups"]}
    assert by_id[capstone]["sort_order"] > by_id[quantitative]["sort_order"]
    drag(quantitative, page.locator("[data-root-drop]"))
    expect(row(quantitative)).to_have_attribute("data-parent", "")
    row(quantitative).locator("summary").press("Enter")
    row(quantitative).get_by_role("button", name="Move to group", exact=True).click()
    move = page.locator("dialog[open]")
    move.get_by_label("Move to group", exact=True).select_option(ge)
    move.get_by_role("button", name="Move", exact=True).click()
    expect(row(quantitative)).to_have_attribute("data-parent", ge)
    row(quantitative).locator("summary").click()
    row(quantitative).get_by_role("button", name="Move to top level", exact=True).click()
    expect(row(quantitative)).to_have_attribute("data-parent", "")
    row(quantitative).locator("summary").click()
    row(quantitative).get_by_role("button", name="Edit", exact=True).click()
    edit = page.locator("dialog[open]")
    edit.get_by_label("Notes", exact=True).fill("Browser-edited target note")
    edit.get_by_role("button", name="Save", exact=True).click()
    page.get_by_role("button", name="Collapse General Education", exact=True).click()
    expect(row(history)).to_be_hidden()
    page.reload()
    expect(row(history)).to_be_hidden()
    page.get_by_role("button", name="Expand General Education", exact=True).click()
    expect(row(history)).to_be_visible()
    assert "Single target" in row(quantitative).inner_text()
    assert "Group of targets" in row(ge).inner_text()
    page.reload()
    expect(row(capstone)).to_have_attribute("data-parent", ge)
    page.screenshot(path=str(artifacts / "v05-desktop-targets.png"), full_page=True)
    check_page(page, base, "/")
    button = page.get_by_role("button", name="Collapse General Education", exact=True)
    button.click()
    expect(page.locator(f'[data-progress-id="group-{history}"]')).to_be_hidden()
    page.get_by_role("button", name="Expand General Education", exact=True).click()
    expect(page.locator(f'[data-progress-id="group-{history}"]')).to_be_visible()
    check_page(page, base, "/courses?year=2026-2027&level=1&prefix=ZZZZ&q=pagination")
    expect(page.locator(".results-heading")).to_contain_text("Showing 1–50 of 125")
    first = page.locator("td.code").first.inner_text()
    page.get_by_role("link", name="Next page", exact=True).click()
    expect(page.locator(".results-heading")).to_contain_text("Showing 51–100 of 125")
    assert page.locator("td.code").first.inner_text() != first
    assert "prefix=ZZZZ" in page.url and "q=pagination" in page.url
    page.go_back()
    expect(page.locator("td.code").first).to_have_text(first)
    page.go_forward()
    expect(page.locator(".results-heading")).to_contain_text("Showing 51–100 of 125")
    check_page(page, base, "/planner/terms/1/courses/new")
    search = page.get_by_role("combobox", name="Course code or title", exact=True)
    search.fill("comp")
    expect(page.locator("[role=option]").first).to_contain_text("COMP")
    search.press("ArrowDown")
    expect(search).to_have_attribute("aria-activedescendant", "catalogue-option-0")
    search.press("Enter")
    expect(page.locator("#course_code_snapshot")).to_have_value("COMP2015")
    expect(page.locator("#course_version_id")).not_to_have_value("")
    search.fill("data str")
    expect(page.locator("[role=option]").first).to_contain_text("Data Structures and Algorithms")
    search.press("ArrowDown")
    search.press("Escape")
    expect(search).to_have_attribute("aria-expanded", "false")
    search.fill("data stru")
    page.locator("[role=option]").first.click()
    expect(page.locator("#course_title_snapshot")).to_have_value("Data Structures and Algorithms")
    options = page.locator("#allocation-group-1 option")
    assert (
        options.filter(
            has_text="General Education / Foundational Courses / History and Civilization"
        ).count()
        == 1
    )
    expect(page.locator(f'#allocation-group-1 option[value="{ge}"]')).to_be_disabled()
    page.locator("#course_code_snapshot").fill("MANU4999")
    expect(page.locator("#course_version_id")).to_have_value("")
    expect(page.locator("#course_id")).to_have_value("")
    page.locator("#course_title_snapshot").fill("Browser manual advanced course")
    page.locator("#units").fill("2")
    page.locator("#allocation-group-1").select_option(history)
    page.locator("#allocation-units-1").fill("2")
    page.locator("#status").select_option("withdrawn")
    page.locator("#grade").select_option("W")
    page.get_by_role("button", name="Add to plan", exact=True).click()
    payload = page.request.get(base + "/export/json").json()
    manual = next(c for c in payload["plan_courses"] if c["course_code_snapshot"] == "MANU4999")
    assert manual["course_version_id"] is None and manual["level_snapshot"] is None
    assert any(
        a["plan_course_id"] == manual["id"] and a["requirement_group_id"] == int(history)
        for a in payload["plan_course_allocations"]
    )
    check_page(page, base, "/")
    theme = page.get_by_role("combobox", name="Theme", exact=True)

    def choose_theme(value):
        with page.expect_response("**/account/theme") as result:
            theme.select_option(value)
        assert result.value.status == 200
        expect(theme).to_be_enabled()

    choose_theme("light")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.screenshot(path=str(artifacts / "v05-desktop-light-dashboard.png"), full_page=True)
    choose_theme("dark")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.screenshot(path=str(artifacts / "v05-desktop-dark-dashboard.png"), full_page=True)
    check_page(page, base, "/planner")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    page.emulate_media(color_scheme="light")
    choose_theme("system")
    expect(page.locator("html")).to_have_attribute("data-theme", "light")
    page.emulate_media(color_scheme="dark")
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    choose_theme("dark")


def mail_url(mailbox, purpose, recipient=None):
    for _ in range(100):
        files = sorted(mailbox.glob("*.eml"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in files:
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            if recipient and message["To"] != recipient:
                continue
            body = message.get_content()
            match = re.search(r"https?://[^\s]+/" + purpose + r"\?token=[A-Za-z0-9_-]+", body)
            if match:
                return match.group()
        time.sleep(0.05)
    raise AssertionError("Expected development email was not recorded.")


def sign_in(page, password):
    page.get_by_label("Email or username").fill("browser@example.com")
    page.get_by_label("Password", exact=True).fill(password)
    page.get_by_role("button", name="Sign in", exact=True).click()


def auth_screens(page, artifacts, name):
    for theme in ["light", "dark"]:
        page.get_by_role("combobox", name="Theme", exact=True).select_option(theme)
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
        expect(page.get_by_role("combobox", name="Theme", exact=True)).to_be_enabled()
        for width in [320, 390, 768, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 900})
            page.reload(wait_until="networkidle")
            page.evaluate("window.scrollTo(0, 0)")
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            if width in {390, 1440}:
                page.screenshot(
                    path=str(artifacts / f"v05-{width}-{theme}-{name}.png"), full_page=True
                )
    page.set_viewport_size({"width": 1440, "height": 1000})


def recovery_workflows(page, base, artifacts, mailbox):
    check_page(page, base, "/")
    expect(page).to_have_title("Dashboard | Kier's Study Planner")
    expect(page.locator("footer")).to_contain_text(
        "Not operated by or affiliated with Hong Kong Baptist University"
    )
    for label in ["Earned", "In progress", "Planned", "Remaining"]:
        expect(page.locator("[data-degree-legend]")).to_contain_text(label)
    assert page.locator(".degree-progress > span").count() == 4
    page.get_by_role("button", name="Sign out", exact=True).click()
    page.get_by_role("link", name="Forgot your password?", exact=True).click()
    auth_screens(page, artifacts, "forgot-password")
    page.get_by_label("Email", exact=True).fill("browser@example.com")
    page.get_by_role("button", name="Send reset link", exact=True).click()
    expect(page.locator('main [role="status"]')).to_contain_text("If an account exists")
    page.goto(mail_url(mailbox, "reset-password"))
    expect(page).to_have_url(base + "/reset-password")
    auth_screens(page, artifacts, "reset-password")
    page.get_by_label("New password", exact=True).fill("Reset-browser-password-456")
    page.get_by_label("Confirm new password", exact=True).fill("Reset-browser-password-456")
    page.get_by_role("button", name="Reset password", exact=True).click()
    page.get_by_role("link", name="Sign in", exact=True).click()
    sign_in(page, "Browser-password-123")
    expect(page.locator('[role="alert"]')).to_contain_text(
        "Email/username or password is incorrect."
    )
    sign_in(page, "Reset-browser-password-456")
    expect(page.get_by_test_id("earned-units")).to_have_text("12 / 128")
    check_page(page, base, "/account/security")
    auth_screens(page, artifacts, "change-password")
    page.get_by_label("Current password", exact=True).fill("Reset-browser-password-456")
    page.get_by_label("New password", exact=True).fill("Changed-browser-password-789")
    page.get_by_label("Confirm new password", exact=True).fill("Changed-browser-password-789")
    page.get_by_role("button", name="Change password", exact=True).click()
    expect(page.get_by_role("heading", name="Password changed", exact=True)).to_be_visible()
    check_page(page, base, "/planner")


def workflows(page, base, artifacts, mailbox):
    check_page(page, base, "/register")
    page.get_by_label("Email", exact=True).fill("browser@example.com")
    page.get_by_label("Username", exact=True).fill("browser")
    page.get_by_label("Password", exact=False).first.fill("Browser-password-123")
    page.get_by_label("Confirm password", exact=True).fill("Browser-password-123")
    page.get_by_role("button", name="Create account", exact=True).click()
    expect(page.get_by_role("heading", name="Check your email", exact=True)).to_be_visible()
    page.goto(mail_url(mailbox, "verify-email"))
    expect(page).to_have_url(base + "/verify-email")
    auth_screens(page, artifacts, "verification")
    page.get_by_role("button", name="Verify email", exact=True).click()
    page.get_by_role("link", name="Sign in", exact=True).click()
    sign_in(page, "Browser-password-123")
    page.get_by_label("Entry academic year").fill("2024/2025")
    page.get_by_label("Programme", exact=True).fill("Browser Mathematics")
    page.get_by_role("button", name="Create study plan", exact=True).click()
    for name, units in [("Major Core", "36"), ("Minor Elective", "18"), ("Free Elective", "30")]:
        page.get_by_label("New target", exact=True).fill(name)
        page.locator("#new-group-units").fill(units)
        page.get_by_role("button", name="Add target", exact=True).click()
    page.get_by_label("New level target").fill("Advanced study")
    page.locator("#new-level-units").fill("36")
    page.get_by_role("button", name="Add level target").click()
    check_page(page, base, "/planner")
    assert page.locator(".study-year").count() == 4
    assert page.locator(".term-section").count() == 8
    page.locator("#year-1").get_by_role("button", name="Add Summer Term", exact=True).click()
    assert page.locator(".term-section").count() == 9
    page.locator("#new-academic-year").fill("2028/2029")
    page.locator("#new-year-label").fill("Placement Programme")
    page.get_by_role("button", name="Add year", exact=True).click()
    year = page.locator("#year-5")
    expect(year).to_contain_text("Placement Programme")
    year.get_by_text("Add study period", exact=True).click()
    year.locator("#new-period-5").fill("Placement")
    year.get_by_role("button", name="Add period", exact=True).click()
    check_page(page, base, "/courses")
    page.get_by_label("Course code or title").fill("scientific")
    page.get_by_role("button", name="Search", exact=True).click()
    page.get_by_role("link", name="MATH3206", exact=True).click()
    expect(page.get_by_role("link", name="View on HKBU Handbook")).to_have_attribute(
        "href", "https://handbook.ar.hkbu.edu.hk/2026-2027/course/MATH3206"
    )
    expect(page.get_by_role("link", name="View official course outline")).to_have_attribute(
        "href", "https://arcourseoutline.hkbu.edu.hk/outline/MATH3206.pdf"
    )
    page.get_by_label("Study period", exact=True).select_option("1")
    page.get_by_role("button", name="Add to plan", exact=True).click()
    expect(page.get_by_label("Course title", exact=True)).to_have_value("Scientific Computing I")
    page.get_by_label("Status", exact=True).select_option("completed")
    page.get_by_label("Grade", exact=False).select_option("B")
    page.locator("#allocation-group-1").select_option(label="Major Core")
    page.locator("#allocation-units-1").fill("3")
    page.get_by_role("button", name="Add another allocation").click()
    page.locator('[name="allocation_group_id"]').nth(1).select_option(label="Minor Elective")
    page.locator('[name="allocated_units"]').nth(1).fill("3")
    page.get_by_role("button", name="Add to plan", exact=True).click()
    expect(page.get_by_test_id("earned-units")).to_have_text("3 / 128")
    expect(page.locator("#term-1")).to_contain_text("Major Core (3)")
    expect(page.locator("#term-1")).to_contain_text("Minor Elective (3)")
    for term_id, status, grade in [(2, "withdrawn", "W"), (3, "completed", "A")]:
        check_page(page, base, f"/planner/terms/{term_id}/courses/new")
        page.get_by_label("Course code", exact=True).fill("TEST1001")
        page.get_by_label("Course title", exact=True).fill("Retake workflow")
        page.get_by_label("Status", exact=True).select_option(status)
        page.get_by_label("Grade", exact=False).select_option(grade)
        page.get_by_role("button", name="Add to plan", exact=True).click()
    before_cgpa = page.get_by_test_id("cgpa").inner_text()
    expect(page.get_by_test_id("earned-units")).to_have_text("6 / 128")
    page.locator("#term-4 > details > summary").click()
    page.locator("#is-exchange-4").check()
    page.locator("#host-4").fill("Browser Host University")
    page.locator("#term-4").get_by_role("button", name="Save period", exact=True).click()
    for title in ["Host A", "Host B"]:
        check_page(page, base, "/planner/terms/4/exchange-courses/new")
        page.get_by_label("Host course title", exact=True).fill(title)
        page.get_by_label("Host grade", exact=False).fill("99/100")
        page.get_by_label("HKBU equivalent code", exact=False).fill("COMP2015")
        page.get_by_label("Transfer status", exact=True).select_option("pending_approval")
        page.locator("#allocation-group-1").select_option(label="Minor Elective")
        page.get_by_role("button", name="Add to plan", exact=True).click()
    expect(page.locator(".review-notes")).to_contain_text("Duplicate HKBU equivalent COMP2015")
    expect(page.get_by_test_id("projected-units")).to_have_text("9 / 128")
    for identifier, equivalent, group in [
        (1, "COMP2015", "Minor Elective"),
        (2, "", "Free Elective"),
    ]:
        check_page(page, base, f"/planner/exchange-courses/{identifier}/edit")
        page.get_by_label("HKBU equivalent code", exact=False).fill(equivalent)
        page.get_by_label("Transfer status", exact=True).select_option("approved")
        page.get_by_label("Host grade", exact=False).fill("F")
        page.locator("#allocation-group-1").select_option(label=group)
        page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_test_id("cgpa")).to_have_text(before_cgpa)
    expect(page.get_by_test_id("earned-units")).to_have_text("12 / 128")
    with page.expect_download() as download:
        page.get_by_role("link", name="Export plan", exact=True).click()
    payload = json.loads(Path(download.value.path()).read_text())
    assert payload["version"] == 2 and len(payload["academic_years"]) == 5
    assert len(payload["plan_course_allocations"]) == 2
    upgrade_workflows(page, base, artifacts)
    paths = [
        ("/", "dashboard"),
        ("/planner", "planner"),
        ("/audit", "audit"),
        ("/requirements", "targets"),
        ("/profile", "profile"),
        ("/courses", "courses"),
        ("/courses/MATH3206", "course-detail"),
        ("/planner/courses/1/edit", "course-form"),
        ("/planner/terms/4/exchange-courses/new", "exchange-form"),
    ]
    for width in [320, 390, 768, 1440, 1920]:
        page.set_viewport_size({"width": width, "height": 900})
        for path, name in paths:
            check_page(page, base, path)
            if path == "/requirements":
                target = page.locator('[data-node-name="History and Civilization"]')
                target.locator("summary").click()
                panel = target.locator(".target-menu-panel").bounding_box()
                assert panel["x"] >= 0 and panel["x"] + panel["width"] <= width
                target.get_by_role("button", name="Move to group", exact=True).click()
                dialog = page.locator("dialog[open]")
                bounds = dialog.bounding_box()
                assert bounds["x"] >= 0 and bounds["x"] + bounds["width"] <= width
                if width == 390:
                    page.screenshot(path=str(artifacts / "v05-mobile-move-dialog.png"))
                dialog.get_by_role("button", name="Cancel", exact=True).click()
            if width in {390, 1440}:
                page.screenshot(
                    path=str(
                        artifacts / f"v05-{'mobile' if width == 390 else 'desktop'}-dark-{name}.png"
                    ),
                    full_page=path != "/planner",
                )
    page.get_by_role("button", name="Sign out", exact=True).click()
    expect(page.get_by_role("heading", name="Sign in", exact=True)).to_be_visible()
    page.get_by_label("Email or username").fill("browser")
    page.get_by_label("Password", exact=True).fill("Browser-password-123")
    page.get_by_role("button", name="Sign in", exact=True).click()
    expect(page.get_by_test_id("cgpa")).to_have_text(before_cgpa)
    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    recovery_workflows(page, base, artifacts, mailbox)
    for code, status in [("FOUR3001", "in_progress"), ("FOUR3002", "planned")]:
        check_page(page, base, "/planner/terms/5/courses/new")
        page.get_by_label("Course code", exact=True).fill(code)
        page.get_by_label("Course title", exact=True).fill("Progress segment fixture")
        page.get_by_label("Status", exact=True).select_option(status)
        page.get_by_role("button", name="Add to plan", exact=True).click()
    check_page(page, base, "/")
    expect(page.get_by_test_id("projected-units")).to_have_text("18 / 128")
    for key in ["earned", "active", "planned", "remaining"]:
        assert page.locator(f".degree-progress > .segment-{key}").bounding_box()["width"] > 0
    page.screenshot(path=str(artifacts / "v05-four-state-progress.png"), full_page=True)
    return {
        "cgpa": before_cgpa,
        "earned": "12 / 128",
        "projected": "18 / 128",
        "workflows": "v0.5 account, targets, catalogue, GPA, exchange and export",
    }


def run(channel):
    artifacts = ROOT / "artifacts"
    artifacts.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="hkbu-browser-") as directory:
        url = f"sqlite:///{Path(directory) / 'browser.sqlite3'}"
        mailbox = Path(directory) / "mailbox"
        env = {
            **os.environ,
            "DATABASE_URL": url,
            "ENVIRONMENT": "development",
            "MAIL_BACKEND": "file",
            "MAIL_FILE_DIRECTORY": str(mailbox),
            "REGISTRATION_MODE": "open",
        }
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=env, check=True
        )
        engine = make_engine(url)
        with Session(engine) as session:
            rows, _ = parse_courses(
                (ROOT / "tests/fixtures/handbook_courses.html").read_text(), "2026-2027"
            )
            upsert_courses(session, rows, ImportReport("2026-2027"))
            session.add(
                Course(
                    code="COMP2015",
                    title="Data Structures and Algorithms",
                    units=3,
                    level=2,
                    source_academic_year="2026-2027",
                    data_status="official_imported",
                )
            )
            session.add_all(
                [
                    Course(
                        code=f"ZZZZ{1000 + i}",
                        title=f"Browser pagination {i}",
                        units=3,
                        level=1,
                        source_academic_year="2026-2027",
                        data_status="official_imported",
                    )
                    for i in range(125)
                ]
            )
            session.commit()
        engine.dispose()
        port = available_port()
        base = f"http://127.0.0.1:{port}"
        env["APP_BASE_URL"] = base
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=ROOT,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        try:
            with httpx.Client(trust_env=False) as client:
                for _ in range(100):
                    if server.poll() is not None:
                        raise RuntimeError(server.stderr.read().decode())
                    try:
                        if client.get(base + "/health").status_code == 200:
                            assert client.get(base + "/ready").json() == {
                                "status": "ready",
                                "version": "0.5.0",
                            }
                            break
                    except httpx.ConnectError:
                        pass
                    time.sleep(0.1)
                else:
                    raise RuntimeError("Browser test server did not start.")
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(channel=channel, headless=True)
                page = browser.new_page(
                    viewport={"width": 1440, "height": 1000}, device_scale_factor=1
                )
                page.set_default_timeout(10000)
                errors, failed_responses = [], []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on(
                    "response",
                    lambda response: (
                        failed_responses.append(
                            f"{response.status} {response.url.split(chr(63))[0]}"
                        )
                        if response.status >= 400
                        and not (response.status == 422 and response.url.endswith("/login"))
                        else None
                    ),
                )
                try:
                    summary = workflows(page, base, artifacts, mailbox)
                    summary["administration"] = admin_workflows(
                        browser, page, base, artifacts, mailbox, env, mail_url
                    )
                except Exception:
                    page.screenshot(path=str(artifacts / "v05-browser-failure.png"), full_page=True)
                    print(
                        "Failure page:",
                        page.url.split("?")[0],
                        page.locator("body").inner_text()[-3000:],
                    )
                    print("Browser errors:", errors, failed_responses)
                    raise
                assert not errors, errors
                assert not failed_responses, failed_responses
                summary.update(
                    status="passed",
                    viewports=[320, 390, 768, 1440, 1920],
                    browser_errors=errors,
                    failed_responses=failed_responses,
                )
                print(json.dumps(summary, indent=2))
                browser.close()
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channel", default="chrome", help="Installed browser channel.")
    run(parser.parse_args().channel)
