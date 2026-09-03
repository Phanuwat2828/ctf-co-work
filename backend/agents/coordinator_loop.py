"""Shared coordinator event loop — used by both Claude SDK and Codex coordinators."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from backend.config import Settings
from backend.cost_tracker import CostTracker
from backend.ctfd import CTFdClient
from backend.deps import CoordinatorDeps
from backend.poller import CTFdPoller
from backend.prompts import ChallengeMeta
from backend.webui import start_web_server

logger = logging.getLogger(__name__)

# Callable type for a coordinator turn: (message) -> None
TurnFn = Callable[[str], Coroutine[Any, Any, None]]


def build_deps(
    settings: Settings,
    model_specs: list[str] | None = None,
    challenges_root: str = "challenges",
    no_submit: bool = False,
    challenge_dirs: dict[str, str] | None = None,
    challenge_metas: dict[str, ChallengeMeta] | None = None,
) -> tuple[CTFdClient, CostTracker, CoordinatorDeps]:
    """Create CTFd client, cost tracker, and coordinator deps."""
    ctfd = CTFdClient(
        base_url=settings.ctfd_url,
        token=settings.ctfd_token,
        username=settings.ctfd_user,
        password=settings.ctfd_pass,
        session_cookie=getattr(settings, "ctfd_session_cookie", ""),
    )
    cost_tracker = CostTracker()
    from backend.providers import model_specs_from_providers
    specs = model_specs or model_specs_from_providers()
    Path(challenges_root).mkdir(parents=True, exist_ok=True)

    deps = CoordinatorDeps(
        ctfd=ctfd,
        cost_tracker=cost_tracker,
        settings=settings,
        model_specs=specs,
        challenges_root=challenges_root,
        no_submit=no_submit,
        max_concurrent_challenges=getattr(settings, "max_concurrent_challenges", 10),
        challenge_dirs=challenge_dirs or {},
        challenge_metas=challenge_metas or {},
    )

    # Pre-load already-pulled challenges
    for d in Path(challenges_root).iterdir():
        meta_path = d / "metadata.yml"
        if meta_path.exists():
            meta = ChallengeMeta.from_yaml(meta_path)
            if meta.name not in deps.challenge_dirs:
                deps.challenge_dirs[meta.name] = str(d)
                deps.challenge_metas[meta.name] = meta

    return ctfd, cost_tracker, deps


async def run_event_loop(
    deps: CoordinatorDeps,
    ctfd: CTFdClient,
    cost_tracker: CostTracker,
    turn_fn: TurnFn,
    status_interval: int = 60,
) -> dict[str, Any]:
    """Run the shared coordinator event loop.

    Args:
        deps: Coordinator dependencies (shared state).
        ctfd: CTFd client (for poller).
        cost_tracker: Cost tracker.
        turn_fn: Async function that sends a message to the coordinator LLM.
        status_interval: Seconds between status updates.
    """
    poller = CTFdPoller(ctfd=ctfd, interval_s=5.0)
    await poller.start()

    # Start web dashboard + operator message endpoint
    web_runner, web_port = await start_web_server(deps, poller, deps.msg_port)
    deps.msg_port = web_port

    logger.info(
        "Coordinator starting: %d models, %d challenges, %d solved",
        len(deps.model_specs),
        len(poller.known_challenges),
        len(poller.known_solved),
    )

    unsolved = poller.known_challenges - poller.known_solved
    initial_msg = (
        f"CTF is LIVE. {len(poller.known_challenges)} challenges, "
        f"{len(poller.known_solved)} solved.\n"
        f"Unsolved: {sorted(unsolved) if unsolved else 'NONE'}\n"
        "List the challenges and their status, but DO NOT spawn any swarms "
        "unless the operator explicitly asks you to. Wait for instructions."
    )

    async def _safe_turn(msg: str) -> None:
        """Send a message to the coordinator LLM without killing the loop
        (e.g. when no API key is configured yet — web setup can fix it live)."""
        try:
            await turn_fn(msg)
        except Exception as e:
            logger.warning("Coordinator turn failed (set up API keys in the web dashboard?): %s", e)

    try:
        await _safe_turn(initial_msg)

        # Auto-spawn unsolved challenges only if enabled (off by default — operator spawns via web)
        if deps.auto_spawn:
            await _auto_spawn_unsolved(deps, poller)

        last_status = asyncio.get_event_loop().time()

        while True:
            events = []
            evt = await poller.get_event(timeout=5.0)
            if evt:
                events.append(evt)
            events.extend(poller.drain_events())

            # Auto-kill swarms for solved challenges
            for evt in events:
                if evt.kind == "challenge_solved" and evt.challenge_name in deps.swarms:
                    swarm = deps.swarms[evt.challenge_name]
                    if not swarm.cancel_event.is_set():
                        await swarm.force_stop()
                        logger.info("Auto-killed swarm for: %s", evt.challenge_name)

            parts: list[str] = []
            for evt in events:
                if evt.kind == "new_challenge":
                    if deps.auto_spawn:
                        parts.append(f"NEW CHALLENGE: '{evt.challenge_name}' appeared. Spawn a swarm.")
                        await _auto_spawn_one(deps, evt.challenge_name)
                    else:
                        parts.append(f"NEW CHALLENGE: '{evt.challenge_name}' appeared. Auto-spawn is OFF — wait for the operator to spawn it.")
                elif evt.kind == "challenge_solved":
                    parts.append(f"SOLVED: '{evt.challenge_name}' — swarm auto-killed.")

            # Detect finished swarms
            had_finish = False
            for name, task in list(deps.swarm_tasks.items()):
                if task.done():
                    parts.append(f"SOLVER FINISHED: Swarm for '{name}' completed. Check results or retry.")
                    deps.swarm_tasks.pop(name, None)
                    had_finish = True

            if had_finish:
                # Auto-retry persistent ("keep trying until flag") challenges right away.
                await _maybe_auto_retry(deps, poller, parts, deps.settings)

            # Drain solver-to-coordinator messages
            while True:
                try:
                    solver_msg = deps.coordinator_inbox.get_nowait()
                    parts.append(f"SOLVER MESSAGE: {solver_msg}")
                except asyncio.QueueEmpty:
                    break

            # Drain operator messages
            while True:
                try:
                    op_msg = deps.operator_inbox.get_nowait()
                    parts.append(f"OPERATOR MESSAGE: {op_msg}")
                    logger.info("Operator message: %s", op_msg[:200])
                except asyncio.QueueEmpty:
                    break

            # Periodic status update — only when there are active swarms or other events
            now = asyncio.get_event_loop().time()
            if now - last_status >= status_interval:
                last_status = now
                active = [n for n, t in deps.swarm_tasks.items() if not t.done()]
                solved_set = poller.known_solved
                unsolved_set = poller.known_challenges - solved_set
                status_line = (
                    f"STATUS: {len(solved_set)} solved, {len(unsolved_set)} unsolved, "
                    f"{len(active)} active swarms. Cost: ${cost_tracker.total_cost_usd:.2f}"
                )
                budget_cap = getattr(deps.settings, "max_total_cost_usd", 0.0)
                if cost_tracker.over_budget(budget_cap):
                    status_line += (
                        f"\nBUDGET WARNING: total spend ${cost_tracker.total_cost_usd:.2f} "
                        f"has exceeded the configured cap of ${budget_cap:.2f}. "
                        "Consider killing low-priority swarms or asking the operator before spawning more."
                    )
                # Only send to coordinator if there's something happening
                if active or parts:
                    parts.append(status_line)
                else:
                    logger.info(f"Event -> coordinator: {status_line}")
                # Give deferred auto-retries a chance when capacity frees up.
                await _maybe_auto_retry(deps, poller, parts, deps.settings)

            if parts:
                msg = "\n\n".join(parts)
                logger.info("Event -> coordinator: %s", msg[:200])
                await _safe_turn(msg)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info("Coordinator shutting down...")
    except Exception as e:
        logger.error("Coordinator fatal: %s", e, exc_info=True)
    finally:
        if web_runner:
            await web_runner.cleanup()
        await poller.stop()
        for swarm in deps.swarms.values():
            swarm.kill()
        for task in deps.swarm_tasks.values():
            task.cancel()
        if deps.swarm_tasks:
            await asyncio.gather(*deps.swarm_tasks.values(), return_exceptions=True)
        cost_tracker.log_summary()
        try:
            await ctfd.close()
        except Exception:
            pass

    return {
        "results": deps.results,
        "total_cost_usd": cost_tracker.total_cost_usd,
        "total_tokens": cost_tracker.total_tokens,
    }


async def _auto_spawn_one(deps: CoordinatorDeps, challenge_name: str) -> None:
    """Auto-spawn a swarm for a single challenge if not already running."""
    if challenge_name in deps.swarms:
        return
    active = sum(1 for t in deps.swarm_tasks.values() if not t.done())
    if active >= deps.max_concurrent_challenges:
        return
    try:
        from backend.agents.coordinator_core import _ready_model_specs, do_spawn_swarm
        if not _ready_model_specs(deps):
            return
        result = await do_spawn_swarm(deps, challenge_name)
        logger.info(f"Auto-spawn {challenge_name}: {result[:100]}")
    except Exception as e:
        logger.warning(f"Auto-spawn failed for {challenge_name}: {e}")


async def _auto_spawn_unsolved(deps: CoordinatorDeps, poller) -> None:
    """Auto-spawn swarms for all unsolved challenges that don't have active swarms."""
    unsolved = poller.known_challenges - poller.known_solved
    for name in sorted(unsolved):
        await _auto_spawn_one(deps, name)


