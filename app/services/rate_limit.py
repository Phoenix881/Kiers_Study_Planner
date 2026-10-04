import hashlib
import time
from threading import Lock

from fastapi import HTTPException


class RateLimiter:
    """Bounded single-process limiter; reverse-proxy trust must be configured separately."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.buckets = {}
        self.lock = Lock()

    def check(self, action, key, limit, seconds):
        now = self.clock()
        identifier = (action, hashlib.sha256(str(key).encode()).hexdigest())
        with self.lock:
            self.buckets = {k: v for k, v in self.buckets.items() if v[1] > now}
            count, expiry = self.buckets.get(identifier, (0, now + seconds))
            if count >= limit or (identifier not in self.buckets and len(self.buckets) >= 10000):
                raise HTTPException(
                    429,
                    "Too many attempts. Please try again later.",
                    headers={"Retry-After": str(max(1, int(expiry - now)))},
                )
            self.buckets[identifier] = (count + 1, expiry)

    def protect(self, request, action, key=""):
        limits = {
            "login": (120, 10, 600),
            "register": (20, 5, 3600),
            "resend": (30, 3, 900),
            "reset_request": (30, 3, 900),
            "reset_submit": (30, 8, 900),
            "verify_submit": (30, 8, 900),
            "password_change": (30, 8, 900),
            "account_delete": (30, 8, 900),
            "admin_action": (120, 60, 900),
        }
        ip_limit, account_limit, window = limits[action]
        self.check(
            action + ":ip", request.client.host if request.client else "unknown", ip_limit, window
        )
        if key:
            self.check(action + ":account", key.strip().lower()[:254], account_limit, window)


limiter = RateLimiter()


def get_limiter():
    return limiter
