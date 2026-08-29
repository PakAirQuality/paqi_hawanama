"""
Security dependencies for the API.
"""

import secrets
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

# Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def verify_tasks_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Verify that the request has a valid authorization token for tasks endpoints.
    
    This protects tasks endpoints from unauthorized access while allowing
    Google Cloud Scheduler to invoke them with proper OIDC tokens.
    """
    # Check if this is a Cloud Scheduler request first
    is_scheduler = await verify_cloud_scheduler_request(request)
    
    if is_scheduler:
        # For Cloud Scheduler, we trust the OIDC token validation done by Cloud Run
        return True
    
    # For non-scheduler requests, require authorization token
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Require TASKS_API_SECRET to be configured
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


async def verify_cloud_scheduler_request(request: Request):
    """
    Verify Cloud Scheduler requests.

    Cloud Run validates the OIDC token before the request reaches
    application code, so if the scheduler headers are present AND
    an Authorization bearer token is included, we can trust the
    request. Without a bearer token the headers alone are spoofable.
    """
    user_agent = request.headers.get("user-agent", "")
    x_cloudscheduler = request.headers.get("x-cloudscheduler", "")

    has_scheduler_headers = (
        "Google-Cloud-Scheduler" in user_agent or bool(x_cloudscheduler)
    )

    # Only trust scheduler headers when an OIDC bearer token is also
    # present (Cloud Run validates it before our code runs).
    auth_header = request.headers.get("authorization", "")
    has_bearer = auth_header.lower().startswith("bearer ")

    if has_scheduler_headers and has_bearer:
        return True

    return False


async def verify_twitter_endpoint_access(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    """
    Combined security check for Twitter automation endpoint.
    Allows both Cloud Scheduler (OIDC) and manual access with secret.
    """
    # Check if this is a Cloud Scheduler request
    is_scheduler = await verify_cloud_scheduler_request(request)
    
    if is_scheduler:
        # For Cloud Scheduler, we trust the OIDC token validation done by Cloud Run
        return True
    
    # For non-scheduler requests, verify the authorization token
    await verify_tasks_token(credentials)
    return True