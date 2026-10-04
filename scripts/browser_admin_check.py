"""v0.5 browser flows; all accounts and mail belong to the disposable test database."""

import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect

from app.config import ROOT

PASSWORD = "Beta-browser-password-123"


def admin_workflows(browser, original, base, artifacts, mailbox, env, mail_url):
    errors, failures = [], []
    contexts = []
    pages = []
    database = Path(env["DATABASE_URL"].removeprefix("sqlite:///"))

    def academic_export(page):
        payload = page.request.get(base + "/export/json").json()
        payload.pop("exported_at")
        return payload

    before = academic_export(original)
    expect(original.get_by_role("link", name="Admin", exact=True)).to_have_count(0)
    with sqlite3.connect(database) as db:
        catalogue = db.execute("SELECT COUNT(*) FROM courses").fetchone()
        versions = db.execute("SELECT COUNT(*) FROM course_versions").fetchone()

    def new_page():
        context = browser.new_context(viewport={"width": 1440, "height": 1000})
        contexts.append(context)
        page = context.new_page()
        pages.append(page)
        page.on("pageerror", lambda error: errors.append(str(error)))

        def response_check(response):
            path = urlsplit(response.url).path
            expected = (path == "/login" and response.status in {403, 422}) or (
                path == "/account/delete" and response.status == 422
            )
            if response.status >= 400 and not expected:
                failures.append(f"{response.status} {path}")

        page.on("response", response_check)
        return page

    def login(page, name):
        page.goto(base + "/login")
        page.get_by_label("Email or username").fill(name)
        page.get_by_label("Password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Sign in", exact=True).click()

    def register(page, name, verify=True):
        page.goto(base + "/register")
        page.get_by_label("Email", exact=True).fill(f"{name}@example.com")
        page.get_by_label("Username", exact=True).fill(name)
        page.locator("#password").fill(PASSWORD)
        page.get_by_label("Confirm password", exact=True).fill(PASSWORD)
        page.get_by_role("button", name="Create account", exact=True).click()
        expect(page.get_by_role("heading", name="Check your email", exact=True)).to_be_visible()
        if verify:
            page.goto(mail_url(mailbox, "verify-email", f"{name}@example.com"))
            page.get_by_role("button", name="Verify email", exact=True).click()
            login(page, name)
        with sqlite3.connect(database) as db:
            return db.execute("SELECT id FROM users WHERE username=?", (name,)).fetchone()[0]

    def screen(page, name, theme="light"):
        page.get_by_role("combobox", name="Theme", exact=True).select_option(theme)
        expect(page.get_by_role("combobox", name="Theme", exact=True)).to_be_enabled()
        expect(page.locator("html")).to_have_attribute("data-theme", theme)
        page.screenshot(path=str(artifacts / f"v05-{name}.png"), full_page=True)

    def responsive(page, path):
        for width in [320, 390, 768, 1440, 1920]:
            page.set_viewport_size({"width": width, "height": 900})
            response = page.goto(base + path)
            assert response.status == 200
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), (
                path,
                width,
            )
            assert page.locator("main").bounding_box()["height"] > 100
            # Controls must wrap their text without clipping it or changing page width.
            assert page.locator("main .button").evaluate_all(
                "els => els.every(e => e.scrollWidth <= e.clientWidth + 1)"
            ), (path, width, "button clipping")
        page.set_viewport_size({"width": 1440, "height": 1000})

    try:
        operator = new_page()
        operator_id = register(operator, "betaoperator")
        subprocess.run(
            [sys.executable, "scripts/set_admin.py", "betaoperator", "--grant"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        login(operator, "betaoperator")
        expect(operator.get_by_role("link", name="Admin", exact=True)).to_be_visible()
        operator.get_by_role("link", name="Admin", exact=True).click()
        expect(operator.locator(".account-facts")).to_contain_text("Ready")
        screen(operator, "admin-overview-light")

        target = new_page()
        target_id = register(target, "betatarget", verify=False)

        def action(name, identifier=target_id, reason=None, confirmation=None, screenshot=None):
            operator.goto(base + f"/admin/users/{identifier}")
            operator.get_by_role("link", name=name, exact=True).click()
            if reason:
                operator.get_by_label("Internal reason", exact=False).fill(reason)
            if confirmation:
                operator.locator("#confirmation").fill(confirmation)
            if screenshot:
                screen(operator, screenshot)
            operator.get_by_role("button", name=name, exact=True).click()
            expect(operator.locator('main [role="status"]')).to_be_visible()

        mail_count = len(list(mailbox.glob("*.eml")))
        action("Send verification email")
        for _ in range(100):
            if len(list(mailbox.glob("*.eml"))) > mail_count:
                break
            time.sleep(0.05)
        else:
            raise AssertionError("Admin verification email was not delivered to the test mailbox")
        target.goto(mail_url(mailbox, "verify-email", "betatarget@example.com"))
        target.get_by_role("button", name="Verify email", exact=True).click()
        login(target, "betatarget")
        expect(target.get_by_role("link", name="Admin", exact=True)).to_have_count(0)
        target.get_by_label("Entry academic year").fill("2025/2026")
        target.get_by_label("Programme", exact=True).fill("PRIVATE DELETION PROGRAMME")
        target.get_by_role("button", name="Create study plan", exact=True).click()

        def add_target(name, parent="", group=False):
            target.locator("#new-group").fill(name)
            target.locator("#new-group-parent").select_option(parent)
            target.locator("#new-group-mode").select_option(
                "sum_children" if group else "own_target"
            )
            if not group:
                target.locator("#new-group-units").fill("3")
            target.get_by_role("button", name="Add target", exact=True).click()
            return target.locator(f'[data-node-name="{name}"]').get_attribute("data-node-id")

        parent = add_target("PRIVATE parent", group=True)
        child = add_target("PRIVATE nested", parent, True)
        leaf = add_target("PRIVATE allocation", child)
        data = target.request.get(base + "/export/json").json()
        profile_id = data["profile"]["id"]
        term_id = data["terms"][0]["id"]
        target.goto(base + f"/planner/terms/{term_id}/courses/new")
        target.get_by_label("Course code", exact=True).fill("DELE1001")
        target.get_by_label("Course title", exact=True).fill("PRIVATE COURSE CONTENT")
        target.get_by_label("Status", exact=True).select_option("completed")
        target.get_by_label("Grade", exact=False).select_option("A")
        target.locator("#allocation-group-1").select_option(leaf)
        target.locator("#allocation-units-1").fill("3")
        target.get_by_role("button", name="Add to plan", exact=True).click()
        owned = academic_export(target)
        assert len(owned["plan_courses"]) == 1 and len(owned["plan_course_allocations"]) == 1

        operator.goto(base + "/admin/users")
        operator.get_by_label("Username or email").fill("BETATARGET@EXAMPLE.COM")
        operator.get_by_role("button", name="Search", exact=True).click()
        expect(operator.locator("tbody tr")).to_have_count(1)
        screen(operator, "admin-users-dark", "dark")
        operator.get_by_role("link", name="betatarget", exact=True).click()
        assert "PRIVATE" not in operator.locator("main").inner_text()
        screen(operator, "admin-user-detail-light")
        action("Send password reset email")
        assert "/reset-password?token=" in mail_url(
            mailbox, "reset-password", "betatarget@example.com"
        )
        action("Revoke all sessions")
        target.goto(base + "/planner")
        expect(target).to_have_url(base + "/login")
        login(target, "betatarget")
        expect(target).not_to_have_url(base + "/login")
        action(
            "Disable account",
            reason="Browser account-safety check",
            screenshot="admin-disable-confirm",
        )
        target.goto(base + "/planner")
        expect(target).to_have_url(base + "/login")
        login(target, "betatarget")
        expect(target.locator('[role="alert"]')).to_contain_text("unavailable")
        action("Re-enable account")
        login(target, "betatarget")
        target.goto(base + "/planner")
        expect(target.get_by_test_id("earned-units")).to_have_text("3 / 128")
        assert academic_export(target) == owned

        for path in [
            "/admin",
            "/admin/users",
            f"/admin/users/{target_id}",
            f"/admin/users/{target_id}/confirm/disable_user",
            "/admin/audit",
        ]:
            responsive(operator, path)
        operator.set_viewport_size({"width": 390, "height": 900})
        operator.goto(base + f"/admin/users/{target_id}")
        screen(operator, "mobile-admin-user-detail")
        operator.set_viewport_size({"width": 1440, "height": 1000})
        operator.goto(base + f"/admin/users/{operator_id}")
        for name in ["Disable account", "Delete account and data", "Revoke all sessions"]:
            expect(operator.get_by_role("link", name=name, exact=True)).to_have_count(0)

        target.goto(base + "/profile")
        target.get_by_role("link", name="Delete account and planner data", exact=True).click()
        responsive(target, "/account/delete")
        screen(target, "profile-delete-account")
        for password, confirmation in [("wrong-password", "DELETE"), (PASSWORD, "delete")]:
            target.get_by_label("Current password", exact=True).fill(password)
            target.get_by_label("Type DELETE to confirm", exact=True).fill(confirmation)
            target.get_by_role("button", name="Delete account and planner data", exact=True).click()
            expect(target.locator('[role="alert"]')).to_be_visible()
        target.get_by_label("Current password", exact=True).fill(PASSWORD)
        target.get_by_label("Type DELETE to confirm", exact=True).fill("DELETE")
        target.get_by_role("button", name="Delete account and planner data", exact=True).click()
        expect(target.get_by_role("heading", name="Account deleted", exact=True)).to_be_visible()
        login(target, "betatarget")
        expect(target.locator('[role="alert"]')).to_contain_text("incorrect")
        with sqlite3.connect(database) as db:
            assert db.execute("SELECT COUNT(*) FROM users WHERE id=?", (target_id,)).fetchone() == (
                0,
            )
            assert db.execute(
                "SELECT COUNT(*) FROM account_tokens WHERE user_id=?", (target_id,)
            ).fetchone() == (0,)
            for table in ["academic_years", "terms", "requirement_groups", "level_requirements"]:
                assert db.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE profile_id=?", (profile_id,)
                ).fetchone() == (0,)
            assert db.execute(
                "SELECT COUNT(*) FROM student_profiles WHERE id=?", (profile_id,)
            ).fetchone() == (0,)
            assert db.execute("PRAGMA foreign_key_check").fetchall() == []
            assert db.execute("SELECT COUNT(*) FROM courses").fetchone() == catalogue
            assert db.execute("SELECT COUNT(*) FROM course_versions").fetchone() == versions

        removed = new_page()
        removed_id = register(removed, "adminremoved", verify=False)
        action("Delete account and data", removed_id, confirmation="adminremoved")
        operator.goto(base + "/admin/audit")
        for label in [
            "Send verification email",
            "Send password reset email",
            "Revoke all sessions",
            "Disable account",
            "Re-enable account",
            "Delete account and data",
        ]:
            expect(operator.locator("tbody")).to_contain_text(label)
        expect(operator.locator("tbody")).to_contain_text("adminremoved")
        assert academic_export(original) == before
        assert not errors, errors
        assert not failures, failures
        return "passed: CLI bootstrap, metadata-only admin, mail, revoke, disable/re-enable, audit, self/admin deletion, other-user/catalogue preservation"
    except Exception:
        for index, page in enumerate(pages):
            page.screenshot(path=str(artifacts / f"v05-admin-failure-{index}.png"), full_page=True)
            print(
                "Admin failure page:",
                urlsplit(page.url).path,
                page.locator("body").inner_text()[-1800:],
            )
        print("Admin browser errors:", errors, failures)
        raise
    finally:
        for context in contexts:
            context.close()
