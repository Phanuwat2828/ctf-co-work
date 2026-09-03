"""Tests for backend.skills — category/tag matching and prompt rendering."""

from backend.skills import match_skills, render_skills_section


def test_match_by_category_direct():
    skills = match_skills("Cryptography", [])
    names = {s.name for s in skills}
    assert "Cryptography" in names


def test_web_and_pwn_categories_do_not_cross_match():
    web_skills = {s.name for s in match_skills("Web Exploitation", [])}
    pwn_skills = {s.name for s in match_skills("Binary Exploitation", [])}

    assert "Web Exploitation" in web_skills
    assert "Binary Exploitation (Pwn)" not in web_skills

    assert "Binary Exploitation (Pwn)" in pwn_skills
    assert "Web Exploitation" not in pwn_skills


def test_match_by_tag_when_category_unrelated():
    skills = match_skills("Misc", ["rsa"])
    names = {s.name for s in skills}
    assert "Cryptography" in names


def test_unknown_category_and_no_tags_returns_empty():
    assert match_skills("Some Unknown Category", []) == []
    assert match_skills("", []) == []


def test_render_skills_section_empty_when_no_skills():
    assert render_skills_section([]) == ""


def test_render_skills_section_includes_heading_and_names():
    skills = match_skills("Forensics", [])
    section = render_skills_section(skills)
    assert "## Technique Playbook" in section
    assert "Forensics" in section
