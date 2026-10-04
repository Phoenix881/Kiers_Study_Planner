from pathlib import Path

import httpx
from sqlalchemy import func, select

from app.models import Course, CourseVersion
from app.sources.handbook import (
    ImportReport,
    discover_prefixes,
    fetch_page,
    import_handbook,
    parse_courses,
    upsert_courses,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_discovery_and_real_html_structure():
    assert discover_prefixes((FIXTURES / "handbook_index.html").read_text()) == [
        "BIOL",
        "COMP",
        "MATH",
    ]
    rows, warnings = parse_courses((FIXTURES / "handbook_courses.html").read_text(), "2026-2027")
    assert len(rows) == 4
    first = rows[0]
    assert (first.code, first.title, first.units, first.level, first.department) == (
        "MATH3206",
        "Scientific Computing I",
        3,
        3,
        "MATH",
    )
    assert first.prerequisite_text == "MATH1005 or Year 3 Standing"
    assert first.corequisite_text == "MATH3001"
    assert first.antirequisite_text == "COMP2027"
    assert first.description == "A synthetic description for parser tests."
    assert first.outline_url == "https://arcourseoutline.hkbu.edu.hk/outline/MATH3206.pdf"
    assert first.source_url == "https://handbook.ar.hkbu.edu.hk/2026-2027/course/MATH3206"
    assert rows[2].level == 7
    assert rows[3].level is None
    assert any("Malformed" in w for w in warnings)
    assert any("stored NULL" in w for w in warnings)
    assert any("typo" in w for w in warnings)


def test_versions_idempotence_updates_and_dry_run(session):
    html = (FIXTURES / "handbook_courses.html").read_text()
    rows, _ = parse_courses(html, "2026-2027")
    first = ImportReport("2026-2027")
    upsert_courses(session, rows, first)
    session.commit()
    version = session.scalar(select(CourseVersion).join(Course).where(Course.code == "MATH3206"))
    timestamp = version.last_checked_at
    rows[0].title = "Updated title"
    again = ImportReport("2026-2027")
    upsert_courses(session, rows, again)
    session.commit()
    assert again.new_course_identities == again.new_course_versions == 0
    assert again.updated_versions == 4
    assert version.title == "Updated title"
    assert version.last_checked_at >= timestamp
    historical, _ = parse_courses(html, "2025-2026")
    upsert_courses(session, historical, ImportReport("2025-2026"))
    session.commit()
    assert session.scalar(select(func.count(Course.id))) == 4
    assert session.scalar(select(func.count(CourseVersion.id))) == 8

    def respond(request):
        return httpx.Response(
            200,
            text='<select name="letter_code"><option value="MATH">MATH</option></select>'
            if request.url.path.endswith("/course")
            else html,
        )

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        report = import_handbook(session, "2027-2028", client, dry_run=True, delay=0)
    assert report.new_course_versions == 4
    assert session.scalar(select(func.count(CourseVersion.id))) == 8


def test_import_failure_rolls_back_and_throttling_is_not_retried(session):
    urls = []

    def respond(request):
        urls.append(str(request.url))
        if request.url.path.endswith("/course"):
            return httpx.Response(
                200, text='<select name="letter_code"><option value="MATH">MATH</option></select>'
            )
        return httpx.Response(429)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        report = import_handbook(session, "2026-2027", client, delay=0)
    assert len(urls) == 2
    assert report.errors == ["MATH: HTTP 429"]
    assert session.scalar(select(func.count(Course.id))) == 0


def test_transient_fetch_retries():
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503 if len(calls) == 1 else 200, text="ok")

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert (
            fetch_page(
                client, "https://handbook.ar.hkbu.edu.hk/2026-2027/course", sleep=lambda _: None
            )
            == "ok"
        )
    assert len(calls) == 2


def test_bilingual_whitespace_dotted_codes_and_numeric_unit_suffixes():
    html = '<div class="panel"><h4>A.F. Level 7</h4><div class="course-item"><h5>A.F.7410 Test\nBilingual title (3)</h5></div></div>'
    rows, warnings = parse_courses(html, "2026-2027")
    assert len(rows) == 1
    assert rows[0].code == "AF7410"
    assert rows[0].source_url.endswith("/AF7410")
    assert rows[0].level == 7
    assert rows[0].department == "AF"
    assert rows[0].title == "Test Bilingual title"
    assert any("no unit label" in w for w in warnings)
