from __future__ import annotations

import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECTS_ROOT = PACKAGE_ROOT.parent.parent
APPS_CONFIG_PATH = PACKAGE_ROOT.parent / "apps.json"


def load_apps() -> list[dict]:
    data = json.loads(APPS_CONFIG_PATH.read_text(encoding="utf-8"))
    apps = data.get("apps")
    if not isinstance(apps, list):
        raise ValueError("apps.json must contain an 'apps' list")
    return apps
