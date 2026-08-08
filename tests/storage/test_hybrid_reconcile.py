#!/usr/bin/env python3
"""
Tests for bidirectional reconciliation in BackgroundSyncService.

Covers:
- Push local-only memories to cloud
- Pull cloud-only memories to local
- Tombstone respect (don't re-sync deleted)
- Never deletes data on either side
- Metadata drift (newer updated_at wins)
- Dry-run mode
- Idempotency (second run finds nothing)
"""

import asyncio
import os
import sys
import tempfile
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch
from typing import Dict, Any

import pytest
import pytest_asyncio

# Add src to path for imports
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.storage.hybrid import (
    HybridMemoryStorage,
    BackgroundSyncService,
    SyncOperation,
)
from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage
from mcp_memory_service.models.memory import Memory
from mcp_memory_service.utils.hashing import generate_content_hash

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class ReconcileMockCloudflareStorage:
    """Mock Cloudflare storage with bulk hash fetch support for reconcile tests."""

    def __init__(self, **kwargs):
        self.initialized = False
        self.stored_memories: Dict[str, Memory] = {}
        self.fail_operations = False
        self.base_url = "https://mock"
        self.d1_database_id = "mock-db"
        self.store_call_count = 0
        self.delete_call_count = 0
        self.update_call_count = 0

    async def initialize(self):
        self.initialized = True

    async def store(self, memory: Memory):
        self.store_call_count += 1
        if self.fail_operations:
            return False, "Mock operation failed"
        self.stored_memories[memory.content_hash] = memory
        return True, "Stored"

    async def delete(self, content_hash: str):
        self.delete_call_count += 1
        if self.fail_operations:
            return False, "Mock operation failed"
        if content_hash in self.stored_memories:
            del self.stored_memories[content_hash]
            return True, "Deleted"
        return False, "Not found"

    async def update_memory_metadata(
        self, content_hash, updates, preserve_timestamps=True
    ):
        self.update_call_count += 1
        if content_hash in self.stored_memories:
            mem = self.stored_memories[content_hash]
            if "tags" in updates:
                mem.tags = updates["tags"]
            if "memory_type" in updates:
                mem.memory_type = updates["memory_type"]
            return True, "Updated"
        return False, "Not found"

    async def get_stats(self):
        return {
            "total_memories": len(self.stored_memories),
            "storage_backend": "MockCloudflare",
            "vector_count": len(self.stored_memories),
            "total_vectors": len(self.stored_memories),
        }

    async def get_by_hash(self, content_hash: str):
        return self.stored_memories.get(content_hash)

    async def get_all_memories_cursor(self, limit=500, cursor=None):
        """Return all stored memories (ignoring cursor for simplicity)."""
        return list(self.stored_memories.values())

    async def get_all_memories(self, limit=None, offset=0):
        return list(self.stored_memories.values())

    async def _retry_request(self, method, url, **kwargs):
        """Mock D1 bulk hash fetch for _fetch_secondary_hashes()."""
        params = kwargs.get("json", {}).get("params", [])
        last_id = params[0] if params else 0

        all_hashes = list(self.stored_memories.keys())
        # Return hashes with id > last_id
        result = []
        for i, h in enumerate(all_hashes, start=1):
            if i > last_id:
                result.append({"id": i, "content_hash": h})

        limit_val = params[1] if len(params) > 1 else 1000
        result = result[:limit_val]

        resp = Mock()
        resp.json = Mock(
            return_value={
                "success": True,
                "result": [{"results": result}],
            }
        )
        return resp

    async def close(self):
        pass


def make_memory(content: str, tags=None, memory_type="test", updated_at=None):
    """Helper to create a Memory with content hash."""
    return Memory(
        content=content,
        content_hash=generate_content_hash(content),
        tags=tags or ["test"],
        memory_type=memory_type,
        metadata={},
        created_at=1638360000.0,
        updated_at=updated_at or 1638360000.0,
    )


