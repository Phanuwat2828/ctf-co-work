"""Tests for the on-demand skill library import filter and prompt wiring."""

from __future__ import annotations

import import_skills
from backend.prompts import ChallengeMeta, build_prompt, skill_library_lines


def test_filter_keeps_ctf_relevant():
    assert import_skills.is_ctf_skill("hunt-xxe")
    assert import_skills.is_ctf_skill("performing-ssrf-vulnerability-exploitation")
    assert import_skills.is_ctf_skill("testing-xss-vulnerabilities")
    assert import_skills.is_ctf_skill("reverse-engineering-rust-malware")
    assert import_skills.is_ctf_skill("osint")


def test_filter_skips_defensive_enterprise_work():
    assert not import_skills.is_ctf_skill("building-detection-rule-with-splunk-spl")
    assert not import_skills.is_ctf_skill("implementing-aws-macie-for-data-classification")
    assert not import_skills.is_ctf_skill("achieving-cmmc-level-2-compliance")


def test_skill_library_lines_empty_without_index(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_SKILLS_DIR", str(tmp_path / "missing"))
    assert skill_library_lines() == []


def test_skill_library_lines_present_with_index(tmp_path, monkeypatch):
    (tmp_path / "INDEX.txt").write_text("hunt-xxe\tdesc\n", encoding="utf-8")
    monkeypatch.setenv("CTF_SKILLS_DIR", str(tmp_path))
    lines = skill_library_lines()
    assert any("Skill Library" in line for line in lines)
    assert any("/challenge/skills/INDEX.txt" in line for line in lines)


def test_build_prompt_includes_skill_library_section(tmp_path, monkeypatch):
    (tmp_path / "INDEX.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("CTF_SKILLS_DIR", str(tmp_path))
    meta = ChallengeMeta(name="C", category="web", description="d")
    prompt = build_prompt(meta, [], container_arch="x86_64")
    assert "## Skill Library" in prompt
    assert "/challenge/skills/" in prompt


def test_build_prompt_tells_agent_to_start_with_category_skills(tmp_path, monkeypatch):
    (tmp_path / "INDEX.txt").write_text("x\n", encoding="utf-8")
    monkeypatch.setenv("CTF_SKILLS_DIR", str(tmp_path))
    meta = ChallengeMeta(name="C", category="Cryptography", tags=["rsa"], description="d")
    prompt = build_prompt(meta, [], container_arch="x86_64")
    assert "START by reading" in prompt
    # crypto category keywords must appear in the grep hint
    assert "rsa" in prompt
    assert "grep -i -E" in prompt


def test_build_prompt_without_library_has_no_section(tmp_path, monkeypatch):
    monkeypatch.setenv("CTF_SKILLS_DIR", str(tmp_path / "nope"))
    meta = ChallengeMeta(name="C", category="web", description="d")
    prompt = build_prompt(meta, [], container_arch="x86_64")
    assert "## Skill Library" not in prompt
