"""Tests for backend.cost_tracker.CostTracker.over_budget()."""

from __future__ import annotations

from pydantic_ai.usage import RunUsage

from backend.cost_tracker import CostTracker


def _tracker_with_cost(cost_usd: float) -> CostTracker:
    """Build a tracker with one agent whose recorded cost is exactly cost_usd
    (bypasses real pricing lookups, which aren't the concern of these tests)."""
    from backend.cost_tracker import AgentUsage

    tracker = CostTracker()
    tracker.by_agent["agent-1"] = AgentUsage(usage=RunUsage(), model_name="test-model", cost_usd=cost_usd)
    return tracker


def test_zero_cap_means_no_budget_limit():
    tracker = _tracker_with_cost(1000.0)
    assert tracker.over_budget(0) is False
    assert tracker.over_budget(-5) is False


def test_cap_above_total_cost_is_not_over_budget():
    tracker = _tracker_with_cost(5.0)
    assert tracker.over_budget(10.0) is False


def test_cap_at_or_below_total_cost_is_over_budget():
    tracker = _tracker_with_cost(10.0)
    assert tracker.over_budget(10.0) is True
    assert tracker.over_budget(5.0) is True


def test_empty_tracker_never_over_budget_with_positive_cap():
    tracker = CostTracker()
    assert tracker.over_budget(10.0) is False
