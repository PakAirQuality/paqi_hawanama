"""OpenAQ tests reuse the ingestion test environment (dummy settings, repo paths)."""

from tests.ingestion.conftest import *  # noqa: F401,F403  (sets POSTGRES_* dummies, repo_root/api_root/schema_dump)
