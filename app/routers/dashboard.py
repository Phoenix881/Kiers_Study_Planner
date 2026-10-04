from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.db import get_session
from app.security import owned_profile
from app.services.summary import build_overview
from app.web import render

router = APIRouter()


@router.get("/")
def dashboard(request: Request, session: Session = Depends(get_session)):
    profile = owned_profile(request, session)
    if profile is None:
        return RedirectResponse("/profile", status_code=303)
    return render(request, "dashboard.html", profile=profile, overview=build_overview(profile))
