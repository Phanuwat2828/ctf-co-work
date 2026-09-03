"""Tests for ChallengeSwarm role-split support (agent_plan entries)."""

from __future__ import annotations

from types import SimpleNamespace

from backend.agents.swarm import ChallengeSwarm
from backend.planner import AgentPlan, make_agent_key
from backend.prompts import ChallengeMeta


def _swarm(agent_plan=None, model_specs=None) -> ChallengeSwarm:
    meta = ChallengeMeta(name="Chal", category="crypto", description="d")
    return ChallengeSwarm(
        challenge_dir="/tmp/x",
        meta=meta,
        ctfd=None,
        cost_tracker=SimpleNamespace(),
        settings=SimpleNamespace(),
        model_specs=model_specs or ["m-a", "m-b"],
        agent_plan=agent_plan,
    )


def test_no_plan_uses_classic_one_per_model():
    sw = _swarm()
    assert sw._agent_entries() == [("m-a", "m-a", ""), ("m-b", "m-b", "")]


def test_plan_entries_allow_model_duplication_with_distinct_roles():
    plans = [
        AgentPlan(agent_key=make_agent_key("m-a", "Recon"), model_spec="m-a",
                  role_title="Recon", role_prompt="you are recon"),
        AgentPlan(agent_key=make_agent_key("m-a", "Exploit"), model_spec="m-a",
                  role_title="Exploit", role_prompt="you are exploit"),
    ]
    sw = _swarm(agent_plan=plans, model_specs=["m-a"])
    entries = sw._agent_entries()
    assert len(entries) == 2
    keys = {e[0] for e in entries}
    assert len(keys) == 2  # unique keys despite same model
    assert all(e[2] for e in entries)  # roles carried


def test_get_status_agents_keyed_by_agent_key():
    plans = [
        AgentPlan(agent_key=make_agent_key("m-a", "Recon"), model_spec="m-a",
                  role_title="Recon", role_prompt="recon role"),
        AgentPlan(agent_key=make_agent_key("m-b", "Hunt"), model_spec="m-b",
                  role_title="Hunt", role_prompt="hunt role"),
    ]
    sw = _swarm(agent_plan=plans)
    status = sw.get_status()
    assert sorted(status["agents"].keys()) == sorted(p.agent_key for p in plans)
    # Not started yet -> finished status
    assert all(a["status"] == "finished" for a in status["agents"].values())
