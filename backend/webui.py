"""Web dashboard + control API for the CTF coordinator (aiohttp).

Serves a single-page UI at ``/`` that shows live swarm/agent/challenge status,
lets the operator send chat commands (POST /api/msg -> operator inbox), and
directly controls swarms (spawn / kill / broadcast / bump / view trace).

Started from ``backend.agents.coordinator_loop.run_event_loop`` so it shares
the live ``CoordinatorDeps`` and poller state.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from aiohttp import web

import httpx

logger = logging.getLogger(__name__)

INDEX_HTML_PATH = Path(__file__).parent / "webui" / "index.html"

_docker_cache: tuple[float, bool] = (0.0, True)  # (checked_at, ok)


async def _docker_available() -> bool:
    """Cheap check that the Docker daemon is reachable (cached 10s)."""
    import time as _time

    global _docker_cache
    now = _time.monotonic()
    if now - _docker_cache[0] < 10:
        return _docker_cache[1]
    try:
        import aiodocker

        docker = aiodocker.Docker()
        try:
            await docker.ping()
            ok = True
        finally:
            await docker.close()
    except Exception:
        ok = False
    _docker_cache = (now, ok)
    return ok

CONFIG_FIELDS = (
    "ctfd_url",
    "ctfd_token",
    "ctfd_user",
    "ctfd_pass",
    "ctfd_session_cookie",
    "anthropic_api_key",
    "openai_api_key",
    "gemini_api_key",
    "azure_openai_endpoint",
    "azure_openai_api_key",
    "opencode_zen_api_key",
    "aws_bearer_token",
)

SECRET_FIELDS = {
    "ctfd_token",
    "ctfd_pass",
    "ctfd_session_cookie",
    "anthropic_api_key",
    "openai_api_key",
    "gemini_api_key",
    "azure_openai_api_key",
    "opencode_zen_api_key",
    "aws_bearer_token",
}


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "••••"
    return value[:4] + "…" + value[-4:]


def _request_token(request: web.Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[len("Bearer "):].strip()
    return request.query.get("token", "").strip()


@web.middleware
async def _auth_middleware(request: web.Request, handler: Any) -> web.StreamResponse:
    """Require a Bearer token on every route except the index page, when
    settings.webui_token is set. Empty token (default) disables auth entirely."""
    deps = request.app.get("deps")
    expected = getattr(getattr(deps, "settings", None), "webui_token", "") if deps else ""
    if not expected or request.path == "/":
        return await handler(request)
    if _request_token(request) != expected:
        return web.json_response({"ok": False, "error": "unauthorized"}, status=401)
    return await handler(request)


def _write_env(deps: Any) -> None:
    """Persist current settings back to .env (preserving comments/unknown lines)."""
    from backend.config import Settings

    path = Path(deps.challenges_root).parent / ".env"
    if not path.exists():
        path = Path(".env")
    field_names = {f.upper() for f in Settings.model_fields}
    try:
        existing = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        existing = []
    kept = []
    for line in existing:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and stripped.split("=", 1)[0].strip().upper() in field_names:
            continue
        kept.append(line)
    lines = [ln for ln in kept if ln.strip()] + [""]
    for field in Settings.model_fields:
        lines.append(f"{field.upper()}={getattr(deps.settings, field)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _apply_api_keys_to_env(deps: Any) -> None:
    s = deps.settings
    os.environ["ANTHROPIC_API_KEY"] = s.anthropic_api_key or ""
    os.environ["OPENAI_API_KEY"] = s.openai_api_key or ""
    os.environ["GEMINI_API_KEY"] = s.gemini_api_key or ""
    os.environ["AZURE_OPENAI_ENDPOINT"] = s.azure_openai_endpoint or ""
    os.environ["AZURE_OPENAI_API_KEY"] = s.azure_openai_api_key or ""
    os.environ["OPENCODE_ZEN_API_KEY"] = s.opencode_zen_api_key or ""


def _config_status(deps: Any) -> dict[str, bool]:
    s = deps.settings
    ctfd_ok = bool(
        s.ctfd_url
        and not s.ctfd_url.rstrip("/").startswith(("http://localhost", "https://ctf.example"))
        and (s.ctfd_token or s.ctfd_session_cookie or (s.ctfd_user and s.ctfd_pass))
    )
    return {
        "ctfd": ctfd_ok,
        "anthropic": bool(s.anthropic_api_key),
        "openai": bool(s.openai_api_key),
        "gemini": bool(s.gemini_api_key),
    }


def _has_model_keys(deps: Any) -> bool:
    s = deps.settings
    if bool(
        s.anthropic_api_key
        or s.openai_api_key
        or s.gemini_api_key
        or s.azure_openai_api_key
        or s.opencode_zen_api_key
        or s.aws_bearer_token
    ):
        return True
    from backend.providers import has_any_key
    return has_any_key()


def _sync_provider_settings(deps: Any) -> None:
    """Push provider keys/base URLs into Settings + env + .env and recompute
    the model-spec lineup so swarms reflect the provider list."""
    from backend.providers import load_providers, model_specs_from_providers

    providers = load_providers()
    s = deps.settings
    for p in providers:
        if p.kind == "claude-sdk":
            s.anthropic_api_key = p.api_key
        elif p.kind == "codex":
            s.openai_api_key = p.api_key
        elif p.kind == "google":
            s.gemini_api_key = p.api_key
        elif p.kind == "azure":
            s.azure_openai_api_key = p.api_key
            if p.base_url:
                s.azure_openai_endpoint = p.base_url
        elif p.kind == "zen":
            s.opencode_zen_api_key = p.api_key
        elif p.kind == "bedrock":
            s.aws_bearer_token = p.api_key
    _apply_api_keys_to_env(deps)
    deps.model_specs = model_specs_from_providers(providers)
    _write_env(deps)
    logger.info("Providers synced -> %d model specs", len(deps.model_specs))


# Provider base URLs (shown in the test panel)


async def _test_ctfd(url: str, token: str, user: str, password: str, session_cookie: str = "") -> dict:
    if not url or url.rstrip("/").startswith(("http://localhost", "https://ctf.example")):
        return {"ok": False, "base_url": url, "detail": "CTFd URL not set yet."}
    from backend.ctfd import CTFdClient
    client = CTFdClient(
        base_url=url, token=token, username=user, password=password,
        session_cookie=session_cookie,
    )
    try:
        stubs = await client.fetch_challenge_stubs()
        auth = "session cookie" if session_cookie else ("token" if token else "user/pass")
        return {"ok": True, "base_url": url, "detail": f"connected via {auth} — {len(stubs)} challenges visible"}
    except Exception as e:
        detail = str(e)[:300]
        if "401" in detail or "403" in detail:
            detail = "authentication failed (bad " + ("session cookie" if session_cookie else "token/credentials") + "): " + detail
        return {"ok": False, "base_url": url, "detail": detail}
    finally:
        await client.close()


async def _test_bearer(base_url: str, path: str, headers: dict, expect_json: bool = False) -> dict:
    try:
        async with httpx.AsyncClient(timeout=15, verify=False) as c:
            r = await c.get(base_url + path, headers=headers)
        if r.status_code in (401, 403):
            return {"ok": False, "base_url": base_url, "detail": "invalid key (HTTP " + str(r.status_code) + ")"}
        if expect_json:
            ct = r.headers.get("content-type", "")
            if "json" not in ct:
                return {"ok": False, "base_url": base_url,
                        "detail": f"endpoint returned {ct or 'non-JSON'} — check base_url (may need a /v1 path)"}
        if r.status_code == 200:
            return {"ok": True, "base_url": base_url, "detail": "key valid"}
        return {"ok": True, "base_url": base_url, "detail": f"key looks valid (HTTP {r.status_code})"}
    except Exception as e:
        return {"ok": False, "base_url": base_url, "detail": str(e)[:300]}


async def _test_anthropic_message(base: str, api_key: str, model: str = "claude-3-5-haiku-latest") -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(
                base + "/v1/messages",
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                json={"model": model, "max_tokens": 1, "messages": [{"role": "user", "content": "hi"}]},
            )
        if r.status_code in (401, 403):
            return {"ok": False, "base_url": base, "detail": f"invalid key (HTTP {r.status_code})"}
        return {"ok": True, "base_url": base, "detail": f"key valid (HTTP {r.status_code})"}
    except Exception as e:
        return {"ok": False, "base_url": base, "detail": str(e)[:200]}


async def _test_custom_openai(base: str, api_key: str) -> dict:
    """Test an OpenAI-compatible endpoint; auto-try the /v1 variant and
    report the working base_url when the given one returns HTML."""
    headers = {"Authorization": "Bearer " + api_key}
    result = await _test_bearer(base, "/models", headers, expect_json=True)
    if result["ok"]:
        return result
    if not base.rstrip("/").endswith("/v1"):
        alt = base.rstrip("/") + "/v1"
        alt_result = await _test_bearer(alt, "/models", headers, expect_json=True)
        if alt_result["ok"]:
            alt_result["detail"] = "key valid — set base_url to: " + alt
            return alt_result
    return result


# Short, cheap ping the model must answer for a real end-to-end test.
TEST_CHAT_PROMPT = "Reply with exactly: pong"
# 64 tokens so reasoning models still have room to emit visible text after
# their chain-of-thought (8 was too small -> empty content on capable models).
TEST_CHAT_MAX_TOKENS = 64


async def _post_chat_completions(url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None) -> tuple[httpx.Response | None, str]:
    """POST a tiny chat-completions message. Returns (response, endpoint_used).

    `client` is only used by tests to inject a mocked transport; when provided,
    its lifecycle is owned by the caller (it may be reused across attempts).
    """
    if client is None:
        # Production: a fresh client per attempt, closed after the request.
        async with httpx.AsyncClient(timeout=20, verify=False) as c:
            r = await c.post(
                url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "max_tokens": TEST_CHAT_MAX_TOKENS,
                    "messages": [{"role": "user", "content": TEST_CHAT_PROMPT}],
                },
            )
    else:
        # Test injection: the caller owns the client and may reuse it across attempts.
        r = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "max_tokens": TEST_CHAT_MAX_TOKENS,
                "messages": [{"role": "user", "content": TEST_CHAT_PROMPT}],
            },
        )
    return r, url


def _chat_reply_text(data: Any) -> str:
    """Extract the assistant's text from an OpenAI chat-completions response.

    Checks `content` first, then `reasoning_content` — reasoning models (e.g.
    DeepSeek-reasoner) put their visible answer in reasoning_content while
    `content` may be empty when the token budget runs out.
    """
    try:
        message = data["choices"][0]["message"]
    except Exception:
        return ""
    for field in ("content", "reasoning_content"):
        value = message.get(field)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


async def _test_openai_chat_message(
    base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None
) -> dict:
    """Send a real chat message to {base}/chat/completions and check the reply.

    Verifies both the endpoint path (e.g. whether the base needs a /v1 segment —
    pydantic-ai posts to {base_url}/chat/completions with no auto /v1) and that
    the endpoint/key/format work. A valid chat-completions response counts as
    success even when the message text is empty (some models return only
    reasoning, or no text for a tiny prompt) — the point is path + auth, not
    judging the model's output. Auto-retries with a /v1 base when the stored
    base looks like a host root.

    `client` is only used by tests to inject a mocked transport.
    """
    if not api_key:
        return {"ok": False, "detail": "no API key set for this provider", "endpoint": ""}
    base = (base_url or "https://api.openai.com/v1").rstrip("/")
    model = model or "gpt-4o-mini"

    candidates = [f"{base}/chat/completions"]
    if not base.endswith("/v1"):
        candidates.append(f"{base}/v1/chat/completions")

    last_detail = "no response"
    for url in candidates:
        try:
            r, endpoint = await _post_chat_completions(url, api_key, model, client=client)
        except Exception as e:
            last_detail = f"{url} — {e}"
            continue
        if r.status_code in (401, 403):
            last_detail = f"{endpoint} — auth failed (HTTP {r.status_code})"
            continue
        try:
            data = r.json()
        except Exception:
            last_detail = (
                f"{endpoint} — HTTP {r.status_code}, not JSON "
                "(content-type may be HTML) — check base_url (may need a /v1 path)"
            )
            continue
        if r.status_code >= 400:
            body_txt = str(data)[:300]
            last_detail = f"{endpoint} — HTTP {r.status_code}: {body_txt}"
            continue
        # Is this actually a chat-completions response (choices[0].message)?
        try:
            data["choices"][0]["message"]
        except Exception:
            last_detail = (
                f"{endpoint} — HTTP {r.status_code} but response is not a chat "
                f"completions object (shape: {str(data)[:200]})"
            )
            continue
        reply = _chat_reply_text(data)
        if reply:
            return {
                "ok": True,
                "endpoint": endpoint,
                "detail": f"model '{model}' replied via {endpoint}",
                "reply": reply,
            }
        return {
            "ok": True,
            "endpoint": endpoint,
            "detail": (
                f"endpoint + key OK via {endpoint} — model '{model}' returned no "
                "visible text (reasoning-only or empty reply)"
            ),
        }

    return {"ok": False, "endpoint": "", "detail": last_detail}


def _anthropic_reply_text(data: Any) -> str:
    """Extract text from an Anthropic messages response."""
    try:
        parts = data.get("content") or []
        return " ".join(b.get("text", "") for b in parts if b.get("type") == "text").strip()
    except Exception:
        return ""


async def _test_anthropic_message_ex(
    base_url: str, api_key: str, model: str, client: httpx.AsyncClient | None = None
) -> dict:
    """POST a real message to {base}/v1/messages (Anthropic SDK appends /v1, so
    a base that already ends in /v1 is normalized first). A valid messages
    response counts as success even without visible text."""
    if not api_key:
        return {"ok": False, "detail": "no API key set for this provider", "endpoint": ""}
    model = model or "claude-3-5-haiku-latest"

    base = (base_url or "https://api.anthropic.com").rstrip("/")
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    url = f"{base}/v1/messages"

    try:
        if client is None:
            async with httpx.AsyncClient(timeout=20) as c:
                r = await c.post(
                    url,
                    headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                    json={
                        "model": model,
                        "max_tokens": TEST_CHAT_MAX_TOKENS,
                        "messages": [{"role": "user", "content": TEST_CHAT_PROMPT}],
                    },
                )
        else:
            r = await client.post(
                url,
                headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"},
                json={
                    "model": model,
                    "max_tokens": TEST_CHAT_MAX_TOKENS,
                    "messages": [{"role": "user", "content": TEST_CHAT_PROMPT}],
                },
            )
    except Exception as e:
        return {"ok": False, "endpoint": url, "detail": str(e)[:300]}

    if r.status_code in (401, 403):
        return {"ok": False, "endpoint": url, "detail": f"auth failed (HTTP {r.status_code})"}
    try:
        data = r.json()
    except Exception:
        return {"ok": False, "endpoint": url, "detail": f"HTTP {r.status_code}, not JSON"}
    if r.status_code >= 400:
        return {"ok": False, "endpoint": url, "detail": f"HTTP {r.status_code}: {str(data)[:300]}"}

    reply = _anthropic_reply_text(data)
    if reply:
        return {
            "ok": True,
            "endpoint": url,
            "detail": f"model '{model}' replied via {url}",
            "reply": reply,
        }
    if isinstance(data.get("content"), list):
        # A valid Anthropic messages object without visible text (e.g. only a
        # thinking block) still means endpoint + key work.
        return {
            "ok": True,
            "endpoint": url,
            "detail": (
                f"endpoint + key OK via {url} — model '{model}' returned no "
                "visible text (thinking-only or empty reply)"
            ),
        }
    return {
        "ok": False,
        "endpoint": url,
        "detail": f"HTTP {r.status_code} but response is not a messages object (shape: {str(data)[:200]})",
    }


async def _test_provider(request: web.Request) -> web.Response:
    """Send a real chat message to one provider's model and report whether it
    replied, along with the exact endpoint used (to validate the API path)."""
    name = request.match_info["name"]
    try:
        data = await request.json()
        model = str(data.get("model") or "").strip()
    except Exception:
        model = ""

    from backend.providers import find_provider
    provider = find_provider(name)
    if not provider:
        return _json({"ok": False, "error": f"provider '{name}' not found"})

    if not provider.api_key:
        return _json({"ok": False, "error": f"no API key set for provider '{name}'"})

    model = model or (provider.models[0] if provider.models else "")

    if provider.api_format == "anthropic":
        result = await _test_anthropic_message_ex(provider.base_url, provider.api_key, model)
    else:
        result = await _test_openai_chat_message(provider.base_url, provider.api_key, model)

    result["name"] = name
    result["model"] = model
    result["api_format"] = provider.api_format or provider.kind
    return _json({"ok": result.get("ok", False), "result": result})


async def _test_config(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    s = deps.settings

    def eff(field: str, secret: bool = False) -> str:
        cur = getattr(s, field, "") or ""
        if field in data:
            v = str(data.get(field) or "").strip()
            if v and not (secret and v == _mask(cur)):
                return v
        return cur

    results: dict[str, Any] = {
        "ctfd": await _test_ctfd(
            eff("ctfd_url"), eff("ctfd_token", True),
            eff("ctfd_user"), eff("ctfd_pass", True),
            eff("ctfd_session_cookie", True),
        ),
    }

    # Only custom providers (from the Providers panel) are tested here.
    from backend.providers import load_providers
    for p in load_providers():
        if p.kind not in ("openai_compatible", "anthropic") or not p.name:
            continue
        base = (p.base_url or "https://api.openai.com/v1").rstrip("/")
        if not p.api_key:
            results[p.name] = {"ok": False, "base_url": base, "detail": "no key set"}
        elif p.api_format == "anthropic":
            results[p.name] = await _test_anthropic_message(
                base, p.api_key, (p.models or ["claude-3-5-haiku-latest"])[0]
            )
        else:
            results[p.name] = await _test_custom_openai(base, p.api_key)
    return _json({"ok": True, "results": results})


def _json(data: Any) -> web.Response:
    return web.json_response(data, dumps=lambda o: json.dumps(o, ensure_ascii=False, default=str))


async def _index(request: web.Request) -> web.Response:
    text = INDEX_HTML_PATH.read_text(encoding="utf-8") if INDEX_HTML_PATH.exists() else "<h1>index.html missing</h1>"
    return web.Response(
        text=text,
        content_type="text/html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate"},
    )


async def _status(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    poller = request.app["poller"]
    known = set(poller.known_challenges) | set(deps.manual_challenges)
    solved = set(poller.known_solved) | {
        name for name, r in deps.results.items() if r.get("flag")
    }
    unsolved = sorted(known - solved)
    swarms: dict[str, Any] = {}
    for name, swarm in deps.swarms.items():
        try:
            swarms[name] = swarm.get_status()
        except Exception:
            continue
    challenge_meta = {}
    for name, meta in deps.challenge_metas.items():
        challenge_meta[name] = f"{meta.category or '?'} / {meta.value or '?'} pts"

    from backend.tracing import activity_bins, is_active
    from backend.agents.coordinator_core import _ready_model_specs

    activity: dict[str, dict] = {}
    for name in known:
        activity[name] = {
            "bins": activity_bins(name),
            "active": is_active(name),
        }

    ready_models = _ready_model_specs(deps)
    budget_cap = getattr(deps.settings, "max_total_cost_usd", 0.0)

    return _json({
        "ctfd_url": getattr(deps.settings, "ctfd_url", ""),
        "models": deps.model_specs,
        "ready_models": ready_models,
        "max_concurrent": deps.max_concurrent_challenges,
        "total_cost_usd": deps.cost_tracker.total_cost_usd,
        "total_tokens": deps.cost_tracker.total_tokens,
        "budget_cap_usd": budget_cap,
        "over_budget": deps.cost_tracker.over_budget(budget_cap),
        "known_challenges": sorted(known),
        "solved": sorted(solved),
        "unsolved": unsolved,
        "swarms": swarms,
        "results": deps.results,
        "challenge_meta": challenge_meta,
        "activity": activity,
        "active_swarms": sum(1 for t in deps.swarm_tasks.values() if not t.done()),
        "cost_by_model": deps.cost_tracker.get_usage_by_model(),
        "config_ready": _config_status(deps),
        "has_model_keys": _has_model_keys(deps),
        "docker_ok": await _docker_available(),
        "auto_spawn": bool(getattr(deps, "auto_spawn", False)),
        "persist": sorted(getattr(deps, "persistent_challenges", set())),
        "attempts": dict(getattr(deps, "attempts", {})),
        "max_attempts": getattr(deps.settings, "max_attempts_per_challenge", 3),
    })


async def _get_config(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    s = deps.settings
    return _json({
        "ctfd_url": s.ctfd_url,
        "ctfd_token": _mask(s.ctfd_token),
        "ctfd_session_cookie": _mask(s.ctfd_session_cookie),
        "ctfd_user": s.ctfd_user,
        "ctfd_pass": _mask(s.ctfd_pass),
        "anthropic_api_key": _mask(s.anthropic_api_key),
        "openai_api_key": _mask(s.openai_api_key),
        "gemini_api_key": _mask(s.gemini_api_key),
        "azure_openai_endpoint": s.azure_openai_endpoint,
        "azure_openai_api_key": _mask(s.azure_openai_api_key),
        "opencode_zen_api_key": _mask(s.opencode_zen_api_key),
        "aws_region": getattr(s, "aws_region", "us-east-1"),
        "model_specs": deps.model_specs,
    })


async def _save_config(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    poller = request.app["poller"]
    try:
        data = await request.json()
    except Exception:
        return _json({"ok": False, "error": "invalid JSON"})

    s = deps.settings
    changed: list[str] = []

    def _set(field: str, raw: Any, secret: bool = False) -> None:
        if field not in data:
            return
        value = str(data.get(field) or "").strip()
        current = getattr(s, field, "")
        if secret and value and value == _mask(current):
            return  # unchanged masked placeholder
        setattr(s, field, value)
        changed.append(field)

    for field in CONFIG_FIELDS:
        _set(field, data.get(field), secret=field in SECRET_FIELDS)

    # Optional: update the model lineup (comma/newline separated)
    if isinstance(data.get("model_specs"), list):
        specs = [str(x).strip() for x in data["model_specs"] if str(x).strip()]
        if specs:
            deps.model_specs = specs
            changed.append("model_specs")
    for field in SECRET_FIELDS:
        cur = getattr(s, field, "")
        if cur.startswith(("ctfd_your_", "sk-ant-...", "sk-...", "your_")):
            setattr(s, field, "")
            if field in changed:
                changed.append(field)

    _write_env(deps)
    _apply_api_keys_to_env(deps)

    # Reconfigure CTFd + poller live
    try:
        deps.ctfd.reconfigure(
            base_url=s.ctfd_url,
            token=s.ctfd_token,
            username=s.ctfd_user,
            password=s.ctfd_pass,
            session_cookie=s.ctfd_session_cookie,
        )
        await poller.reconfigure(deps.ctfd)
        ctfd_note = "CTFd connection updated."
    except Exception as e:
        ctfd_note = f"CTFd update failed: {e}"

    _apply_api_keys_to_env(deps)
    logger.info("Config updated via web: %s", ", ".join(changed) or "no changes")

    restart_note = ""
    if any(f in changed for f in ("anthropic_api_key", "openai_api_key", "gemini_api_key")):
        restart_note = "API keys saved. If the coordinator LLM was started without keys, restart it (Ctrl+C then ./run.sh) for it to take effect. New solvers will use the keys immediately."

    return _json({
        "ok": True,
        "changed": changed,
        "ctfd_note": ctfd_note,
        "note": restart_note or "Configuration saved.",
        "config_ready": _config_status(deps),
        "has_model_keys": _has_model_keys(deps),
    })


async def _get_providers(request: web.Request) -> web.Response:
    from backend.providers import API_FORMATS, load_providers
    providers = [{
        "name": p.name,
        "kind": p.kind,
        "api_format": p.api_format,
        "base_url": p.base_url,
        "api_key": _mask(p.api_key),
        "models": p.models,
    } for p in load_providers()]
    formats = [{"value": v, "label": l} for v, l in API_FORMATS]
    return _json({"providers": providers, "formats": formats})


async def _add_provider(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    try:
        data = await request.json()
    except Exception:
        return _json({"ok": False, "error": "invalid JSON"})

    from backend.providers import ProviderConfig, load_providers, save_providers

    name = str(data.get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "provider name required"})

    providers = load_providers()
    pc = ProviderConfig.from_dict(data)
    existing = next((p for p in providers if p.name.lower() == name.lower()), None)
    if existing:
        # masked placeholder or empty field -> keep the existing key
        if existing.api_key and (pc.api_key == _mask(existing.api_key) or not pc.api_key):
            pc.api_key = existing.api_key
        providers[providers.index(existing)] = pc
    else:
        providers.append(pc)
    save_providers(providers)
    _sync_provider_settings(deps)
    return _json({"ok": True, "note": f"provider '{name}' saved", "model_specs": deps.model_specs})


async def _delete_provider(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    from backend.providers import load_providers, save_providers
    providers = [p for p in load_providers() if p.name.lower() != name.lower()]
    save_providers(providers)
    _sync_provider_settings(deps)
    return _json({"ok": True, "message": f"removed '{name}'", "model_specs": deps.model_specs})


async def _add_manual_challenge(request: web.Request) -> web.Response:
    """Add a custom challenge (no CTFd) — solver just reports the flag directly.

    Accepts either application/json (no files) or multipart/form-data with a
    `files` field (one or more) to attach distfiles for the solver.
    """
    deps = request.app["deps"]
    files: list[Any] = []
    if request.content_type == "multipart/form-data":
        try:
            posted = await request.post()
        except Exception:
            return _json({"ok": False, "error": "invalid form data"})
        data: dict[str, Any] = {k: v for k, v in posted.items() if not isinstance(v, web.FileField)}
        files = [v for v in posted.getall("files", []) if isinstance(v, web.FileField)]
    else:
        try:
            data = await request.json()
        except Exception:
            return _json({"ok": False, "error": "invalid JSON"})

    name = str(data.get("name") or "").strip()
    if not name:
        return _json({"ok": False, "error": "challenge name required"})

    from backend.prompts import ChallengeMeta
    import yaml

    slug = re.sub(r"[<>:\"/\\|?*.\x00-\x1f]", "", name.lower().strip())
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-") or "challenge"

    base = Path(deps.challenges_root) / "manual"
    try:
        base.mkdir(parents=True, exist_ok=True)
        ch_dir = base / slug
        ch_dir.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return _json({"ok": False, "error": f"cannot create challenge folder under '{base}' — check write permission: {e}"})

    meta = {
        "name": name,
        "category": str(data.get("category") or "").strip(),
        "description": str(data.get("description") or "").strip(),
        "value": int(data.get("value") or 0),
        "connection_info": str(data.get("connection_info") or "").strip(),
        "tags": [],
        "solves": 0,
        "manual": True,
    }
    try:
        (ch_dir / "metadata.yml").write_text(
            yaml.dump(meta, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    except OSError as e:
        return _json({"ok": False, "error": f"cannot write '{ch_dir / 'metadata.yml'}' — check folder ownership (chown -R to your user): {e}"})

    saved = 0
    if files:
        distfiles_dir = ch_dir / "distfiles"
        try:
            distfiles_dir.mkdir(parents=True, exist_ok=True)
            for field in files:
                # Path(...).name strips any directory components (incl. `../`) —
                # the file is written strictly inside distfiles_dir.
                safe_name = Path(field.filename or "").name
                if not safe_name:
                    continue
                with (distfiles_dir / safe_name).open("wb") as out:
                    out.write(field.file.read())
                saved += 1
        except OSError as e:
            return _json({"ok": False, "error": f"cannot write distfiles into '{distfiles_dir}' — check folder ownership: {e}"})

    meta_obj = ChallengeMeta.from_yaml(ch_dir / "metadata.yml")
    deps.challenge_dirs[name] = str(ch_dir)
    deps.challenge_metas[name] = meta_obj
    deps.manual_challenges[name] = str(ch_dir)

    logger.info("Manual challenge added: %s (%d file(s))", name, saved)
    suffix = f" with {saved} file(s) attached" if saved else ""
    return _json({"ok": True, "message": f"Challenge '{name}' added{suffix} — Spawn swarm to solve (flag reported directly, no CTFd submit)."})


async def _toggle_autospawn(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    try:
        data = await request.json()
    except Exception:
        data = {}
    enabled = bool(data.get("enabled", False))
    deps.auto_spawn = enabled
    logger.info("Auto-spawn %s", "enabled" if enabled else "disabled")
    return _json({"ok": True, "auto_spawn": enabled})


async def _msg(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    try:
        data = await request.json()
        message = str(data.get("message", "")).strip()
    except Exception:
        message = ""
    if not message:
        return _json({"ok": False, "error": "message required"})
    deps.operator_inbox.put_nowait(message)
    logger.info("Operator message: %s", message[:200])
    return _json({"ok": True, "queued": message})


async def _spawn(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    from backend.agents.coordinator_core import do_spawn_swarm
    models = None
    role_mode = False
    count = 0
    instruction = ""
    try:
        data = await request.json()
        if isinstance(data, dict):
            if isinstance(data.get("models"), list):
                models = [str(m).strip() for m in data["models"] if str(m).strip()]
            role_mode = bool(data.get("role_mode", False))
            try:
                count = int(data.get("count") or 0)
            except (TypeError, ValueError):
                count = 0
            instruction = str(data.get("instruction") or "").strip()
    except Exception:
        pass
    try:
        msg = await do_spawn_swarm(deps, name, model_specs=models,
                                   role_mode=role_mode, count=count, instruction=instruction)
        return _json({"ok": True, "message": msg})
    except Exception as e:
        logger.warning("Spawn failed for %s: %s", name, e)
        return _json({"ok": False, "message": f"spawn error: {e}"})


async def _kill(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    from backend.agents.coordinator_core import do_kill_swarm
    return _json({"ok": True, "message": await do_kill_swarm(deps, name)})


async def _broadcast(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    try:
        data = await request.json()
        message = str(data.get("message", "")).strip()
    except Exception:
        message = ""
    if not message:
        return _json({"ok": False, "error": "message required"})
    from backend.agents.coordinator_core import do_broadcast
    return _json({"ok": True, "message": await do_broadcast(deps, name, message)})


async def _set_persist(request: web.Request) -> web.Response:
    """Toggle 'keep trying until the flag is found' for a challenge."""
    deps = request.app["deps"]
    poller = request.app["poller"]
    name = request.match_info["name"]
    try:
        data = await request.json()
        enabled = bool(data.get("enabled", False))
    except Exception:
        enabled = False
    from backend.agents.coordinator_core import do_set_persistent
    solved = set(poller.known_solved) | {
        n for n, r in deps.results.items() if r.get("flag")
    }
    message = await do_set_persistent(deps, name, enabled, solved)
    return _json({
        "ok": True,
        "message": message,
        "persistent": name in deps.persistent_challenges,
        "attempts": deps.attempts.get(name, 0),
    })


async def _flag_wrong(request: web.Request) -> web.Response:
    """Operator marks the reported flag wrong -> stop, record it, retry with the
    previous log summarized for the fresh attempt."""
    deps = request.app["deps"]
    name = request.match_info["name"]
    try:
        from backend.agents.coordinator_core import do_flag_wrong
        message = await do_flag_wrong(deps, name)
        return _json({
            "ok": True,
            "message": message,
            "attempts": deps.attempts.get(name, 0),
            "bad_flags": len(deps.bad_flags.get(name, [])),
        })
    except Exception as e:
        logger.warning("wrong-flag failed for %s: %s", name, e, exc_info=True)
        return _json({"ok": False, "error": f"wrong-flag error: {e}"})


async def _bump(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    try:
        data = await request.json()
        model = str(data.get("model", "")).strip()
        insights = str(data.get("insights", "")).strip()
    except Exception:
        model, insights = "", ""
    if not model:
        return _json({"ok": False, "error": "model required"})
    from backend.agents.coordinator_core import do_bump_agent
    return _json({"ok": True, "message": await do_bump_agent(deps, name, model, insights)})


async def _trace(request: web.Request) -> web.Response:
    deps = request.app["deps"]
    name = request.match_info["name"]
    model = request.query.get("model", "")
    try:
        last_n = int(request.query.get("last_n", 80))
    except ValueError:
        last_n = 80
    if not model:
        return _json({"ok": False, "trace": "model query param required"})
    from backend.agents.coordinator_core import do_read_solver_trace
    text = await do_read_solver_trace(deps, name, model, last_n)
    return _json({"ok": True, "trace": text})


def _format_log_lines(lines: list[str], last_n: int = 200) -> str:
    """Format raw JSONL lines into a readable text summary (same style as the
    live trace reader)."""
    import json as _json_mod

    recent = lines[-last_n:]
    summary = []
    for line in recent:
        try:
            d = _json_mod.loads(line)
        except Exception:
            summary.append(line[:200])
            continue
        t = d.get("type", "?")
        ts = d.get("ts")
        stamp = ""
        if ts:
            try:
                stamp = __import__("time").strftime("%H:%M:%S", __import__("time").localtime(ts))
            except Exception:
                stamp = ""
        prefix = f"[{stamp}] " if stamp else ""
        if t == "tool_call":
            summary.append(f"{prefix}step {d.get('step','?')} CALL {d.get('tool','?')}: {str(d.get('args',''))[:300]}")
        elif t == "tool_result":
            summary.append(f"{prefix}step {d.get('step','?')} RESULT {d.get('tool','?')}: {str(d.get('result',''))[:300]}")
        elif t == "model_response":
            summary.append(f"{prefix}step {d.get('step','?')} MODEL: {str(d.get('text',''))[:200]}")
        elif t == "usage":
            summary.append(f"{prefix}usage: in={d.get('input_tokens',0)} out={d.get('output_tokens',0)} cost=${d.get('cost_usd',0):.4f}")
        elif t in ("finish", "error", "bump", "turn_failed", "start", "stop", "loop_break", "flag_confirmed"):
            extra = {k: v for k, v in d.items() if k not in ("ts", "type")}
            summary.append(f"{prefix}** {t}: {str(extra)[:200]}")
        else:
            summary.append(f"{prefix}{t}: {str(d)[:200]}")
    return "\n".join(summary)


async def _list_logs(request: web.Request) -> web.Response:
    log_dir = Path("logs")
    files = []
    if log_dir.exists():
        try:
            for p in sorted(log_dir.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True):
                st = p.stat()
                files.append({"name": p.name, "mtime": st.st_mtime, "size": st.st_size})
        except OSError:
            pass
    return _json({"logs": files})


async def _logs_for_challenge(request: web.Request) -> web.Response:
    """Return the most recent trace file for a challenge (works after solve)."""
    from backend.tracing import _sanitize

    name = request.match_info["name"]
    prefix = "trace-" + _sanitize(name) + "-"
    log_dir = Path("logs")
    files: list[Path] = []
    if log_dir.exists():
        try:
            files = [p for p in log_dir.glob("trace-*.jsonl") if p.name.startswith(prefix)]
        except OSError:
            files = []
    if not files:
        return _json({"ok": False, "file": None})
    latest = max(files, key=lambda p: p.stat().st_mtime)
    return _json({"ok": True, "file": latest.name})


async def _read_log(request: web.Request) -> web.Response:
    name = request.query.get("path", "")
    if not name or "/" in name or "\\" in name or ".." in name:
        return _json({"ok": False, "trace": "invalid path"})
    path = Path("logs") / name
    if not path.exists():
        return _json({"ok": False, "trace": "not found"})
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as e:
        return _json({"ok": False, "trace": f"read error: {e}"})
    return _json({"ok": True, "trace": _format_log_lines(lines, 400)})


def build_app(deps: Any, poller: Any) -> web.Application:
    """Build the aiohttp app bound to coordinator deps + poller."""
    # 200 MB client_max_size — default 1 MB is too small for challenge distfiles
    # (memory dumps, pcaps, disk images) uploaded via the "Add challenge" modal.
    app = web.Application(middlewares=[_auth_middleware], client_max_size=200 * 1024 * 1024)
    app["deps"] = deps
    app["poller"] = poller
    app.router.add_get("/", _index)
    app.router.add_get("/api/status", _status)
    app.router.add_get("/api/config", _get_config)
    app.router.add_post("/api/config", _save_config)
    app.router.add_post("/api/test", _test_config)
    app.router.add_get("/api/providers", _get_providers)
    app.router.add_post("/api/providers", _add_provider)
    app.router.add_delete("/api/providers/{name}", _delete_provider)
    app.router.add_post("/api/providers/{name}/test", _test_provider)
    app.router.add_post("/api/msg", _msg)
    app.router.add_post("/msg", _msg)  # backward-compat for `ctf-msg`
    app.router.add_post("/api/autospawn", _toggle_autospawn)
    app.router.add_post("/api/challenges/{name}/spawn", _spawn)
    app.router.add_post("/api/challenges/manual", _add_manual_challenge)
    app.router.add_post("/api/challenges/{name}/persist", _set_persist)
    app.router.add_post("/api/challenges/{name}/wrong-flag", _flag_wrong)
    app.router.add_post("/api/swarms/{name}/kill", _kill)
    app.router.add_post("/api/swarms/{name}/broadcast", _broadcast)
    app.router.add_post("/api/swarms/{name}/bump", _bump)
    app.router.add_get("/api/swarms/{name}/trace", _trace)
    app.router.add_get("/api/logs", _list_logs)
    app.router.add_get("/api/logs/read", _read_log)
    app.router.add_get("/api/logs/for/{name}", _logs_for_challenge)
    return app


async def start_web_server(deps: Any, poller: Any, port: int = 0) -> tuple[web.AppRunner, int]:
    """Start the web server. Returns (runner, actual_port)."""
    app = build_app(deps, poller)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", port)
    await site.start()
    actual_port = port
    try:
        actual_port = runner.addresses[0][1]
    except Exception:
        pass
    logger.info("Web dashboard: http://127.0.0.1:%d  (msg endpoint: /api/msg)", actual_port)
    return runner, actual_port