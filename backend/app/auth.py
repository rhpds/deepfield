"""API authentication for DeepField endpoints.

Two auth methods:
1. API key via X-API-Key header (service-to-service)
2. OAuth proxy forwarded user via X-Forwarded-User header (browser SSO)

When DEEPFIELD_API_KEY is not set, auth is disabled (local dev).
X-Forwarded-User is only trusted from TRUSTED_PROXY_HOSTS.
"""

import os
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

DEEPFIELD_API_KEY = os.environ.get("DEEPFIELD_API_KEY", "")
INTEGRATION_API_KEY = os.environ.get("INTEGRATION_API_KEY", "")
TRUSTED_PROXY_HOSTS = set(
    h.strip()
    for h in os.environ.get("TRUSTED_PROXY_HOSTS", "127.0.0.1,::1").split(",")
    if h.strip()
)

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(request: Request = None, api_key: str = Security(_api_key_header)):
    if not DEEPFIELD_API_KEY:
        return
    if api_key and api_key == DEEPFIELD_API_KEY:
        return
    if api_key and INTEGRATION_API_KEY and api_key == INTEGRATION_API_KEY:
        return
    if request and request.headers.get("X-Forwarded-User"):
        client_host = getattr(getattr(request, "client", None), "host", None)
        if client_host and client_host in TRUSTED_PROXY_HOSTS:
            return
    raise HTTPException(status_code=403, detail="Authentication required")


def require_write_access(request: Request = None, api_key: str = Security(_api_key_header)):
    """Stricter auth for mutating endpoints — same checks as require_api_key."""
    require_api_key(request, api_key)
