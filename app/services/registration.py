import os
import secrets
from dataclasses import dataclass, field


@dataclass(frozen=True)
class RegistrationSettings:
    mode: str = "open"
    invite_code: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        return cls(os.getenv("REGISTRATION_MODE", "open"), os.getenv("BETA_INVITE_CODE", ""))

    def validate(self):
        if self.mode not in {"open", "invite", "closed"}:
            raise RuntimeError("REGISTRATION_MODE must be open, invite or closed.")
        if self.mode == "invite" and not 1 <= len(self.invite_code) <= 256:
            raise RuntimeError("Invite registration requires BETA_INVITE_CODE (1-256 characters).")

    def accepts(self, submitted):
        return self.mode == "open" or (
            self.mode == "invite"
            and bool(self.invite_code)
            and len(submitted) <= 256
            and secrets.compare_digest(submitted.encode(), self.invite_code.encode())
        )
