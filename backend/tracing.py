"""Per-tool-call JSONL event tracing — one file per solver, streamable via tail -f."""

from __future__ import annotations

import atexit
import json
import time
from collections import deque
from pathlib import Path

# Per-challenge live activity tracking (for the dashboard sparklines).
ACTIVITY_WINDOW = 60.0
_activity: dict[str, deque[float]] = {}


def record_activity(challenge_name: str) -> None:
    now = time.time()
    dq = _activity.setdefault(challenge_name, deque(maxlen=10000))
    dq.append(now)
    # Drop entries outside the window so memory stays bounded
    cutoff = now - ACTIVITY_WINDOW - 5
    while dq and dq[0] < cutoff:
        dq.popleft()


def activity_bins(challenge_name: str, bins: int = 24, width: float = 2.5) -> list[int]:
    """Return counts per time bucket over the last `bins*width` seconds."""
    dq = _activity.get(challenge_name)
    if not dq:
        return [0] * bins
    now = time.time()
    counts = [0] * bins
    cutoff = now - bins * width
    for ts in dq:
        if ts < cutoff:
            continue
        idx = int((now - ts) / width)
        if 0 <= idx < bins:
            counts[bins - 1 - idx] += 1
    return counts


def is_active(challenge_name: str, within: float = 10.0) -> bool:
    dq = _activity.get(challenge_name)
    if not dq:
        return False
    return (time.time() - dq[-1]) < within


def _sanitize(s: str) -> str:
    # Filenames end up in URLs (log browser) — strip URL-/filesystem-hostile chars.
    for ch in "/\\:#?&=<>\"'|*% ":
        s = s.replace(ch, "_")
    return s


def prune_old_logs(log_dir: str = "logs", max_files: int = 300, max_age_days: float = 30) -> int:
    """Delete old trace-*.jsonl files beyond a count/age limit. Returns count removed.

    Keeps the `max_files` most recently modified files; among the rest, also
    drops anything already older than `max_age_days` regardless of count.
    """
    directory = Path(log_dir)
    if not directory.exists():
        return 0

    files = sorted(directory.glob("trace-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = time.time() - max_age_days * 86400
    removed = 0
    for i, path in enumerate(files):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if i >= max_files or mtime < cutoff:
            try:
                path.unlink()
                removed += 1
            except OSError:
                pass
    return removed


class SolverTracer:
    """Append-only JSONL event tracer. Flushes every write for tail -f streaming."""

    def __init__(self, challenge_name: str, model_id: str, log_dir: str = "logs") -> None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.challenge_name = challenge_name
        self.model_id = model_id
        self.path = str(Path(log_dir) / f"trace-{_sanitize(challenge_name)}-{_sanitize(model_id)}-{ts}.jsonl")
        self._fh = open(self.path, "a")
        atexit.register(self._close)

    def close(self) -> None:
        """Explicitly close the trace file. Safe to call multiple times."""
        if not self._fh.closed:
            try:
                self._fh.close()
            except Exception:
                pass
        atexit.unregister(self._close)

    _close = close  # atexit compat

    def _write(self, event: dict) -> None:
        try:
            self._fh.write(json.dumps({"ts": time.time(), **event}) + "\n")
            self._fh.flush()
        except Exception:
            pass

    def tool_call(self, tool_name: str, args: dict | str, step: int) -> None:
        args_str = args if isinstance(args, str) else json.dumps(args)
        self._write({"type": "tool_call", "tool": tool_name, "args": args_str[:2000], "step": step})
        record_activity(self.challenge_name)

    def tool_result(self, tool_name: str, result: str, step: int) -> None:
        self._write({"type": "tool_result", "tool": tool_name, "result": result[:2000], "step": step})
        record_activity(self.challenge_name)

    def model_response(self, text: str, step: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self._write({"type": "model_response", "text": text[:1000], "step": step,
                      "input_tokens": input_tokens, "output_tokens": output_tokens})
        record_activity(self.challenge_name)

    def usage(self, input_tokens: int, output_tokens: int, cache_read: int, cost_usd: float) -> None:
        self._write({"type": "usage", "input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_tokens": cache_read, "cost_usd": round(cost_usd, 6)})

    def event(self, kind: str, **kwargs) -> None:
        self._write({"type": kind, **kwargs})
