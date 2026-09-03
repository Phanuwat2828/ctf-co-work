"""Persist confirmed flags to logs/flags.jsonl so a found flag is never lost,
even when UI/in-memory state is cleared or the process restarts."""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger(__name__)


def record_flag(challenge: str, flag: str, model: str = "", log_path: str = "logs/flags.jsonl") -> str | None:
    """Append one confirmed flag to the JSONL log. Never raises — logs a warning
    on failure and returns the path on success."""
    if not flag:
        return None
    try:
        Path(log_path).parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": time.time(),
            "challenge": challenge,
            "model": model,
            "flag": flag,
        }
        with open(log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        logger.warning("Could not write flag log %s", log_path, exc_info=True)
        return None

    logger.info("FLAG FOUND [%s]: %s", challenge, flag)
    return log_path
