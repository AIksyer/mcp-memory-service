"""Tests for R2 backup quarantine — pending/ → backups/ promotion (v4 Task 7)."""

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.backup.scheduler import BackupService


def create_test_db(db_path: Path, count: int = 5):
    """Create a test SQLite DB with memories table."""
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS memories (content_hash TEXT UNIQUE, content TEXT)")
    for i in range(count):
        conn.execute("INSERT OR REPLACE INTO memories VALUES (?, ?)", (f"hash_{i:032d}", f"content_{i}"))
    conn.commit()
    conn.close()


@pytest_asyncio.fixture
async def backup_service(tmp_path):
    """Create a BackupService with a test DB."""
    db_path = tmp_path / "test.db"
    create_test_db(db_path)
    service = BackupService(backups_dir=str(tmp_path / "backups"), db_path=str(db_path))
    yield service


class TestQuarantine:
    """Tests for backup quarantine (pending/ → backups/)."""

    @pytest.mark.asyncio
    async def test_new_backup_goes_to_pending(self, backup_service, tmp_path):
        """_push_to_r2 uploads to pending/ prefix."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        captured_key = None
        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_R2_BUCKET", "test-bucket"), \
             patch.object(backup_service, "_r2_cleanup_under_pressure", return_value={"action": "no_cleanup_needed"}), \
             patch.object(backup_service, "_r2_promote_pending", return_value={"promoted": 0}):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"success": True}
                mock_response.raise_for_status = MagicMock()
                mock_client.put.return_value = mock_response
                mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

                result = await backup_service._push_to_r2(backup_file, {})

                # Verify the object_key starts with pending/
                assert result["success"] is True
                assert result["object_key"].startswith("pending/")

    @pytest.mark.asyncio
    async def test_pending_older_than_threshold_promoted(self, backup_service):
        """Pending backup older than quarantine hours → promoted to backups/."""
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        pending_objects = [
            {"key": "pending/sqlite_vec_old.db", "last_modified": old_time, "size": 100},
        ]

        backup_data = b"backup content"
        upload_keys = []

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_R2_BUCKET", "test-bucket"), \
             patch.object(backup_service, "_r2_list_objects", return_value=pending_objects), \
             patch.object(backup_service, "_r2_download_object", return_value=backup_data), \
             patch.object(backup_service, "_r2_delete_object", return_value=True):
            with patch("httpx.AsyncClient") as mock_client_class:
                mock_client = AsyncMock()
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {"success": True}
                mock_response.raise_for_status = MagicMock()
                mock_client.put.return_value = mock_response
                mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

                # Capture the upload URL to verify it goes to backups/
                async def capture_put(url, **kwargs):
                    upload_keys.append(url)
                    return mock_response
                mock_client.put.side_effect = capture_put

                result = await backup_service._r2_promote_pending()

                assert result["promoted"] == 1
                # Verify upload went to backups/ prefix
                assert any("backups/sqlite_vec_old.db" in url for url in upload_keys)

    @pytest.mark.asyncio
    async def test_pending_younger_than_threshold_not_promoted(self, backup_service):
        """Pending backup younger than quarantine hours → NOT promoted."""
        recent_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        pending_objects = [
            {"key": "pending/sqlite_vec_recent.db", "last_modified": recent_time, "size": 100},
        ]

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"), \
             patch.object(backup_service, "_r2_list_objects", return_value=pending_objects), \
             patch.object(backup_service, "_r2_download_object", return_value=b"data") as mock_download:
            result = await backup_service._r2_promote_pending()

            assert result["promoted"] == 0
            # Download should NOT have been called (backup still in quarantine)
            mock_download.assert_not_called()
