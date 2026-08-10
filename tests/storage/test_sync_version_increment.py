# Copyright 2024 Heinrich Krupp
# Modifications Copyright 2026 AIksyer
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
"""Tests for sync_version increment in store() and update_memory_metadata() (v4)."""

import sqlite3
import sys
import time
from pathlib import Path
from unittest.mock import patch

import pytest
import pytest_asyncio

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.models.memory import Memory
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage


@pytest_asyncio.fixture
async def storage(tmp_path):
    """Create a SqliteVecMemoryStorage with a test DB."""
    db_path = tmp_path / "test.db"
    s = SqliteVecMemoryStorage(db_path=str(db_path))
    await s.initialize()
    yield s
    if s.conn:
        s.conn.close()


class TestStoreSetsSyncVersion:
    """Tests that store() sets sync_version and device_id."""

    @pytest.mark.asyncio
    async def test_store_sets_sync_version_1(self, storage):
        """store() sets sync_version=1 for new memories."""
        mem = Memory(content="test content", content_hash="abc123")
        success, msg = await storage.store(mem)
        assert success

        retrieved = await storage.get_by_hash("abc123")
        assert retrieved is not None
        assert retrieved.sync_version == 1

    @pytest.mark.asyncio
    async def test_store_sets_device_id(self, storage):
        """store() sets device_id from memory object."""
        mem = Memory(content="test content", content_hash="def456", device_id="device-001")
        success, msg = await storage.store(mem)
        assert success

        retrieved = await storage.get_by_hash("def456")
        assert retrieved is not None
        assert retrieved.device_id == "device-001"


class TestUpdateIncrementsSyncVersion:
    """Tests that update_memory_metadata() increments sync_version."""

    @pytest.mark.asyncio
    async def test_update_increments_sync_version(self, storage):
        """update_memory_metadata() increments sync_version from 1 to 2."""
        mem = Memory(content="test content", content_hash="ghi789")
        await storage.store(mem)

        # Verify initial sync_version
        retrieved = await storage.get_by_hash("ghi789")
        assert retrieved.sync_version == 1

        # Update
        success, msg = await storage.update_memory_metadata(
            "ghi789", {"tags": ["updated"]}
        )
        assert success

        # Verify incremented
        retrieved = await storage.get_by_hash("ghi789")
        assert retrieved.sync_version == 2

    @pytest.mark.asyncio
    async def test_multiple_updates_increment_correctly(self, storage):
        """Multiple updates increment sync_version 1→2→3."""
        mem = Memory(content="test content", content_hash="jkl012")
        await storage.store(mem)

        await storage.update_memory_metadata("jkl012", {"tags": ["v1"]})
        retrieved = await storage.get_by_hash("jkl012")
        assert retrieved.sync_version == 2

        await storage.update_memory_metadata("jkl012", {"tags": ["v2"]})
        retrieved = await storage.get_by_hash("jkl012")
        assert retrieved.sync_version == 3

    @pytest.mark.asyncio
    async def test_get_by_hash_returns_sync_version_and_device_id(self, storage):
        """get_by_hash() returns sync_version and device_id."""
        mem = Memory(
            content="test content",
            content_hash="mno345",
            device_id="device-002",
        )
        await storage.store(mem)

        retrieved = await storage.get_by_hash("mno345")
        assert retrieved is not None
        assert retrieved.sync_version == 1
        assert retrieved.device_id == "device-002"
