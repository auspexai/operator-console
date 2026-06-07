"""Pytest harness for the operator-console backend.

The console backend had no tests before M6 — this establishes the harness:
- `client`        — a TestClient over `create_app` with a throwaway config.
- `authed_client` — same, but with `require_session` monkeypatched to a signed-in
  maintainer. (Proxy routes call `require_session(request)` inline rather than via
  `Depends`, so a dependency override won't reach it; patching the name the proxy
  module imported is the seam.)
- coordinator upstreams are mocked with `respx` (the proxy creates its own
  `httpx.AsyncClient`; respx intercepts at the transport layer — no code change).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from auspexai_operator_console.config import OperatorConsoleConfig
from auspexai_operator_console.main import create_app

COORD_URL = "http://coord.test"


def _config(tmp_path: Path) -> OperatorConsoleConfig:
    return OperatorConsoleConfig(
        coord_url=COORD_URL,
        coord_service_token="test-service-token",
        bind_host="127.0.0.1",
        bind_port=8099,
        static_dir=tmp_path / "static",
        session_secret="test-session-secret-0123456789abcdef",
        cooldown_hours=0,
        allowed_networks=[],
        passphrase_store_path=tmp_path / "passphrase",
        verify_roster_signature=False,
    )


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(_config(tmp_path)))


@pytest.fixture
def authed_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(
        "auspexai_operator_console.proxy.require_session",
        lambda request: "test-maintainer",
    )
    return TestClient(create_app(_config(tmp_path)))
