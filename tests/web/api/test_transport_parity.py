"""Regression: HTTP /mcp tool surface must match stdio's surface.

The standard MCP Streamable HTTP transport now delegates to the same
`MemoryServer` instance the stdio transport uses. This test verifies
that the tool surface stays aligned and that local-only tools are
filtered out for remote callers.
"""

import os
import tempfile

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mcp_memory_service.web.dependencies import set_storage
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test.db")


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def test_app(initialized_storage, monkeypatch):
    from mcp_memory_service.web.oauth import middleware
    monkeypatch.setattr(middleware, "API_KEY", None)
    monkeypatch.setattr(middleware, "OAUTH_ENABLED", False)
    monkeypatch.setattr(middleware, "ALLOW_ANONYMOUS_ACCESS", True)

    from mcp_memory_service.web.app import app
    from mcp_memory_service.web.oauth.middleware import (
        get_current_user, require_read_access, AuthenticationResult,
    )

    set_storage(initialized_storage)

    async def mock_user():
        return AuthenticationResult(
            authenticated=True, client_id="test", scope="read write",
            auth_method="test",
        )

    app.dependency_overrides[get_current_user] = mock_user
    app.dependency_overrides[require_read_access] = mock_user

    with TestClient(app) as client:
        yield client
    app.dependency_overrides.clear()


MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _initialize(test_app):
    """Send initialize handshake via SDK transport."""
    test_app.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "1"},
            },
        },
        headers=MCP_HEADERS,
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_http_mcp_surface_matches_stdio(test_app):
    """`tools/list` over HTTP must advertise the same names + schemas as
    `MemoryServer.list_tools()` directly, minus the local-only tools that
    must not be exposed remotely."""
    import mcp_memory_service.server  # bootstrap circular import
    from mcp_memory_service.web.api.mcp import _get_memory_server

    # The REST singleton has transport_mode="stdio" (default), so it returns
    # ALL tools. The SDK transport in the lifespan has transport_mode="remote"
    # and filters local-only. We compare against the remote-filtered set.
    server = _get_memory_server()
    stdio_tools = await server.list_tools()
    local_only = server.local_only_tools()
    expected_http_names = {t.name for t in stdio_tools} - local_only

    _initialize(test_app)

    response = test_app.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=MCP_HEADERS,
    )
    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    http_tools = response.json()["result"]["tools"]
    http_names = {t["name"] for t in http_tools}

    assert http_names == expected_http_names, (
        f"HTTP and stdio tool sets diverged beyond the local_only carve-out. "
        f"HTTP-only: {http_names - expected_http_names}, "
        f"missing-from-http: {expected_http_names - http_names}"
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_local_only_tools_excluded_from_http_list(test_app):
    """Local-only tools (memory_harvest, memory_ingest) must not appear
    in HTTP `tools/list` — they read caller-supplied filesystem paths and
    are stdio-only by policy."""
    import mcp_memory_service.server  # noqa: F401
    from mcp_memory_service.web.api.mcp import _get_memory_server

    server = _get_memory_server()
    local_only = server.local_only_tools()
    assert local_only, "Test premise broken: nothing flagged local-only"

    _initialize(test_app)

    response = test_app.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        headers=MCP_HEADERS,
    )
    assert response.status_code == 200, f"Got {response.status_code}: {response.text}"
    http_names = {t["name"] for t in response.json()["result"]["tools"]}
    leaked = http_names & local_only
    assert not leaked, f"local-only tools leaked into HTTP tools/list: {leaked}"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_local_only_tools_rejected_on_http_call(test_app):
    """Calling a local-only tool over HTTP must return a JSON-RPC error.

    The SDK transport's MemoryServer has transport_mode='remote', so
    call_tool() raises ValueError for local-only tools, which the SDK
    converts to an internal-error JSON-RPC response.
    """
    import mcp_memory_service.server  # noqa: F401
    from mcp_memory_service.web.api.mcp import _get_memory_server

    server = _get_memory_server()
    local_only = server.local_only_tools()

    targets = list(local_only)
    assert targets, "Test premise broken: no local-only names to check"

    _initialize(test_app)

    for name in targets:
        response = test_app.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": name, "arguments": {}},
            },
            headers=MCP_HEADERS,
        )
        # The SDK transport returns 200 with isError=True in the result
        # when the handler raises an exception (standard MCP behavior).
        body = response.json()
        assert "result" in body, f"{name}: expected result in JSON-RPC, got {body}"
        assert body["result"].get("isError") is True, (
            f"{name}: expected isError=True, got {body['result']}"
        )
        # The error message should mention the tool is not available
        content_text = body["result"]["content"][0]["text"]
        assert "not available" in content_text.lower(), (
            f"{name}: expected 'not available' in error text, got: {content_text}"
        )
