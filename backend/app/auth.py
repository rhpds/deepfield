"""API authentication for DeepField endpoints."""

import os
from fastapi import HTTPException, Request, Security
from fastapi.security import APIKeyHeader

DEEPFIELD_API_KEY = os.environ.get("DEEPFIELD_API_KEY", "")
_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(request: Request = None, api_key: str = Security(_api_key_header)):
    if api_key and DEEPFIELD_API_KEY and api_key == DEEPFIELD_API_KEY:
        return
    if request:
        if request.headers.get("sec-fetch-site") == "same-origin":
            return
        origin = request.headers.get("origin", "")
        if origin and "deepfield" in origin:
            return
    if not DEEPFIELD_API_KEY:
        return
    raise HTTPException(status_code=403, detail="Invalid or missing API key")
