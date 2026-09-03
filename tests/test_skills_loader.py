"""Tests for loading technique playbooks from the skills/*.md folder."""

from __future__ import annotations

import backend.skills as skills_mod
from backend.skills import load_skills_from


def test_skill_folder_is_loaded_and_nonempty():
    skills = load_skills_from(skills_mod.SKILLS_DIR)
    names = [s.name for s in skills]
    # The bundled folder ships with the 7 core playbooks.
    assert {"Cryptography", "Web Exploitation", "Forensics"} <= set(names)
    assert all(s.playbook.strip() for s in skills), "every playbook needs a body"


def test_frontmatter_metadata_is_parsed():
    crypto = next(s for s in load_skills_from(skills_mod.SKILLS_DIR) if s.name == "Cryptography")
    assert "crypto" in crypto.match_categories
    assert "rsa" in crypto.match_tags
    assert "RsaCtfTool" in crypto.playbook


def test_loader_reads_new_md_file(tmp_path):
    (tmp_path / "zz-test-skill.md").write_text(
        "---\n"
        "name: Test Skill\n"
        "categories:\n"
        "  - testcat\n"
        "tags: [testtag]\n"
        "---\n"
        "\n"
        "- some guidance\n"
    )
    skills = load_skills_from(tmp_path)
    assert len(skills) == 1
    s = skills[0]
    assert s.name == "Test Skill"
    assert s.match_categories == ("testcat",)
    assert s.match_tags == ("testtag",)
    assert s.playbook == "- some guidance"


def test_loader_missing_directory_returns_empty(tmp_path):
    assert load_skills_from(tmp_path / "nope") == []


def test_loader_ignores_non_md_files(tmp_path):
    (tmp_path / "readme.md").write_text("not a skill")
    (tmp_path / "notes.txt").write_text("ignored")
    assert len(load_skills_from(tmp_path)) == 1  # only readme.md parsed
