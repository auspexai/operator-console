"""GitHub OAuth Device Flow + session + Maintainer-roster gate.

O-M2 minimum shipped 2026-05-23. O-M2-tail (2026-05-24) adds:
  - Defense #3: Sigstore-verified roster (optional, toggle via config)
  - Defense #5: 24h cooldown for new Maintainers (active_from check)
  - Defense #6: rage-shell secondary factor (IP allowlist + local passphrase)
  - Trusted-proxy coordinator auth (service token + X-Maintainer-Login)

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
       enforces cooldown (#5) and rage-shell factor (#6), and if all
       pass, sets a session cookie.

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
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address, ip_network
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request, status

GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
GITHUB_USER_URL = "https://api.github.com/user"
ROSTER_URL = (
    "https://raw.githubusercontent.com/auspexai/.github/main/security/active_maintainers.json"
)

GITHUB_OAUTH_CLIENT_ID = "Ov23lierutLLeF9skyHu"

ROSTER_CACHE_SECONDS = 300  # 5 minutes

logger = logging.getLogger(__name__)


class _RosterCache:
    """In-process cache for the Maintainer roster. 5-minute TTL.

    Stores full entry dicts (not just logins) so the cooldown check can
    read active_from timestamps.
    """

    def __init__(self) -> None:
        self._cached_entries: list[dict[str, Any]] | None = None
        self._fetched_at: float = 0.0

    async def get_entries(self) -> list[dict[str, Any]]:
        import time

        now = time.monotonic()
        if self._cached_entries is not None and (now - self._fetched_at) < ROSTER_CACHE_SECONDS:
            return self._cached_entries
        async with httpx.AsyncClient(timeout=5.0) as client:
            r = await client.get(ROSTER_URL)
            r.raise_for_status()
            data = r.json()
        entries = data.get("active", [])
        self._cached_entries = entries
        self._fetched_at = now
        logins = {e["github_login"] for e in entries}
        logger.info("roster refreshed; active Maintainers: %s", sorted(logins))
        return entries

    async def get_active_logins(self) -> set[str]:
        entries = await self.get_entries()
        return {e["github_login"] for e in entries}

    async def get_entry(self, login: str) -> dict[str, Any] | None:
        entries = await self.get_entries()
        for e in entries:
            if e["github_login"] == login:
                return e
        return None


_roster = _RosterCache()


def _check_cooldown(entry: dict[str, Any], cooldown_hours: int) -> str | None:
    """Returns an error message if the Maintainer is still in cooldown, else None."""
    active_from_str = entry.get("active_from")
    if not active_from_str:
        return None
    try:
        active_from = datetime.fromisoformat(active_from_str)
        if active_from.tzinfo is None:
            active_from = active_from.replace(tzinfo=UTC)
    except ValueError:
        return None
    cutoff = datetime.now(UTC) - timedelta(hours=cooldown_hours)
    if active_from > cutoff:
        remaining = active_from + timedelta(hours=cooldown_hours) - datetime.now(UTC)
        hours_left = max(1, int(remaining.total_seconds() / 3600))
        return f"new Maintainer cooldown: ~{hours_left}h remaining (active_from={active_from_str})"
    return None


def _check_rage_shell_factor(
    request: Request,
    allowed_networks: list[str],
    passphrase_store: Any | None,
    session_passphrase: str | None,
) -> str | None:
    """Returns an error message if the rage-shell factor check fails, else None."""
    if not allowed_networks and passphrase_store is None:
        return None

    client_ip = (
        request.headers.get("CF-Connecting-IP") or request.client.host
        if request.client
        else "unknown"
    )
    for net in allowed_networks:
        try:
            if ip_address(client_ip) in ip_network(net, strict=False):
                return None
        except ValueError:
            if client_ip == net:
                return None

    if passphrase_store is not None and session_passphrase:
        from .passphrase_store import PassphraseStoreError, verify

        try:
            if verify(passphrase_store, session_passphrase):
                return None
        except PassphraseStoreError:
            logger.warning("rage-shell passphrase store not readable")

    return f"rage-shell factor required: IP {client_ip} not in allowed networks and no valid passphrase"


_SETUP_TOKEN_MAX_AGE = 300  # 5 minutes


def _make_setup_token(secret: str, github_login: str, github_user_id: int) -> str:
    from itsdangerous import URLSafeTimedSerializer

    s = URLSafeTimedSerializer(secret, salt="rage-shell-setup")
    return s.dumps({"github_login": github_login, "github_user_id": github_user_id})


def _verify_setup_token(secret: str, token: str) -> dict[str, Any] | None:
    from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

    s = URLSafeTimedSerializer(secret, salt="rage-shell-setup")
    try:
        return s.loads(token, max_age=_SETUP_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None


def build_router(config=None) -> APIRouter:
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
                detail={
                    "error": {"code": "github_device_code_failed", "github_status": r.status_code}
                },
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
            if err == "authorization_pending":
                return {"status": "pending", "github_error": err}
            if err == "slow_down":
                # GitHub rate-limited our polling. Per RFC 8628 §3.5, the
                # client MUST increase its polling interval; GitHub's
                # response includes the new minimum interval. Surface it
                # so the frontend can adjust its setInterval cadence.
                new_interval = int(token_body.get("interval", 10))
                return {
                    "status": "pending",
                    "github_error": err,
                    "next_interval_seconds": new_interval,
                }
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
        entry = await _roster.get_entry(github_login)
        if entry is None:
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

        # Defense #5: 24h cooldown for new Maintainers.
        if config is not None:
            cooldown_msg = _check_cooldown(entry, config.cooldown_hours)
            if cooldown_msg is not None:
                request.session.clear()
                logger.warning("auth: cooldown rejection for %r: %s", github_login, cooldown_msg)
                return {
                    "status": "denied",
                    "reason": "cooldown_active",
                    "detail": cooldown_msg,
                    "github_login": github_login,
                }

            # Defense #6: rage-shell secondary factor.
            from .passphrase_store import default_store

            pstore = default_store(encrypted_file_path=config.passphrase_store_path)
            rage_msg = _check_rage_shell_factor(
                request,
                config.allowed_networks,
                pstore,
                request.headers.get("X-Operator-Passphrase"),
            )
            if rage_msg is not None:
                request.session.clear()
                logger.warning(
                    "auth: rage-shell factor rejection for %r: %s", github_login, rage_msg
                )
                setup_token = _make_setup_token(
                    config.session_secret,
                    github_login,
                    github_user_id,
                )
                has_passphrase = pstore.has_passphrase()
                return {
                    "status": "denied",
                    "reason": "passphrase_setup_required"
                    if not has_passphrase
                    else "rage_shell_factor_required",
                    "detail": rage_msg,
                    "github_login": github_login,
                    "setup_token": setup_token,
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

    @router.post("/setup-passphrase")
    async def setup_passphrase(request: Request) -> dict[str, Any]:
        """Set or reset the operator passphrase. Requires a valid setup token
        from a successful GitHub OAuth + roster check."""
        from .passphrase_store import PassphraseStoreError, default_store

        body = await request.json()
        token = body.get("setup_token", "")
        passphrase = body.get("passphrase", "")
        confirm = body.get("confirm", "")

        if not token or not passphrase:
            raise HTTPException(status_code=400, detail="setup_token and passphrase required")
        if passphrase != confirm:
            raise HTTPException(status_code=400, detail="passphrases do not match")
        if len(passphrase) < 8:
            raise HTTPException(status_code=400, detail="passphrase must be at least 8 characters")

        payload = _verify_setup_token(config.session_secret, token)
        if payload is None:
            raise HTTPException(status_code=403, detail="invalid or expired setup token")

        github_login = payload["github_login"]
        github_user_id = payload["github_user_id"]

        pstore = default_store(encrypted_file_path=config.passphrase_store_path)
        try:
            pstore.store(passphrase)
        except PassphraseStoreError as exc:
            logger.error("setup-passphrase: store failed for %r: %s", github_login, exc)
            raise HTTPException(status_code=500, detail="failed to store passphrase") from exc

        logger.info(
            "auth: passphrase %s by %r", "reset" if pstore.has_passphrase() else "set", github_login
        )

        request.session["github_login"] = github_login
        request.session["github_user_id"] = github_user_id
        return {
            "status": "signed_in",
            "github_login": github_login,
            "github_user_id": github_user_id,
        }

    @router.post("/verify-passphrase")
    async def verify_passphrase(request: Request) -> dict[str, Any]:
        """Verify the operator passphrase using a setup token from a
        prior GitHub OAuth flow. Issues a session on success."""
        from .passphrase_store import PassphraseStoreError, default_store, verify

        body = await request.json()
        token = body.get("setup_token", "")
        passphrase = body.get("passphrase", "")

        if not token or not passphrase:
            raise HTTPException(status_code=400, detail="setup_token and passphrase required")

        payload = _verify_setup_token(config.session_secret, token)
        if payload is None:
            raise HTTPException(status_code=403, detail="invalid or expired setup token")

        pstore = default_store(encrypted_file_path=config.passphrase_store_path)
        try:
            if not verify(pstore, passphrase):
                raise HTTPException(status_code=403, detail="incorrect passphrase")
        except PassphraseStoreError as exc:
            logger.error("verify-passphrase: store error: %s", exc)
            raise HTTPException(status_code=500, detail="passphrase store error") from exc

        github_login = payload["github_login"]
        github_user_id = payload["github_user_id"]
        request.session["github_login"] = github_login
        request.session["github_user_id"] = github_user_id
        logger.info("auth: passphrase verified for %r", github_login)
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


def coord_headers(login: str, service_token: str | None) -> dict[str, str]:
    """Build headers for a trusted-proxy request to the coordinator.

    The operator console authenticates to the coordinator with a service
    token and passes the individual Maintainer's login via
    X-Maintainer-Login for per-maintainer audit attribution.
    """
    headers: dict[str, str] = {"X-Maintainer-Login": login}
    if service_token:
        headers["Authorization"] = f"Bearer {service_token}"
    return headers
