"""
Security dependencies for the API.

Two credentials exist:

* ``TASKS_API_SECRET`` — a shared bearer for operator actions (ingest, publish, bot,
  pipeline jobs). Only Cloud Scheduler (via OIDC, below) and operators hold it; it is
  never shipped to a browser.
* Cloud Scheduler OIDC — on the ingest role, a request is trusted when its bearer is a
  Google-signed ID token for ``settings.SCHEDULER_SERVICE_ACCOUNT`` with the ingest
  service URL as audience. Cloud Run IAM already rejects anything else before it reaches
  us, but verifying here means a different principal with run.invoker, or a forged
  ``X-CloudScheduler`` header, still cannot pass as the scheduler.
"""

import logging
import os
import secrets
import threading
import time
from typing import Optional

import httpx
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.concurrency import run_in_threadpool

from app.core.config import settings

logger = logging.getLogger(__name__)

# Bearer token security scheme
security = HTTPBearer(auto_error=False)

_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v1/certs"
_GOOGLE_ISSUERS = {"https://accounts.google.com", "accounts.google.com"}
_certs_cache: dict = {"certs": None, "fetched_at": 0.0}
_certs_lock = threading.Lock()
_CERTS_TTL_S = 6 * 3600


def _google_certs() -> dict:
    """Google's current OAuth2 signing certificates (PEM by key id), cached for 6 h."""
    now = time.monotonic()
    with _certs_lock:
        if _certs_cache["certs"] is not None and now - _certs_cache["fetched_at"] < _CERTS_TTL_S:
            return _certs_cache["certs"]
    resp = httpx.get(_GOOGLE_CERTS_URL, timeout=10.0)
    resp.raise_for_status()
    certs = resp.json()
    with _certs_lock:
        _certs_cache.update(certs=certs, fetched_at=now)
    return certs


def _verify_google_id_token(token: str, audience: str) -> Optional[dict]:
    """Return the claims of a valid Google ID token for ``audience``, else None."""
    from google.auth import jwt

    try:
        claims = jwt.decode(token, certs=_google_certs(), verify=True, audience=audience)
    except Exception as exc:  # bad signature, expired, wrong audience, malformed
        logger.debug("ID token rejected: %s", type(exc).__name__)
        return None
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        return None
    return claims


async def verify_cloud_scheduler_request(request: Request) -> bool:
    """True only for a verified Cloud Scheduler OIDC token on the ingest role."""
    if os.environ.get("INGEST_ROLE", "").lower() != "true":
        return False
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        return False
    token = auth_header[7:].strip()
    # A Google ID token is a 3-part JWT; the shared operator secret is not. Skip the
    # network round-trip for anything that cannot be an ID token.
    if token.count(".") != 2:
        return False
    try:
        claims = await run_in_threadpool(_verify_google_id_token, token, settings.INGEST_BASE_URL)
    except Exception as exc:  # cert fetch failed: fail closed, the scheduler retries
        logger.warning("Could not verify scheduler token (%s); rejecting", type(exc).__name__)
        return False
    if not claims:
        return False
    if claims.get("email") != settings.SCHEDULER_SERVICE_ACCOUNT or not claims.get("email_verified", False):
        logger.warning("Scheduler token for unexpected principal rejected")
        return False
    return True


async def verify_tasks_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Verify that the request may call an operator/task endpoint: either a verified
    Cloud Scheduler OIDC token (ingest role) or the TASKS_API_SECRET bearer.
    """
    if await verify_cloud_scheduler_request(request):
        return True

    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token = credentials.credentials

    if not settings.TASKS_API_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Task authentication not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(token, settings.TASKS_API_SECRET):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


async def verify_bam_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Verify the bearer token used by SFL's central system to push BAM readings.

    Unlike verify_tasks_token there is no Cloud Scheduler / OIDC branch: this
    endpoint is reached by an external third party over public HTTPS and is
    guarded solely by the shared BAM_INGEST_TOKEN.
    """
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.BAM_INGEST_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="BAM ingest authentication not configured",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not secrets.compare_digest(credentials.credentials, settings.BAM_INGEST_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="Invalid authorization token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


async def verify_twitter_endpoint_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """Scheduler OIDC or TASKS_API_SECRET, same as verify_tasks_token."""
    await verify_tasks_token(request, credentials)
    return True
