from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import StudentProfile
from app.schemas.inputs import ProfileInput
from app.security import current_user, owned_profile
from app.services.plans import ensure_terms
from app.web import form_errors, render

router = APIRouter()


@router.get("/profile")
def profile_page(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session, required=False)
    return render(request, "profile.html", profile=profile, values=profile or {})


@router.post("/profile")
async def save_profile(request: Request, session: Session = Depends(get_session)):
    user = current_user(request, session)
    profile = owned_profile(request, session, required=False)
    values = dict(await request.form())
    try:
        data = ProfileInput.model_validate(values)
    except ValidationError as exc:
        return render(
            request, "profile.html", 422, profile=profile, values=values, errors=form_errors(exc)
        )
    new = profile is None
    if new:
        profile = StudentProfile(user_id=user.id)
        session.add(profile)
    for key, value in data.model_dump(exclude={"curriculum_key"}).items():
        setattr(profile, key, value)
    if new:
        ensure_terms(session, profile)
    session.commit()
    return RedirectResponse("/requirements" if new else "/profile?saved=1", 303)
