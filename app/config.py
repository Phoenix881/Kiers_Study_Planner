import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_DIR = ROOT / "app"
DATA_DIR = ROOT / "data"
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{DATA_DIR / 'study_companion.sqlite3'}")
SITE_NAME = "Kier's Study Planner"

GROUPS = (
    "Major Core",
    "Major Elective",
    "Science Core",
    "University Core",
    "General Education",
    "GE Capstone",
    "Minor Core",
    "Minor Elective",
    "Free Elective",
    "Other",
)
TERM_LABELS = {"semester_1": "Semester 1", "semester_2": "Semester 2", "summer": "Summer Term"}
GROUP_SUGGESTIONS = (
    "Major",
    "Major Core",
    "Major Required",
    "Major Elective",
    "Major Honours Project",
    "Major Capstone",
    "Home Major",
    "Home Major Core",
    "Home Major Required",
    "Home Major Elective",
    "Home Major Honours Project",
    "Second Major",
    "Second Major Core",
    "Second Major Required",
    "Second Major Elective",
    "Second Major Honours Project",
    "Transdisciplinary Second Major",
    "Minor Programme",
    "Minor Core",
    "Minor Required",
    "Minor Elective",
    "Concentration",
    "Concentration Core",
    "Concentration Required",
    "Concentration Elective",
    "Science Core",
    "Science Elective",
    "Faculty Core",
    "Common Core",
    "University Core",
    "University Core - English",
    "University Core - Chinese",
    "University Core - English/Chinese",
    "University Core - Healthy Living",
    "University Core - Healthy Lifestyle",
    "University Core - Art of Persuasion",
    "University Language",
    "University Language - English",
    "University Language - Chinese",
    "General Education",
    "GE - History and Civilization",
    "GE - Culture and Civilisation",
    "GE - Values and Meaning of Life",
    "GE - Values & Meaning of Life",
    "GE - Quantitative Reasoning",
    "GE - AI Literacy",
    "GE - Healthy Lifestyle",
    "GE - Interdisciplinary Thematic Courses",
    "GE - Thematic Courses",
    "GE Capstone",
    "Free Elective",
    "Other",
)
STATUSES = {
    "planned": "Planned",
    "in_progress": "In Progress",
    "completed": "Completed",
    "withdrawn": "Withdrawn",
}
TRANSFER_STATUSES = {
    "planned": "Planned",
    "pending_approval": "Pending Approval",
    "approved": "Approved",
}
