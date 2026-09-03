"""Tests for the per-challenge "keep trying until flag" persist endpoint."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

from backend.cost_tracker import CostTracker
from backend.webui import build_app


def _make_deps() -> SimpleNamespace:
    settings = SimpleNamespace(
        ctfd_url="",
        webui_token="",
        max_total_cost_usd=0.0,
        max_attempts_per_challenge=3,
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
        challenge_dirs={},
        challenge_metas={},
        model_specs=[],
        max_concurrent_challenges=10,
        cost_tracker=CostTracker(),
        auto_spawn=False,
        persistent_challenges=set(),
        attempts={},
        attempt_notes={},
    )


def _make_poller() -> SimpleNamespace:
    return SimpleNamespace(known_challenges=set(), known_solved=set())


@pytest.mark.asyncio
async def test_persist_enable_disables(monkeypatch):
    deps = _make_deps()

    async def fake_set(deps_arg, challenge, enabled, solved):
        if enabled:
            deps_arg.persistent_challenges.add(challenge)
            deps_arg.attempts[challenge] = 0
        else:
            deps_arg.persistent_challenges.discard(challenge)
        return "ok " + ("on" if enabled else "off")

    import backend.agents.coordinator_core as cc
    monkeypatch.setattr(cc, "do_set_persistent", fake_set)

    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/challenges/Dir/persist", json={"enabled": True})
        data = await resp.json()
        assert data["ok"] is True
        assert data["persistent"] is True

        resp = await client.post("/api/challenges/Dir/persist", json={"enabled": False})
        data = await resp.json()
        assert data["persistent"] is False


@pytest.mark.asyncio
async def test_persist_endpoint_route_registered():
    deps = _make_deps()
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/challenges/Anything/persist", json={"enabled": True})
        assert resp.status == 200
