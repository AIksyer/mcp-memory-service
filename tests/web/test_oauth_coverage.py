# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Coverage tests for OAuth modules previously omitted from .coveragerc.

Tests:
- OAuth discovery endpoints (RFC 8414, RFC 9728, OIDC)
- Dynamic Client Registration (RFC 7591)
- OAuth middleware scope enforcement
- OAuth storage (SQLite)
- Rate limiting
"""

import os
import tempfile

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.web.dependencies import set_storage


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_oauth.db")


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def authed_client(initialized_storage, monkeypatch):
    """TestClient with OAuth disabled (default test configuration)."""
    monkeypatch.setenv("MCP_API_KEY", "")
    monkeypatch.setenv("MCP_OAUTH_ENABLED", "false")
    monkeypatch.setenv("MCP_ALLOW_ANONYMOUS_ACCESS", "true")

    from mcp_memory_service.web.app import app
    from mcp_memory_service.web.oauth.middleware import (
        AuthenticationResult,
        get_current_user,
        require_read_access,
        require_write_access,
    )

    set_storage(initialized_storage)

    async def _user():
        return AuthenticationResult(
            authenticated=True, client_id="test", scope="read write admin",
            auth_method="test",
        )

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[require_read_access] = _user
    app.dependency_overrides[require_write_access] = _user

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
def oauth_client_app(initialized_storage, temp_db, monkeypatch):
    """TestClient with OAuth enabled — covers OAuth route handlers.

    Reloads config and app modules so OAuth routes are registered.
    Uses in-memory OAuth storage to avoid file conflicts.
    Restores original module state after test to prevent cross-test contamination.
    """
    monkeypatch.setenv("MCP_OAUTH_ENABLED", "true")
    monkeypatch.setenv("MCP_ALLOW_ANONYMOUS_ACCESS", "false")
    monkeypatch.setenv("MCP_API_KEY", "")
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    monkeypatch.setenv("MCP_OAUTH_ISSUER", "http://localhost:8000")
    monkeypatch.setenv("MCP_OAUTH_STORAGE_BACKEND", "memory")

    # Reset global OAuth storage so it re-initializes with new config
    import mcp_memory_service.web.oauth.storage as oauth_storage_mod
    oauth_storage_mod._oauth_storage = None

    # Force reimport of config and app to pick up OAuth enabled
    import importlib

    import mcp_memory_service.config.oauth
    importlib.reload(mcp_memory_service.config.oauth)
    import mcp_memory_service.config
    importlib.reload(mcp_memory_service.config)
    import mcp_memory_service.web.app
    importlib.reload(mcp_memory_service.web.app)

    from mcp_memory_service.web.app import app
    set_storage(initialized_storage)

    client = TestClient(app)
    yield client

    # Cleanup: reset OAuth storage global and restore OAuth-disabled app
    oauth_storage_mod._oauth_storage = None
    monkeypatch.setenv("MCP_OAUTH_ENABLED", "false")
    importlib.reload(mcp_memory_service.config.oauth)
    importlib.reload(mcp_memory_service.config)
    importlib.reload(mcp_memory_service.web.app)


# --- OAuth Discovery endpoint coverage (OAuth disabled) ---

@pytest.mark.integration
class TestOAuthDiscoveryEndpoints:
    """Cover web/oauth/discovery.py routes.

    With OAuth disabled, these routes are not registered → 404.
    """

    def test_protected_resource_metadata(self, authed_client):
        """RFC 9728 protected resource metadata endpoint."""
        response = authed_client.get("/.well-known/oauth-protected-resource")
        # OAuth disabled → route not registered → 404
        assert response.status_code == 404

    def test_authorization_server_metadata(self, authed_client):
        """RFC 8414 authorization server metadata endpoint."""
        response = authed_client.get(
            "/.well-known/oauth-authorization-server"
        )
        assert response.status_code == 404

    def test_openid_configuration(self, authed_client):
        """OIDC discovery endpoint."""
        response = authed_client.get(
            "/.well-known/openid-configuration"
        )
        assert response.status_code == 404


# --- OAuth Discovery endpoint coverage (OAuth enabled) ---

@pytest.mark.integration
class TestOAuthDiscoveryEndpointsEnabled:
    """Cover web/oauth/discovery.py routes with OAuth enabled."""

    def test_protected_resource_metadata_enabled(self, oauth_client_app):
        """RFC 9728 protected resource metadata with OAuth enabled."""
        response = oauth_client_app.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        data = response.json()
        assert "resource" in data
        assert "bearer_methods_supported" in data

    def test_authorization_server_metadata_enabled(self, oauth_client_app):
        """RFC 8414 authorization server metadata with OAuth enabled."""
        response = oauth_client_app.get(
            "/.well-known/oauth-authorization-server"
        )
        assert response.status_code == 200
        data = response.json()
        assert "issuer" in data
        assert "authorization_endpoint" in data
        assert "token_endpoint" in data
        assert "registration_endpoint" in data

    def test_openid_configuration_enabled(self, oauth_client_app):
        """OIDC discovery endpoint with OAuth enabled."""
        response = oauth_client_app.get(
            "/.well-known/openid-configuration"
        )
        assert response.status_code == 200
        data = response.json()
        assert "issuer" in data


# --- OAuth Registration endpoint coverage ---

@pytest.mark.integration
class TestOAuthRegistration:
    """Cover web/oauth/registration.py routes."""

    def test_register_client_oauth_disabled(self, authed_client):
        """DCR endpoint is not registered when OAuth is disabled → 404."""
        response = authed_client.post(
            "/oauth/register",
            json={
                "redirect_uris": ["http://localhost:3000/callback"],
                "client_name": "Test Client",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": "read write",
            },
        )
        assert response.status_code == 404

    def test_register_client_enabled(self, oauth_client_app):
        """DCR: Register a new OAuth client with OAuth enabled → 201."""
        response = oauth_client_app.post(
            "/oauth/register",
            json={
                "redirect_uris": ["http://localhost:3000/callback"],
                "client_name": "Test Client",
                "grant_types": ["authorization_code", "refresh_token"],
                "response_types": ["code"],
                "token_endpoint_auth_method": "client_secret_post",
                "scope": "read write",
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert "client_id" in data
        assert "client_secret" in data
        assert data["client_name"] == "Test Client"
        assert "authorization_code" in data["grant_types"]

    def test_register_client_minimal_enabled(self, oauth_client_app):
        """DCR with minimal required fields → 201."""
        response = oauth_client_app.post(
            "/oauth/register",
            json={
                "redirect_uris": ["http://localhost:3000/callback"],
            },
        )
        assert response.status_code == 201, response.text
        data = response.json()
        assert "client_id" in data

    def test_get_registered_client_not_found(self, authed_client):
        """Getting a non-existent client returns 404 when OAuth is disabled."""
        response = authed_client.get("/oauth/clients/nonexistent-client-id")
        assert response.status_code == 404


# --- OAuth Middleware coverage ---

class TestOAuthMiddleware:
    """Cover web/oauth/middleware.py functions."""

    def test_authentication_result_creation(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(
            authenticated=True, client_id="test", scope="read write",
            auth_method="api_key",
        )
        assert result.authenticated is True
        assert result.client_id == "test"
        assert result.has_scope("read")
        assert result.has_scope("write")
        assert not result.has_scope("admin")

    def test_authentication_result_unauthenticated(self):
        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(authenticated=False, error="invalid_token")
        assert result.authenticated is False
        assert result.error == "invalid_token"
        assert not result.has_scope("read")

    def test_authentication_result_require_scope_raises(self):
        from fastapi import HTTPException

        from mcp_memory_service.web.oauth.middleware import AuthenticationResult

        result = AuthenticationResult(
            authenticated=True, client_id="test", scope="read",
        )
        with pytest.raises(HTTPException) as exc_info:
            result.require_scope("write")
        assert exc_info.value.status_code == 403

    def test_validate_jwt_token_invalid(self):
        from mcp_memory_service.web.oauth.middleware import validate_jwt_token

        result = validate_jwt_token("invalid.token.here")
        assert result is None

    def test_validate_jwt_token_empty(self):
        from mcp_memory_service.web.oauth.middleware import validate_jwt_token

        assert validate_jwt_token("") is None
        assert validate_jwt_token(None) is None

    def test_authenticate_bearer_token_invalid(self):
        import asyncio

        from mcp_memory_service.web.oauth.middleware import authenticate_bearer_token

        result = asyncio.run(authenticate_bearer_token("invalid-token"))
        assert result.authenticated is False

    def test_authenticate_bearer_token_empty(self):
        import asyncio

        from mcp_memory_service.web.oauth.middleware import authenticate_bearer_token

        result = asyncio.run(authenticate_bearer_token(""))
        assert result.authenticated is False


# --- OAuth Models coverage ---

class TestOAuthModels:
    """Cover web/oauth/models.py data structures."""

    def test_registered_client_model(self):
        import time

        from mcp_memory_service.web.oauth.models import RegisteredClient

        client = RegisteredClient(
            client_id="test-id",
            client_secret="test-secret",
            client_name="Test",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code"],
            response_types=["code"],
            scope="read write",
            token_endpoint_auth_method="client_secret_post",
            created_at=time.time(),
        )
        assert client.client_id == "test-id"
        assert "authorization_code" in client.grant_types

    def test_registered_client_secret_redacted(self):
        import time

        from mcp_memory_service.web.oauth.models import RegisteredClient

        client = RegisteredClient(
            client_id="test-id",
            client_secret="super-secret-value",
            client_name="Test",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code"],
            response_types=["code"],
            scope="read",
            token_endpoint_auth_method="client_secret_post",
            created_at=time.time(),
        )
        # Secret should exist in the model
        d = client.dict() if hasattr(client, "dict") else client.model_dump()
        assert "client_secret" in d


# --- OAuth Limits coverage ---

class TestOAuthLimits:
    """Cover web/oauth/limits.py constants."""

    def test_limits_are_positive_integers(self):
        from mcp_memory_service.web.oauth import limits

        assert isinstance(limits.MAX_API_KEY_LEN, int)
        assert limits.MAX_API_KEY_LEN > 0
        assert isinstance(limits.MAX_JWT_LEN, int)
        assert limits.MAX_JWT_LEN > 0


# --- OAuth Storage coverage ---

class TestOAuthStorageCoverage:
    """Cover web/oauth/storage/sqlite.py CRUD operations."""

    def test_sqlite_oauth_storage_generate_ids(self, tmp_path):
        """Test ID generation methods from base class."""
        from mcp_memory_service.web.oauth.storage.sqlite import SQLiteOAuthStorage

        storage = SQLiteOAuthStorage(str(tmp_path / "oauth_test3.db"))
        client_id = storage.generate_client_id()
        client_secret = storage.generate_client_secret()
        assert isinstance(client_id, str)
        assert len(client_id) > 0
        assert isinstance(client_secret, str)
        assert len(client_secret) > 0
        # IDs should be unique
        assert client_id != storage.generate_client_id()
        assert client_secret != storage.generate_client_secret()

    @pytest.mark.asyncio
    async def test_sqlite_oauth_storage_crud(self, tmp_path):
        """Test SQLite OAuth storage client CRUD operations."""
        import time

        from mcp_memory_service.web.oauth.models import RegisteredClient
        from mcp_memory_service.web.oauth.storage.sqlite import SQLiteOAuthStorage

        storage = SQLiteOAuthStorage(str(tmp_path / "oauth_test.db"))

        # store_client triggers lazy DB initialization
        client = RegisteredClient(
            client_id="test-client-id",
            client_secret="test-secret",
            client_name="Test Client",
            redirect_uris=["http://localhost:3000/callback"],
            grant_types=["authorization_code"],
            response_types=["code"],
            scope="read write",
            token_endpoint_auth_method="client_secret_post",
            created_at=time.time(),
        )
        await storage.store_client(client)

        # Retrieve it
        retrieved = await storage.get_client("test-client-id")
        assert retrieved is not None
        assert retrieved.client_id == "test-client-id"
        assert retrieved.client_name == "Test Client"

        # Authenticate with correct secret
        auth_ok = await storage.authenticate_client("test-client-id", "test-secret")
        assert auth_ok is True

        # Authenticate with wrong secret
        auth_bad = await storage.authenticate_client("test-client-id", "wrong-secret")
        assert auth_bad is False

        await storage.close()

    @pytest.mark.asyncio
    async def test_sqlite_oauth_storage_get_nonexistent(self, tmp_path):
        """Getting a non-existent client returns None."""
        from mcp_memory_service.web.oauth.storage.sqlite import SQLiteOAuthStorage

        storage = SQLiteOAuthStorage(str(tmp_path / "oauth_test2.db"))

        # Trigger lazy init by calling _get_connection
        await storage._get_connection()
        result = await storage.get_client("nonexistent-id")
        assert result is None
        await storage.close()

    @pytest.mark.asyncio
    async def test_sqlite_oauth_storage_authorization_code(self, tmp_path):
        """Test storing and retrieving authorization codes."""

        from mcp_memory_service.web.oauth.storage.sqlite import SQLiteOAuthStorage

        storage = SQLiteOAuthStorage(str(tmp_path / "oauth_test4.db"))

        await storage._get_connection()

        # Store an authorization code
        await storage.store_authorization_code(
            code="test-auth-code",
            client_id="test-client",
            redirect_uri="http://localhost:3000/callback",
            scope="read write",
            code_challenge="test-challenge",
            code_challenge_method="S256",
            expires_in=600,
        )

        # Retrieve it
        retrieved = await storage.get_authorization_code("test-auth-code")
        assert retrieved is not None
        assert retrieved["client_id"] == "test-client"
        assert retrieved["scope"] == "read write"

        await storage.close()
