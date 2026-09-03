"""Tests for the "flag is wrong -> retry reading the previous log" flow."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

import backend.agents.coordinator_core as cc
from backend.cost_tracker import CostTracker
from backend.webui import build_app


def _deps() -> SimpleNamespace:
    settings = SimpleNamespace(
        ctfd_url="", webui_token="", max_total_cost_usd=0.0, max_attempts_per_challenge=3,
        anthropic_api_key="", openai_api_key="", gemini_api_key="",
        azure_openai_api_key="", opencode_zen_api_key="", aws_bearer_token="",
    )
    return SimpleNamespace(
        settings=settings,
        manual_challenges={"Hand": "/tmp/manual"},
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
        bad_flags={},
    )


@pytest.mark.asyncio
async def test_flag_wrong_records_clears_and_retries(monkeypatch):
    deps = _deps()
    deps.results["Hand"] = {"flag": "FLAG{wrong1}", "submit": "reported directly (no CTFd)"}

    broadcast_lines: list[str] = []

    class FakeBus:
        async def broadcast(self, content: str):
            broadcast_lines.append(content)

    async def fake_spawn(sp_deps, challenge, model_specs=None, role_mode=False, count=0, instruction=""):
        sp_deps.swarms[challenge] = SimpleNamespace(message_bus=FakeBus())
        return "swarm spawned"

    monkeypatch.setattr(cc, "do_spawn_swarm", fake_spawn)
    monkeypatch.setattr(cc, "_latest_attempt_log_text", lambda challenge: "PREVIOUS-LOG-EXCERPT")

    msg = await cc.do_flag_wrong(deps, "Hand")

    assert "FLAG{wrong1}" in deps.bad_flags["Hand"]
    assert "Hand" not in deps.results  # no longer reported solved
    assert deps.attempts.get("Hand") == 1
    assert "WRONG" in msg
    assert broadcast_lines, "fresh attempt must receive guidance"
    assert "FLAG{wrong1}" in broadcast_lines[0]
    assert "PREVIOUS-LOG-EXCERPT" in broadcast_lines[0]


@pytest.mark.asyncio
async def test_flag_wrong_without_reported_flag_is_noop(monkeypatch):
    deps = _deps()
    spawned = []
    async def fake_spawn(*a, **k):
        spawned.append(1)
        return "ok"
    monkeypatch.setattr(cc, "do_spawn_swarm", fake_spawn)

    msg = await cc.do_flag_wrong(deps, "Hand")
    assert "No reported flag" in msg
    assert not spawned


@pytest.mark.asyncio
async def test_wrong_guidance_includes_bad_flags(monkeypatch):
    deps = _deps()
    deps.bad_flags["Hand"] = ["FLAG{w1}", "FLAG{w2}"]
    monkeypatch.setattr(cc, "_latest_attempt_log_text", lambda challenge: "LOG-TAIL")
    guidance = cc.wrong_flag_guidance(deps, "Hand")
    assert "FLAG{w1}" in guidance and "FLAG{w2}" in guidance
    assert "LOG-TAIL" in guidance


@pytest.mark.asyncio
async def test_wrong_flag_endpoint_registered(monkeypatch):
    deps = _deps()

    async def fake(sp_deps, challenge):
        return "marked wrong"

    monkeypatch.setattr(cc, "do_flag_wrong", fake)
    app = build_app(deps, SimpleNamespace(known_challenges=set(), known_solved=set()))
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/challenges/Hand/wrong-flag", json={})
        assert resp.status == 200
        assert (await resp.json())["message"] == "marked wrong"
