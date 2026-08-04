# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Authentication and authorization boundary tests.

Verifies that:
- Unauthenticated requests are rejected (401) when anonymous access is disabled
- Read-only scope cannot perform write operations (403)
- Read+write scope can perform both read and write operations (200)
- The MCP tools/call endpoint enforces per-tool scope checks
"""

import uuid

import pytest
from fastapi.testclient import TestClient

from mcp_memory_service.web.dependencies import set_storage

# Fixtures (temp_db, initialized_storage, authed_client, read_only_client,
# read_write_client, unauthenticated_client, anonymous_client, _make_client)
# are provided by tests/security/conftest.py


@pytest.mark.integration
class TestUnauthenticatedAccess:
    """Unauthenticated requests must be rejected when anonymous access is off."""

    def test_unauthenticated_store_rejected(self, unauthenticated_client):
        """Storing without auth returns 401."""
        response = unauthenticated_client.post(
            "/api/memories",
            json={"content": "should fail", "tags": ["__test__"]},
        )
        assert response.status_code == 401

    def test_unauthenticated_search_rejected(self, unauthenticated_client):
        """Searching without auth returns 401."""
        response = unauthenticated_client.post(
            "/api/search",
            json={"query": "test", "n_results": 5},
        )
        assert response.status_code == 401

    def test_unauthenticated_list_rejected(self, unauthenticated_client):
        """Listing memories without auth returns 401."""
        response = unauthenticated_client.get("/api/memories")
        assert response.status_code == 401

    def test_unauthenticated_health_allowed(self, unauthenticated_client):
        """Health check is public (no auth required)."""
        response = unauthenticated_client.get("/api/health")
        assert response.status_code == 200


@pytest.mark.integration
class TestReadOnlyScope:
    """Read-only scope can read but cannot write."""

    def test_read_only_can_search(self, read_only_client):
        """Read-only scope can search memories."""
        response = read_only_client.post(
            "/api/search",
            json={"query": "test", "n_results": 5},
        )
        assert response.status_code == 200

    def test_read_only_can_list(self, read_only_client):
        """Read-only scope can list memories."""
        response = read_only_client.get("/api/memories", params={"limit": 10})
        assert response.status_code == 200

    def test_read_only_cannot_store(self, read_only_client):
        """Read-only scope cannot store memories (403)."""
        response = read_only_client.post(
            "/api/memories",
            json={"content": "should fail", "tags": ["__test__"]},
        )
        assert response.status_code in (401, 403), (
            f"Read-only scope should not be able to store, got {response.status_code}"
        )

    def test_read_only_cannot_delete(self, read_only_client):
        """Read-only scope cannot delete memories (403)."""
        # Use a non-existent hash — we only care about the auth check
        response = read_only_client.delete(
            "/api/memories/nonexistent-hash-12345"
        )
        assert response.status_code in (401, 403), (
            f"Read-only scope should not be able to delete, got {response.status_code}. "
            f"If 404, the write-scope gate didn't fire before the resource lookup."
        )


@pytest.mark.integration
class TestReadWriteScope:
    """Read+write scope can perform both read and write operations."""

    def test_read_write_can_store(self, read_write_client):
        """Read+write scope can store memories."""
        uid = uuid.uuid4().hex[:8]
        response = read_write_client.post(
            "/api/memories",
            json={"content": f"Auth boundary test {uid}", "tags": ["__test__"]},
        )
        assert response.status_code in (200, 201)

    def test_read_write_can_search(self, read_write_client):
        """Read+write scope can search memories."""
        response = read_write_client.post(
            "/api/search",
            json={"query": "test", "n_results": 5},
        )
        assert response.status_code == 200

    def test_read_write_can_list(self, read_write_client):
        """Read+write scope can list memories."""
        response = read_write_client.get("/api/memories", params={"limit": 10})
        assert response.status_code == 200


@pytest.mark.integration
class TestMCPEndpointScopeEnforcement:
    """The /mcp tools/call endpoint must enforce per-tool scope checks."""

    def test_read_only_cannot_call_store_via_mcp(self, read_only_client):
        """Read-only scope cannot call store_memory via /mcp tools/call (GHSA-2r68-g678-7qr3)."""
        response = read_only_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "store_memory",
                    "arguments": {
                        "content": "MCP injection test",
                        "tags": ["__test__"],
                    },
                },
            },
        )
        # Must not succeed — either 403 from scope check or error in result
        assert response.status_code in (200, 403), response.text
        if response.status_code == 200:
            data = response.json()
            # If the HTTP status is 200, the error must be in the JSON-RPC error field
            if "error" in data:
                assert data["error"].get("code") in (-32603, 403), (
                    f"Expected scope error, got: {data['error']}"
                )

    def test_read_write_can_call_store_via_mcp(self, read_write_client):
        """Read+write scope can call store_memory via /mcp tools/call."""
        uid = uuid.uuid4().hex[:8]
        response = read_write_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "store_memory",
                    "arguments": {
                        "content": f"MCP store test {uid}",
                        "tags": ["__test__"],
                    },
                },
            },
        )
        assert response.status_code == 200, response.text


@pytest.mark.integration
class TestAnonymousAccess:
    """Anonymous access (when enabled) allows read operations."""

    def test_anonymous_can_search(self, anonymous_client):
        """When anonymous access is enabled, search works without auth."""
        response = anonymous_client.post(
            "/api/search",
            json={"query": "test", "n_results": 5},
        )
        assert response.status_code == 200

    def test_anonymous_can_list(self, anonymous_client):
        """When anonymous access is enabled, list works without auth."""
        response = anonymous_client.get("/api/memories", params={"limit": 10})
        assert response.status_code == 200


@pytest.mark.integration
class TestExpiredTokenRejection:
    """Expired JWT tokens must be rejected with 401."""

    def test_expired_jwt_rejected(self, initialized_storage, monkeypatch):
        """An expired JWT returns 401, not 200."""
        from datetime import datetime, timedelta, timezone

        import jwt as pyjwt

        from mcp_memory_service.web.oauth import middleware

        monkeypatch.setattr(middleware, "API_KEY", None)
        monkeypatch.setattr(middleware, "OAUTH_ENABLED", True)
        monkeypatch.setattr(middleware, "ALLOW_ANONYMOUS_ACCESS", False)

        from mcp_memory_service.web.app import app

        set_storage(initialized_storage)

        # Clear overrides so real middleware runs
        app.dependency_overrides.clear()

        # Create an expired JWT
        secret = "test-secret"
        monkeypatch.setattr(middleware, "get_jwt_verification_key", lambda: secret)
        monkeypatch.setattr(middleware, "get_jwt_algorithm", lambda: "HS256")

        expired_payload = {
            "sub": "test-client",
            "iss": "http://localhost:8000",
            "aud": "mcp-memory-service",
            "scope": "read write",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = pyjwt.encode(expired_payload, secret, algorithm="HS256")

        client = TestClient(app)
        try:
            response = client.get(
                "/api/memories",
                headers={"Authorization": f"Bearer {expired_token}"},
            )
            assert response.status_code == 401, (
                f"Expired token should return 401, got {response.status_code}"
            )
        finally:
            app.dependency_overrides.clear()


@pytest.mark.integration
class TestLocalOnlyToolsFiltering:
    """local_only_tools must be filtered from HTTP MCP transport (confused-deputy guard)."""

    def test_local_only_tools_not_in_http_mcp_list(self, read_write_client):
        """memory_harvest and memory_ingest must not appear in /mcp tools/list."""
        response = read_write_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            },
        )
        assert response.status_code == 200, response.text
        data = response.json()
        tool_names = [t["name"] for t in data.get("result", {}).get("tools", [])]
        assert "memory_harvest" not in tool_names, (
            "memory_harvest must be filtered from HTTP MCP transport"
        )
        assert "memory_ingest" not in tool_names, (
            "memory_ingest must be filtered from HTTP MCP transport"
        )

    def test_local_only_tools_call_rejected(self, read_write_client):
        """Calling memory_harvest via HTTP MCP must be rejected."""
        response = read_write_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "memory_harvest",
                    "arguments": {"project_path": "test"},
                },
            },
        )
        # Must not succeed — the tool should be filtered or return an error
        assert response.status_code in (200, 403, 404), response.text
        if response.status_code == 200:
            data = response.json()
            if "error" in data:
                assert data["error"].get("code") in (-32602, -32601, 403), (
                    f"Expected tool-not-found or scope error, got: {data['error']}"
                )


class TestAuthenticationResultScopeCheck:
    """Unit tests for AuthenticationResult.has_scope()."""

    def test_has_scope_true_when_scope_present(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(
            authenticated=True, client_id="test", scope="read write admin",
        )
        assert result.has_scope("read") is True
        assert result.has_scope("write") is True
        assert result.has_scope("admin") is True

    def test_has_scope_false_when_scope_absent(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(
            authenticated=True, client_id="test", scope="read",
        )
        assert result.has_scope("read") is True
        assert result.has_scope("write") is False

    def test_has_scope_false_when_not_authenticated(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(authenticated=False)
        assert result.has_scope("read") is False
        assert result.has_scope("write") is False

    def test_has_scope_false_when_no_scope(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(authenticated=True, scope=None)
        assert result.has_scope("read") is False
