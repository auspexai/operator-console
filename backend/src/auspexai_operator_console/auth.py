"""GitHub OAuth Device Flow + session + Maintainer-roster gate.

O-M2 minimum (signature verification of active_maintainers.json is
deferred to a later milestone; for now we trust the raw fetched JSON
because it's served from a GitHub URL we control + protected by
branch-protection rules per the threat model doc).

Flow:

  1. POST /api/v0/auth/login
     - Calls GitHub Device Flow start (https://github.com/login/device/code).
     - Returns user_code + verification_uri + device_code (opaque) for
       the frontend to display + poll.

  2. GET /api/v0/auth/poll?device_code=<x>
     - Calls GitHub token endpoint with the device_code.
     - If still pending: returns {"status": "pending"}.
     - If complete: exchanges the access token for user identity (via
       /user), checks the github_login against active_maintainers.json,
       and if the user is an active Maintainer, sets a session cookie.
     - On non-Maintainer login: returns {"status": "denied"} + clears
       any existing session.

  3. GET /api/v0/auth/whoami
     - Returns the current session info if signed in.
     - Returns {"signed_in": false} if not.

  4. POST /api/v0/auth/logout
     - Clears the session cookie.

The session cookie is signed by starlette.middleware.sessions (itsdangerous-
backed). The SESSION_SECRET env var must be set; otherwise the app refuses
to start (fail-fast).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
ROSTER_URL = (
    "https://raw.githubusercontent.com/auspexai/.github/main/security/active_maintainers.json"
)

# Public-by-design per auspexai_github_oauth_app.md; same Client ID as worker.
GITHUB_OAUTH_CLIENT_ID = "Ov23lierutLLeF9skyHu"

ROSTER_CACHE_SECONDS = 300  # 5 minutes

logger = logging.getLogger(__name__)


class _RosterCache:
    """Tiny in-process cache for the Maintainer roster. 5-minute TTL."""

    def __init__(self) -> None:
        self._cached_logins: set[str] | None = None
        self._fetched_at: float = 0.0

    async def get_active_logins(self) -> set[str]:
        import time

        now = time.monotonic()
        if self._cached_logins is not None and (now - self._fetched_at) < ROSTER_CACHE_SECONDS:
            return self._cached_logins
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(ROSTER_URL)
            r.raise_for_status()
            data = r.json()
        logins = {entry["github_login"] for entry in data.get("active", [])}
        self._cached_logins = logins
        self._fetched_at = now
        logger.info("roster refreshed; active Maintainers: %s", sorted(logins))
        return logins


_roster = _RosterCache()


def build_router() -> APIRouter:
    router = APIRouter(prefix="/api/v0/auth", tags=["auth"])

    @router.post("/login")
    async def login() -> dict[str, Any]:
        """Initiate GitHub OAuth Device Flow. Returns the user-code + URL
        for the frontend to display and the device-code for polling."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(
                GITHUB_DEVICE_CODE_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_OAUTH_CLIENT_ID,
                    "scope": "read:user",
                },
            )
        if r.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": {"code": "github_device_code_failed", "github_status": r.status_code}},
            )
        body = r.json()
        return {
            "user_code": body["user_code"],
            "verification_uri": body["verification_uri"],
            "device_code": body["device_code"],
            "interval_seconds": body.get("interval", 5),
            "expires_in": body.get("expires_in", 900),
        }

    @router.get("/poll")
    async def poll(request: Request, device_code: str) -> dict[str, Any]:
        """Poll GitHub for device-flow completion. On success, sets the
        session cookie and returns {"status": "signed_in", "login": ...}."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            token_r = await client.post(
                GITHUB_TOKEN_URL,
                headers={"Accept": "application/json"},
                data={
                    "client_id": GITHUB_OAUTH_CLIENT_ID,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        token_body = token_r.json()
        if "error" in token_body:
            err = token_body["error"]
            # Pending states per RFC 8628:
            if err in ("authorization_pending", "slow_down"):
                return {"status": "pending", "github_error": err}
            if err == "expired_token":
                return {"status": "expired"}
            if err == "access_denied":
                return {"status": "denied", "reason": "user_declined_at_github"}
            return {"status": "error", "github_error": err}

        access_token = token_body["access_token"]

        # Resolve GitHub identity.
        async with httpx.AsyncClient(timeout=10.0) as client:
            user_r = await client.get(
                GITHUB_USER_URL,
                headers={
                    "Accept": "application/vnd.github+json",
                    "Authorization": f"Bearer {access_token}",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
            )
        if user_r.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": {"code": "github_user_lookup_failed"}},
            )
        user = user_r.json()
        github_login = user.get("login")
        github_user_id = user.get("id")
        if not github_login:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={"error": {"code": "github_user_missing_login"}},
            )

        # Roster check.
        active_logins = await _roster.get_active_logins()
        if github_login not in active_logins:
            # Clear any prior session.
            request.session.clear()
            logger.warning(
                "auth: rejected login for github_login=%r (not in active_maintainers.json)",
                github_login,
            )
            return {
                "status": "denied",
                "reason": "not_in_active_maintainers",
                "github_login": github_login,
            }

        # Issue session.
        request.session["github_login"] = github_login
        request.session["github_user_id"] = github_user_id
        logger.info("auth: session issued for github_login=%r", github_login)
        return {
            "status": "signed_in",
            "github_login": github_login,
            "github_user_id": github_user_id,
        }

    @router.get("/whoami")
    async def whoami(request: Request) -> dict[str, Any]:
        login = request.session.get("github_login")
        if not login:
            return {"signed_in": False}
        return {
            "signed_in": True,
            "github_login": login,
            "github_user_id": request.session.get("github_user_id"),
        }

    @router.post("/logout")
    async def logout(request: Request) -> dict[str, Any]:
        request.session.clear()
        return {"status": "signed_out"}

    return router


def require_session(request: Request) -> str:
    """FastAPI dependency: 401 if no signed-in session; returns the
    github_login otherwise."""
    login = request.session.get("github_login")
    if not login:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": {"code": "not_signed_in"}},
        )
    return login
