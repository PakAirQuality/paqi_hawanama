"""
Build/runtime provenance for the ingestion code path.

The audit found that the deployed image ran a *different* copy of the ingestion
tasks than the one checked in under apps/api (a Dockerfile COPY overlay pasted
apps/worker/tasks over app/tasks, and sys.modules aliases redirected imports).
This module makes that class of drift impossible to miss:

  * `describe()`        — which files actually back the task modules, plus the git SHA
  * `assert_canonical()` — raises if any legacy path/alias is present or a task
                           module is loaded from outside this package

The Dockerfile runs `assert_canonical(import_modules=False)` at build time (pure
file-system check, no settings needed) and start.sh runs the full check once
the app is importable.
"""

from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from typing import Dict, Optional

PROVENANCE = "hawanama.ingestion.canonical.v1"
GIT_SHA = os.getenv("HAWANAMA_GIT_SHA", "unknown")

# .../apps/api/app/ingestion
CANONICAL_ROOT = Path(__file__).resolve().parent
# .../apps/api/app
APP_ROOT = CANONICAL_ROOT.parent

# Module paths whose files must live under app/ingestion or app/services/ingestion.
_TASK_MODULES = (
    "app.ingestion.tasks.data_ingestion",
    "app.ingestion.tasks.city_ingest",
    "app.ingestion.tasks.station_discovery",
    "app.ingestion.db",
    "app.ingestion.manifests",
    "app.services.ingestion.iqair_service",
)

# sys.modules names the old worker_compat shim used to register.
_LEGACY_ALIASES = (
    "config",
    "config.settings",
    "services",
    "services.iqair_client",
    "services.database",
    "manifest_utils",
)

# Paths (relative to app/) that must not exist in a canonical checkout/image.
_LEGACY_PATHS = (
    "tasks",
    "worker_compat.py",
    "worker_services",
    "worker_config",
    "manifest_utils.py",
)


def _allowed_roots() -> tuple[Path, ...]:
    return (CANONICAL_ROOT, APP_ROOT / "services" / "ingestion")


def describe(import_modules: bool = True) -> Dict[str, Optional[str]]:
    """Return a JSON-safe description of where the ingestion code comes from."""
    out: Dict[str, Optional[str]] = {
        "provenance": PROVENANCE,
        "git_sha": GIT_SHA,
        "canonical_root": str(CANONICAL_ROOT),
    }
    if not import_modules:
        return out
    for name in _TASK_MODULES:
        try:
            mod = importlib.import_module(name)
            out[name] = getattr(mod, "__file__", None)
        except Exception as exc:  # pragma: no cover - surfaced by assert_canonical
            out[name] = f"IMPORT_ERROR: {type(exc).__name__}: {exc}"
    return out


def assert_canonical(strict: bool = True, import_modules: bool = True) -> None:
    """
    Raise RuntimeError if the ingestion code path is not the canonical one.

    strict=True also fails when any legacy path still exists on disk.
    import_modules=False skips importing the task modules (used at Docker build
    time where Settings() cannot be constructed).
    """
    problems = []

    if strict:
        for rel in _LEGACY_PATHS:
            p = APP_ROOT / rel
            if p.exists():
                problems.append(f"legacy path present: {p}")

    present_aliases = [a for a in _LEGACY_ALIASES if a in sys.modules]
    if present_aliases:
        problems.append(f"legacy sys.modules aliases present: {present_aliases}")

    if import_modules:
        roots = _allowed_roots()
        for name in _TASK_MODULES:
            try:
                mod = importlib.import_module(name)
            except Exception as exc:
                problems.append(f"cannot import {name}: {type(exc).__name__}: {exc}")
                continue
            file = getattr(mod, "__file__", None)
            if not file:
                problems.append(f"{name} has no __file__")
                continue
            fp = Path(file).resolve()
            if not any(root == fp or root in fp.parents for root in roots):
                problems.append(f"{name} loaded from non-canonical path {fp}")

    if problems:
        raise RuntimeError("Ingestion provenance check failed:\n  - " + "\n  - ".join(problems))
