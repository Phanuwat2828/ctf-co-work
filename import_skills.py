"""One-shot importer: copy CTF-relevant skills from a downloaded skill library
into ./agent_skills (name.md each) and build INDEX.txt for on-demand use.

Usage:
    uv run python import_skills.py [SOURCE_DIR] [--out agent_skills] [--dry-run]

The source layout is expected to be:  SOURCE/<skill-name>/SKILL.md
(default source: ~/Downloads/Users/k1god/.agents/skills)

Selection is by filename allowlist — skills whose names match CTF solving work
(web/API exploitation, reverse/binary, forensics artifacts, OSINT, LLM testing).
Everything else in the source (SOC/detection/GRC/enterprise defense) is skipped.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Substrings/keywords that mark a skill as CTF-solve relevant (matched against
# the folder name, lowercased).
CTF_KEYWORDS: list[str] = [
    # web / api / injection
    "xss", "xxe", "ssrf", "csrf", "injection", "sqli", "sql-injection", "oauth",
    "jwt", "api-", "graphql", "deserialization", "burp", "spring", "nodejs",
    "hunt-", "web-", "authentication", "authorization", "idor", "file-upload",
    "cors", "csrf", "rce", "lfi", "rfi", "smuggling", "csrf", "websocket",
    "rate-limiting-bypass", "postman", "dependency-confusion", "xml",
    # reverse / binary / exploit
    "reverse-engineering", "ghidra", "ida", "angr", "binary-analysis", "radare",
    "shellcode", "buffer-overflow", "heap-", "stack-", "exploit", "pwntools",
    "deobfusc", "obfuscat", "unpack", "golang-malware", "rust-malware",
    "elf-", "pe-", "apk", "smali", "dex", "android", "ios-app", "objection",
    "crackme", "keygen", "ctf", "pwn",
    # forensics / artifact analysis (solver-useful subset)
    "forensic", "analyzing-", "wireshark", "network-forensics", "packet",
    "volatility", "mft", "memory-", "disk-image", "deleted-file", "autopsy",
    "timeline", "artifact", "steganograph", "exif", "recovery",
    # crypto
    "crypt", "rsa", "cipher", "hash", "aes", "xor", "encod",
    # osint
    "osint", "dns-enumeration", "subdomain", "certificate-transparency",
    "urlscan", "shodan", "dnstwist",
    # llm / ai security
    "prompt-injection", "llm", "rag-", "garak", "ai-threat", "red-team-llm",
    "vector-and-embedding",
]

# Explicit skips that slip through broad keywords (enterprise-defense heavy).
SKIP_IF_CONTAINS: list[str] = [
    "detecting-", "hunting-for-", "hunting-", "building-", "implementing-",
    "configuring-", "securing-", "remediating-", "performing-access", "deploying-",
    "analyzing-aws", "analyzing-azure", "analyzing-kubernetes", "analyzing-linux",
    "analyzing-windows", "analyzing-cloud", "analyzing-dns", "analyzing-email",
    "analyzing-malware", "analyzing-cobalt", "analyzing-command", "monitoring-",
    "conducting-", "generating-", "processing-", "executing-", "assessing-",
    "achieving-", "acquiring-", "achieving-", "automating-", "emulating-",
    "investigating-", "red-teaming-llms", "wifi-password", "ssl-stripping",
    "physical-", "phishing-simulation", "credentials", "lazagne",
]

# Allow specific analyzing-* artifact/forensics skills that ARE useful even
# though the generic "analyzing-" pattern is skipped above.
_ANALYZING_CTF_OK = [
    "analyzing-mft-for-deleted-file-recovery", "analyzing-prefetch-files-for-execution-history",
    "analyzing-disk-image", "analyzing-browser-forensics", "analyzing-usb-device-connection-history",
    "analyzing-windows-amcache-artifacts", "analyzing-lnk-file-and-jump-list-artifacts",
]


def is_ctf_skill(name: str) -> bool:
    """True when a skill folder name looks relevant to CTF solving."""
    low = name.lower()
    if any(k in low for k in SKIP_IF_CONTAINS) and name.lower() not in _ANALYZING_CTF_OK:
        return False
    if name.lower() in _ANALYZING_CTF_OK:
        return True
    return any(k in low for k in CTF_KEYWORDS)


def _first_line(text: str, limit: int = 220) -> str:
    text = text.strip().replace("\n", " ").replace("\t", " ")
    text = re.sub(r"\s+", " ", text)
    return text[:limit]


def _description_from_md(text: str) -> str:
    """Pull the 'description:' value from YAML frontmatter (best effort)."""
    m = re.search(r"(?ms)^description:\s*(.+?)(?:^[a-z_]+:|^---)", text)
    if not m:
        return ""
    return _first_line(m.group(1).strip())


def import_skills(source: Path, out: Path, dry_run: bool = False) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    picked: list[tuple[str, str]] = []  # (name, description)
    skipped = 0
    total_bytes = 0
    seen: set[str] = set()

    for skill_dir in sorted(p for p in source.iterdir() if p.is_dir()):
        md = skill_dir / "SKILL.md"
        name = skill_dir.name
        if not md.exists() or not is_ctf_skill(name):
            skipped += 1
            continue
        if name in seen:
            continue
        seen.add(name)
        text = md.read_text(encoding="utf-8", errors="replace")
        desc = _description_from_md(text) or _first_line(text[:400])
        picked.append((name, desc))
        total_bytes += len(text.encode("utf-8"))
        if not dry_run:
            (out / f"{name}.md").write_text(text, encoding="utf-8")

    if not dry_run:
        # Index lines name the actual file (with .md) so `cat <name>.md` works.
        index_lines = [f"{name}.md\t{desc}" for name, desc in picked]
        (out / "INDEX.txt").write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    return {
        "picked": len(picked),
        "skipped": skipped,
        "bytes": total_bytes,
        "out": str(out),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Import CTF-relevant skills into agent_skills/")
    ap.add_argument("source", nargs="?", default=str(Path.home() / "Downloads/Users/k1god/.agents/skills"))
    ap.add_argument("--out", default="agent_skills")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    src = Path(args.source).expanduser()
    if not src.is_dir():
        print(f"Source not found: {src}", file=sys.stderr)
        return 1

    result = import_skills(src, Path(args.out), dry_run=args.dry_run)
    print(
        f"{'[dry-run] ' if args.dry_run else ''}"
        f"picked {result['picked']} skills ({result['bytes'] / 1024:.0f} KB) "
        f"-> {result['out']}; skipped {result['skipped']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
