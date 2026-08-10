#!/usr/bin/env python3
"""
Tests for remote backup push (R2 + GitHub) in BackupService.
"""

import asyncio
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
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
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE IF NOT EXISTS memories (content_hash TEXT UNIQUE, content TEXT)")
    for i in range(count):
        conn.execute(
            "INSERT OR REPLACE INTO memories VALUES (?, ?)",
            (f"hash_{i:032d}", f"content_{i}"),
        )
    conn.commit()
    conn.close()


@pytest_asyncio.fixture
async def backup_service(tmp_path):
    """Create a BackupService with a test DB."""
    db_path = tmp_path / "test.db"
    create_test_db(db_path)
    service = BackupService(backups_dir=str(tmp_path / "backups"), db_path=str(db_path))
    yield service


class TestCheckIntegrity:
    """Tests for _check_integrity()."""

    @pytest.mark.asyncio
    async def test_integrity_ok(self, backup_service):
        """Healthy DB passes integrity check."""
        result = await backup_service._check_integrity()
        assert result is True

    @pytest.mark.asyncio
    async def test_integrity_missing_db(self, tmp_path):
        """Missing DB fails integrity check."""
        service = BackupService(
            backups_dir=str(tmp_path / "backups"),
            db_path=str(tmp_path / "nonexistent.db"),
        )
        result = await service._check_integrity()
        assert result is False


class TestPushToR2:
    """Tests for _push_to_r2()."""

    @pytest.mark.asyncio
    async def test_r2_disabled(self, backup_service, tmp_path):
        """R2 push is skipped when disabled."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test")
        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", False):
            result = await backup_service._push_to_r2(backup_file, {})
            assert result["success"] is True
            assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_r2_missing_token(self, backup_service, tmp_path):
        """R2 push fails gracefully when token is missing."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test")
        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", None):
            result = await backup_service._push_to_r2(backup_file, {})
            assert result["success"] is False
            assert "credentials" in result["error"].lower()

    @pytest.mark.asyncio
    async def test_r2_success(self, backup_service, tmp_path):
        """R2 push uploads file successfully."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        with patch("mcp_memory_service.backup.scheduler.BACKUP_R2_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_R2_BUCKET", "test-bucket"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_API_TOKEN", "test-token"), \
             patch("mcp_memory_service.backup.scheduler.CLOUDFLARE_ACCOUNT_ID", "test-account"):
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
                assert result["success"] is True
                assert "object_key" in result
                assert result["sha256"] == hashlib.sha256(b"test db content").hexdigest()


class TestPushToGitHub:
    """Tests for _push_to_github()."""

    @pytest.mark.asyncio
    async def test_github_disabled(self, backup_service, tmp_path):
        """GitHub push is skipped when disabled."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test")
        with patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_ENABLED", False):
            result = await backup_service._push_to_github(backup_file, {})
            assert result["success"] is True
            assert result["skipped"] is True

    @pytest.mark.asyncio
    async def test_github_missing_repo(self, backup_service, tmp_path):
        """GitHub push fails when repo is not configured."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test")
        with patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_REPO", ""):
            result = await backup_service._push_to_github(backup_file, {})
            assert result["success"] is False

    @pytest.mark.asyncio
    async def test_github_success(self, backup_service, tmp_path):
        """GitHub push commits manifest + checksum to repo (audit only, no DB file)."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / "data").mkdir()
        subprocess.run(["git", "init"], cwd=str(repo_dir), capture_output=True)
        subprocess.run(["git", "config", "user.email", "test@test.com"], cwd=str(repo_dir), capture_output=True)
        subprocess.run(["git", "config", "user.name", "Test"], cwd=str(repo_dir), capture_output=True)

        with patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_ENABLED", True), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_REPO", "user/repo"), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_BRANCH", "master"), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_TOKEN", "ghp_test"), \
             patch("mcp_memory_service.backup.scheduler.BACKUP_GITHUB_LOCAL_DIR", str(repo_dir)):
            original_run = subprocess.run

            def patched_run(args, **kwargs):
                if "push" in args:
                    result = MagicMock()
                    result.returncode = 0
                    result.stderr = ""
                    result.stdout = ""
                    return result
                return original_run(args, **kwargs)

            with patch("mcp_memory_service.backup.scheduler.subprocess.run", side_effect=patched_run):
                result = await backup_service._push_to_github(
                    backup_file, {"memory_count": 5, "file_sha256": "abc123def456", "timestamp": "2026-01-01"}
                )
                assert result["success"] is True
                # Manifest + checksum exist
                assert (repo_dir / "data" / "backup_manifest.json").exists()
                assert (repo_dir / "data" / "checksum.txt").exists()
                # DB file does NOT exist (audit only — v2 change)
                assert not (repo_dir / "data" / "sqlite_vec.db").exists()


class TestPushToRemote:
    """Tests for _push_to_remote() orchestration."""

    @pytest.mark.asyncio
    async def test_orchestrates_all_targets(self, backup_service, tmp_path):
        """_push_to_remote pushes to all enabled targets."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        with patch.object(backup_service, "_push_to_r2", return_value={"success": True, "target": "r2"}), \
             patch.object(backup_service, "_push_to_github", return_value={"success": True, "target": "github"}):
            result = await backup_service._push_to_remote(backup_file, {"memory_count": 5})
            assert result["r2"]["success"] is True
            assert result["github"]["success"] is True

    @pytest.mark.asyncio
    async def test_continues_on_partial_failure(self, backup_service, tmp_path):
        """If R2 fails, GitHub should still succeed."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        with patch.object(backup_service, "_push_to_r2", return_value={"success": False, "error": "network"}), \
             patch.object(backup_service, "_push_to_github", return_value={"success": True, "target": "github"}):
            result = await backup_service._push_to_remote(backup_file, {"memory_count": 5})
            assert result["r2"]["success"] is False
            assert result["github"]["success"] is True

    @pytest.mark.asyncio
    async def test_aborts_on_integrity_failure(self, backup_service, tmp_path):
        """Remote push is aborted when integrity check fails."""
        backup_file = tmp_path / "backup.db"
        backup_file.write_bytes(b"test db content")

        with patch.object(backup_service, "_check_integrity", return_value=False):
            result = await backup_service._push_to_remote(backup_file, {"memory_count": 5})
            assert result["r2"]["success"] is False
            assert "integrity_check_failed" in result["r2"]["error"]
            assert result["github"]["success"] is False
            assert "integrity_check_failed" in result["github"]["error"]


class TestCreateBackupWithRemote:
    """Tests that create_backup() includes remote push."""

    @pytest.mark.asyncio
    async def test_create_backup_includes_remote(self, backup_service, tmp_path):
        """create_backup() result includes remote push results."""
        with patch.object(backup_service, "_push_to_remote", return_value={
            "r2": {"success": True, "target": "r2"},
            "github": {"success": True, "target": "github"},
        }) as mock_remote:
            result = await backup_service.create_backup(description="test")
            assert result["success"] is True
            assert "remote" in result
            assert result["remote"]["r2"]["success"] is True
            assert result["remote"]["github"]["success"] is True
            mock_remote.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_backup_local_succeeds_even_if_remote_fails(self, backup_service):
        """Local backup succeeds even if all remote targets fail."""
        with patch.object(backup_service, "_push_to_remote", return_value={
            "r2": {"success": False, "error": "network"},
            "github": {"success": False, "error": "auth"},
        }):
            result = await backup_service.create_backup(description="test")
            assert result["success"] is True  # local backup still succeeds
            assert result["remote"]["r2"]["success"] is False
            assert result["remote"]["github"]["success"] is False
