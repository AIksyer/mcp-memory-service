# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Tests for tag-usage analytics period filtering (P0 fix).

Tests that the /api/analytics/tag-usage endpoint correctly filters
tag usage data by the `period` parameter (week, month, all).
"""

import pytest
import pytest_asyncio
import tempfile
import os
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from mcp_memory_service.web.dependencies import set_storage
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.models.memory import Memory
from mcp_memory_service.utils.hashing import generate_content_hash


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_period.db")
        yield db_path


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    """Create and initialize a real SQLite storage backend."""
    monkeypatch.setenv('MCP_SEMANTIC_DEDUP_ENABLED', 'false')
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def test_app(initialized_storage, monkeypatch):
    """Create a FastAPI test application with initialized storage."""
    monkeypatch.setenv('MCP_API_KEY', '')
    monkeypatch.setenv('MCP_OAUTH_ENABLED', 'false')
    monkeypatch.setenv('MCP_ALLOW_ANONYMOUS_ACCESS', 'true')

    from mcp_memory_service.web.app import app
    from mcp_memory_service.web.oauth.middleware import (
        get_current_user, require_write_access, require_read_access,
        AuthenticationResult
    )

    set_storage(initialized_storage)

    async def mock_get_current_user():
        return AuthenticationResult(
            authenticated=True,
            client_id="test_client",
            scope="read write admin",
            auth_method="test"
        )

    app.dependency_overrides[get_current_user] = mock_get_current_user
    app.dependency_overrides[require_write_access] = mock_get_current_user
    app.dependency_overrides[require_read_access] = mock_get_current_user

    client = TestClient(app)
    yield client
    app.dependency_overrides.clear()


async def _store_memory_with_timestamp(storage, content, tags, timestamp):
    """Store a memory and override its created_at timestamp in the DB."""
    memory = Memory(
        content=content,
        content_hash=generate_content_hash(content),
        tags=tags,
        memory_type="note"
    )
    success, message = await storage.store(memory)
    assert success, f"Failed to store memory: {message}"
    # Override the created_at timestamp directly in the DB
    storage.conn.execute(
        "UPDATE memories SET created_at = ? WHERE content_hash = ?",
        (timestamp, memory.content_hash)
    )
    storage.conn.commit()
    return memory.content_hash


# ── Period filtering tests ──────────────────────────────────────────

@pytest.mark.asyncio
async def test_tag_usage_all_period_returns_all_tags(test_app, initialized_storage):
    """period=all should return tags from all memories regardless of time."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()

    await _store_memory_with_timestamp(
        initialized_storage, "Recent memory content", ["recent-tag"], now_ts
    )
    await _store_memory_with_timestamp(
        initialized_storage, "Old memory content", ["old-tag"], old_ts
    )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=all")
    assert response.status_code == 200
    data = response.json()
    tag_names = [t["tag"] for t in data["tags"]]
    assert "recent-tag" in tag_names
    assert "old-tag" in tag_names
    assert data["period"] == "all"


@pytest.mark.asyncio
async def test_tag_usage_week_period_excludes_old_memories(test_app, initialized_storage):
    """period=week should only return tags from memories created in the last 7 days."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()

    await _store_memory_with_timestamp(
        initialized_storage, "Recent memory content for week test", ["recent-tag"], now_ts
    )
    await _store_memory_with_timestamp(
        initialized_storage, "Old memory content for week test", ["old-tag"], old_ts
    )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=week")
    assert response.status_code == 200
    data = response.json()
    tag_names = [t["tag"] for t in data["tags"]]
    assert "recent-tag" in tag_names
    assert "old-tag" not in tag_names
    assert data["period"] == "week"
    assert data["total_memories"] == 1


@pytest.mark.asyncio
async def test_tag_usage_month_period_excludes_very_old_memories(test_app, initialized_storage):
    """period=month should only return tags from memories created in the last 30 days."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()

    await _store_memory_with_timestamp(
        initialized_storage, "Recent memory content for month test", ["recent-tag"], now_ts
    )
    await _store_memory_with_timestamp(
        initialized_storage, "Old memory content for month test", ["old-tag"], old_ts
    )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=month")
    assert response.status_code == 200
    data = response.json()
    tag_names = [t["tag"] for t in data["tags"]]
    assert "recent-tag" in tag_names
    assert "old-tag" not in tag_names
    assert data["period"] == "month"
    assert data["total_memories"] == 1


@pytest.mark.asyncio
async def test_tag_usage_week_includes_boundary_memory(test_app, initialized_storage):
    """A memory created exactly 6 days ago should be included in the week period."""
    six_days_ago_ts = (datetime.now(timezone.utc) - timedelta(days=6)).timestamp()

    await _store_memory_with_timestamp(
        initialized_storage, "Boundary memory content", ["boundary-tag"], six_days_ago_ts
    )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=week")
    assert response.status_code == 200
    data = response.json()
    tag_names = [t["tag"] for t in data["tags"]]
    assert "boundary-tag" in tag_names


