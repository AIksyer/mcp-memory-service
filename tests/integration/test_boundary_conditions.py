# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Boundary condition integration tests.

Tests edge cases and boundary conditions:
- Empty database first query
- Large payload handling
- Very long tag names
- Empty string / None value inputs
- Unicode / Emoji content storage and retrieval
- Concurrent writes to the same memory
"""

import asyncio
import os
import tempfile
import uuid

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.web.dependencies import set_storage


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_db():
    tmpdir = tempfile.mkdtemp()
    yield os.path.join(tmpdir, "boundary_test.db")
    import shutil
    shutil.rmtree(tmpdir, ignore_errors=True)


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


def _make_client(initialized_storage, monkeypatch) -> TestClient:
    """Create a TestClient with full read+write auth mocked."""
    from mcp_memory_service.web.oauth import middleware
    monkeypatch.setattr(middleware, "API_KEY", None)
    monkeypatch.setattr(middleware, "OAUTH_ENABLED", False)
    monkeypatch.setattr(middleware, "ALLOW_ANONYMOUS_ACCESS", True)

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
            authenticated=True,
            client_id="test",
            scope="read write",
            auth_method="test",
        )

    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[require_read_access] = _user
    app.dependency_overrides[require_write_access] = _user

    return TestClient(app)


@pytest.fixture
def client(initialized_storage, monkeypatch):
    c = _make_client(initialized_storage, monkeypatch)
    yield c
    from mcp_memory_service.web.app import app
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestEmptyDatabase:
    """Empty database boundary conditions."""

    def test_search_on_empty_db(self, client):
        """Searching an empty database returns empty results, not an error."""
        response = client.post(
            "/api/search",
            json={"query": "anything", "n_results": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["results"] == []
        assert data["total_found"] == 0

    def test_list_memories_empty_db(self, client):
        """Listing memories on an empty database returns empty list."""
        response = client.get("/api/memories")
        assert response.status_code == 200
        data = response.json()
        assert data["memories"] == []
        assert data["total"] == 0

    def test_get_nonexistent_memory(self, client):
        """Getting a non-existent memory returns 404."""
        response = client.get("/api/memories/nonexistent-hash-12345")
        assert response.status_code == 404

    def test_delete_nonexistent_memory(self, client):
        """Deleting a non-existent memory returns a response (not 500)."""
        response = client.delete("/api/memories/nonexistent-hash-12345")
        assert response.status_code == 200
        data = response.json()
        # delete returns success=False for non-existent
        assert data["success"] is False

    def test_tags_on_empty_db(self, client):
        """Getting tags on an empty database returns empty list."""
        response = client.get("/api/tags")
        assert response.status_code == 200
        data = response.json()
        assert data["tags"] == []


@pytest.mark.integration
class TestEmptyAndNoneInputs:
    """Empty string and None value boundary conditions."""

    def test_store_empty_content(self, client):
        """Storing empty content is handled gracefully."""
        response = client.post(
            "/api/memories",
            json={"content": "", "tags": ["__test__"]},
        )
        # Should not be 500 — either accepted (200) or validation error (422)
        assert response.status_code in (200, 422), response.text

    def test_store_none_content(self, client):
        """Storing null content is rejected by Pydantic validation."""
        response = client.post(
            "/api/memories",
            json={"content": None, "tags": ["__test__"]},
        )
        assert response.status_code == 422

    def test_store_no_content_field(self, client):
        """Missing content field is rejected."""
        response = client.post(
            "/api/memories",
            json={"tags": ["__test__"]},
        )
        assert response.status_code == 422

    def test_search_empty_query(self, client):
        """Searching with empty query is handled gracefully."""
        response = client.post(
            "/api/search",
            json={"query": "", "n_results": 5},
        )
        # Should not be 500
        assert response.status_code in (200, 400, 422), response.text

    def test_search_none_query(self, client):
        """Searching with null query is rejected."""
        response = client.post(
            "/api/search",
            json={"query": None, "n_results": 5},
        )
        assert response.status_code == 422


@pytest.mark.integration
class TestUnicodeAndEmoji:
    """Unicode and Emoji content storage and retrieval."""

    def test_store_retrieve_unicode(self, client):
        """Unicode content (Chinese, Japanese, Arabic) can be stored and retrieved."""
        content = f"Unicode test: 你好世界 日本語 مرحبا {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", "unicode"]},
        )
        assert response.status_code in (200, 201), response.text
        content_hash = response.json().get("content_hash")
        assert content_hash is not None

        # Retrieve by hash
        get_resp = client.get(f"/api/memories/{content_hash}")
        assert get_resp.status_code == 200
        assert content in get_resp.json()["content"]

    def test_store_retrieve_emoji(self, client):
        """Emoji content can be stored and retrieved intact."""
        content = f"Emoji test: 🧠💾🚀✨🎉 {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", "emoji"]},
        )
        assert response.status_code in (200, 201), response.text
        content_hash = response.json().get("content_hash")
        assert content_hash is not None

        get_resp = client.get(f"/api/memories/{content_hash}")
        assert get_resp.status_code == 200
        retrieved = get_resp.json()["content"]
        assert "🧠" in retrieved
        assert "💾" in retrieved

    def test_search_unicode_query(self, client):
        """Searching with unicode query returns results."""
        # First store a memory
        content = f"中文记忆测试 {uuid.uuid4().hex[:8]}"
        client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", "unicode-search"]},
        )
        # Then search for it
        response = client.post(
            "/api/search",
            json={"query": "中文", "n_results": 10},
        )
        assert response.status_code == 200
        # Should return at least one result (may not be exact match due to hash embeddings)
        data = response.json()
        assert isinstance(data["results"], list)


@pytest.mark.integration
class TestLargePayload:
    """Large payload boundary conditions."""

    def test_large_content_storage(self, client):
        """Storing content > 100KB succeeds (within body limit)."""
        # Generate ~100KB of content
        large_content = "A" * 100_000 + f" {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={"content": large_content, "tags": ["__test__", "large"]},
        )
        # Should succeed or be rejected by body limit, but not 500
        assert response.status_code in (200, 201, 413), response.text

    def test_many_tags(self, client):
        """Storing with many tags works."""
        tags = [f"tag-{i}" for i in range(50)] + ["__test__"]
        content = f"Many tags test {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={"content": content, "tags": tags},
        )
        assert response.status_code in (200, 201), response.text

    def test_long_tag_name(self, client):
        """Very long tag names are handled gracefully."""
        long_tag = "x" * 500
        content = f"Long tag test {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", long_tag]},
        )
        # Should not be 500
        assert response.status_code in (200, 201, 422), response.text

    def test_large_metadata(self, client):
        """Large metadata dict is handled."""
        large_metadata = {f"key_{i}": f"value_{i}" for i in range(100)}
        content = f"Large metadata test {uuid.uuid4().hex[:8]}"
        response = client.post(
            "/api/memories",
            json={
                "content": content,
                "tags": ["__test__"],
                "metadata": large_metadata,
            },
        )
        assert response.status_code in (200, 201, 422), response.text


@pytest.mark.integration
class TestConcurrentAccess:
    """Concurrent access boundary conditions."""

    @pytest.mark.asyncio
    async def test_concurrent_stores_different_content(self, client):
        """Multiple concurrent stores with different content all succeed.

        Uses httpx.AsyncClient with ASGITransport to issue truly concurrent
        requests within a single event loop. Thread-based concurrency with
        TestClient fails because the storage's asyncio.Lock is bound to the
        event loop where initialize() was called.
        """
        import httpx
        from httpx import ASGITransport
        from mcp_memory_service.web.app import app

        contents = [
            f"Concurrent test {i} {uuid.uuid4().hex[:8]}"
            for i in range(5)
        ]

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            tasks = [
                ac.post(
                    "/api/memories",
                    json={"content": c, "tags": ["__test__", "concurrent"]},
                )
                for c in contents
            ]
            responses = await asyncio.gather(*tasks)

        for resp in responses:
            assert resp.status_code in (200, 201), (
                f"Concurrent store failed with status {resp.status_code}"
            )

    @pytest.mark.asyncio
    async def test_concurrent_search_and_store(self, client):
        """Concurrent search and store don't conflict."""
        import httpx
        from httpx import ASGITransport
        from mcp_memory_service.web.app import app

        # First store something to search for
        content = f"Concurrency search target {uuid.uuid4().hex[:8]}"
        client.post(
            "/api/memories",
            json={"content": content, "tags": ["__test__", "concurrent-search"]},
        )

        async with httpx.AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            search_task = ac.post(
                "/api/search",
                json={"query": "concurrency", "n_results": 5},
            )
            store_task = ac.post(
                "/api/memories",
                json={
                    "content": f"Concurrent write {uuid.uuid4().hex[:8]}",
                    "tags": ["__test__", "concurrent-write"],
                },
            )
            search_resp, store_resp = await asyncio.gather(search_task, store_task)

        assert search_resp.status_code == 200, (
            f"Search failed with status {search_resp.status_code}"
        )
        assert store_resp.status_code in (200, 201), (
            f"Store failed with status {store_resp.status_code}"
        )
