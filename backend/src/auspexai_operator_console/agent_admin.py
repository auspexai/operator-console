"""Assessment-agent admin surface (§9 #46).

The auto-draft agent is RAGE-LOCAL ops tooling (systemd timer + env file),
not a coordinator resource — and the console backend runs on the same box,
so this is a direct local read/write surface, session-gated like every
proxied action. Deliberately narrow:

  GET  /api/v0/agent/assessment       — config + timer state (the API key is
                                        reported as a BOOLEAN only, never
                                        echoed).
  POST /api/v0/agent/assessment/cap   — set ASSESSMENT_MAX_DRAFTS_PER_TICK
                                        (the per-tick spend bound).

On a host without the agent installed (env file absent), GET reports
installed=false and POST 409s — the console degrades, it doesn't break.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from .auth import require_session
from .config import OperatorConsoleConfig

DEFAULT_ENV_PATH = "/etc/auspexai/assessment-agent.env"
TIMER_UNIT = "auspexai-assessment-agent.timer"
SERVICE_UNIT = "auspexai-assessment-agent.service"


class CapUpdate(BaseModel):
    max_drafts_per_tick: int = Field(ge=0, le=100)


def _env_path() -> Path:
    return Path(os.environ.get("ASSESSMENT_AGENT_ENV", DEFAULT_ENV_PATH))


def _parse_env(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        out[k.strip()] = v.strip()
    return out


def _systemd_state(unit: str) -> dict[str, str]:
    """Read-only unit state via systemctl show (unprivileged-safe);
    best-effort — an error degrades to 'unknown'."""
    try:
        raw = subprocess.run(
            [
                "systemctl",
                "show",
                unit,
                "--property=ActiveState,SubState,NextElapseUSecRealtime,ExecMainStatus",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        return dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    except Exception:
        return {}


def build_router(config: OperatorConsoleConfig) -> APIRouter:
    router = APIRouter(prefix="/api/v0/agent")

    @router.get("/assessment")
    async def assessment_status(request: Request) -> dict[str, Any]:
        require_session(request)
        path = _env_path()
        if not path.is_file():
            return {"installed": False}
        env = _parse_env(path.read_text(encoding="utf-8"))
        timer = _systemd_state(TIMER_UNIT)
        service = _systemd_state(SERVICE_UNIT)
        return {
            "installed": True,
            "model": env.get("ASSESSMENT_MODEL", "claude-opus-4-8"),
            # NEVER echo the key — presence only.
            "api_key_present": bool(env.get("ANTHROPIC_API_KEY")),
            "max_drafts_per_tick": int(env.get("ASSESSMENT_MAX_DRAFTS_PER_TICK", "5") or 5),
            "timer_active": timer.get("ActiveState") == "active",
            "timer_next": timer.get("NextElapseUSecRealtime") or None,
            "last_run_exit": service.get("ExecMainStatus") or None,
        }

    @router.post("/assessment/cap")
    async def set_cap(request: Request, body: CapUpdate) -> dict[str, Any]:
        require_session(request)
        path = _env_path()
        if not path.is_file():
            raise HTTPException(
                status_code=409, detail="assessment agent not installed on this host"
            )
        text = path.read_text(encoding="utf-8")
        line = f"ASSESSMENT_MAX_DRAFTS_PER_TICK={body.max_drafts_per_tick}"
        if re.search(r"^ASSESSMENT_MAX_DRAFTS_PER_TICK=.*$", text, flags=re.M):
            text = re.sub(r"^ASSESSMENT_MAX_DRAFTS_PER_TICK=.*$", line, text, flags=re.M)
        else:
            text = text.rstrip("\n") + f"\n{line}\n"
        path.write_text(text, encoding="utf-8")
        return {"ok": True, "max_drafts_per_tick": body.max_drafts_per_tick}

    return router
