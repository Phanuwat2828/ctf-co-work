"""Technique playbooks — category/tag-matched CTF know-how injected into the
solver system prompt.

Each playbook lives in its own Markdown file under ``skills/`` (project root)
with a YAML frontmatter block:

    ---
    name: Cryptography
    categories: [crypto]
    tags: [crypto, rsa, xor, cipher]
    ---

    <playbook body — bullet-list markdown>

``match_skills`` picks playbooks by challenge category/tag (substring match,
case-insensitive) and ``render_skills_section`` turns the matched set into the
"## Technique Playbook" section of the system prompt. ``prompts.py`` does the
injection, so all three solver backends pick these up automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Skills live next to the repo root (sibling of backend/) so they are easy to
# browse/edit. Falls back to a skills/ dir packaged inside the backend package.
SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


@dataclass
class Skill:
    name: str
    match_categories: tuple[str, ...]
    match_tags: tuple[str, ...] = field(default_factory=tuple)
    playbook: str = ""


def _to_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return [str(v) for v in value if str(v).strip()]


def _parse_skill_file(path: Path) -> Skill:
    """Parse one .md file into a Skill (YAML frontmatter + markdown body)."""
    text = path.read_text(encoding="utf-8")
    meta: dict[str, Any] = {}
    body = text.strip()

    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for end in range(1, len(lines)):
            if lines[end].strip() == "---":
                fm_text = "\n".join(lines[1:end])
                try:
                    parsed = yaml.safe_load(fm_text)
                    if isinstance(parsed, dict):
                        meta = parsed
                except yaml.YAMLError:
                    meta = {}
                body = "\n".join(lines[end + 1:]).strip()
                break

    return Skill(
        name=str(meta.get("name") or path.stem).strip(),
        match_categories=tuple(c.lower() for c in _to_str_list(meta.get("categories"))),
        match_tags=tuple(t.lower() for t in _to_str_list(meta.get("tags"))),
        playbook=body,
    )


def load_skills_from(skills_dir: str | Path = SKILLS_DIR) -> list[Skill]:
    """Load every *.md playbook in a directory (sorted by filename)."""
    directory = Path(skills_dir)
    if not directory.is_dir():
        return []
    return [_parse_skill_file(path) for path in sorted(directory.glob("*.md"))]


SKILLS: list[Skill] = load_skills_from()


def match_skills(category: str, tags: list[str] | None = None) -> list[Skill]:
    """Return all skills whose category/tag patterns match the challenge's category or tags."""
    cat_lower = (category or "").lower()
    tags_lower = [t.lower() for t in (tags or [])]

    matched: list[Skill] = []
    for skill in SKILLS:
        cat_hit = any(pat in cat_lower for pat in skill.match_categories)
        tag_hit = any(pat in tag for tag in tags_lower for pat in skill.match_tags)
        if cat_hit or tag_hit:
            matched.append(skill)
    return matched


def render_skills_section(skills: list[Skill]) -> str:
    """Render matched skills as a Markdown section for the system prompt. Empty string if none."""
    if not skills:
        return ""

    lines = ["## Technique Playbook", ""]
    for skill in skills:
        lines.append(f"### {skill.name}")
        lines.append(skill.playbook)
        lines.append("")
    return "\n".join(lines).rstrip()
