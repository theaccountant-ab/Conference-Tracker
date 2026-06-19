"""Configuration for the publication analyzer.

Independent of the tracker's config. Settings come from (in order of
precedence): environment variables, then an optional YAML file. The Gemini API
key should live in the environment / a local .env, never in committed YAML.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import yaml  # type: ignore
except ImportError:  # pragma: no cover - yaml is a listed dependency
    yaml = None


@dataclass
class Config:
    gemini_api_key: str = ""
    model: str = "gemini-2.5-flash"
    # Journals counted as "top-tier". Empty means "let the model judge by
    # reputation". When None is passed downstream, a finance/econ leaning
    # default set is used (see analysis.DEFAULT_TOP_TIER_JOURNALS).
    top_tier_journals: List[str] = field(default_factory=list)


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

    return Config(
        # Accept GEMINI_API_KEY or GOOGLE_API_KEY (the SDK reads either, too).
        gemini_api_key=_env(
            "GEMINI_API_KEY",
            _env("GOOGLE_API_KEY", data.get("gemini_api_key", "")),
        ),
        model=_env("PA_MODEL", data.get("model", "gemini-2.5-flash")),
        top_tier_journals=list(data.get("top_tier_journals", []) or []),
    )
