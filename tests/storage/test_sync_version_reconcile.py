"""Tests for sync_version-based reconcile and conflict detection (v4 Tasks 5+6)."""

import asyncio
import sys
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.models.memory import Memory


class TestReconcileUsesSyncVersion:
    """Tests that _reconcile_drift_in_both uses sync_version (Task 5)."""

    @pytest.mark.asyncio
    async def test_cloud_higher_sync_version_updates_local(self):
        """Cloud has higher sync_version → local updated."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        # Cloud memory: sync_version=3, updated_at older
        cf_memory = Memory(content="test", content_hash="abc", sync_version=3, updated_at=1000.0)
        # Local memory: sync_version=1, updated_at newer
        local_memory = Memory(content="test", content_hash="abc", sync_version=1, updated_at=2000.0)

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        primary.update_memory_metadata = AsyncMock(return_value=(True, "ok"))

        stats = {"failed": 0}
        result = await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # Cloud wins despite older updated_at (sync_version=3 > 1)
        primary.update_memory_metadata.assert_called_once()
        assert result == 1
        assert stats["failed"] == 0

    @pytest.mark.asyncio
    async def test_local_higher_sync_version_queues_cloud_update(self):
        """Local has higher sync_version → cloud update queued."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService, SyncOperation

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        # Cloud: sync_version=1
        cf_memory = Memory(content="test", content_hash="abc", sync_version=1, updated_at=2000.0)
        # Local: sync_version=5
        local_memory = Memory(content="test", content_hash="abc", sync_version=5, updated_at=1000.0)

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        service.enqueue_operation = AsyncMock()

        stats = {"failed": 0}
        result = await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # Local wins, should queue update to cloud
        service.enqueue_operation.assert_called_once()
        assert result == 1

    @pytest.mark.asyncio
    async def test_equal_sync_version_falls_back_to_updated_at(self):
        """Equal sync_version, different updated_at → falls back to updated_at."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        # Both sync_version=2, cloud has newer updated_at
        cf_memory = Memory(content="test", content_hash="abc", sync_version=2, updated_at=2000.0)
        local_memory = Memory(content="test", content_hash="abc", sync_version=2, updated_at=1000.0)

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        primary.update_memory_metadata = AsyncMock(return_value=(True, "ok"))

        stats = {"failed": 0}
        result = await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # Cloud wins via updated_at fallback
        primary.update_memory_metadata.assert_called_once()
        assert result == 1

    @pytest.mark.asyncio
    async def test_equal_sync_version_equal_updated_at_skipped(self):
        """Equal sync_version, equal updated_at → skipped (no drift)."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        cf_memory = Memory(content="test", content_hash="abc", sync_version=2, updated_at=1000.0)
        local_memory = Memory(content="test", content_hash="abc", sync_version=2, updated_at=1000.0)

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        primary.update_memory_metadata = AsyncMock(return_value=(True, "ok"))
        service.enqueue_operation = AsyncMock()

        stats = {"failed": 0}
        result = await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # No drift — neither side updated
        primary.update_memory_metadata.assert_not_called()
        service.enqueue_operation.assert_not_called()
        assert result == 0


class TestConflictDetection:
    """Tests for conflict detection → backup_conflicts table (Task 6)."""

    @pytest.mark.asyncio
    async def test_version_divergence_logs_conflict(self):
        """When sync_version diverges (both > 0), conflict row inserted."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        # Mock primary with a conn that records SQL and returns None for SELECTs
        executed_sql = []

        def mock_execute(sql, params=None):
            executed_sql.append((sql, params))
            mock_result = MagicMock()
            # Return None for fetchone() so dedup SELECT doesn't find existing conflict
            mock_result.fetchone.return_value = None
            return mock_result

        mock_conn = MagicMock()
        mock_conn.execute = MagicMock(side_effect=mock_execute)
        mock_conn.commit = MagicMock()
        primary.conn = mock_conn

        cf_memory = Memory(
            content="test", content_hash="abc", sync_version=5,
            updated_at=2000.0, device_id="cloud-device"
        )
        local_memory = Memory(
            content="test", content_hash="abc", sync_version=2,
            updated_at=1000.0, device_id="local-device"
        )

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        primary.update_memory_metadata = AsyncMock(return_value=(True, "ok"))

        stats = {"failed": 0}
        await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # Verify conflict was logged
        conflict_inserts = [s for s, p in executed_sql if "backup_conflicts" in s and "INSERT" in s.upper()]
        assert len(conflict_inserts) >= 1

    @pytest.mark.asyncio
    async def test_no_conflict_when_one_side_sync_version_zero(self):
        """No conflict logged when one side has sync_version=0 (pre-v4)."""
        from mcp_memory_service.storage.hybrid import BackgroundSyncService

        primary = MagicMock()
        secondary = MagicMock()
        service = BackgroundSyncService(primary, secondary)

        executed_sql = []
        mock_conn = MagicMock()
        mock_conn.execute = MagicMock(side_effect=lambda sql, params=None: executed_sql.append(sql) or MagicMock())
        mock_conn.commit = MagicMock()
        primary.conn = mock_conn

        # Cloud: sync_version=0 (pre-v4), Local: sync_version=2
        cf_memory = Memory(content="test", content_hash="abc", sync_version=0, updated_at=2000.0)
        local_memory = Memory(content="test", content_hash="abc", sync_version=2, updated_at=1000.0)

        primary.get_by_hash = AsyncMock(return_value=local_memory)
        secondary.get_by_hash = AsyncMock(return_value=cf_memory)
        service.enqueue_operation = AsyncMock()

        stats = {"failed": 0}
        await service._reconcile_drift_in_both({"abc"}, dry_run=False, stats=stats)

        # No conflict logged (one side has sync_version=0)
        conflict_inserts = [s for s in executed_sql if "backup_conflicts" in s]
        assert len(conflict_inserts) == 0
