"""Tests for the flag persistence helper (logs/flags.jsonl)."""

from __future__ import annotations

import json

from backend.flaglog import record_flag


def test_record_flag_writes_jsonl(tmp_path):
    path = tmp_path / "flags.jsonl"
    record_flag("Chal A", "FLAG{abc123}", model="m1", log_path=str(path))
    record_flag("Chal B", "FLAG{xyz}", log_path=str(path))

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["challenge"] == "Chal A"
    assert first["flag"] == "FLAG{abc123}"
    assert first["model"] == "m1"
    assert "ts" in first


def test_record_flag_empty_returns_none(tmp_path):
    path = tmp_path / "flags.jsonl"
    assert record_flag("Chal", "", log_path=str(path)) is None
    assert not path.exists()


def test_record_flag_creates_parent_dir(tmp_path):
    path = tmp_path / "sub" / "flags.jsonl"
    record_flag("Chal", "FLAG{a}", log_path=str(path))
    assert path.exists()
