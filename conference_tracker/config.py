"""Configuration loading.

Settings come from (in order of precedence): explicit constructor args,
environment variables, then a YAML config file. Secrets (passwords, API keys)
should live in environment variables / a local .env, never in the YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - yaml is a listed dependency
    yaml = None


@dataclass
class MailboxConfig:
    host: str = ""
    port: int = 993
    username: str = ""
    password: str = ""
    folder: str = "INBOX"
    # When True, fetch only UNSEEN messages and mark them seen after processing.
    # When False, fetch all messages in the folder (useful for a first run).
    unseen_only: bool = True
    use_ssl: bool = True


@dataclass
class Config:
    gemini_api_key: str = ""
    model: str = "gemini-2.5-flash"
    csv_path: str = "conferences.csv"
    # GA4 Measurement ID (e.g. "G-XXXXXXXXXX"). Public by design — when set, the
    # generated page loads Google Analytics and reports per-conference clicks.
    ga_measurement_id: str = ""
    mailbox: MailboxConfig = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.mailbox is None:
            self.mailbox = MailboxConfig()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from a YAML file (optional) overlaid with env vars."""
    data: dict = {}
    if path and os.path.exists(path):
        if yaml is None:
            raise RuntimeError("PyYAML is required to read a config file.")
        with open(path, "r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}

    mailbox_data = data.get("mailbox", {}) or {}
    mailbox = MailboxConfig(
        host=_env("CT_MAIL_HOST", mailbox_data.get("host", "")),
        port=int(_env("CT_MAIL_PORT", str(mailbox_data.get("port", 993)))),
        username=_env("CT_MAIL_USER", mailbox_data.get("username", "")),
        password=_env("CT_MAIL_PASSWORD", mailbox_data.get("password", "")),
        folder=_env("CT_MAIL_FOLDER", mailbox_data.get("folder", "INBOX")),
        unseen_only=str(
            _env("CT_MAIL_UNSEEN_ONLY", str(mailbox_data.get("unseen_only", True)))
        ).lower()
        not in ("0", "false", "no"),
        use_ssl=str(
            _env("CT_MAIL_USE_SSL", str(mailbox_data.get("use_ssl", True)))
        ).lower()
        not in ("0", "false", "no"),
    )

    return Config(
        # Accept GEMINI_API_KEY or GOOGLE_API_KEY (the SDK reads either, too).
        gemini_api_key=_env(
            "GEMINI_API_KEY",
            _env("GOOGLE_API_KEY", data.get("gemini_api_key", "")),
        ),
        model=_env("CT_MODEL", data.get("model", "gemini-2.5-flash")),
        csv_path=_env("CT_CSV_PATH", data.get("csv_path", "conferences.csv")),
        ga_measurement_id=_env(
            "CT_GA_MEASUREMENT_ID", data.get("ga_measurement_id", "")
        ),
        mailbox=mailbox,
    )
