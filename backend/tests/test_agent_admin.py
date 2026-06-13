"""Assessment-agent admin surface (§9 #46): session gate + env round-trip.

Uses ASSESSMENT_AGENT_ENV to point at a tmp env file — no systemd needed
(the unit-state fields degrade gracefully off-host)."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


def _env_file(tmp_path: Path, monkeypatch, body: str) -> Path:
    p = tmp_path / "assessment-agent.env"
    p.write_text(body, encoding="utf-8")
    monkeypatch.setenv("ASSESSMENT_AGENT_ENV", str(p))
    return p


def test_requires_session(client: TestClient) -> None:
    assert client.get("/api/v0/agent/assessment").status_code == 401
    assert (
        client.post("/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 3}).status_code
        == 401
    )


def test_status_reports_config_without_echoing_key(
    authed_client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    _env_file(
        tmp_path,
        monkeypatch,
        "AUSPEXAI_MAINTAINER_TOKEN=tok\nANTHROPIC_API_KEY=sk-secret\n"
        "ASSESSMENT_MODEL=claude-opus-4-8\nASSESSMENT_MAX_DRAFTS_PER_TICK=7\n",
    )
    r = authed_client.get("/api/v0/agent/assessment")
    assert r.status_code == 200
    body = r.json()
    assert body["installed"] is True
    assert body["api_key_present"] is True
    assert body["max_drafts_per_tick"] == 7
    assert "sk-secret" not in r.text  # the key itself NEVER leaves the host


def test_status_not_installed(authed_client: TestClient, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("ASSESSMENT_AGENT_ENV", str(tmp_path / "missing.env"))
    assert authed_client.get("/api/v0/agent/assessment").json() == {"installed": False}


# ---- §9 #48: experiment-assessment agent (the auto-approval ENGINE) ---------


def test_experiment_assessment_requires_session(client: TestClient) -> None:
    assert client.get("/api/v0/agent/experiment-assessment").status_code == 401


def test_experiment_assessment_not_installed(authed_client: TestClient, monkeypatch) -> None:
    # Units not loaded → not-installed/inactive (never crashes). Monkeypatched so
    # the result is host-independent (rage itself may have the unit installed).
    monkeypatch.setattr("auspexai_operator_console.agent_admin._systemd_state", lambda unit: {})
    body = authed_client.get("/api/v0/agent/experiment-assessment").json()
    assert body["installed"] is False
    assert body["timer_active"] is False
    # Exposes only ENGINE state — no env/key fields (the gate lives coord-side).
    assert set(body) == {"installed", "timer_active", "timer_next", "last_run_exit"}


def test_experiment_assessment_active(authed_client: TestClient, monkeypatch) -> None:
    def fake_state(unit: str) -> dict[str, str]:
        if unit.endswith(".timer"):
            return {"LoadState": "loaded", "ActiveState": "active", "NextElapseUSecRealtime": "123"}
        return {"ExecMainStatus": "0"}

    monkeypatch.setattr("auspexai_operator_console.agent_admin._systemd_state", fake_state)
    body = authed_client.get("/api/v0/agent/experiment-assessment").json()
    assert body["installed"] is True
    assert body["timer_active"] is True
    assert body["last_run_exit"] == "0"


def test_cap_update_round_trips_and_preserves_file(
    authed_client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    p = _env_file(
        tmp_path,
        monkeypatch,
        "# comment survives\nAUSPEXAI_MAINTAINER_TOKEN=tok\nANTHROPIC_API_KEY=\n",
    )
    r = authed_client.post("/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 2})
    assert r.status_code == 200
    text = p.read_text(encoding="utf-8")
    assert "ASSESSMENT_MAX_DRAFTS_PER_TICK=2" in text
    assert "# comment survives" in text
    assert "AUSPEXAI_MAINTAINER_TOKEN=tok" in text
    # second write replaces in place
    authed_client.post("/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 9})
    assert p.read_text(encoding="utf-8").count("ASSESSMENT_MAX_DRAFTS_PER_TICK=") == 1
    assert authed_client.get("/api/v0/agent/assessment").json()["max_drafts_per_tick"] == 9


def test_cap_write_failure_returns_503_not_500(
    authed_client: TestClient, tmp_path: Path, monkeypatch
) -> None:
    # Read-only filesystem (ProtectSystem=strict without a ReadWritePaths
    # carve-out): the write OSErrors — surface a clean 503, never a raw 500.
    _env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=\n")

    def boom(self: Path, *a: object, **k: object) -> None:
        raise OSError(30, "Read-only file system")

    monkeypatch.setattr(Path, "write_text", boom)
    r = authed_client.post("/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 0})
    assert r.status_code == 503
    assert "env file" in r.json()["detail"]


def test_cap_validation(authed_client: TestClient, tmp_path: Path, monkeypatch) -> None:
    _env_file(tmp_path, monkeypatch, "ANTHROPIC_API_KEY=\n")
    assert (
        authed_client.post(
            "/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 999}
        ).status_code
        == 422
    )
    monkeypatch.setenv("ASSESSMENT_AGENT_ENV", str(tmp_path / "missing.env"))
    assert (
        authed_client.post(
            "/api/v0/agent/assessment/cap", json={"max_drafts_per_tick": 3}
        ).status_code
        == 409
    )
