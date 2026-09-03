"""Tests for backend.tracing.prune_old_logs()."""

from __future__ import annotations

import os
import time

from backend.tracing import prune_old_logs


def _make_trace_file(log_dir, name: str, age_seconds: float = 0) -> None:
    path = log_dir / name
    path.write_text('{"ts": 0, "type": "start"}\n')
    if age_seconds:
        mtime = time.time() - age_seconds
        os.utime(path, (mtime, mtime))


def test_prune_removes_files_beyond_max_count(tmp_path):
    for i in range(5):
        _make_trace_file(tmp_path, f"trace-Chal-model-{i:02d}.jsonl", age_seconds=5 - i)

    removed = prune_old_logs(str(tmp_path), max_files=3, max_age_days=30)

    remaining = sorted(p.name for p in tmp_path.glob("trace-*.jsonl"))
    assert removed == 2
    assert len(remaining) == 3


def test_prune_removes_files_older_than_max_age_days(tmp_path):
    _make_trace_file(tmp_path, "trace-old.jsonl", age_seconds=40 * 86400)
    _make_trace_file(tmp_path, "trace-new.jsonl", age_seconds=0)

    removed = prune_old_logs(str(tmp_path), max_files=300, max_age_days=30)

    remaining = sorted(p.name for p in tmp_path.glob("trace-*.jsonl"))
    assert removed == 1
    assert remaining == ["trace-new.jsonl"]


def test_prune_ignores_non_trace_files(tmp_path):
    (tmp_path / "notes.txt").write_text("hello")
    _make_trace_file(tmp_path, "trace-a.jsonl", age_seconds=50 * 86400)

    removed = prune_old_logs(str(tmp_path), max_files=0, max_age_days=30)

    assert removed == 1
    assert (tmp_path / "notes.txt").exists()


def test_prune_on_missing_directory_returns_zero(tmp_path):
    missing = tmp_path / "does-not-exist"
    assert prune_old_logs(str(missing)) == 0
