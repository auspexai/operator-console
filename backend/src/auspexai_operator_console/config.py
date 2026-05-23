"""Runtime configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class OperatorConsoleConfig:
    """Loaded configuration. Env-only for now; no TOML file (everything
    interesting is either compile-time-default or sensitive secret from
    the deployment environment)."""

    coord_url: str
    coord_bearer: str | None  # None = backend can't talk to coord (read-only deploy)
    bind_host: str
    bind_port: int
    static_dir: Path
    session_secret: str  # Signed-cookie secret. MUST be set; no default.

    @classmethod
    def from_env(cls) -> OperatorConsoleConfig:
        session_secret = os.environ.get("SESSION_SECRET", "").strip()
        if not session_secret:
            raise RuntimeError(
                "SESSION_SECRET env var is required (signs the operator-console's "
                "session cookies). Generate one with: python3 -c 'import secrets; "
                "print(secrets.token_urlsafe(64))'"
            )
        return cls(
            coord_url=os.environ.get("COORD_URL", "http://127.0.0.1:4226"),
            coord_bearer=os.environ.get("MAINTAINER_TOKEN") or None,
            bind_host=os.environ.get("HOST", "127.0.0.1"),
            bind_port=int(os.environ.get("PORT", "4227")),
            static_dir=Path(
                os.environ.get(
                    "STATIC_DIR",
                    str(Path(__file__).parent / "static"),
                )
            ),
            session_secret=session_secret,
        )
