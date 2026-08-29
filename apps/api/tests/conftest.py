"""Root pytest configuration for Hawanama API tests."""

import sys
from pathlib import Path

# Ensure the API package is importable without install
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Load .env from hawanama-main root so GEMINI_API_KEY (and other secrets)
# are available as env vars for live bench tests.
_env_file = Path(__file__).resolve().parent.parent.parent.parent / ".env"
if _env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(_env_file, override=False)
