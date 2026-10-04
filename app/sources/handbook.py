"""HKBU Handbook HTML discovery, parsing and local catalogue updates."""

import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.models import Course, CourseVersion
from app.sources.hkbu_urls import course_outline_url, normalize_course_code, valid_course_code

HOST = "https://handbook.ar.hkbu.edu.hk"


def validate_year(year):
    if not re.fullmatch(r"20\d{2}-20\d{2}", year) or int(year[5:]) != int(year[:4]) + 1:
        raise ValueError("Use a consecutive Handbook academic year, for example 2026-2027.")
    return year


def discover_prefixes(html):
    soup = BeautifulSoup(html, "html.parser")
    prefixes = set()
    for option in soup.select('select[name="letter_code"] option, select#letter-code option'):
        value = option.get("value", "").strip()
        if re.fullmatch(r"[A-Z]{2,8}", value):
            prefixes.add(value)
    for link in soup.select("a[href]"):
        match = re.fullmatch(r"/20\d{2}-20\d{2}/course/([A-Z]{2,8})/?", urlparse(link["href"]).path)
        if match:
            prefixes.add(match[1])
    return sorted(prefixes)


@dataclass
class ParsedCourse:
    code: str
    title: str
    units: Decimal
    level: int | None
    department: str | None
    academic_year: str
    source_url: str
    outline_url: str
    prerequisite_text: str | None = None
    corequisite_text: str | None = None
    antirequisite_text: str | None = None
    description: str | None = None


def parse_courses(html, year):
    validate_year(year)
    soup = BeautifulSoup(html, "html.parser")
    rows, warnings = [], []
    seen = set()
    for item in soup.select(".course-item"):
        heading = item.find("h5")
        text = " ".join(heading.get_text(" ", strip=True).split()) if heading else ""
        match = re.fullmatch(
            r"((?:[A-Z]\.?){2,8}\s*\d{4}[A-Z]?)\s+(.+?)\s*\((\d+(?:\.\d+)?)\s*(units?|untis)?\)",
            text,
            re.I,
        )
        if not match or not valid_course_code(normalize_course_code(match[1])):
            warnings.append(f"Malformed course heading skipped: {text[:180]}")
            continue
        code, title, units = normalize_course_code(match[1]), match[2].strip(), Decimal(match[3])
        if len(title) > 240 or units > 9999 or units.as_tuple().exponent < -2:
            warnings.append(f"Out-of-range metadata skipped: {code}")
            continue
        if code in seen:
            warnings.append(f"Duplicate course heading skipped: {code}")
            continue
        seen.add(code)
        panel = item.find_parent(class_="panel")
        panel_heading = panel.select_one("h4") if panel else None
        level_text = panel_heading.get_text(" ", strip=True) if panel_heading else ""
        level_match = re.fullmatch(
            r"((?:[A-Z]\.?){2,8})\s+Level\s+(\d+)", " ".join(level_text.split()), re.I
        )
        level = int(level_match[2]) if level_match else None
        prefix = re.match(r"[A-Z.]+", code)[0].replace(".", "")
        if level_match and level_match[1].upper().replace(".", "") != prefix:
            level = None
        if level is None:
            warnings.append(f"{code}: no unambiguous explicit level; stored NULL")
        if match[4] and match[4].lower() == "untis":
            warnings.append(f"{code}: source unit-label typo 'untis' normalized")
        if not match[4]:
            warnings.append(f"{code}: numeric Handbook unit suffix has no unit label")
        fields = {}
        for label in item.select("dt"):
            key = label.get_text(" ", strip=True).rstrip(":").lower().replace("-", "")
            target = {
                "prerequisite": "prerequisite_text",
                "prerequisites": "prerequisite_text",
                "corequisite": "corequisite_text",
                "corequisites": "corequisite_text",
                "antirequisite": "antirequisite_text",
                "antirequisites": "antirequisite_text",
            }.get(key)
            value = label.find_next_sibling("dd")
            if target and value:
                fields[target] = value.get_text(" ", strip=True)
        detail = item.select_one(".detail")
        rows.append(
            ParsedCourse(
                code,
                title,
                units,
                level,
                prefix,
                year,
                f"{HOST}/{year}/course/{code}",
                course_outline_url(code),
                description=detail.get_text(" ", strip=True) if detail else None,
                **fields,
            )
        )
    if not soup.select(".course-item"):
        warnings.append("No course items found in page")
    return rows, warnings


@dataclass
class ImportReport:
    academic_year: str
    prefixes_discovered: int = 0
    courses_discovered: int = 0
    new_course_identities: int = 0
    new_course_versions: int = 0
    updated_versions: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def upsert_courses(session, rows, report):
    for row in rows:
        course = session.scalar(select(Course).where(Course.code == row.code))
        if course is None:
            course = Course(code=row.code)
            session.add(course)
            session.flush()
            report.new_course_identities += 1
        version = session.scalar(
            select(CourseVersion).where(
                CourseVersion.course_id == course.id,
                CourseVersion.academic_year == row.academic_year,
            )
        )
        if version is None:
            version = CourseVersion(course=course, academic_year=row.academic_year)
            session.add(version)
            report.new_course_versions += 1
        else:
            report.updated_versions += 1
        for name, value in vars(row).items():
            if name != "code":
                setattr(version, name, value)
        version.last_checked_at = datetime.now(timezone.utc)
        version.data_status = "official_imported"
        session.flush()


def fetch_page(client, url, sleep=time.sleep):
    for attempt in range(3):
        try:
            response = client.get(url)
            # Respect throttling/access refusals; never retry 403 or 429.
            if response.status_code in {500, 502, 503, 504} and attempt < 2:
                sleep(0.5 * (attempt + 1))
                continue
            response.raise_for_status()
            return response.text
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == 2:
                raise
            sleep(0.5 * (attempt + 1))
    raise RuntimeError("Could not fetch Handbook page")


def import_handbook(session, year, client=None, dry_run=False, delay=0.2):
    validate_year(year)
    report = ImportReport(year)
    own_client = client is None
    if own_client:
        client = httpx.Client(
            timeout=30,
            follow_redirects=False,
            headers={
                "User-Agent": "HKBUStudyCompanion/0.2 (independent local academic catalogue cache)"
            },
        )
    try:
        prefixes = discover_prefixes(fetch_page(client, f"{HOST}/{year}/course"))
        report.prefixes_discovered = len(prefixes)
        if not prefixes:
            report.errors.append("No prefixes discovered; no catalogue data was changed.")
        parsed_rows = []
        for prefix in prefixes:
            try:
                html = fetch_page(client, f"{HOST}/{year}/course/{prefix}")
                rows, warnings = parse_courses(html, year)
                report.warnings.extend(f"{prefix}: {warning}" for warning in warnings)
                report.courses_discovered += len(rows)
                parsed_rows.extend(rows)
            except httpx.HTTPStatusError as exc:
                report.errors.append(f"{prefix}: HTTP {exc.response.status_code}")
                if exc.response.status_code in {401, 403, 429}:
                    break
            except httpx.HTTPError as exc:
                report.errors.append(f"{prefix}: {type(exc).__name__}")
            if delay:
                time.sleep(delay)
        # Finish network work before opening a SQLite write transaction.
        if not report.errors:
            upsert_courses(session, parsed_rows, report)
        if dry_run or report.errors:
            session.rollback()
        else:
            session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        if own_client:
            client.close()
    return report