@pytest.mark.asyncio
async def test_tag_usage_invalid_period_returns_400(test_app, initialized_storage):
    """Invalid period value should return HTTP 400."""
    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=invalid")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_tag_usage_default_period_is_all(test_app, initialized_storage):
    """When period is not specified, default should be 'all'."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=90)).timestamp()

    await _store_memory_with_timestamp(
        initialized_storage, "Recent default memory", ["recent-default"], now_ts
    )
    await _store_memory_with_timestamp(
        initialized_storage, "Old default memory", ["old-default"], old_ts
    )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage")
    assert response.status_code == 200
    data = response.json()
    tag_names = [t["tag"] for t in data["tags"]]
    assert "recent-default" in tag_names
    assert "old-default" in tag_names
    assert data["period"] == "all"


@pytest.mark.asyncio
async def test_tag_usage_period_filters_tag_counts(test_app, initialized_storage):
    """Tag counts should reflect only memories within the period."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()

    # Store 3 recent memories with "shared-tag"
    for i in range(3):
        await _store_memory_with_timestamp(
            initialized_storage, f"Recent shared {i}", ["shared-tag"], now_ts
        )
    # Store 2 old memories with "shared-tag" — these should be excluded in week period
    for i in range(2):
        await _store_memory_with_timestamp(
            initialized_storage, f"Old shared {i}", ["shared-tag"], old_ts
        )

    set_storage(initialized_storage)

    # All period — should see count of 5
    response_all = test_app.get("/api/analytics/tag-usage?period=all")
    assert response_all.status_code == 200
    data_all = response_all.json()
    shared_all = [t for t in data_all["tags"] if t["tag"] == "shared-tag"]
    assert len(shared_all) == 1
    assert shared_all[0]["count"] == 5

    # Week period — should see count of 3
    response_week = test_app.get("/api/analytics/tag-usage?period=week")
    assert response_week.status_code == 200
    data_week = response_week.json()
    shared_week = [t for t in data_week["tags"] if t["tag"] == "shared-tag"]
    assert len(shared_week) == 1
    assert shared_week[0]["count"] == 3


@pytest.mark.asyncio
async def test_tag_usage_period_empty_database(test_app, initialized_storage):
    """Empty database should return empty tags for any period."""
    set_storage(initialized_storage)

    for period in ("all", "week", "month"):
        response = test_app.get(f"/api/analytics/tag-usage?period={period}")
        assert response.status_code == 200
        data = response.json()
        assert data["tags"] == []
        assert data["total_memories"] == 0


@pytest.mark.asyncio
async def test_tag_usage_period_limit_parameter(test_app, initialized_storage):
    """Limit parameter should still work with period filtering."""
    now_ts = datetime.now(timezone.utc).timestamp()

    for i in range(10):
        await _store_memory_with_timestamp(
            initialized_storage, f"Limited memory {i}", [f"tag-{i}"], now_ts
        )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=week&limit=3")
    assert response.status_code == 200
    data = response.json()
    assert len(data["tags"]) <= 3


@pytest.mark.asyncio
async def test_tag_usage_period_percentage_calculation(test_app, initialized_storage):
    """Percentages should be calculated against period-filtered total, not global total."""
    now_ts = datetime.now(timezone.utc).timestamp()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=60)).timestamp()

    # 2 recent memories with "tag-a"
    for i in range(2):
        await _store_memory_with_timestamp(
            initialized_storage, f"Recent A {i}", ["tag-a"], now_ts
        )
    # 1 recent memory with "tag-b"
    await _store_memory_with_timestamp(
        initialized_storage, "Recent B", ["tag-b"], now_ts
    )
    # 5 old memories with "tag-a" — excluded in week
    for i in range(5):
        await _store_memory_with_timestamp(
            initialized_storage, f"Old A {i}", ["tag-a"], old_ts
        )

    set_storage(initialized_storage)
    response = test_app.get("/api/analytics/tag-usage?period=week")
    assert response.status_code == 200
    data = response.json()

    # total_memories should be 3 (2 tag-a + 1 tag-b), not 8
    assert data["total_memories"] == 3

    tag_a = [t for t in data["tags"] if t["tag"] == "tag-a"]
    assert len(tag_a) == 1
    assert tag_a[0]["count"] == 2
    assert tag_a[0]["percentage"] == round(2 / 3 * 100, 1)

    tag_b = [t for t in data["tags"] if t["tag"] == "tag-b"]
    assert len(tag_b) == 1
    assert tag_b[0]["count"] == 1
    assert tag_b[0]["percentage"] == round(1 / 3 * 100, 1)
