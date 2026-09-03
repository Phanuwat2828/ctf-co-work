#!/usr/bin/env bash
# CTF Agent launcher — build sandbox image (if needed) + run the coordinator.
#
# Usage:
#   ./run.sh                     # build image (if missing) + run coordinator
#   ./run.sh --no-build          # skip image build/check
#   ./run.sh --single <dir>      # solve a single local challenge directory
#   ./run.sh --ctfd-url URL --ctfd-token TOKEN --max-challenges 5
#   ./run.sh --build-only        # only build the sandbox image, then exit
#   ./run.sh --reset             # wipe config/logs/challenges, then start fresh
#
# Env overrides:
#   CTF_AGENT_IMAGE   docker image name (default: ctf-sandbox)
#   CTF_NO_BUILD=1    same as --no-build

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

IMAGE_NAME="${CTF_AGENT_IMAGE:-ctf-sandbox}"
BUILD_IMAGE=true
BUILD_ONLY=false
RESET=false
declare -a PASS_ARGS=()

for arg in "$@"; do
  case "$arg" in
    --no-build) BUILD_IMAGE=false ;;
    --build-only) BUILD_IMAGE=true; BUILD_ONLY=true ;;
    --reset) RESET=true ;;
    --single)
      BUILD_IMAGE=true
      PASS_ARGS+=("$arg")
      ;;
    *) PASS_ARGS+=("$arg") ;;
  esac
done

c_green=$'\e[32m'; c_yellow=$'\e[33m'; c_red=$'\e[31m'; c_dim=$'\e[2m'; c_reset=$'\e[0m'
info()  { echo "${c_green}[ctf-agent]${c_reset} $*"; }
warn()  { echo "${c_yellow}[ctf-agent]${c_reset} $*"; }
die()   { echo "${c_red}[ctf-agent] ERROR:${c_reset} $*" >&2; exit 1; }

# ── Docker ────────────────────────────────────────────────────────────────────
if ! command -v docker >/dev/null 2>&1; then
  die "docker not found. Install Docker first."
fi

# ── Reset: wipe config/logs/challenges + orphan containers ────────────────────
if [ "$RESET" = true ]; then
  warn "Resetting: removing .env, providers.json, logs/, challenges/ and orphan containers…"
  pkill -f "ctf-solve" 2>/dev/null
  sleep 1
  rm -f .env providers.json
  rm -rf logs challenges
  if docker info >/dev/null 2>&1; then
    docker ps -aq --filter label=ctf-agent 2>/dev/null | xargs -r docker rm -f 2>/dev/null
  fi
  info "Reset complete — starting fresh."
fi

if ! docker info >/dev/null 2>&1; then
  die "Cannot connect to Docker daemon. Check that it is running and your user is in the 'docker' group (run: sudo usermod -aG docker \$USER, then re-login)."
fi

# ── uv ────────────────────────────────────────────────────────────────────────
if ! command -v uv >/dev/null 2>&1; then
  warn "uv not found — installing it now…"
  if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
    die "Failed to install uv. Install it manually:  curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi
  # uv installs to ~/.local/bin — make sure it's on PATH for this run
  export PATH="$HOME/.local/bin:$PATH"
fi

# ── .env ──────────────────────────────────────────────────────────────────────
if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env from .env.example — EDIT IT with your CTFd URL/token and API keys before running."
fi

# ── Dependencies ───────────────────────────────────────────────────────────────
info "Installing Python dependencies (uv sync)…"
uv sync --quiet

# ── Sandbox image ─────────────────────────────────────────────────────────────
if [ "$BUILD_IMAGE" = true ]; then
  if docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    info "Sandbox image '$IMAGE_NAME' already present — skipping build."
  else
    info "Building sandbox image '$IMAGE_NAME' (this can take a long time)…"
    docker build -f sandbox/Dockerfile.sandbox -t "$IMAGE_NAME" .
  fi
fi

if [ "$BUILD_ONLY" = true ]; then
  info "Image ready: $IMAGE_NAME"
  exit 0
fi

# ── Run ────────────────────────────────────────────────────────────────────────
if [ ${#PASS_ARGS[@]} -gt 0 ]; then
  info "Running: uv run ctf-solve ${PASS_ARGS[*]}"
else
  info "Running coordinator…  (web dashboard: http://127.0.0.1:9400 — Ctrl+C to stop)"
fi

exec uv run ctf-solve "${PASS_ARGS[@]}"