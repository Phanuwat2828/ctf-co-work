"""Tests for the webui auth middleware — token-gated /api/* routes."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from backend.cost_tracker import CostTracker
from backend.webui import build_app


def _make_deps(webui_token: str = "") -> SimpleNamespace:
    settings = SimpleNamespace(
        ctfd_url="",
        webui_token=webui_token,
        max_total_cost_usd=0.0,
        anthropic_api_key="",
        openai_api_key="",
        gemini_api_key="",
        azure_openai_api_key="",
        opencode_zen_api_key="",
        aws_bearer_token="",
    )
    return SimpleNamespace(
        settings=settings,
        manual_challenges={},
        results={},
        swarms={},
        swarm_tasks={},
        challenge_metas={},
        model_specs=[],
        max_concurrent_challenges=10,
        cost_tracker=CostTracker(),
        auto_spawn=False,
    )


def _make_poller() -> SimpleNamespace:
    return SimpleNamespace(known_challenges=set(), known_solved=set())


@pytest.mark.asyncio
async def test_no_token_configured_allows_all_requests():
    deps = _make_deps(webui_token="")
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/status")
        assert resp.status == 200


@pytest.mark.asyncio
async def test_token_configured_rejects_missing_or_wrong_token():
    deps = _make_deps(webui_token="secret123")
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/status")
        assert resp.status == 401

        resp = await client.get("/api/status", headers={"Authorization": "Bearer wrong"})
        assert resp.status == 401


@pytest.mark.asyncio
async def test_token_configured_accepts_correct_bearer_token():
    deps = _make_deps(webui_token="secret123")
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/status", headers={"Authorization": "Bearer secret123"})
        assert resp.status == 200


@pytest.mark.asyncio
async def test_token_configured_accepts_query_param_token():
    deps = _make_deps(webui_token="secret123")
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/api/status?token=secret123")
        assert resp.status == 200


@pytest.mark.asyncio
async def test_index_page_always_accessible_without_token():
    deps = _make_deps(webui_token="secret123")
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.get("/")
        assert resp.status == 200
