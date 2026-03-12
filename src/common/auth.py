"""
Authentication middleware for FastAPI.
"""
import hmac
from fastapi import Request, HTTPException
from src.common.config import API_KEY


async def require_api_key(request: Request):
    """Dependency: enforce Bearer token on API endpoints."""
    if not API_KEY:
        raise HTTPException(status_code=500, detail="Server misconfigured — API_KEY not set")

    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else ""

    if not token or not hmac.compare_digest(token, API_KEY):
        raise HTTPException(status_code=401, detail="Unauthorized")
