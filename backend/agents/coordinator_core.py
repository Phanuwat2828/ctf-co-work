"""Shared coordinator tool logic — called by both Claude SDK and Codex coordinators."""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

from backend.deps import CoordinatorDeps
from backend.prompts import ChallengeMeta
from backend.solver_base import FLAG_FOUND

logger = logging.getLogger(__name__)


async def do_fetch_challenges(deps: CoordinatorDeps) -> str:
    challenges = await deps.ctfd.fetch_all_challenges()
    solved = await deps.ctfd.fetch_solved_names()
    result = [
        {
            "name": ch.get("name", "?"),
            "category": ch.get("category", "?"),
            "value": ch.get("value", 0),
            "solves": ch.get("solves", 0),
            "status": "SOLVED" if ch.get("name") in solved else "unsolved",
            "description": (ch.get("description") or "")[:200],
        }
        for ch in challenges
    ]
    return json.dumps(result, indent=2)


async def do_get_solve_status(deps: CoordinatorDeps) -> str:
    solved = await deps.ctfd.fetch_solved_names()
    swarm_status = {name: swarm.get_status() for name, swarm in deps.swarms.items()}
    return json.dumps({"solved": sorted(solved), "active_swarms": swarm_status}, indent=2)


def _provider_ready(provider: str, s) -> bool:
    match provider:
        case "claude-sdk":
            return bool(s.anthropic_api_key)
        case "codex":
            return bool(s.openai_api_key)
        case "google":
            return bool(s.gemini_api_key)
        case "azure":
            return bool(s.azure_openai_api_key)
        case "zen":
            return bool(s.opencode_zen_api_key)
        case "bedrock":
            return bool(s.aws_bearer_token)
        case _:
            return True


def _ready_model_specs(deps: CoordinatorDeps) -> list[str]:
    from backend.models import provider_from_spec
    ready: list[str] = []
    for spec in deps.model_specs:
        provider = provider_from_spec(spec)
        if provider == "custom":
            from backend.providers import find_provider
            parts = spec.split("/")
            name = parts[1] if len(parts) >= 3 else ""
            p = find_provider(name)
            if p and p.api_key:
                ready.append(spec)
        elif _provider_ready(provider, deps.settings):
            ready.append(spec)
    return ready


async def do_spawn_swarm(
    deps: CoordinatorDeps,
    challenge_name: str,
    model_specs: list[str] | None = None,
    role_mode: bool = False,
    count: int = 0,
    instruction: str = "",
) -> str:
    s = deps.settings
    ready_specs = _ready_model_specs(deps)
    if not ready_specs:
        return "No API keys configured for the selected models — open the web dashboard (⚙ Setup) and add at least one key first."
    if model_specs:
        # Restrict to requested specs that are actually ready
        wanted = [m for m in model_specs if m in ready_specs]
        if not wanted:
            return "None of the selected models are ready — check their API keys."
        ready_specs = wanted
    # Retire ALL finished swarms before checking capacity
    finished = [
        name for name, swarm in deps.swarms.items()
        if swarm.cancel_event.is_set()
        or (name in deps.swarm_tasks and deps.swarm_tasks[name].done())
    ]
    for name in finished:
        del deps.swarms[name]
        deps.swarm_tasks.pop(name, None)

    active_count = len(deps.swarms)
    if active_count >= deps.max_concurrent_challenges:
        return f"At capacity ({active_count}/{deps.max_concurrent_challenges} challenges running). Wait for one to finish."

    if challenge_name in deps.swarms:
        return f"Swarm still running for {challenge_name}"

    # Auto-pull challenge if needed
    if challenge_name not in deps.challenge_dirs:
        challenges = await deps.ctfd.fetch_all_challenges()
        ch_data = next((c for c in challenges if c.get("name") == challenge_name), None)
        if not ch_data:
            return f"Challenge '{challenge_name}' not found on CTFd"
        output_dir = str(Path(deps.challenges_root))
        ch_dir = await deps.ctfd.pull_challenge(ch_data, output_dir)
        deps.challenge_dirs[challenge_name] = ch_dir
        deps.challenge_metas[challenge_name] = ChallengeMeta.from_yaml(Path(ch_dir) / "metadata.yml")

    from backend.agents.swarm import ChallengeSwarm

    # Role-split mode: an LLM planner (or a category template fallback) decides
    # distinct strategies for each agent; models may repeat across roles.
    agent_plan = None
    if role_mode:
        from backend.planner import plan_roles
        from backend.prompts import list_distfiles

        meta = deps.challenge_metas[challenge_name]
        distfiles = list_distfiles(deps.challenge_dirs[challenge_name])
        agent_plan = await plan_roles(
            meta, list(ready_specs), count, instruction,
            settings=deps.settings, distfile_names=distfiles,
        )

    swarm = ChallengeSwarm(
        challenge_dir=deps.challenge_dirs[challenge_name],
        meta=deps.challenge_metas[challenge_name],
        ctfd=deps.ctfd,
        cost_tracker=deps.cost_tracker,
        settings=deps.settings,
        model_specs=ready_specs,
        no_submit=deps.no_submit or challenge_name in getattr(deps, "manual_challenges", {}),
        coordinator_inbox=deps.coordinator_inbox,
        agent_plan=agent_plan,
    )
    deps.swarms[challenge_name] = swarm

    async def _run_and_cleanup() -> None:
        result = await swarm.run()
        # Flag already submitted/confirmed by solver's submit_fn — just record the result
        if result and result.status == FLAG_FOUND:
            deps.results[challenge_name] = {
                "flag": result.flag,
                "submit": "reported directly (no CTFd)" if swarm.no_submit else "confirmed by solver",
            }
            from backend.flaglog import record_flag
            record_flag(challenge_name, result.flag)

    task = asyncio.create_task(_run_and_cleanup(), name=f"swarm-{challenge_name}")
    deps.swarm_tasks[challenge_name] = task
    agent_count = len(agent_plan) if agent_plan else len(ready_specs)
    return f"Swarm spawned for {challenge_name} with {agent_count} agent(s)"


