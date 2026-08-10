"""Tests for backup conflict API endpoints (v4 Task 8)."""

import sqlite3
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))


def create_test_db_with_conflicts(db_path: Path, conflicts: list[dict]):
    """Create a test DB with backup_conflicts table and insert rows."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS backup_conflicts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "content_hash TEXT NOT NULL, "
        "local_version INTEGER, remote_version INTEGER, "
        "local_device_id TEXT, remote_device_id TEXT, "
        "conflict_type TEXT NOT NULL, "
        "local_updated_at REAL, remote_updated_at REAL, "
        "detected_at TEXT NOT NULL, "
        "resolved_at TEXT, resolution TEXT, metadata TEXT DEFAULT '{}')"
    )
    for c in conflicts:
        conn.execute(
            "INSERT INTO backup_conflicts "
            "(content_hash, local_version, remote_version, conflict_type, detected_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (c["content_hash"], c.get("local_version"), c.get("remote_version"),
             c["conflict_type"], c["detected_at"]),
        )
    conn.commit()
    conn.close()


class TestConflictEndpoints:
    """Tests for GET /backup/conflicts and POST /backup/conflicts/resolve."""

    def test_get_conflicts_returns_unresolved(self, tmp_path):
        """GET /backup/conflicts returns unresolved conflicts."""
        from fastapi.testclient import TestClient
        from mcp_memory_service.web.api.backup import router
        from fastapi import FastAPI

        db_path = tmp_path / "test.db"
        create_test_db_with_conflicts(db_path, [
            {"content_hash": "abc", "local_version": 1, "remote_version": 3,
             "conflict_type": "version_divergence", "detected_at": "2026-08-10T00:00:00Z"},
        ])

        app = FastAPI()
        app.include_router(router)

        with patch("mcp_memory_service.web.api.backup.require_read_access", return_value=True):
            with patch("mcp_memory_service.backup.scheduler.get_backup_service") as mock_get:
                from mcp_memory_service.backup.scheduler import BackupService
                service = BackupService(backups_dir=str(tmp_path / "backups"), db_path=str(db_path))
                mock_get.return_value = service

                with patch("mcp_memory_service.web.api.backup.require_read_access"):
                    from starlette.requests import Request
                    client = TestClient(app)

                    # Bypass auth
                    app.dependency_overrides[
                        __import__("mcp_memory_service.web.api.backup", fromlist=["require_read_access"]).require_read_access
                    ] = lambda: True

                    resp = client.get("/backup/conflicts")
                    assert resp.status_code == 200
                    data = resp.json()
                    assert data["total_count"] == 1
                    assert data["conflicts"][0]["content_hash"] == "abc"

    def test_resolve_conflict_marks_resolved(self, tmp_path):
        """POST /backup/conflicts/resolve marks conflict as resolved."""
        from fastapi.testclient import TestClient
        from mcp_memory_service.web.api.backup import router
        from fastapi import FastAPI

        db_path = tmp_path / "test.db"
        create_test_db_with_conflicts(db_path, [
            {"content_hash": "abc", "local_version": 1, "remote_version": 3,
             "conflict_type": "version_divergence", "detected_at": "2026-08-10T00:00:00Z"},
        ])

        app = FastAPI()
        app.include_router(router)

        from mcp_memory_service.backup.scheduler import BackupService
        service = BackupService(backups_dir=str(tmp_path / "backups"), db_path=str(db_path))

        with patch("mcp_memory_service.backup.scheduler.get_backup_service", return_value=service):
            app.dependency_overrides[
                __import__("mcp_memory_service.web.api.backup", fromlist=["require_write_access"]).require_write_access
            ] = lambda: True

            client = TestClient(app)
            resp = client.post("/backup/conflicts/resolve?conflict_id=1&resolution=manual")
            assert resp.status_code == 200
            assert resp.json()["success"] is True

            # Verify conflict is resolved
            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT resolved_at, resolution FROM backup_conflicts WHERE id=1").fetchone()
            conn.close()
            assert row[0] is not None
            assert row[1] == "manual"

    def test_resolved_conflicts_excluded_from_get(self, tmp_path):
        """Resolved conflicts are excluded from GET /backup/conflicts."""
        from fastapi.testclient import TestClient
        from mcp_memory_service.web.api.backup import router
        from fastapi import FastAPI

        db_path = tmp_path / "test.db"
        create_test_db_with_conflicts(db_path, [
            {"content_hash": "abc", "local_version": 1, "remote_version": 3,
             "conflict_type": "version_divergence", "detected_at": "2026-08-10T00:00:00Z"},
            {"content_hash": "def", "local_version": 2, "remote_version": 5,
             "conflict_type": "version_divergence", "detected_at": "2026-08-10T01:00:00Z"},
        ])

        # Pre-resolve one conflict
        conn = sqlite3.connect(str(db_path))
        conn.execute("UPDATE backup_conflicts SET resolved_at = '2026-08-10T02:00:00Z', resolution = 'manual' WHERE id = 1")
        conn.commit()
        conn.close()

        app = FastAPI()
        app.include_router(router)

        from mcp_memory_service.backup.scheduler import BackupService
        service = BackupService(backups_dir=str(tmp_path / "backups"), db_path=str(db_path))

        with patch("mcp_memory_service.backup.scheduler.get_backup_service", return_value=service):
            app.dependency_overrides[
                __import__("mcp_memory_service.web.api.backup", fromlist=["require_read_access"]).require_read_access
            ] = lambda: True

            client = TestClient(app)
            resp = client.get("/backup/conflicts")
            assert resp.status_code == 200
            data = resp.json()
            assert data["total_count"] == 1  # Only the unresolved one
            assert data["conflicts"][0]["content_hash"] == "def"
