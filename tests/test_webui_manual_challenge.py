"""Tests for the manual "Add challenge" endpoint — JSON path and multipart file uploads."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from aiohttp import FormData
from aiohttp.test_utils import TestClient, TestServer

from backend.cost_tracker import CostTracker
from backend.prompts import list_distfiles
from backend.webui import build_app


def _make_deps(challenges_root: str) -> SimpleNamespace:
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
        challenge_dirs={},
        challenge_metas={},
        model_specs=[],
        max_concurrent_challenges=10,
        cost_tracker=CostTracker(),
        auto_spawn=False,
        challenges_root=challenges_root,
    )


def _make_poller() -> SimpleNamespace:
    return SimpleNamespace(known_challenges=set(), known_solved=set())


@pytest.mark.asyncio
async def test_json_request_without_files_creates_challenge_no_distfiles(tmp_path):
    deps = _make_deps(str(tmp_path))
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        resp = await client.post("/api/challenges/manual", json={
            "name": "No Files Challenge",
            "category": "misc",
            "value": 50,
        })
        data = await resp.json()
        assert data["ok"] is True

    ch_dir = Path(deps.challenge_dirs["No Files Challenge"])
    assert (ch_dir / "metadata.yml").exists()
    assert not (ch_dir / "distfiles").exists()


@pytest.mark.asyncio
async def test_multipart_upload_writes_distfiles(tmp_path):
    deps = _make_deps(str(tmp_path))
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("name", "File Challenge")
        form.add_field("category", "crypto")
        form.add_field("value", "100")
        form.add_field("files", b"hello world", filename="notes.txt", content_type="text/plain")
        form.add_field("files", b"\x89PNG-fake-bytes", filename="flag.png", content_type="image/png")

        resp = await client.post("/api/challenges/manual", data=form)
        data = await resp.json()
        assert data["ok"] is True
        assert "2 file" in data["message"]

    ch_dir = Path(deps.challenge_dirs["File Challenge"])
    distfiles = ch_dir / "distfiles"
    assert (distfiles / "notes.txt").read_bytes() == b"hello world"
    assert (distfiles / "flag.png").read_bytes() == b"\x89PNG-fake-bytes"


@pytest.mark.asyncio
async def test_multipart_upload_sanitizes_path_traversal_filename(tmp_path):
    deps = _make_deps(str(tmp_path))
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        # Hand-craft the multipart body with a literal unescaped "../" in the
        # filename — a malicious client controls raw bytes and won't go through
        # aiohttp's FormData encoder (which percent-encodes slashes).
        boundary = "testboundary123"
        body = (
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="name"\r\n\r\n'
            "Traversal Challenge\r\n"
            f"--{boundary}\r\n"
            'Content-Disposition: form-data; name="files"; filename="../../evil.txt"\r\n'
            "Content-Type: text/plain\r\n\r\n"
            "evil\r\n"
            f"--{boundary}--\r\n"
        ).encode()
        resp = await client.post(
            "/api/challenges/manual",
            data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        data = await resp.json()
        assert data["ok"] is True

    ch_dir = Path(deps.challenge_dirs["Traversal Challenge"])
    distfiles = ch_dir / "distfiles"
    # The sanitized file must land inside distfiles/, never escape via ../
    assert (distfiles / "evil.txt").read_bytes() == b"evil"
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path.parent / "evil.txt").exists()


@pytest.mark.asyncio
async def test_uploaded_files_are_visible_via_list_distfiles(tmp_path):
    deps = _make_deps(str(tmp_path))
    app = build_app(deps, _make_poller())
    async with TestClient(TestServer(app)) as client:
        form = FormData()
        form.add_field("name", "Visible Challenge")
        form.add_field("files", b"data", filename="chal.bin", content_type="application/octet-stream")
        resp = await client.post("/api/challenges/manual", data=form)
        assert (await resp.json())["ok"] is True

    ch_dir = deps.challenge_dirs["Visible Challenge"]
    assert list_distfiles(ch_dir) == ["chal.bin"]
