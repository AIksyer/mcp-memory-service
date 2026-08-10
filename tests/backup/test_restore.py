#!/usr/bin/env python3
"""
Tests for R2 staging restore in BackupService.

Safety properties verified:
- No auto-reconcile after restore (Blue Team C-2 mitigation)
- Schema_version compatibility check (Blue Team M-4 mitigation)
- Current DB backed up before replacing
- Integrity check rejects corrupted downloads
"""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.backup.scheduler import BackupService


def create_test_db_with_schema(db_path: Path, schema_version: int = 13, count: int = 5):
    """Create a test SQLite DB with memories + metadata(schema_version)."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS memories (content_hash TEXT UNIQUE, content TEXT)"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS metadata (key TEXT UNIQUE, value TEXT)")
    conn.execute(
        "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
        (str(schema_version),),
    )
    for i in range(count):
        conn.execute(
            "INSERT OR REPLACE INTO memories VALUES (?, ?)",
            (f"hash_{i:032d}", f"content_{i}"),
        )
    conn.commit()
    conn.close()


def read_db_bytes(db_path: Path) -> bytes:
    """Read a SQLite DB file as bytes."""
    return db_path.read_bytes()


def count_memories(db_path: Path) -> int:
    """Count rows in memories table."""
    conn = sqlite3.connect(str(db_path))
    count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()
    return count


@pytest_asyncio.fixture
async def backup_service(tmp_path):
    """Create a BackupService with a test DB (schema_version=13, 5 memories)."""
    db_path = tmp_path / "test.db"
    create_test_db_with_schema(db_path, schema_version=13, count=5)
    service = BackupService(
        backups_dir=str(tmp_path / "backups"), db_path=str(db_path)
    )
    yield service


@pytest_asyncio.fixture
async def backup_db(tmp_path):
    """Create a separate backup DB (schema_version=13, 10 memories)."""
    backup_path = tmp_path / "backup_source.db"
    create_test_db_with_schema(backup_path, schema_version=13, count=10)
    return backup_path


class TestRestoreFromR2:
    """Tests for restore_from_r2()."""

    @pytest.mark.asyncio
    async def test_restore_downloads_and_validates(
        self, backup_service, backup_db, tmp_path
    ):
        """Restore downloads from R2, validates, and replaces the primary DB."""
        backup_bytes = read_db_bytes(backup_db)

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_download_object", return_value=backup_bytes):
            result = await backup_service.restore_from_r2("backups/test.db")

        assert result["success"] is True
        assert result["object_key"] == "backups/test.db"
        # Primary DB now has the backup's 10 memories (was 5)
        assert count_memories(backup_service.db_path) == 10
        # Staging file cleaned up
        staging_files = list(backup_service.backups_dir.glob("r2_staging_*.db"))
        assert staging_files == []

    @pytest.mark.asyncio
    async def test_restore_rejects_corrupted_db(self, backup_service):
        """Restore fails when downloaded data is not a valid SQLite DB."""
        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_download_object", return_value=b"garbage not a db"):
            result = await backup_service.restore_from_r2("backups/corrupt.db")

        assert result["success"] is False
        assert "integrity" in result["error"].lower()
        # Primary DB unchanged
        assert count_memories(backup_service.db_path) == 5

    @pytest.mark.asyncio
    async def test_restore_rejects_schema_mismatch(
        self, backup_service, tmp_path
    ):
        """Restore fails when backup has an older schema_version."""
        old_backup = tmp_path / "old_backup.db"
        create_test_db_with_schema(old_backup, schema_version=5, count=3)
        backup_bytes = read_db_bytes(old_backup)

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_download_object", return_value=backup_bytes):
            result = await backup_service.restore_from_r2("backups/old.db")

        assert result["success"] is False
        assert "schema" in result["error"].lower()
        # Primary DB unchanged
        assert count_memories(backup_service.db_path) == 5

    @pytest.mark.asyncio
    async def test_restore_backs_up_current_db(
        self, backup_service, backup_db
    ):
        """Restore creates a .pre_r2_restore backup of the current DB."""
        backup_bytes = read_db_bytes(backup_db)

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_download_object", return_value=backup_bytes):
            result = await backup_service.restore_from_r2("backups/test.db")

        assert result["success"] is True
        pre_restore = backup_service.db_path.with_suffix(".db.pre_r2_restore")
        assert pre_restore.exists()
        # Pre-restore backup has the original 5 memories
        assert count_memories(pre_restore) == 5

    @pytest.mark.asyncio
    async def test_restore_does_not_touch_d1(
        self, backup_service, backup_db
    ):
        """Restore result contains explicit warning about NOT reconciling."""
        backup_bytes = read_db_bytes(backup_db)

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_download_object", return_value=backup_bytes):
            result = await backup_service.restore_from_r2("backups/test.db")

        assert result["success"] is True
        assert "warning" in result
        assert "reconcile" in result["warning"].lower()
        # Verify no sync/reconcile methods exist on BackupService
        assert not hasattr(backup_service, "reconcile")
        assert not hasattr(backup_service, "_sync_to_cloudflare")


class TestR2CleanupUnderPressure:
    """Tests for _r2_cleanup_under_pressure()."""

    @pytest.mark.asyncio
    async def test_cleanup_triggered_when_over_threshold(self, backup_service):
        """Cleanup deletes oldest backups first when over threshold."""
        # 9 GB usage > 8 GB threshold
        nine_gb = 9 * 1024 * 1024 * 1024

        objects = [
            {
                "key": "backups/old_20260101.db",
                "last_modified": "2026-01-01T00:00:00Z",
                "size": 5 * 1024 * 1024,  # 5MB
            },
            {
                "key": "backups/new_20260810.db",
                "last_modified": "2026-08-10T00:00:00Z",
                "size": 5 * 1024 * 1024,  # 5MB
            },
        ]

        deleted_keys = []
        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(
                 backup_service, "_r2_get_usage_bytes", return_value=nine_gb
            ), \
             patch.object(
                 backup_service, "_r2_list_objects", return_value=objects
            ), \
             patch.object(
                 backup_service,
                 "_r2_delete_object",
                 side_effect=lambda key: deleted_keys.append(key) or True,
            ):
            result = await backup_service._r2_cleanup_under_pressure()

        assert result["action"] == "cleanup_performed"
        assert result["deleted_count"] >= 1
        # Oldest backup deleted first
        assert "backups/old_20260101.db" in deleted_keys

    @pytest.mark.asyncio
    async def test_no_cleanup_when_under_threshold(self, backup_service):
        """No cleanup when usage is well under threshold."""
        # 100 MB usage << 8 GB threshold
        hundred_mb = 100 * 1024 * 1024

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(
                 backup_service, "_r2_get_usage_bytes", return_value=hundred_mb
            ), \
             patch.object(
                 backup_service, "_r2_list_objects", return_value=[]
            ) as mock_list:
            result = await backup_service._r2_cleanup_under_pressure()

        assert result["action"] == "no_cleanup_needed"
        # _r2_list_objects should not even be called (early return)
        mock_list.assert_not_called()
