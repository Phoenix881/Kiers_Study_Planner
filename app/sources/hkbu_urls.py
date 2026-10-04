import re

HANDBOOK_URL = "https://handbook.ar.hkbu.edu.hk/"
EXCHANGE_URL = "https://ar.hkbu.edu.hk/student-services/exemption-unit-transfer/overseas-exchange"


def normalize_course_code(code: str) -> str:
    return re.sub(r"[\s.]+", "", code).upper()


def valid_course_code(code: str) -> bool:
    return bool(re.fullmatch(r"(?:[A-Z]\.?){2,8}[0-9]{4}[A-Z]?", code))


def course_outline_url(course_code: str) -> str:
    code = normalize_course_code(course_code)
    if not valid_course_code(code):
        raise ValueError("Enter a course code such as MATH3206.")
    return f"https://arcourseoutline.hkbu.edu.hk/outline/{code}.pdf"
