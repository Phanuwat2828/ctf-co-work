"""Tests for deleting hand-added (manual) challenges."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp.test_utils import TestClient, TestServer

import backend.agents.coordinator_core as cc
from backend.cost_tracker import CostTracker
from backend.webui import build_app


def _deps(tmp_path) -> SimpleNamespace:
    ch_dir = tmp_path / "challenges" / "manual" / "hand-one"
    ch_dir.mkdir(parents=True)
    (ch_dir / "metadata.yml").write_text("name: Hand One\n", encoding="utf-8")

    settings = SimpleNamespace(
        ctfd_url="", webui_token="", max_total_cost_usd=0.0, max_attempts_per_challenge=3,
        anthropic_api_key="", openai_api_key="", gemini_api_key="",
        azure_openai_api_key="", opencode_zen_api_key="", aws_bearer_token="",
    )
    return SimpleNamespace(
        settings=settings,
        manual_challenges={"Hand One": str(ch_dir)},
        results={"Hand One": {"flag": "FLAG{x}", "submit": "reported directly (no CTFd)"}},
        swarms={},
        swarm_tasks={},
        challenge_dirs={"Hand One": str(ch_dir)},
        challenge_metas={"Hand One": SimpleNamespace(name="Hand One")},
        model_specs=[],
        max_concurrent_challenges=10,
        cost_tracker=CostTracker(),
        auto_spawn=False,
        persistent_challenges={"Hand One"},
        attempts={"Hand One": 2},
        attempt_notes={"Hand One": ["note"]},
        bad_flags={"Hand One": ["FLAG{bad}"]},
    )


@pytest.mark.asyncio
async def test_delete_manual_removes_state_and_folder(tmp_path):
    deps = _deps(tmp_path)
    msg = await cc.do_delete_manual(deps, "Hand One")

    assert "deleted" in msg
    assert "Hand One" not in deps.manual_challenges
    assert "Hand One" not in deps.results
    assert "Hand One" not in deps.persistent_challenges
    assert not (tmp_path / "challenges" / "manual" / "hand-one").exists()


@pytest.mark.asyncio
async def test_delete_non_manual_returns_error(tmp_path):
    deps = _deps(tmp_path)
    msg = await cc.do_delete_manual(deps, "CTFd Challenge")
    assert "not a manually-added" in msg
    assert "CTFd Challenge" not in deps.manual_challenges  # nothing removed


@pytest.mark.asyncio
async def test_delete_endpoint_registered_and_called(monkeypatch, tmp_path):
    deps = _deps(tmp_path)

    async def fake(deps_arg, name):
        return f"deleted {name}"

    monkeypatch.setattr(cc, "do_delete_manual", fake)
    app = build_app(deps, SimpleNamespace(known_challenges=set(), known_solved=set()))
    async with TestClient(TestServer(app)) as client:
        resp = await client.delete("/api/challenges/Hand One")
        assert resp.status == 200
        assert (await resp.json())["message"] == "deleted Hand One"
