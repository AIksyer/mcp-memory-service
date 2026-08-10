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
Backup management endpoints for MCP Memory Service.

Provides status monitoring, manual backup triggering, and backup listing.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

# OAuth authentication imports
from ..oauth.middleware import (
    AuthenticationResult,
    require_read_access,
    require_write_access,
)

router = APIRouter()


class BackupStatusResponse(BaseModel):
    """Backup status response model."""

    enabled: bool
    interval: str
    retention_days: int
    max_count: int
    backup_count: int
    total_size_bytes: int
    last_backup_time: float | None
    time_since_last_seconds: float | None
    next_backup_at: str | None
    scheduler_running: bool
    backup_directory: str | None = None


class BackupCreateResponse(BaseModel):
    """Backup creation response model."""

    success: bool
    filename: str | None = None
    size_bytes: int | None = None
    created_at: str | None = None
    duration_seconds: float | None = None
    error: str | None = None


class BackupInfo(BaseModel):
    """Backup information model."""

    filename: str
    size_bytes: int
    created_at: str
    age_days: int


class BackupListResponse(BaseModel):
    """Backup list response model."""

    backups: list[BackupInfo]
    total_count: int
    total_size_bytes: int


@router.get("/backup/status", response_model=BackupStatusResponse)
async def get_backup_status(user: AuthenticationResult = Depends(require_read_access)):
    """
    Get current backup service status.

    Returns backup configuration, last backup time, and next scheduled backup.
    """
    try:
        from mcp_memory_service.backup.scheduler import get_backup_scheduler

        scheduler = get_backup_scheduler()
        status = scheduler.get_status()

        return BackupStatusResponse(
            enabled=status.get("enabled", False),
            interval=status.get("interval", "daily"),
            retention_days=status.get("retention_days", 7),
            max_count=status.get("max_count", 10),
            backup_count=status.get("backup_count", 0),
            total_size_bytes=status.get("total_size_bytes", 0),
            last_backup_time=status.get("last_backup_time"),
            time_since_last_seconds=status.get("time_since_last_seconds"),
            next_backup_at=status.get("next_backup_at"),
            scheduler_running=status.get("scheduler_running", False),
            backup_directory=status.get("backups_dir"),
        )

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to get backup status: {e!s}"
        )


