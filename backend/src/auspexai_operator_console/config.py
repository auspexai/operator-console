"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OperatorConsoleConfig:
    """Loaded configuration. Env-only for now; no TOML file (everything
    interesting is either compile-time-default or sensitive secret from
    the deployment environment).

    O-M2-tail (2026-05-24): added cooldown, rage-shell factor, Sigstore
    verification toggle, and trusted-proxy service token.
    """

    coord_url: str
    coord_service_token: str | None  # trusted-proxy service token (replaces MAINTAINER_TOKEN)
    bind_host: str
    bind_port: int
    static_dir: Path
    session_secret: str
    cooldown_hours: int  # defense #5: reject logins for Maintainers added < N hours ago
    allowed_networks: list[str]  # defense #6: IP prefixes that skip the local passphrase
    passphrase_store_path: Path  # defense #6: encrypted-file backend path for operator passphrase
    verify_roster_signature: bool  # defense #3: require Sigstore signature on roster

    @classmethod
    def from_env(cls) -> OperatorConsoleConfig:
        session_secret = os.environ.get("SESSION_SECRET", "").strip()
        if not session_secret:
            raise RuntimeError(
                "SESSION_SECRET env var is required (signs the operator-console's "
                "session cookies). Generate one with: python3 -c 'import secrets; "
                "print(secrets.token_urlsafe(64))'"
            )
        allowed_raw = os.environ.get("ALLOWED_NETWORKS", "127.0.0.1,::1")
        passphrase_store_path = os.environ.get(
            "PASSPHRASE_STORE_PATH",
            "/var/lib/auspexai-operator-console/passphrase.enc",
        )
        return cls(
            coord_url=os.environ.get("COORD_URL", "http://127.0.0.1:4226"),
            coord_service_token=os.environ.get("COORDINATOR_SERVICE_TOKEN")
            or os.environ.get("MAINTAINER_TOKEN")
            or None,
            bind_host=os.environ.get("HOST", "127.0.0.1"),
            bind_port=int(os.environ.get("PORT", "4227")),
            static_dir=Path(
                os.environ.get(
                    "STATIC_DIR",
                    str(Path(__file__).parent / "static"),
                )
            ),
            session_secret=session_secret,
            cooldown_hours=int(os.environ.get("COOLDOWN_HOURS", "24")),
            allowed_networks=[n.strip() for n in allowed_raw.split(",") if n.strip()],
            passphrase_store_path=Path(passphrase_store_path),
            verify_roster_signature=os.environ.get("VERIFY_ROSTER_SIGNATURE", "false").lower()
            in ("1", "true", "yes"),
        )