async def _maybe_auto_retry(deps: CoordinatorDeps, poller, parts: list[str], settings) -> None:
    """Keep trying persistent challenges: whenever one has no running swarm and is
    still unsolved, spawn a fresh attempt (new context) with guidance from the
    previous rounds. Stops on solve, kill, no ready models, or the attempt cap
    (max_attempts_per_challenge; 0 = until the operator stops it)."""
    if not deps.persistent_challenges:
        return
    try:
        from backend.agents.coordinator_core import (
            _ready_model_specs,
            attempt_guidance,
            do_spawn_swarm,
            should_retry,
        )
    except Exception:
        return

    cap = getattr(settings, "max_attempts_per_challenge", 3)
    solved = set(poller.known_solved) | {n for n, r in deps.results.items() if r.get("flag")}

    for name in list(deps.persistent_challenges):
        if name in solved:
            deps.persistent_challenges.discard(name)
            continue
        if name in deps.swarm_tasks or name in deps.swarms:
            continue  # already running
        if not should_retry(deps, name, solved, cap):
            deps.persistent_challenges.discard(name)
            logger.warning("Attempt cap (%s) reached for '%s' — auto-retry stopped", cap, name)
            continue
        if not _ready_model_specs(deps):
            deps.persistent_challenges.discard(name)
            logger.warning("No ready models — auto-retry stopped for '%s'", name)
            continue

        # Summarize the previous (finished) round before do_spawn_swarm retires it.
        old_swarm = deps.swarms.get(name)
        prev_round_summary = "no findings recorded"
        if old_swarm is not None:
            try:
                agents = old_swarm.get_status().get("agents", {})
                bits = [f"[{spec}] {a.get('findings', '')[:200]}" for spec, a in agents.items()
                        if a.get("findings")]
                if bits:
                    prev_round_summary = "; ".join(bits)[:600]
            except Exception:
                pass

        prev = deps.attempts.get(name, 0)
        msg = await do_spawn_swarm(deps, name)
        if name not in deps.swarms:
            # At capacity or a transient failure — stay enabled, retry next cycle.
            parts.append(f"AUTO-RETRY: next attempt for '{name}' deferred ({msg[:120]})")
            continue

        new_attempt = prev + 1
        deps.attempts[name] = new_attempt
        deps.attempt_notes.setdefault(name, []).append(
            f"Round {prev}: {prev_round_summary}"
        )
        guidance = attempt_guidance(deps, name, new_attempt)
        try:
            await deps.swarms[name].message_bus.broadcast(guidance)
        except Exception:
            logger.warning("Auto-retry guidance broadcast failed", exc_info=True)
        parts.append(f"AUTO-RETRY: attempt #{new_attempt} started for '{name}'")
        logger.info("Auto-retry attempt #%d for '%s'", new_attempt, name)

