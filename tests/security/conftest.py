# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Shared fixtures for security tests.

Provides temp_db, initialized_storage, authed_client, and auth-scope
client fixtures used across test_sql_injection, test_path_traversal,
test_xss_injection, and test_auth_boundaries.
"""

import os
import tempfile

import pytest
import pytest_asyncio
from fastapi import HTTPException, status
from fastapi.testclient import TestClient

from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.web.dependencies import set_storage


@pytest.fixture
def temp_db():
    with tempfile.TemporaryDirectory() as tmpdir:
        yield os.path.join(tmpdir, "test_security.db")


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def authed_client(initialized_storage, monkeypatch):
    """TestClient with full read/write/admin scope and anonymous access enabled."""
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


def _make_client(initialized_storage, monkeypatch, *, scope: str | None,
                 allow_anonymous: bool = False) -> TestClient:
    """Create a TestClient with specific auth configuration.

    Args:
        scope: OAuth scope string ("read", "read write", None for unauthenticated)
        allow_anonymous: If True, sets MCP_ALLOW_ANONYMOUS_ACCESS=true

    Note: We only override ``get_current_user`` and ``require_read_access``.
    ``require_write_access`` is left to the real implementation so it can
    enforce per-scope checks against the mocked user.
    """
    from mcp_memory_service.web.oauth import middleware
    monkeypatch.setattr(middleware, "API_KEY", None)
    monkeypatch.setattr(middleware, "OAUTH_ENABLED", False)
    monkeypatch.setattr(middleware, "ALLOW_ANONYMOUS_ACCESS", allow_anonymous)

    from mcp_memory_service.web.app import app
    from mcp_memory_service.web.oauth.middleware import (
        AuthenticationResult,
        get_current_user,
        require_read_access,
    )

    set_storage(initialized_storage)

    if scope is not None:
        async def mock_user():
            return AuthenticationResult(
                authenticated=True, client_id="test-client",
                scope=scope, auth_method="test",
            )

        app.dependency_overrides[get_current_user] = mock_user
        app.dependency_overrides[require_read_access] = mock_user
    else:
        async def reject():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authentication required",
            )

        app.dependency_overrides[get_current_user] = reject
        app.dependency_overrides[require_read_access] = reject

    return TestClient(app)


@pytest.fixture
def read_only_client(initialized_storage, monkeypatch):
    client = _make_client(initialized_storage, monkeypatch, scope="read")
    yield client
    from mcp_memory_service.web.app import app
    app.dependency_overrides.clear()


@pytest.fixture
def read_write_client(initialized_storage, monkeypatch):
    client = _make_client(initialized_storage, monkeypatch, scope="read write")
    yield client
    from mcp_memory_service.web.app import app
    app.dependency_overrides.clear()


@pytest.fixture
def unauthenticated_client(initialized_storage, monkeypatch):
    client = _make_client(initialized_storage, monkeypatch, scope=None)
    yield client
    from mcp_memory_service.web.app import app
    app.dependency_overrides.clear()


@pytest.fixture
def anonymous_client(initialized_storage, monkeypatch):
    """Client with anonymous access enabled — no auth overrides, real middleware."""
    from mcp_memory_service.web.oauth import middleware
    monkeypatch.setattr(middleware, "API_KEY", None)
    monkeypatch.setattr(middleware, "OAUTH_ENABLED", False)
    monkeypatch.setattr(middleware, "ALLOW_ANONYMOUS_ACCESS", True)

    from mcp_memory_service.web.app import app

    set_storage(initialized_storage)

    # Clear any overrides from previous tests so the real middleware runs
    app.dependency_overrides.clear()

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()
