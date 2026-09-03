"""Tests for skill-library usage detection + reminder logic in the tool wrapper."""

from __future__ import annotations

from backend.agents.solver import SKILL_REMINDER, tool_accesses_skills


def test_tool_accesses_skills_bash_cat():
    assert tool_accesses_skills({"command": "cat /challenge/skills/hunt-xxe.md"})
    assert tool_accesses_skills({"command": "grep -i xxe /challenge/skills/INDEX.txt"})
    assert tool_accesses_skills("cat /challenge/skills/x.md")


def test_tool_accesses_skills_false_for_normal_tools():
    assert not tool_accesses_skills({"command": "ls -la /challenge/distfiles"})
    assert not tool_accesses_skills({"command": "curl http://example.com"})
    assert not tool_accesses_skills({"path": "/challenge/distfiles/a.txt"})


def test_reminder_message_mentions_index_and_cat():
    assert "/challenge/skills/INDEX.txt" in SKILL_REMINDER
    assert "cat" in SKILL_REMINDER
