"""Tests for the strategy planner (role-split of a swarm). No network calls:
planner paths exercised are the fallback distribution and JSON parsing."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.planner import (
    _distribute_fallback,
    _parse_planner_json,
    make_agent_key,
    plan_roles,
    resolve_planner_model,
)
from backend.prompts import ChallengeMeta


def _meta(category: str = "crypto") -> ChallengeMeta:
    return ChallengeMeta(name="Chal X", category=category, description="Break it", tags=["crypto"])


def _empty_settings() -> SimpleNamespace:
    return SimpleNamespace(anthropic_api_key="", openai_api_key="", gemini_api_key="")


def test_fallback_returns_exact_count_with_duplicates():
    meta = _meta()
    plans = _distribute_fallback(meta, ["m-a", "m-b"], count=5)
    assert len(plans) == 5
    keys = [p.agent_key for p in plans]
    assert len(set(keys)) == 5, "agent keys must be unique even with model duplicates"
    # model reuse happens (2 models, 5 agents)
    assert any(p.model_spec == "m-a" for p in plans)
    assert all(p.role_prompt for p in plans)


def test_fallback_count_zero_means_one_per_model():
    meta = _meta()
    plans = _distribute_fallback(meta, ["m-a", "m-b", "m-c"], count=0)
    assert len(plans) == 3
    assert {p.model_spec for p in plans} == {"m-a", "m-b", "m-c"}


def test_fallback_category_crypto_roles():
    meta = _meta(category="crypto")
    plans = _distribute_fallback(meta, ["m-a"], count=2)
    assert "crypto" in plans[0].role_prompt.lower() or "primitive" in plans[0].role_prompt.lower()


@pytest.mark.asyncio
async def test_plan_roles_without_settings_uses_fallback():
    meta = _meta()
    plans = await plan_roles(meta, ["m-a", "m-b"], count=4, settings=None)
    assert len(plans) == 4


@pytest.mark.asyncio
async def test_plan_roles_no_planner_key_uses_fallback(tmp_path, monkeypatch):
    # Point providers.json at an empty temp dir so no custom key leaks in.
    import backend.planner as planner_mod
    import backend.providers as providers_mod
    monkeypatch.setattr(providers_mod, "PROVIDERS_FILE", tmp_path / "providers.json")
    monkeypatch.setattr(planner_mod, "resolve_planner_model", lambda settings: None)

    plans = await plan_roles(_meta(), ["m-a"], count=3, settings=_empty_settings())
    assert len(plans) == 3


@pytest.mark.asyncio
async def test_plan_roles_count_zero_targets_model_count():
    meta = _meta()
    plans = await plan_roles(meta, ["m-a", "m-b"], count=0, settings=None)
    assert len(plans) == 2


def test_parse_planner_json_handles_fences_and_junk():
    text = '```json\n{"roles": [{"title": "A", "model": "m", "brief": "do x"}]}\n```'
    roles = _parse_planner_json(text)
    assert roles[0]["title"] == "A"


def test_parse_planner_json_rejects_bad_output():
    with pytest.raises(ValueError):
        _parse_planner_json("not json at all")


def test_make_agent_key_is_unique_and_slugged():
    assert make_agent_key("gpt-5.4", "Recon & enumeration") == "gpt-5.4#recon-enumeration"
    assert make_agent_key("gpt-5.4", "Recon & enumeration") != make_agent_key("gpt-5.4", "Exploit author")


def test_resolve_planner_model_none_without_keys(tmp_path, monkeypatch):
    import backend.planner as planner_mod
    import backend.providers as providers_mod
    monkeypatch.setattr(providers_mod, "PROVIDERS_FILE", tmp_path / "providers.json")

    assert planner_mod.resolve_planner_model(_empty_settings()) is None
    assert resolve_planner_model(_empty_settings()) is None