async def do_check_swarm_status(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    return json.dumps(swarm.get_status(), indent=2)


async def do_submit_flag(deps: CoordinatorDeps, challenge_name: str, flag: str) -> str:
    if deps.no_submit:
        return f'DRY RUN — would submit "{flag.strip()}" for {challenge_name}'
    try:
        result = await deps.ctfd.submit_flag(challenge_name, flag)
        return result.display
    except Exception as e:
        return f"submit_flag error: {e}"


async def do_kill_swarm(deps: CoordinatorDeps, challenge_name: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    # Force-cancel solvers and delete their containers immediately
    await swarm.force_stop()
    # Remove from registry so the dashboard reflects the kill immediately
    deps.swarms.pop(challenge_name, None)
    task = deps.swarm_tasks.pop(challenge_name, None)
    if task:
        task.cancel()
    # A manual kill stops the "keep trying until flag" loop for this challenge.
    deps.persistent_challenges.discard(challenge_name)
    return f"Swarm for {challenge_name} cancelled"


def should_retry(deps: CoordinatorDeps, challenge: str, solved_names: set[str], cap: int) -> bool:
    """Whether the coordinator should auto-start another attempt for a challenge
    whose swarm finished without a flag. cap <= 0 means unlimited attempts."""
    if challenge in solved_names:
        return False
    if challenge not in deps.persistent_challenges:
        return False
    return not (cap > 0 and deps.attempts.get(challenge, 0) >= cap)


def attempt_guidance(deps: CoordinatorDeps, challenge: str, attempt: int) -> str:
    """Build guidance for the next attempt from prior failed attempts."""
    notes = deps.attempt_notes.get(challenge, [])
    body = "\n".join(notes[-3:]) if notes else "(no prior attempts)"
    return (
        f"[coordinator] This is attempt #{attempt} for '{challenge}' — the previous "
        f"attempt(s) finished WITHOUT finding the flag:\n{body}\n"
        "Start fresh. Do NOT repeat the same technique that already failed — pick a "
        "different approach and explore deeper. The flag is still there; keep going until "
        "submit_flag returns CORRECT."
    )


async def do_set_persistent(deps: CoordinatorDeps, challenge: str, enabled: bool, solved_names: set[str]) -> str:
    """Enable/disable 'keep trying until the flag is found' for a challenge.
    Enabling on an unsolved challenge with no running swarm starts attempt #1."""
    if not enabled:
        deps.persistent_challenges.discard(challenge)
        return f"Auto-retry for '{challenge}' turned OFF."
    deps.persistent_challenges.add(challenge)
    deps.attempts[challenge] = 0
    deps.attempt_notes[challenge] = []
    if challenge in solved_names:
        return f"'{challenge}' is already solved — nothing to retry."
    if challenge in deps.swarms:
        return f"Will keep trying '{challenge}' until the flag is found (swarm already running)."
    spawn_msg = await do_spawn_swarm(deps, challenge)
    return f"Will keep trying '{challenge}' until the flag is found. {spawn_msg}"


def _latest_attempt_log_text(challenge: str, last_n: int = 80, max_chars: int = 2600) -> str:
    """Condensed tail of the most recent trace log for a challenge."""
    import time as _time

    from backend.tracing import _sanitize

    prefix = "trace-" + _sanitize(challenge) + "-"
    log_dir = Path("logs")
    if not log_dir.is_dir():
        return ""
    files = [p for p in log_dir.glob("trace-*.jsonl") if p.name.startswith(prefix)]
    if not files:
        return ""
    latest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        raw = latest.read_text(encoding="utf-8", errors="replace").splitlines()[-last_n:]
    except OSError:
        return ""

    events: list[str] = []
    for line in raw:
        try:
            d = json.loads(line)
        except Exception:
            events.append(line[:150])
            continue
        ts = d.get("ts")
        stamp = _time.strftime("%H:%M:%S", _time.localtime(ts)) if ts else ""
        kind = d.get("type", "?")
        if kind == "tool_call":
            events.append(f"{stamp} CALL {d.get('tool')}: {str(d.get('args'))[:120]}")
        elif kind == "tool_result":
            events.append(f"{stamp} RESULT {d.get('tool')}: {str(d.get('result'))[:150]}")
        elif kind == "model_response":
            events.append(f"{stamp} MODEL: {str(d.get('text'))[:120]}")
        else:
            extra = {k: v for k, v in d.items() if k not in ("ts", "type")}
            events.append(f"{stamp} {kind}: {str(extra)[:150]}")
    out = "\n".join(events)
    return out[:max_chars]


def wrong_flag_guidance(deps: CoordinatorDeps, challenge: str) -> str:
    """Guidance for a fresh attempt after the operator marks a flag wrong."""
    bad = deps.bad_flags.get(challenge, [])
    bad_txt = ", ".join(bad) if bad else "(previous flags)"
    head = (
        f"[coordinator] The flag(s) previously reported for '{challenge}' were marked "
        f"WRONG by the operator: {bad_txt}. Do NOT repeat them.\n"
        "Review the previous attempt's activity below, learn what was already tried and "
        "failed, and pursue a DIFFERENT method or angle to find the real flag."
    )
    log_txt = _latest_attempt_log_text(challenge)
    if log_txt:
        head += f"\n--- previous attempt log (tail) ---\n{log_txt}"
    return head


async def do_flag_wrong(deps: CoordinatorDeps, challenge_name: str) -> str:
    """Operator says the reported flag for a challenge is wrong.

    Records the flag as bad, force-stops any running swarm, then spawns a fresh
    attempt whose solvers are told the previous flag was wrong and are given a
    condensed copy of the previous attempt log to learn from."""
    result = deps.results.pop(challenge_name, None)
    flag = (result or {}).get("flag")
    if not flag:
        return f"No reported flag for '{challenge_name}' to mark wrong."

    deps.bad_flags.setdefault(challenge_name, []).append(flag)
    deps.persistent_challenges.discard(challenge_name)

    # Stop anything still running for this challenge before retrying.
    swarm = deps.swarms.pop(challenge_name, None)
    if swarm is not None:
        try:
            await swarm.force_stop()
        except Exception:
            pass
    task = deps.swarm_tasks.pop(challenge_name, None)
    if task is not None and not task.done():
        task.cancel()

    spawn_msg = await do_spawn_swarm(deps, challenge_name)
    if challenge_name in deps.swarms:
        guidance = wrong_flag_guidance(deps, challenge_name)
        try:
            await deps.swarms[challenge_name].message_bus.broadcast(guidance)
        except Exception:
            logger.warning("Wrong-flag guidance broadcast failed", exc_info=True)
        deps.attempts[challenge_name] = deps.attempts.get(challenge_name, 0) + 1
        return (
            f"Flag '{flag}' marked WRONG — fresh attempt started; solvers were told to "
            f"read the previous log and try a different method. {spawn_msg}"
        )
    return f"Flag '{flag}' marked WRONG. {spawn_msg}"


async def do_bump_agent(deps: CoordinatorDeps, challenge_name: str, model_spec: str, insights: str) -> str:
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec} in {challenge_name}"
    solver.bump(insights)
    return f"Bumped {model_spec} on {challenge_name}"


async def do_read_solver_trace(deps: CoordinatorDeps, challenge_name: str, model_spec: str, last_n: int = 20) -> str:
    """Read the last N trace events from a solver's JSONL log."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm for {challenge_name}"
    solver = swarm.solvers.get(model_spec)
    if not solver:
        return f"No solver for {model_spec}"
    trace_path = getattr(solver, "tracer", None)
    if not trace_path:
        return "No tracer on solver"
    path = trace_path.path if hasattr(trace_path, "path") else str(trace_path)
    try:
        lines = Path(path).read_text().strip().split("\n")
        recent = lines[-last_n:]
        summary = []
        for line in recent:
            try:
                d = json.loads(line)
                t = d.get("type", "?")
                if t == "tool_call":
                    args_str = str(d.get("args", ""))[:100]
                    summary.append(f"step {d.get('step','?')} CALL {d.get('tool','?')}: {args_str}")
                elif t == "tool_result":
                    result_str = str(d.get("result", ""))[:100]
                    summary.append(f"step {d.get('step','?')} RESULT {d.get('tool','?')}: {result_str}")
                elif t in ("finish", "error", "bump", "turn_failed"):
                    summary.append(f"** {t}: {json.dumps({k:v for k,v in d.items() if k != 'ts'})}")
                elif t == "usage":
                    summary.append(f"usage: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} cost=${d.get('cost_usd',0):.4f}")
                else:
                    summary.append(f"{t}: {str(d)[:80]}")
            except Exception:
                summary.append(line[:100])
        return "\n".join(summary)
    except FileNotFoundError:
        return f"Trace file not found: {path}"
    except Exception as e:
        return f"Error reading trace: {e}"


async def do_broadcast(deps: CoordinatorDeps, challenge_name: str, message: str) -> str:
    """Broadcast a message to all solvers working on a challenge."""
    swarm = deps.swarms.get(challenge_name)
    if not swarm:
        return f"No swarm running for {challenge_name}"
    await swarm.message_bus.broadcast(message)
    return f"Broadcast to all solvers on {challenge_name}"
