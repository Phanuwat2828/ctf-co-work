"""Tests for the "keep trying until flag" auto-retry decision logic."""

from __future__ import annotations

from types import SimpleNamespace

from backend.agents.coordinator_core import should_retry


def _deps(persistent=(), attempts=None) -> SimpleNamespace:
    return SimpleNamespace(
        persistent_challenges=set(persistent),
        attempts=dict(attempts or {}),
        attempt_notes={},
        results={},
    )


def test_retry_when_enabled_and_under_cap():
    deps = _deps(persistent=("A",))
    assert should_retry(deps, "A", set(), cap=3) is True


def test_no_retry_when_not_enabled():
    deps = _deps(persistent=("A",))
    assert should_retry(deps, "B", set(), cap=3) is False


def test_no_retry_when_solved():
    deps = _deps(persistent=("A",))
    assert should_retry(deps, "A", {"A"}, cap=3) is False


def test_no_retry_after_cap_reached():
    deps = _deps(persistent=("A",), attempts={"A": 3})
    assert should_retry(deps, "A", set(), cap=3) is False


def test_cap_zero_means_unlimited():
    deps = _deps(persistent=("A",), attempts={"A": 12})
    assert should_retry(deps, "A", set(), cap=0) is True


def test_enabled_then_solved_disables_next_check():
    deps = _deps(persistent=("A",), attempts={"A": 1})
    assert should_retry(deps, "A", {"A"}, cap=0) is False
