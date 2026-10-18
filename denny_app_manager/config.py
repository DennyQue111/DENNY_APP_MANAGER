from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECTS_ROOT = PACKAGE_ROOT.parent.parent
APPS_CONFIG_PATH = PACKAGE_ROOT.parent / "apps.json"
LOCAL_ENV_PATH = PACKAGE_ROOT.parent / ".env"


def load_local_settings() -> dict[str, str]:
    settings = {}
    if not LOCAL_ENV_PATH.is_file():
        return settings
    for raw_line in LOCAL_ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip().strip("\"'")
        if key.strip():
            settings[key.strip()] = value
    return settings


def load_apps() -> list[dict]:
    data = json.loads(APPS_CONFIG_PATH.read_text(encoding="utf-8"))
    apps = data.get("apps")
    if not isinstance(apps, list):
        raise ValueError("apps.json must contain an 'apps' list")
    return apps
