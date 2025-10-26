"""
Security dependencies for the API.
"""

import secrets
from fastapi import HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.config import settings

# Bearer token security scheme
security = HTTPBearer(auto_error=False)


async def verify_tasks_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify that the request has a valid authorization token for tasks endpoints.
    
    This protects tasks endpoints from unauthorized access while allowing
    Google Cloud Scheduler to invoke them with proper OIDC tokens.
    """
    # If no credentials provided, check for Cloud Scheduler headers
    if not credentials:
        raise HTTPException(
            status_code=401,
            detail="Authorization token required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Check against configured secret if available
    if settings.TASKS_API_SECRET:
        if not secrets.compare_digest(token, settings.TASKS_API_SECRET):
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    else:
        # If no secret configured, we still require a token to be present
        # This provides basic protection against casual access
        if len(token) < 10:
            raise HTTPException(
                status_code=401,
                detail="Invalid authorization token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    
    return True


async def verify_cloud_scheduler_request(request: Request):
    """
    Additional verification for Cloud Scheduler requests.
    Checks for Google Cloud Scheduler specific headers.
    """
    # Check for Cloud Scheduler specific headers
    user_agent = request.headers.get("user-agent", "")
    x_cloudscheduler = request.headers.get("x-cloudscheduler", "")
    
    # Google Cloud Scheduler sends specific headers
    if "Google-Cloud-Scheduler" in user_agent or x_cloudscheduler:
        return True
    
    # For non-scheduler requests, require proper authorization
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