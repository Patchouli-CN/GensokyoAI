"""Web Runtime Origin / CORS 校验安全测试。"""

from __future__ import annotations

from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from GensokyoAI.backends.web_server.http_adapter import create_app


class _FakeRuntimeService:
    def __init__(self) -> None:
        self.shutdown_called = False

    async def health(self) -> dict[str, Any]:
        return {"ok": True}

    async def info(self) -> dict[str, Any]:
        return {"name": "fake"}

    async def handle(self, method: str, params: dict[str, Any] | None = None) -> Any:
        return {"method": method, "params": params or {}}

    async def shutdown(self) -> None:
        self.shutdown_called = True


@pytest.fixture
def fake_service() -> _FakeRuntimeService:
    return _FakeRuntimeService()


@pytest.mark.asyncio
async def test_default_rejects_cross_origin(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(create_app(service=fake_service))
    client = TestClient(server)
    await client.start_server()
    try:
        response = await client.get("/health", headers={"Origin": "https://evil.example"})
        assert response.status == 403
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_no_origin_header_is_allowed(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(create_app(service=fake_service))
    client = TestClient(server)
    await client.start_server()
    try:
        response = await client.get("/health")
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_allowed_origin_matches_hostname(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(
        create_app(service=fake_service, allowed_origins=["https://allowed.example"])
    )
    client = TestClient(server)
    await client.start_server()
    try:
        allowed = await client.get("/health", headers={"Origin": "https://allowed.example"})
        assert allowed.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_subdomain_is_not_allowed(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(create_app(service=fake_service, allowed_origins=["https://example.com"]))
    client = TestClient(server)
    await client.start_server()
    try:
        evil = await client.get("/health", headers={"Origin": "https://evil.example.com"})
        assert evil.status == 403
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_allow_all_origins_explicitly(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(create_app(service=fake_service, allowed_origins=["*"]))
    client = TestClient(server)
    await client.start_server()
    try:
        response = await client.get("/health", headers={"Origin": "https://anything.example"})
        assert response.status == 200
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_origin_with_port_is_matched_by_hostname(fake_service: _FakeRuntimeService) -> None:
    server = TestServer(create_app(service=fake_service, allowed_origins=["http://localhost:3000"]))
    client = TestClient(server)
    await client.start_server()
    try:
        response = await client.get("/health", headers={"Origin": "http://localhost:3000"})
        assert response.status == 200
    finally:
        await client.close()
