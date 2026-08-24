"""Filesystem layout and persisted configuration."""

from __future__ import annotations

import json
import os
from pathlib import Path

APP_NAME = "yoto-iconer"

AUTH_BASE = "https://login.yotoplay.com"
API_BASE = "https://api.yotoplay.com"
AUDIENCE = "https://api.yotoplay.com"

CALLBACK_PORT = 8787
CALLBACK_PATH = "/callback"
REDIRECT_URI = f"http://127.0.0.1:{CALLBACK_PORT}{CALLBACK_PATH}"

# The docs say user:content:manage implies user:content:view, but the API
# checks the literal scope string on the token, so ask for both explicitly.
SCOPES = "user:content:manage user:content:view user:icons:manage offline_access"


def home() -> Path:
    """Root of all persisted state. Overridable for tests via YOTO_ICONER_HOME."""
    override = os.environ.get("YOTO_ICONER_HOME")
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / APP_NAME


def config_path() -> Path:
    return home() / "config.json"


def tokens_path() -> Path:
    return home() / "tokens.json"


def catalog_path() -> Path:
    return home() / "catalog.sqlite"


def backups_dir() -> Path:
    return home() / "backups"


def cache_dir() -> Path:
    return home() / "cache"


def ensure_home() -> Path:
    d = home()
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_config() -> dict:
    p = config_path()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text())
    except json.JSONDecodeError:
        return {}


def save_config(cfg: dict) -> None:
    ensure_home()
    config_path().write_text(json.dumps(cfg, indent=2) + "\n")


def client_id() -> str | None:
    """Client id from the environment, falling back to config.json."""
    return os.environ.get("YOTO_CLIENT_ID") or load_config().get("client_id")
