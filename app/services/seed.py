from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    AcademicYear,
    Course,
    ExchangeCourse,
    ExchangeCourseAllocation,
    PlanCourse,
    PlanCourseAllocation,
    RequirementGroup,
    StudentProfile,
    Term,
)
from app.sources.hkbu_urls import course_outline_url

DEMO_COURSES = [
    ("COMP1005", "Essence of Computing", 3),
    ("COMP2015", "Data Structures and Algorithms", 3),
    ("COMP2045", "Programming and Problem Solving", 2),
    ("COMP2046", "Problem Solving using OOP", 2),
    ("MATH1005", "Calculus I", 3),
    ("MATH1205", "Discrete Mathematics", 3),
    ("MATH2007", "Programming with Mathematical Software", 1),
    ("MATH2205", "Multivariable Calculus", 3),
    ("MATH2206", "Probability and Statistics", 3),
    ("MATH2207", "Linear Algebra I", 3),
    ("MATH2215", "Mathematical Analysis", 3),
    ("MATH2216", "Statistical Methods and Theory", 3),
    ("MATH2225", "Calculus II", 3),
    ("MATH3205", "Operations Research I", 3),
    ("MATH3206", "Scientific Computing I", 3),
    ("MATH3405", "Differential Equations I", 3),
    ("MATH3406", "Abstract Algebra", 3),
    ("MATH3805", "Regression Analysis", 3),
    ("MATH3806", "Multivariate Statistical Methods", 3),
    ("MATH4226", "Introduction to Deep Learning", 3),
    ("MATH4998", "Mathematical Science Project I", 3),
]


def seed_catalogue(session: Session) -> dict[str, Course]:
    courses = {course.code: course for course in session.scalars(select(Course))}
    for code, title, units in DEMO_COURSES:
        if code not in courses:
            course = Course(
                code=code,
                title=title,
                units=Decimal(units),
                outline_url=course_outline_url(code),
                data_status="demo_unverified",
            )
            session.add(course)
            courses[code] = course
    session.flush()
    return courses


def seed_demo(session: Session, with_exchange=False, catalogue_only=False) -> bool:
    catalogue = seed_catalogue(session)
    if catalogue_only or session.get(StudentProfile, 1):
        session.commit()
        return False
    profile = StudentProfile(
        id=1,
        admission_year="2024/25",
        programme_name="BSc (Hons) Mathematics and Statistics",
        minor_name="Computer Science (demo)",
        required_total_units=128,
        curriculum_key="demo_math_stats_2024_25",
    )
    session.add(profile)
    # Explicit legacy-shaped demonstration, independent of new-profile defaults.
    for index in range(4):
        year = AcademicYear(
            profile=profile,
            academic_year=f"{2024 + index}/{2025 + index}",
            label=f"Year {index + 1}",
            sort_order=index,
        )
        session.add(year)
        for position, (kind, name) in enumerate(
            [("semester_1", "Semester 1"), ("semester_2", "Semester 2"), ("summer", "Summer Term")]
        ):
            if index == 3 and kind == "summer":
                continue
            session.add(
                Term(
                    profile=profile,
                    academic_year=year,
                    study_year=index + 1,
                    term_type=kind,
                    name=name,
                    sort_order=index * 3 + position,
                )
            )
    session.flush()
    terms = {term.sort_order: term for term in profile.terms}

    def add(
        order, code, grade=None, group="Major Core", status="completed", title=None, units=None
    ):
        course = catalogue.get(code)
        session.add(
            PlanCourse(
                term=terms[order],
                course=course,
                course_version=course.latest_version if course else None,
                course_code_snapshot=code,
                course_title_snapshot=title or course.title,
                units=units if units is not None else course.units,
                requirement_group=group,
                status=status,
                grade=grade,
            )
        )

    for code, grade in zip(
        ["MATH2205", "MATH2206", "MATH2207", "MATH2215", "MATH2216"],
        ["B+", "B+", "A-", "B+", "A-"],
        strict=True,
    ):
        add(0, code, grade)
    for code, grade, group in [
        ("COMP2045", "B+", "Minor Core"),
        ("COMP2046", "A-", "Minor Core"),
        ("COMP1005", "A", "Science Core"),
        ("MATH1005", "B-", "Major Core"),
        ("MATH1205", "B", "Major Elective"),
        ("MATH2007", "A", "Major Core"),
    ]:
        add(1, code, grade, group)
    add(2, "DEMO1001", "S", "General Education", title="Community learning (demo)", units=3)
    add(3, "MATH2225", "A-")
    add(3, "MATH3406", "W", status="withdrawn")
    add(4, "MATH3205", "B+", "Major Elective")
    add(4, "MATH3405", "B", "Major Elective")
    add(6, "MATH3206", group="Major Core", status="in_progress")
    add(6, "MATH3805", group="Major Elective", status="in_progress")
    add(
        6,
        "DEMO2001",
        group="University Core",
        status="in_progress",
        title="University core course (demo)",
        units=3,
    )
    add(9, "MATH3806", group="Major Elective", status="planned")
    add(9, "MATH4998", status="planned")
    add(10, "MATH4226", group="Major Elective", status="planned")
    add(10, "MATH3406", group="Major Core", status="planned")
    if with_exchange:
        term = terms[7]
        term.is_exchange = True
        term.host_university = "Sogang University"
        session.add(
            ExchangeCourse(
                term=term,
                host_course_code="CSE4185",
                host_course_title="Data Structures (demo)",
                host_units=3,
                host_grade="A",
                hkbu_equivalent_course_id=catalogue["COMP2015"].id,
                hkbu_equivalent_code="COMP2015",
                hkbu_equivalent_title="Data Structures and Algorithms",
                transferred_units=3,
                requirement_group="Minor Elective",
                transfer_status="approved",
                notes="Illustrative student-entered equivalency, not an official approval.",
            )
        )
        session.add(
            ExchangeCourse(
                term=term,
                host_course_title="Interactive Media (demo)",
                host_units=3,
                host_grade="B+",
                hkbu_equivalent_title="Free Elective",
                transferred_units=3,
                requirement_group="Free Elective",
                transfer_status="pending_approval",
            )
        )
    session.flush()
    groups = {}
    for term in profile.terms:
        for entry in [*term.courses, *term.exchange_courses]:
            name = entry.requirement_group
            if name not in groups:
                groups[name] = RequirementGroup(
                    profile=profile, name=name, required_units=0, sort_order=len(groups)
                )
                session.add(groups[name])
            cls = (
                PlanCourseAllocation if isinstance(entry, PlanCourse) else ExchangeCourseAllocation
            )
            entry.allocations.append(
                cls(
                    group=groups[name],
                    allocated_units=entry.units
                    if isinstance(entry, PlanCourse)
                    else entry.transferred_units,
                )
            )
    session.commit()
    return True
