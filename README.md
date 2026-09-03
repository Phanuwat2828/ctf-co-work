# CTF Agent (ctf-co-work)

A self-hosted CTF solving agent. A **coordinator** watches a CTFd platform and
spawns **swarms** of AI solvers against each challenge — every solver runs in its
own isolated Docker sandbox and races to be the first to submit a correct flag.

## Highlights

- **Multi-model swarm** — several models attack one challenge at once; first to
  confirm the flag wins, the rest are stopped.
- **Coordinator LLM** — reads solver traces and can guide strategy, spawn swarms,
  broadcast hints, and keep retrying until a flag is found.
- **Role-split swarms** — an optional planner LLM divides agents by attack
  strategy (recon, exploit, crypto…), with configurable agent count; models may
  be reused across roles.
- **On-demand skill library** — hundreds of technique playbooks are mounted into
  each sandbox (`/challenge/skills`); the solver greps an index and reads only
  the skills it needs. Category-matched short playbooks are also injected
  automatically from `skills/`.
- **Web dashboard** — live status per challenge/swarm, trace viewer, chat with
  the coordinator, spawn/kill/broadcast/bump controls, "keep trying until flag",
  provider testing, and a **wrong-flag → retry reading previous logs** flow.
- **Flag safety** — confirmed flags are written to `logs/flags.jsonl` and shown
  on the dashboard (with one-click copy), so a solved challenge is never lost.
- **Optional hardening** — dashboard bearer token and a total spend cap.

## How it runs

```
CTFd platform
   │  (polls every ~5s)
Coordinator (LLM) + web dashboard (http://127.0.0.1:9400)
   │
   ├── swarm per challenge (several solvers, each in its own Docker sandbox)
   └── flag confirmed → logged + shown on dashboard
```

## Quick start

```bash
# 1. Install deps (Python 3.14+ with uv)
uv sync

# 2. Build the solver sandbox image (Kali-based, pre-loaded with CTF tools)
docker build -f sandbox/Dockerfile.sandbox -t ctf-sandbox .

# 3. Configure credentials
cp .env.example .env     # add CTFd URL/token + model API keys

# 4. Run (coordinator + web dashboard)
./run.sh                 # dashboard at http://127.0.0.1:9400
```

Optional add-ons:

```bash
# Interactive Kali box (separate image kali-ctf) for manual work
cd sandbox-kali && docker compose up -d --build

# Import the on-demand CTF skill library (from a local skill collection)
uv run python import_skills.py
```

## Dashboard

- Top bar: auto-spawn toggle, logs, providers, settings.
- Challenge table: status, flag (copy), trace, spawn, keep-trying toggle,
  broadcast/bump/kill, and "❌ flag ผิด" to mark a reported flag wrong and retry.
- Spawn modal: pick models, or enable **“Let AI split roles”** (agent count +
  optional planner instruction).
- Providers panel: manage API providers (OpenAI/Anthropic/Google/custom) and
  test each one with a real chat message.

More (including troubleshooting) in [RUN_GUIDE.md](RUN_GUIDE.md).

## Model backends

Solvers can run through:

- **Claude SDK** (`claude-sdk/…`) — subscription-first
- **Codex CLI** (`codex/…`) — subscription-first
- **API models** — Bedrock, Azure OpenAI, Zen, Google, and custom
  OpenAI-compatible / Anthropic-proxy providers (`providers.json`)

## Tests

```bash
uv run pytest tests/ -q
```

## Acknowledgements

- [es3n1n/Eruditus](https://github.com/es3n1n/Eruditus) — CTFd interaction and
  HTML helpers in `pull_challenges.py`.

## License

[MIT](LICENSE)
