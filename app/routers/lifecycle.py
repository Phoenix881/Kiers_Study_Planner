import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_session
from app.security import current_user
from app.services.account_security import valid_password
from app.services.accounts import delete_account
from app.services.rate_limit import get_limiter
from app.web import render

router = APIRouter()


@router.get("/account/delete")
def delete_page(request: Request, session: Session = Depends(get_session)):
    current_user(request, session)
    return render(request, "delete_account.html")


@router.post("/account/delete")
async def delete_self(
    request: Request, session: Session = Depends(get_session), limiter=Depends(get_limiter)
):
    user = current_user(request, session)
    limiter.protect(request, "account_delete", str(user.id))
    form = await request.form()
    errors = {}
    if not valid_password(str(form.get("current_password", "")), user.password_hash):
        errors["current_password"] = "Current password is incorrect."
    if form.get("confirmation") != "DELETE":
        errors["confirmation"] = "Type DELETE exactly to confirm."
    if errors:
        return render(request, "delete_account.html", 422, errors=errors)
    try:
        delete_account(session, user)
        session.commit()
    except (ValueError, IntegrityError) as exc:
        session.rollback()
        raise HTTPException(
            409, "The account could not be deleted. Contact the site administrator."
        ) from exc
    request.session.clear()
    request.session["csrf_token"] = secrets.token_urlsafe(32)
    return RedirectResponse("/goodbye", 303)


@router.get("/goodbye")
def goodbye(request: Request):
    return render(request, "delete_account.html", goodbye=True)
