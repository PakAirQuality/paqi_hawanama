"""Run only the voice brief endpoint locally, for trying the Tracker's Listen button before a deploy.

The full API needs Postgres and the geospatial stack; this mounts just app/routers/voice.py.
Needs GEMINI_API_KEY in the environment. Point the dashboard at it with VOICE_DEV_API=http://localhost:8001
in apps/dashboard-frontend/.env.local, then:

    python scripts/voice_dev_server.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# Settings require database values even though this server never connects to one
for key in ("POSTGRES_SERVER", "POSTGRES_USER", "POSTGRES_PASSWORD", "POSTGRES_DB"):
    os.environ.setdefault(key, "unused")
os.environ.setdefault("POSTGRES_PORT", "5432")

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402

from app.routers import voice  # noqa: E402

app = FastAPI(title="Hawanama voice brief (local)")
app.include_router(voice.router, prefix="/api/v1")

if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        sys.exit("GEMINI_API_KEY is not set")
    here = Path(__file__).resolve().parent
    # Reloads when the voice code changes, so an edit is heard without restarting by hand
    uvicorn.run(
        "voice_dev_server:app",
        app_dir=str(here),
        host="127.0.0.1",
        port=int(os.environ.get("VOICE_PORT", "8001")),
        reload=True,
        reload_dirs=[str(here.parent / "app"), str(here)],
    )
