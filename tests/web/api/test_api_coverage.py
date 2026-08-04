# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Coverage tests for web/api endpoints that were previously omitted from .coveragerc.

Tests HTTP status codes and response structures for:
- health.py (basic + detailed health, memory stats, cache clearing)
- configuration.py (env config, credentials)
- sync.py (sync status, force, pause/resume)
- backup.py (backup status, list, trigger)
- events.py (SSE stats)
- manage.py (bulk operations, tag stats, system operations)
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
        yield os.path.join(tmpdir, "test_api.db")


@pytest_asyncio.fixture
async def initialized_storage(temp_db, monkeypatch):
    monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
    storage = SqliteVecMemoryStorage(temp_db)
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.fixture
def authed_client(initialized_storage, monkeypatch):
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


# --- Health endpoint coverage ---

@pytest.mark.integration
class TestHealthEndpoints:
    """Cover web/api/health.py routes."""

    def test_basic_health(self, authed_client):
        response = authed_client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in ("healthy", "degraded")

    def test_detailed_health(self, authed_client):
        response = authed_client.get("/api/health/detailed")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert "version" in data

    def test_sync_status(self, authed_client):
        response = authed_client.get("/api/health/sync-status")
        # sync-status may return 200 or 404 depending on backend (sqlite_vec has no sync)
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "status" in data or "syncing" in data or "enabled" in data

    def test_memory_stats(self, authed_client):
        response = authed_client.get("/api/memory-stats")
        assert response.status_code == 200
        data = response.json()
        assert "process_memory_mb" in data or "rss_mb" in data

    def test_clear_caches(self, authed_client):
        response = authed_client.post("/api/clear-caches")
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


# --- Configuration endpoint coverage ---

@pytest.mark.integration
class TestConfigurationEndpoints:
    """Cover web/api/configuration.py routes."""

    def test_get_env_config(self, authed_client):
        response = authed_client.get("/api/config/env")
        assert response.status_code == 200
        data = response.json()
        assert "categories" in data
        assert isinstance(data["categories"], list)

    def test_get_credentials(self, authed_client):
        response = authed_client.get("/api/config/credentials")
        # May return 200 or 404 if no credentials configured
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "api_token_partial" in data or "account_id" in data

    def test_test_credentials_no_data(self, authed_client):
        """Testing credentials without providing them should return a result."""
        response = authed_client.post(
            "/api/config/credentials/test",
            json={"api_token": "", "account_id": ""},
        )
        # Endpoint returns 200 with valid=False (graceful failure)
        assert response.status_code == 200
        data = response.json()
        assert "valid" in data
        assert data["valid"] is False


# --- Sync endpoint coverage ---

@pytest.mark.integration
class TestSyncEndpoints:
    """Cover web/api/sync.py routes."""

    def test_sync_status(self, authed_client):
        response = authed_client.get("/api/sync/status")
        # sqlite_vec backend has no sync — may return 200 with disabled or 404
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "enabled" in data or "syncing" in data or "status" in data

    def test_force_sync(self, authed_client):
        response = authed_client.post("/api/sync/force")
        # sqlite_vec has no force_sync → 404; 500 would indicate a bug
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "success" in data or "status" in data

    def test_pause_sync(self, authed_client):
        response = authed_client.post("/api/sync/pause")
        # sqlite_vec has no sync → 404; 500 would indicate a bug
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "success" in data or "paused" in data

    def test_resume_sync(self, authed_client):
        response = authed_client.post("/api/sync/resume")
        # sqlite_vec has no sync → 404; 500 would indicate a bug
        assert response.status_code in (200, 404)
        if response.status_code == 200:
            data = response.json()
            assert "success" in data or "resumed" in data


# --- Backup endpoint coverage ---

@pytest.mark.integration
class TestBackupEndpoints:
    """Cover web/api/backup.py routes."""

    def test_backup_status(self, authed_client):
        response = authed_client.get("/api/backup/status")
        assert response.status_code == 200
        data = response.json()
        assert "enabled" in data
        assert "scheduler_running" in data

    def test_backup_list(self, authed_client):
        response = authed_client.get("/api/backup/list")
        assert response.status_code == 200
        data = response.json()
        assert "backups" in data
        assert "total_count" in data

    def test_trigger_backup(self, authed_client):
        response = authed_client.post("/api/backup/now")
        # Backup endpoint always returns 200 (success=True or success=False)
        assert response.status_code == 200
        data = response.json()
        assert "success" in data


# --- Events endpoint coverage ---

@pytest.mark.integration
class TestEventsEndpoints:
    """Cover web/api/events.py routes."""

    def test_events_stats(self, authed_client):
        response = authed_client.get("/api/events/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_connections" in data
        assert "connections" in data


# --- Manage endpoint coverage ---

@pytest.mark.integration
class TestManageEndpoints:
    """Cover web/api/manage.py routes."""

    def test_tag_stats(self, authed_client):
        response = authed_client.get("/api/manage/tags/stats")
        assert response.status_code == 200
        data = response.json()
        assert "tags" in data
        assert "total_tags" in data

    def test_untagged_count(self, authed_client):
        response = authed_client.get("/api/manage/untagged/count")
        assert response.status_code == 200
        data = response.json()
        assert "count" in data

    def test_cleanup_duplicates(self, authed_client):
        response = authed_client.post("/api/manage/cleanup-duplicates")
        # 200 on success, 501 if backend doesn't support cleanup; 500 indicates a bug
        assert response.status_code in (200, 501)

    def test_bulk_delete_no_confirmation(self, authed_client):
        """Bulk delete without proper confirmation should be rejected."""
        response = authed_client.post(
            "/api/manage/bulk-delete",
            json={"tags": ["__test__"]},
        )
        # Should require confirmation count — 400 or 422, never 200
        assert response.status_code in (400, 422)

    def test_system_operation_invalid(self, authed_client):
        """Invalid system operation should be rejected."""
        response = authed_client.post(
            "/api/manage/system/invalid-operation",
            json={},
        )
        assert response.status_code in (400, 404, 422)


# --- Search endpoint coverage ---

@pytest.mark.integration
class TestSearchEndpoints:
    """Cover web/api/search.py routes."""

    def test_semantic_search(self, authed_client):
        response = authed_client.post(
            "/api/search",
            json={"query": "test", "n_results": 5},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_tag_search(self, authed_client):
        response = authed_client.post(
            "/api/search/by-tag",
            json={"tags": ["__test__"], "match_all": False},
        )
        assert response.status_code == 200
        data = response.json()
        assert "results" in data

    def test_time_search(self, authed_client):
        response = authed_client.post(
            "/api/search/by-time",
            json={"time_expression": "yesterday", "n_results": 5},
        )
        # "yesterday" may or may not be parseable depending on time parser availability
        assert response.status_code in (200, 422)
        if response.status_code == 200:
            data = response.json()
            assert "results" in data
            assert "total_found" in data


# --- Memories endpoint coverage ---

@pytest.mark.integration
class TestMemoriesEndpoints:
    """Cover web/api/memories.py CRUD routes."""

    def test_list_memories(self, authed_client):
        response = authed_client.get("/api/memories", params={"limit": 10})
        assert response.status_code == 200
        data = response.json()
        assert "memories" in data or "results" in data

    def test_list_tags(self, authed_client):
        response = authed_client.get("/api/tags")
        assert response.status_code == 200
        data = response.json()
        assert "tags" in data or isinstance(data, list)
