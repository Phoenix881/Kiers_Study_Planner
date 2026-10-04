"""Vendor-neutral transactional mail; the development mailbox is never web-served."""

import logging
import os
import re
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

from app.config import DATA_DIR, SITE_NAME


@dataclass(frozen=True)
class MailSettings:
    environment: str = "development"
    base_url: str = "http://127.0.0.1:8001"
    backend: str = "file"
    directory: Path = DATA_DIR / "mailbox"
    host: str = ""
    port: int = 587
    username: str = ""
    password: str = ""
    use_tls: bool = True
    from_address: str = "planner@localhost"
    from_name: str = SITE_NAME

    @classmethod
    def from_env(cls):
        return cls(
            environment=os.getenv("ENVIRONMENT", "development"),
            base_url=os.getenv("APP_BASE_URL", "http://127.0.0.1:8001").rstrip("/"),
            backend=os.getenv("MAIL_BACKEND", "file"),
            directory=Path(os.getenv("MAIL_FILE_DIRECTORY", str(DATA_DIR / "mailbox"))),
            host=os.getenv("SMTP_HOST", ""),
            port=int(os.getenv("SMTP_PORT", "587")),
            username=os.getenv("SMTP_USERNAME", ""),
            password=os.getenv("SMTP_PASSWORD", ""),
            use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
            from_address=os.getenv("MAIL_FROM_ADDRESS", "planner@localhost"),
            from_name=os.getenv("MAIL_FROM_NAME", SITE_NAME),
        )

    def validate(self):
        try:
            url = urlsplit(self.base_url)
            url.port
        except ValueError as exc:
            raise RuntimeError("APP_BASE_URL must have a valid host and port.") from exc
        if self.environment not in {"development", "production"}:
            raise RuntimeError("ENVIRONMENT must be development or production.")
        if (
            url.scheme not in {"http", "https"}
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
            or url.path not in {"", "/"}
            or any(c.isspace() for c in self.base_url)
        ):
            raise RuntimeError(
                "APP_BASE_URL must be an absolute HTTP(S) origin without credentials, path or query."
            )
        if self.backend not in {"smtp", "file"}:
            raise RuntimeError("MAIL_BACKEND must be smtp or file.")
        if any(c in self.from_address + self.from_name for c in "\r\n") or not re.fullmatch(
            r"[^\s@<>]+@[^\s@<>]+", self.from_address
        ):
            raise RuntimeError("Configure a valid mail sender.")
        if self.backend == "smtp" and (
            not self.host
            or not 1 <= self.port <= 65535
            or bool(self.username) != bool(self.password)
        ):
            raise RuntimeError(
                "SMTP requires a host, valid port and paired username/password settings."
            )
        if self.environment == "production":
            import ipaddress

            try:
                local = not ipaddress.ip_address(url.hostname).is_global
            except ValueError:
                local = (
                    url.hostname == "localhost"
                    or url.hostname.endswith((".localhost", ".local"))
                    or "." not in url.hostname
                )
            if len(os.getenv("SECRET_KEY", "")) < 32:
                raise RuntimeError(
                    "Production requires a persistent SECRET_KEY of at least 32 characters."
                )
            if url.scheme != "https" or local:
                raise RuntimeError("Production APP_BASE_URL must use HTTPS and a non-local host.")
            if (
                self.backend != "smtp"
                or not self.use_tls
                or self.from_address.endswith("@localhost")
            ):
                raise RuntimeError(
                    "Production requires configured SMTP with TLS and a real sender address."
                )


class Mailer:
    def __init__(self, settings):
        self.settings = settings

    def send(self, recipient, subject, body):
        message = EmailMessage()
        message["From"] = formataddr((self.settings.from_name, self.settings.from_address))
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(body)
        if self.settings.backend == "file":
            directory = self.settings.directory
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            directory.chmod(0o700)
            path = directory / f"{uuid4().hex}.eml"
            with os.fdopen(
                os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb"
            ) as stream:
                stream.write(message.as_bytes())
            return
        with smtplib.SMTP(self.settings.host, self.settings.port, timeout=10) as smtp:
            smtp.ehlo()
            if self.settings.use_tls:
                smtp.starttls(context=ssl.create_default_context())
                smtp.ehlo()
            if self.settings.username:
                smtp.login(self.settings.username, self.settings.password)
            smtp.send_message(message)


def get_mailer():
    return Mailer(MailSettings.from_env())


def deliver(mailer, recipient, subject, body):
    try:
        mailer.send(recipient, subject, body)
    except Exception:
        # SMTP exception text can include message contents or server credentials.
        logging.getLogger(__name__).error(
            "Account mail delivery failed. Check mail configuration and transport."
        )