@pytest_asyncio.fixture
async def temp_sqlite_db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name
    yield db_path
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest_asyncio.fixture
async def reconcile_setup(temp_sqlite_db):
    """Create primary + secondary + sync_service for reconcile tests."""
    primary = SqliteVecMemoryStorage(temp_sqlite_db)
    await primary.initialize()

    secondary = ReconcileMockCloudflareStorage()
    await secondary.initialize()

    sync_service = BackgroundSyncService(
        primary, secondary, sync_interval=1, batch_size=10
    )
    # Don't start the sync loop — we call methods directly
    sync_service.is_running = True
    # Ensure drift check is enabled (conftest may override config)
    sync_service.drift_check_enabled = True

    yield primary, secondary, sync_service

    await sync_service.stop()
    if hasattr(primary, "close"):
        await primary.close()


class TestBidirectionalReconcile:
    """Tests for _bidirectional_reconcile()."""

    @pytest.mark.asyncio
    async def test_pushes_local_only_to_cloud(self, reconcile_setup):
        """Memories only in local should be pushed to cloud."""
        primary, secondary, sync_service = reconcile_setup

        # Store 3 memories locally
        m1 = make_memory("local only 1")
        m2 = make_memory("local only 2")
        m3 = make_memory("shared memory")
        await primary.store(m1)
        await primary.store(m2)
        await primary.store(m3)

        # Store only m3 on cloud
        await secondary.store(m3)

        result = await sync_service._bidirectional_reconcile()

        assert result["pushed_to_cloud"] == 2
        assert result["pulled_to_local"] == 0
        assert m1.content_hash in secondary.stored_memories
        assert m2.content_hash in secondary.stored_memories

    @pytest.mark.asyncio
    async def test_pulls_cloud_only_to_local(self, reconcile_setup):
        """Memories only in cloud should be pulled to local."""
        primary, secondary, sync_service = reconcile_setup

        # Store 2 memories on cloud
        cf1 = make_memory("cloud only 1")
        cf2 = make_memory("cloud only 2")
        await secondary.store(cf1)
        await secondary.store(cf2)

        # Store 1 shared memory locally
        shared = make_memory("shared memory")
        await primary.store(shared)
        await secondary.store(shared)

        result = await sync_service._bidirectional_reconcile()

        assert result["pulled_to_local"] == 2
        assert result["pushed_to_cloud"] == 0

        # Verify memories exist locally now
        local_hash = await primary.get_all_content_hashes()
        assert cf1.content_hash in local_hash
        assert cf2.content_hash in local_hash

    @pytest.mark.asyncio
    async def test_never_deletes_data(self, reconcile_setup):
        """Reconcile should never call delete on either side."""
        primary, secondary, sync_service = reconcile_setup

        m1 = make_memory("local only")
        m2 = make_memory("cloud only")
        await primary.store(m1)
        await secondary.store(m2)

        initial_local = len(await primary.get_all_content_hashes())
        initial_cloud = len(secondary.stored_memories)

        await sync_service._bidirectional_reconcile()

        # Neither side should have lost data
        final_local = len(await primary.get_all_content_hashes())
        final_cloud = len(secondary.stored_memories)
        assert final_local >= initial_local
        assert final_cloud >= initial_cloud
        assert secondary.delete_call_count == 0

        # Verify specific memories survive (count-only check can miss delete+add)
        local_hashes = await primary.get_all_content_hashes()
        assert m1.content_hash in local_hashes
        assert m2.content_hash in local_hashes  # pulled from cloud
        assert m1.content_hash in secondary.stored_memories  # pushed to cloud
        assert m2.content_hash in secondary.stored_memories

    @pytest.mark.asyncio
    async def test_respects_tombstones(self, reconcile_setup):
        """Locally deleted memories should not be re-synced from cloud."""
        primary, secondary, sync_service = reconcile_setup

        # Create a memory that exists on cloud
        m = make_memory("will be deleted locally")
        await secondary.store(m)

        # Store then delete locally
        await primary.store(m)
        await primary.delete(m.content_hash)

        result = await sync_service._bidirectional_reconcile()

        # Should skip due to tombstone
        assert result["skipped_tombstone"] >= 1
        assert result["pulled_to_local"] == 0

    @pytest.mark.asyncio
    async def test_dry_run_makes_no_changes(self, reconcile_setup):
        """Dry run should detect differences but not apply changes."""
        primary, secondary, sync_service = reconcile_setup

        m1 = make_memory("local only")
        m2 = make_memory("cloud only")
        await primary.store(m1)
        await secondary.store(m2)

        result = await sync_service._bidirectional_reconcile(dry_run=True)

        assert result["pushed_to_cloud"] == 1
        assert result["pulled_to_local"] == 1
        assert result["dry_run"] if "dry_run" in result else True

        # Verify nothing was actually changed
        assert m1.content_hash not in secondary.stored_memories
        local_hashes = await primary.get_all_content_hashes()
        assert m2.content_hash not in local_hashes

    @pytest.mark.asyncio
    async def test_idempotent_second_run(self, reconcile_setup):
        """Running reconcile twice should find 0 missing on second run."""
        primary, secondary, sync_service = reconcile_setup

        m1 = make_memory("local only")
        m2 = make_memory("cloud only")
        shared = make_memory("shared")
        await primary.store(m1)
        await primary.store(shared)
        await secondary.store(m2)
        await secondary.store(shared)

        # First run should sync both
        result1 = await sync_service._bidirectional_reconcile()
        assert result1["pushed_to_cloud"] == 1
        assert result1["pulled_to_local"] == 1

        # Second run should find nothing to sync
        result2 = await sync_service._bidirectional_reconcile()
        assert result2["pushed_to_cloud"] == 0
        assert result2["pulled_to_local"] == 0

    @pytest.mark.asyncio
    async def test_metadata_drift_cloud_newer(self, reconcile_setup):
        """When cloud has newer updated_at, local should be updated."""
        primary, secondary, sync_service = reconcile_setup

        # Same content hash, different updated_at
        content = "same content"
        local_mem = make_memory(content, tags=["old"], updated_at=1000.0)
        cloud_mem = make_memory(content, tags=["new"], updated_at=2000.0)
        await primary.store(local_mem)
        await secondary.store(cloud_mem)

        result = await sync_service._bidirectional_reconcile()

        # Should detect drift and sync cloud → local
        assert result["drift_synced"] >= 1

        # Verify local was updated
        local_check = await primary.get_by_hash(local_mem.content_hash)
        assert local_check is not None
        assert local_check.tags == ["new"]

    @pytest.mark.asyncio
    async def test_metadata_drift_local_newer(self, reconcile_setup):
        """When local has newer updated_at, cloud should be updated."""
        primary, secondary, sync_service = reconcile_setup

        content = "same content"
        local_mem = make_memory(content, tags=["newer"], updated_at=2000.0)
        cloud_mem = make_memory(content, tags=["older"], updated_at=1000.0)
        await primary.store(local_mem)
        await secondary.store(cloud_mem)

        result = await sync_service._bidirectional_reconcile()

        assert result["drift_synced"] >= 1
        # Verify the update operation was enqueued with preserve_timestamps=False
        assert sync_service.operation_queue.qsize() > 0
        op = sync_service.operation_queue.get_nowait()
        assert op.operation == "update"
        assert op.content_hash == local_mem.content_hash
        assert op.preserve_timestamps is False
        assert "updated_at" in op.updates

    @pytest.mark.asyncio
    async def test_empty_backends(self, reconcile_setup):
        """Reconcile with empty backends should return zeros."""
        primary, secondary, sync_service = reconcile_setup

        result = await sync_service._bidirectional_reconcile()

        assert result["checked"] == 0
        assert result["pushed_to_cloud"] == 0
        assert result["pulled_to_local"] == 0
        assert result["drift_synced"] == 0
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_returns_stats_dict(self, reconcile_setup):
        """Result should contain all expected keys."""
        primary, secondary, sync_service = reconcile_setup

        result = await sync_service._bidirectional_reconcile()

        expected_keys = {
            "checked",
            "pushed_to_cloud",
            "pulled_to_local",
            "drift_synced",
            "skipped_tombstone",
            "failed",
        }
        assert expected_keys.issubset(result.keys())

    @pytest.mark.asyncio
    async def test_secondary_hashes_none_returns_early(self, temp_sqlite_db):
        """When _fetch_secondary_hashes returns None, reconcile should abort gracefully."""
        primary = SqliteVecMemoryStorage(temp_sqlite_db)
        await primary.initialize()

        # Secondary without _retry_request — _fetch_secondary_hashes returns None
        class NoBulkHashCloudflare(ReconcileMockCloudflareStorage):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                # Remove _retry_request so _fetch_secondary_hashes returns None
                delattr = None  # can't actually delete method, but can override

            async def _retry_request(self, *args, **kwargs):
                raise AttributeError("Not supported")

        secondary = NoBulkHashCloudflare()
        await secondary.initialize()

        sync_service = BackgroundSyncService(
            primary, secondary, sync_interval=1, batch_size=10
        )
        sync_service.is_running = True
        sync_service.drift_check_enabled = True

        # Store a memory so there's data
        m = make_memory("test memory")
        await primary.store(m)

        result = await sync_service._bidirectional_reconcile()

        assert "error" in result
        assert result["checked"] == 0
        assert result["pushed_to_cloud"] == 0
        assert result["pulled_to_local"] == 0

        await sync_service.stop()
        if hasattr(primary, "close"):
            await primary.close()

    @pytest.mark.asyncio
    async def test_aborts_when_local_hashes_empty_but_primary_has_memories(
        self, reconcile_setup
    ):
        """If get_all_content_hashes returns empty but primary has memories, abort for safety."""
        primary, secondary, sync_service = reconcile_setup

        # Store memories on both sides
        m1 = make_memory("local memory")
        m2 = make_memory("cloud memory")
        await primary.store(m1)
        await secondary.store(m2)

        # Mock get_all_content_hashes to return empty set (simulating failure)
        original_method = primary.get_all_content_hashes
        primary.get_all_content_hashes = AsyncMock(return_value=set())

        result = await sync_service._bidirectional_reconcile()

        # Should abort, NOT pull all cloud memories
        assert "error" in result
        assert result["pulled_to_local"] == 0
        assert "aborted for safety" in result["error"]

        # Restore original method
        primary.get_all_content_hashes = original_method

    @pytest.mark.asyncio
    async def test_partial_batch_failure(self, reconcile_setup):
        """If secondary.store fails for some memories, others should still succeed."""
        primary, secondary, sync_service = reconcile_setup

        # Store 3 local-only memories
        m1 = make_memory("local 1")
        m2 = make_memory("local 2")
        m3 = make_memory("local 3")
        await primary.store(m1)
        await primary.store(m2)
        await primary.store(m3)

        # Make store fail for m2 only
        original_store = secondary.store
        fail_hash = m2.content_hash

        async def failing_store(memory):
            if memory.content_hash == fail_hash:
                return False, "Simulated failure"
            return await original_store(memory)

        secondary.store = failing_store

        result = await sync_service._bidirectional_reconcile()

        # m1 and m3 should be pushed, m2 should fail
        assert result["pushed_to_cloud"] == 2
        assert result["failed"] >= 1
        assert m1.content_hash in secondary.stored_memories
        assert m3.content_hash in secondary.stored_memories
        assert m2.content_hash not in secondary.stored_memories


class TestReconcileIntegration:
    """Integration tests via HybridMemoryStorage.force_reconcile()."""

    @pytest.mark.asyncio
    async def test_force_reconcile_via_storage(self, temp_sqlite_db):
        """force_reconcile() should work through HybridMemoryStorage."""
        mock_cf_config = {
            "api_token": "test",
            "account_id": "test",
            "vectorize_index": "test",
            "d1_database_id": "test",
        }

        with patch(
            "mcp_memory_service.storage.hybrid.CloudflareStorage",
            ReconcileMockCloudflareStorage,
        ):
            storage = HybridMemoryStorage(
                sqlite_db_path=temp_sqlite_db,
                cloudflare_config=mock_cf_config,
                sync_interval=1,
                batch_size=5,
            )
            await storage.initialize()

            # Store a local-only memory
            m = make_memory("local only for integration")
            await storage.store(m)

            result = await storage.force_reconcile()

            assert "checked" in result
            assert result["pushed_to_cloud"] >= 1
            assert "duration" in result

            await storage.close()
