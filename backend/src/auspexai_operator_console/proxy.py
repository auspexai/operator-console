"""Coordinator API proxy routes for the operator console.

All routes require a signed-in Maintainer session. Every proxied request
carries the X-Maintainer-Login header for per-maintainer audit attribution
on the coordinator side (trusted-proxy model per §11 of
operator_console_design.md).

O-M3: workers fleet, promotion queue, experiment approval.
"""

from __future__ import annotations

from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .auth import coord_headers, require_session


class ProxyError(Exception):
    pass


def build_router(config) -> APIRouter:
    router = APIRouter(prefix="/api/v0/proxy", tags=["proxy"])

    def _headers(request: Request) -> dict[str, str]:
        login = require_session(request)
        return coord_headers(login, config.coord_service_token)

    async def _proxy_get(path: str, headers: dict[str, str]) -> Any:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(f"{config.coord_url}{path}", headers=headers)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
        return r.json()

    async def _proxy_post(path: str, headers: dict[str, str], body: dict | None = None) -> Any:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.post(f"{config.coord_url}{path}", headers=headers, json=body)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
        return r.json()

    # ---- workers fleet ----

    @router.get("/workers")
    async def list_workers(request: Request) -> Any:
        return await _proxy_get("/api/v0/workers", _headers(request))

    @router.post("/workers/{worker_id}/actions/quarantine")
    async def quarantine_worker(request: Request, worker_id: str, reason: str | None = None) -> Any:
        return await _proxy_post(
            f"/api/v0/workers/{worker_id}/actions/quarantine",
            _headers(request),
            {"reason": reason} if reason else None,
        )

    @router.post("/workers/{worker_id}/actions/unquarantine")
    async def unquarantine_worker(request: Request, worker_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/workers/{worker_id}/actions/unquarantine",
            _headers(request),
        )

    # ---- promotion queue ----

    @router.get("/accounts/{account_id}/receipt-stats")
    async def receipt_stats(request: Request, account_id: str) -> Any:
        return await _proxy_get(
            f"/api/v0/accounts/{account_id}/receipt-stats",
            _headers(request),
        )

    @router.post("/accounts/{account_id}/actions/promote")
    async def promote_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/promote",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/demote")
    async def demote_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/demote",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/suspend")
    async def suspend_account(request: Request, account_id: str) -> Any:
        body = await request.json()
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/suspend",
            _headers(request),
            body,
        )

    @router.post("/accounts/{account_id}/actions/unsuspend")
    async def unsuspend_account(request: Request, account_id: str) -> Any:
        return await _proxy_post(
            f"/api/v0/accounts/{account_id}/actions/unsuspend",
            _headers(request),
        )

    # ---- experiments ----

    @router.get("/experiments")
    async def list_experiments(request: Request) -> Any:
        return await _proxy_get("/api/v0/experiments", _headers(request))

    @router.post("/experiments/{experiment_id}/actions/approve")
    async def approve_experiment(request: Request, experiment_id: str) -> Any:
        body = await request.json()
        params = []
        if body.get("integrity_policy"):
            params.append(f"integrity_policy={body['integrity_policy']}")
        for key in ["max_unit_duration_seconds", "max_units", "max_concurrent_assignments", "max_payload_bytes"]:
            if body.get(key) is not None:
                params.append(f"{key}={body[key]}")
        query = f"?{'&'.join(params)}" if params else ""
        return await _proxy_post(
            f"/api/v0/experiments/{experiment_id}/actions/approve{query}",
            _headers(request),
        )

    return router
