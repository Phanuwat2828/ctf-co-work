"""Tests for the per-provider "Test AI" feature — helpers send a real chat
message via an injected mock HTTP transport and validate the endpoint path."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from aiohttp.test_utils import TestClient, TestServer

import backend.webui as webui_mod
from backend.cost_tracker import CostTracker
from backend.providers import ProviderConfig
from backend.webui import _test_anthropic_message_ex, _test_openai_chat_message, build_app

OK_CHAT_BODY = {
    "id": "cmpl-test",
    "object": "chat.completion",
    "choices": [{"index": 0, "message": {"role": "assistant", "content": "pong"}, "finish_reason": "stop"}],
}
OK_ANTHROPIC_BODY = {"content": [{"type": "text", "text": "pong"}]}


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _make_deps() -> SimpleNamespace:
    settings = SimpleNamespace(
        ctfd_url="",
        webui_token="",
        max_total_cost_usd=0.0,
        anthropic_api_key="",
        openai_api_key="",
        gemini_api_key="",
        azure_openai_api_key="",
        opencode_zen_api_key="",
        aws_bearer_token="",
    )
    return SimpleNamespace(
        settings=settings,
        manual_challenges={},
        results={},
        swarms={},
        swarm_tasks={},
        challenge_metas={},
        model_specs=[],
        max_concurrent_challenges=10,
        cost_tracker=CostTracker(),
        auto_spawn=False,
        challenges_root="/tmp",
    )


def _make_poller() -> SimpleNamespace:
    return SimpleNamespace(known_challenges=set(), known_solved=set())


def _patch_provider_find(monkeypatch, providers: list[ProviderConfig]) -> None:
    import backend.providers as providers_mod

    monkeypatch.setattr(
        providers_mod,
        "find_provider",
        lambda name: next((p for p in providers if p.name.lower() == name.lower()), None),
    )


# ---- OpenAI chat-completions helper unit tests ----


@pytest.mark.asyncio
async def test_openai_chat_success_reports_endpoint():
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=OK_CHAT_BODY)

    result = await _test_openai_chat_message(
        "https://gate.example/v1", "key-123", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is True
    assert result["endpoint"] == "https://gate.example/v1/chat/completions"
    assert result["reply"] == "pong"
    # Base already ends in /v1 -> exactly one attempt.
    assert len(recorded) == 1
    assert recorded[0].url.path == "/v1/chat/completions"
    assert '"model":"m-1"' in recorded[0].read().decode()
    assert recorded[0].headers.get("authorization") == "Bearer key-123"


@pytest.mark.asyncio
async def test_openai_chat_retries_with_v1_path():
    """Base without /v1: first POST to {base}/chat/completions 404s, then the
    /v1 variant succeeds — the path-detection case this feature exists for."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        if "/v1/chat/completions" in request.url.path:
            return httpx.Response(200, json=OK_CHAT_BODY)
        return httpx.Response(404, text="not found")

    result = await _test_openai_chat_message(
        "https://gate.example", "key-123", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is True
    assert result["endpoint"] == "https://gate.example/v1/chat/completions"
    assert len(recorded) == 2
    assert recorded[0].url.path == "/chat/completions"
    assert recorded[1].url.path == "/v1/chat/completions"


@pytest.mark.asyncio
async def test_openai_chat_bad_key_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    result = await _test_openai_chat_message(
        "https://gate.example", "key-wrong", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is False
    assert "auth failed" in result["detail"].lower()


@pytest.mark.asyncio
async def test_openai_chat_non_json_response_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not a chat response</html>")

    result = await _test_openai_chat_message(
        "https://gate.example/v1", "key-123", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is False
    assert "not JSON" in result["detail"]


@pytest.mark.asyncio
async def test_openai_chat_empty_content_is_still_ok():
    """Real providers (e.g. reasoning models with a tight token budget) can
    return a valid chat.completion whose content is empty. That is a working
    endpoint+key, not a failure."""
    body = {
        "id": "cmpl-x",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {"role": "assistant", "content": ""}, "finish_reason": "length"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    result = await _test_openai_chat_message(
        "https://gate.example/v1", "key-123", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is True
    assert result["endpoint"] == "https://gate.example/v1/chat/completions"
    assert "no visible text" in result["detail"]


@pytest.mark.asyncio
async def test_openai_chat_reasoning_content_is_used_as_reply():
    """DeepSeek-reasoner style responses put the visible answer in
    reasoning_content when content is empty."""
    body = {
        "id": "cmpl-y",
        "object": "chat.completion",
        "choices": [{"index": 0, "message": {
            "role": "assistant", "content": "", "reasoning_content": "thinking...\nso the answer is pong",
        }, "finish_reason": "stop"}],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=body)

    result = await _test_openai_chat_message(
        "https://gate.example/v1", "key-123", "m-1", client=_mock_client(handler)
    )

    assert result["ok"] is True
    assert "pong" in result["reply"]


@pytest.mark.asyncio
async def test_openai_chat_empty_key_short_circuits():
    result = await _test_openai_chat_message("https://gate.example/v1", "", "m-1")
    assert result["ok"] is False
    assert "no API key" in result["detail"]


# ---- Anthropic helper unit tests ----


@pytest.mark.asyncio
async def test_anthropic_message_posts_to_v1_without_double_v1():
    """A base already ending in /v1 must not produce a /v1/v1/messages URL."""
    recorded: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.append(request)
        return httpx.Response(200, json=OK_ANTHROPIC_BODY)

    result = await _test_anthropic_message_ex(
        "https://proxy.example/v1", "key-123", "claude-haiku-x", client=_mock_client(handler)
    )

    assert result["ok"] is True
    assert result["reply"] == "pong"
    assert recorded[0].url.path == "/v1/messages"
    assert "/v1/v1/" not in str(recorded[0].url)


@pytest.mark.asyncio
async def test_anthropic_message_bad_key_fails():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"type": "error"})

    result = await _test_anthropic_message_ex(
        "https://proxy.example", "key-wrong", "claude-haiku-x", client=_mock_client(handler)
    )

    assert result["ok"] is False
    assert "auth failed" in result["detail"].lower()


# ---- Endpoint wiring tests (no network — helpers are stubbed) ----


async def _post_test(monkeypatch, providers: list[ProviderConfig], name: str, body: dict):
    _patch_provider_find(monkeypatch, providers)
    deps = _make_deps()
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.post(f"/api/providers/{name}/test", json=body)
        return resp.status, await resp.json()


@pytest.mark.asyncio
async def test_endpoint_uses_selected_provider_model(monkeypatch):
    """The endpoint forwards the stored provider config to the openai helper."""
    seen: dict = {}

    async def fake_openai(base_url, api_key, model):
        seen.update(base_url=base_url, api_key=api_key, model=model)
        return {"ok": True, "endpoint": base_url + "/chat/completions", "detail": "ok", "reply": "pong"}

    monkeypatch.setattr(webui_mod, "_test_openai_chat_message", fake_openai)
    providers = [
        ProviderConfig(
            name="RightCode",
            kind="openai_compatible",
            api_format="openai_chat",
            base_url="https://www.right.codes/deepseek/v1",
            api_key="real-key",
            models=["deepseek-v4-flash"],
        )
    ]

    status, data = await _post_test(monkeypatch, providers, "RightCode", {})

    assert status == 200
    assert data["ok"] is True
    assert data["result"]["name"] == "RightCode"
    assert data["result"]["model"] == "deepseek-v4-flash"
    assert data["result"]["api_format"] == "openai_chat"
    assert seen == {
        "base_url": "https://www.right.codes/deepseek/v1",
        "api_key": "real-key",
        "model": "deepseek-v4-flash",
    }


@pytest.mark.asyncio
async def test_endpoint_unknown_provider_returns_json_error(monkeypatch):
    status, data = await _post_test(monkeypatch, [], "Nope", {})
    assert status == 200
    assert data["ok"] is False
    assert "not found" in data["error"]
