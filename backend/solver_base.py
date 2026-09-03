"""Solver result type, status constants, and solver protocol — shared across all backends."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

# Status constants
FLAG_FOUND = "flag_found"
GAVE_UP = "gave_up"
CANCELLED = "cancelled"
ERROR = "error"
QUOTA_ERROR = "quota_error"

# Flag confirmation markers from CTFd
CORRECT_MARKERS = ("CORRECT", "ALREADY SOLVED")


def role_slug(role: str, limit: int = 18) -> str:
    """Short filesystem/URL-safe tag for a role, used to disambiguate agents
    that share the same underlying model."""
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", role.lower()).strip("-")
    return s[:limit] or "agent"


def role_display_label(model_id: str, role: str) -> str:
    """Display/trace label for an agent, e.g. 'gpt-5.4#recon'. Plain model id
    when there is no role (keeps existing single-agent behavior unchanged)."""
    return f"{model_id}#{role_slug(role)}" if role else model_id


def role_system_section(role: str) -> str:
    """The system-prompt block appended when an agent has a specialized role."""
    return "\n\n## Your Role & Strategy\n" + role


@dataclass
class SolverResult:
    flag: str | None
    status: str
    findings_summary: str
    step_count: int
    cost_usd: float
    log_path: str


class SolverProtocol(Protocol):
    """Common interface for all solver backends (Pydantic AI, Claude SDK, Codex)."""

    model_spec: str
    agent_name: str
    sandbox: object

    async def start(self) -> None: ...
    async def run_until_done_or_gave_up(self) -> SolverResult: ...
    def bump(self, insights: str) -> None: ...
    async def stop(self) -> None: ...