@router.post("/backup/now", response_model=BackupCreateResponse)
async def trigger_backup(user: AuthenticationResult = Depends(require_write_access)):
    """
    Manually trigger an immediate backup.

    Creates a new backup of the database regardless of the schedule.
    """
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        result = await backup_service.create_backup(
            description="Manual backup from dashboard"
        )

        if result.get("success"):
            return BackupCreateResponse(
                success=True,
                filename=result.get("filename"),
                size_bytes=result.get("size_bytes"),
                created_at=result.get("created_at"),
                duration_seconds=result.get("duration_seconds"),
            )
        else:
            return BackupCreateResponse(
                success=False, error=result.get("error", "Unknown error")
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create backup: {e!s}")


@router.post("/backup/push-remote")
async def push_remote_backup(
    user: AuthenticationResult = Depends(require_write_access),
):
    """
    Manually trigger a backup with remote push (R2 + GitHub).

    Creates a local backup and pushes to all enabled remote targets.
    """
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        result = await backup_service.create_backup(description="Manual remote push")

        if result.get("success"):
            return {
                "success": True,
                "filename": result.get("filename"),
                "size_bytes": result.get("size_bytes"),
                "created_at": result.get("created_at"),
                "remote": result.get("remote", {}),
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Unknown error"),
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to push remote backup: {e!s}")


@router.get("/backup/list", response_model=BackupListResponse)
async def list_backups(user: AuthenticationResult = Depends(require_read_access)):
    """
    List all available backups.

    Returns list of backups sorted by date (newest first).
    """
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        backups = backup_service.list_backups()

        backup_infos = [
            BackupInfo(
                filename=b["filename"],
                size_bytes=b["size_bytes"],
                created_at=b["created_at"],
                age_days=b["age_days"],
            )
            for b in backups
        ]

        total_size = sum(b["size_bytes"] for b in backups)

        return BackupListResponse(
            backups=backup_infos,
            total_count=len(backup_infos),
            total_size_bytes=total_size,
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list backups: {e!s}")


@router.post("/backup/restore")
async def restore_from_r2(
    object_key: str | None = None,
    user: AuthenticationResult = Depends(require_write_access),
):
    """
    Restore database from an R2 backup via staging.

    Downloads the specified R2 backup (or the latest if no key is given),
    validates integrity and schema version, backs up the current DB, then
    replaces it. Does NOT touch D1 — user must manually reconcile if desired.
    """
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        result = await backup_service.restore_from_r2(object_key)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to restore from R2: {e!s}"
        )


@router.get("/backup/r2/list")
async def list_r2_backups(user: AuthenticationResult = Depends(require_read_access)):
    """List available R2 backup objects."""
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        objects = await backup_service._r2_list_objects()
        backups = [
            obj
            for obj in objects
            if obj.get("key", "").startswith("backups/")
        ]
        return {
            "backups": backups,
            "total_count": len(backups),
        }

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list R2 backups: {e!s}"
        )


@router.get("/backup/conflicts")
async def list_conflicts(user: AuthenticationResult = Depends(require_read_access)):
    """List unresolved backup sync conflicts."""
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        if not backup_service.db_path or not backup_service.db_path.exists():
            return {"conflicts": [], "total_count": 0}

        import sqlite3 as _sqlite3

        def _query_conflicts():
            conn = _sqlite3.connect(str(backup_service.db_path))
            cursor = conn.execute(
                "SELECT id, content_hash, local_version, remote_version, "
                "local_device_id, remote_device_id, conflict_type, "
                "local_updated_at, remote_updated_at, detected_at "
                "FROM backup_conflicts WHERE resolved_at IS NULL "
                "ORDER BY detected_at DESC"
            )
            rows = cursor.fetchall()
            conn.close()
            return rows

        rows = await __import__("asyncio").to_thread(_query_conflicts)
        conflicts = [
            {
                "id": r[0],
                "content_hash": r[1],
                "local_version": r[2],
                "remote_version": r[3],
                "local_device_id": r[4],
                "remote_device_id": r[5],
                "conflict_type": r[6],
                "local_updated_at": r[7],
                "remote_updated_at": r[8],
                "detected_at": r[9],
            }
            for r in rows
        ]
        return {"conflicts": conflicts, "total_count": len(conflicts)}

    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to list conflicts: {e!s}"
        )


@router.post("/backup/conflicts/resolve")
async def resolve_conflict(
    conflict_id: int,
    resolution: str = "manual",
    user: AuthenticationResult = Depends(require_write_access),
):
    """Mark a backup conflict as resolved."""
    try:
        from mcp_memory_service.backup.scheduler import get_backup_service

        backup_service = get_backup_service()
        if not backup_service.db_path or not backup_service.db_path.exists():
            raise HTTPException(status_code=404, detail="Database not found")

        import sqlite3 as _sqlite3
        from datetime import datetime, timezone as _tz

        def _resolve():
            conn = _sqlite3.connect(str(backup_service.db_path))
            now = datetime.now(_tz.utc).isoformat()
            cursor = conn.execute(
                "UPDATE backup_conflicts SET resolved_at = ?, resolution = ? "
                "WHERE id = ? AND resolved_at IS NULL",
                (now, resolution, conflict_id),
            )
            conn.commit()
            affected = cursor.rowcount
            conn.close()
            return affected

        affected = await __import__("asyncio").to_thread(_resolve)
        if affected == 0:
            raise HTTPException(status_code=404, detail="Conflict not found or already resolved")

        return {"success": True, "conflict_id": conflict_id, "resolved_at": datetime.now(_tz.utc).isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Failed to resolve conflict: {e!s}"
        )
