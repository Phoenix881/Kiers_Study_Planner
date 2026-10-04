import os
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.config import APP_DIR, SITE_NAME
from app.db import get_session
from app.routers import (
    account,
    admin,
    audit,
    auth,
    courses,
    dashboard,
    export,
    lifecycle,
    planner,
    profile,
    requirements,
    timeline,
)
from app.security import csrf_protect
from app.services.mail import MailSettings
from app.services.readiness import database_readiness
from app.services.registration import RegistrationSettings
from app.services.security_logging import configure_security_logging, log_failure
from app.web import render

settings = MailSettings.from_env()
configure_security_logging()


@asynccontextmanager
async def lifespan(app):
    settings.validate()
    RegistrationSettings.from_env().validate()
    yield


app = FastAPI(
    title=SITE_NAME,
    version="0.5.0",
    lifespan=lifespan,
    dependencies=[Depends(csrf_protect)],
    docs_url=None,
    redoc_url=None,
)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ.get("SECRET_KEY") or secrets.token_hex(32),
    same_site="strict",
    https_only=settings.environment == "production",
)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        "localhost",
        "127.0.0.1",
        "[::1]",
        "testserver",
        urlsplit(settings.base_url).hostname or "localhost",
    ],
)
app.mount("/static", StaticFiles(directory=str(APP_DIR / "static")), name="static")
app.include_router(profile.router)
app.include_router(auth.router)
app.include_router(account.router)
app.include_router(admin.router)
app.include_router(lifecycle.router)
app.include_router(requirements.router)
app.include_router(timeline.router)
app.include_router(planner.router)
app.include_router(dashboard.router)
app.include_router(audit.router)
app.include_router(courses.router)
app.include_router(export.router)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code == 303:
        from fastapi.responses import RedirectResponse

        return RedirectResponse(exc.headers["Location"], status_code=303)
    response = render(
        request, "error.html", exc.status_code, detail=exc.detail, code=exc.status_code
    )
    response.headers.update(exc.headers or {})
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    request.state.request_id = secrets.token_hex(16)
    try:
        response = await call_next(request)
    except Exception as exc:
        log_failure(request, exc)
        request.scope.setdefault("session", {})
        response = render(
            request,
            "error.html",
            500,
            code=500,
            detail="The request could not be completed. Please try again.",
            request_id=request.state.request_id,
        )
    response.headers["X-Request-ID"] = request.state.request_id
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    if not request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/ready")
def ready(session: Session = Depends(get_session)):
    available = database_readiness(session)
    return JSONResponse(
        {"status": "ready" if available else "not_ready", "version": app.version},
        status_code=200 if available else 503,
    )
