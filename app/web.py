from fastapi import HTTPException, Request
from fastapi.templating import Jinja2Templates
from pydantic import ValidationError

from app.config import (
    APP_DIR,
    GROUP_SUGGESTIONS,
    GROUPS,
    SITE_NAME,
    STATUSES,
    TERM_LABELS,
    TRANSFER_STATUSES,
)
from app.schemas.inputs import VALID_GRADES
from app.services.gpa import format_gpa
from app.services.plans import academic_year
from app.services.registration import RegistrationSettings

templates = Jinja2Templates(directory=str(APP_DIR / "templates"))
templates.env.globals.update(
    groups=GROUPS,
    site_name=SITE_NAME,
    group_suggestions=GROUP_SUGGESTIONS,
    statuses=STATUSES,
    transfer_statuses=TRANSFER_STATUSES,
    grades=VALID_GRADES,
    term_labels=TERM_LABELS,
    academic_year=academic_year,
)
templates.env.filters["units"] = lambda value: (
    f"{value:,.2f}".rstrip("0").rstrip(".") if value is not None else "\u2014"
)
templates.env.filters["gpa"] = format_gpa


def render(request: Request, name: str, status_code=200, **context):
    return templates.TemplateResponse(
        request=request,
        name=name,
        context={
            "errors": {},
            "admin_access": bool(getattr(request.state, "admin_access", False)),
            "registration_mode": RegistrationSettings.from_env().mode,
            **context,
        },
        status_code=status_code,
    )


def form_errors(exc: ValidationError):
    return {
        str(error["loc"][0]): error["msg"].removeprefix("Value error, ") for error in exc.errors()
    }


def find_or_404(session, model, identifier):
    item = session.get(model, identifier)
    if item is None:
        raise HTTPException(404, "That record could not be found.")
    return item
