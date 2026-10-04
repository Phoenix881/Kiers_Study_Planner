import logging
import traceback
from pathlib import Path

from app.models.profile import utc_now


class RedactAccountURLs(logging.Filter):
    def filter(self, record):
        if (
            record.name == "uvicorn.access"
            and isinstance(record.args, tuple)
            and len(record.args) == 5
        ):
            values = list(record.args)
            values[2] = str(values[2]).split("?", 1)[0]
            record.args = tuple(values)
        return True


def configure_security_logging():
    logging.getLogger("uvicorn.access").addFilter(RedactAccountURLs())


def log_failure(request, exc):
    # Exception text, source lines and frame locals may contain passwords or form data.
    frames = traceback.extract_tb(exc.__traceback__)[-30:]
    stack = " | ".join(f"{Path(f.filename).name}:{f.lineno}:{f.name}" for f in frames)
    route = getattr(request.scope.get("route"), "path", "/unmatched")
    logging.getLogger("app.errors").error(
        "%s request_id=%s method=%s route=%s exception=%s stack=%s",
        utc_now().isoformat(),
        request.state.request_id,
        request.method[:16],
        route,
        type(exc).__name__,
        stack,
    )
