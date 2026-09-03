---
name: ctf-flag-reporter
description: Format final answers for CTF, bug bounty lab, wargame, crackme, reversing, pwn, web, crypto, forensics, OSINT, and challenge-solving tasks after a flag, token, proof string, solve key, or answer is found. Use when reporting any CTF result so the response includes the real platform challenge name, category, solved status, Thai labels by default, and an easy-to-copy flag block.
---

# CTF Flag Reporter

## Purpose

Use this skill when a CTF-style task reaches a solved state or a likely flag is discovered. Make the final answer easy to scan and easy to copy, while preserving enough context to identify which challenge the flag belongs to.

## Invocation

- This skill is mandatory before the final CTF response after an exact flag, proof string, token, solve key, or final answer is found.
- The solver should reveal the exact value immediately after evidence confirms it; invoke this skill afterward to produce the final structured report.

## Rules

- Never invent, normalize, or "fix" a flag. Preserve exact case, punctuation, braces, prefixes, and whitespace unless evidence proves decoding or trimming is required.
- If the flag is confirmed, say so directly and place it in its own fenced code block labeled `text`.
- If the flag is only suspected, label it as suspected and explain what evidence is missing.
- If multiple flags are found, report each separately with challenge name or stage.
- Use Thai labels and Thai proof text by default. Use another language only when the user explicitly asks for it.
- Keep writeups short unless the user asks for detail.
- Include command output, file path, endpoint, payload, or reasoning only when it helps verify where the flag came from.
- Do not bury the flag inside prose, tables, long logs, or screenshots.

## Final Answer Format

For one solved challenge, use:

````markdown
**แก้ได้แล้ว**
โจทย์: <real platform challenge name or "ไม่ทราบชื่อโจทย์">
หมวด: <web|pwn|crypto|forensics|rev|misc|osint|unknown>

Flag:
```text
<exact-flag>
```

หลักฐาน: <one short Thai sentence on where/how it was obtained>
````

For multiple flags, use:

````markdown
**แก้ได้แล้ว**
พบ <n> flags.

โจทย์: <real platform challenge name or stage>
หมวด: <category>

Flag:
```text
<exact-flag-1>
```

หลักฐาน: <one short Thai sentence>

โจทย์: <real platform challenge name or stage>
หมวด: <category>

Flag:
```text
<exact-flag-2>
```

หลักฐาน: <one short Thai sentence>
````

For suspected flags, use:

````markdown
**น่าจะเป็น Flag**
โจทย์: <real platform challenge name or "ไม่ทราบชื่อโจทย์">
หมวด: <category or "unknown">

ตัวเลือก:
```text
<exact-candidate>
```

เหตุผล: <short Thai evidence>
ต้องยืนยัน: <missing check>
````

## Challenge Identity

Choose challenge name with this priority:

1. Explicit user-provided challenge title or platform challenge card title.
2. Challenge title near CTF metadata such as points, likes, author, category, prompt text, or flag input.
3. Directory/archive/file name that clearly names the challenge.
4. Page title, HTML title, banner, service name, or in-app heading.
5. `ไม่ทราบชื่อโจทย์`.

Do not prefer a target website page title over a CTF platform title. Example: if the context contains `Waiting Room` in the web page and also `Eternity100` as the challenge card title, report `โจทย์: Eternity100`, not `Waiting Room`.

Infer category from user text, platform metadata, challenge URL, filenames, or solve technique. If not available, use `unknown`; do not ask user unless it blocks solving.

## Copyability

Always put only the flag string inside the fenced code block. No quotes, bullets, prompts, `$`, labels, trailing comments, or extra whitespace inside the block.

## Discord Webhook Report

This skill now reports through the local CTF Flag Service first. The service stores every flag in SQLite, counts duplicates, then sends Discord webhook output.

Default local service endpoint:

```text
http://127.0.0.1:8765/api/report
```

Optional config in `~/.config/opencode/ctf-flag-reporter.json`:

```json
{
  "ctf_flag_service_url": "http://127.0.0.1:8765/api/report",
  "ctf_flag_service_token": "OPTIONAL_API_TOKEN"
}
```

`CTF_FLAG_SERVICE_URL` and `CTF_FLAG_SERVICE_TOKEN` override config for one run. Reporter name defaults to `socket.gethostname()`; `CTF_REPORTER_NAME` can override it if explicitly needed.

After an exact flag is confirmed and shown to user, run this before final response:

```bash
python3 ~/.agents/skills/ctf-flag-reporter/scripts/discord_report.py \
  --challenge "<challenge name>" \
  --category "<category>" \
  --flag "<exact flag>" \
  --summary "<short Thai solve summary>"
```

The script posts to CTF Flag Service. The service returns duplicate count, report id, and Discord webhook status. Do not send suspected flags.
