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
Automatic backup scheduler for MCP Memory Service.

Provides scheduled database backups with configurable intervals and retention policies.
"""

import asyncio
import hashlib
import json
import logging
import os
import shutil
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ..config import (
    BACKUP_ENABLED,
    BACKUP_GITHUB_BRANCH,
    BACKUP_GITHUB_ENABLED,
    BACKUP_GITHUB_LOCAL_DIR,
    BACKUP_GITHUB_REPO,
    BACKUP_GITHUB_TOKEN,
    BACKUP_INTERVAL,
    BACKUP_MAX_COUNT,
    BACKUP_R2_BUCKET,
    BACKUP_R2_ENABLED,
    BACKUP_R2_RETENTION_DAILY,
    BACKUP_R2_RETENTION_MONTHLY,
    BACKUP_R2_RETENTION_WEEKLY,
    BACKUP_REMOTE_ON_STARTUP,
    BACKUP_RETENTION,
    BACKUPS_PATH,
    CLOUDFLARE_ACCOUNT_ID,
    CLOUDFLARE_API_TOKEN,
    SQLITE_VEC_PATH,
)

logger = logging.getLogger(__name__)


class BackupService:
    """Service for creating and managing database backups."""

    def __init__(self, backups_dir: str | None = None, db_path: str | None = None):
        """Initialize backup service.

        Args:
            backups_dir: Directory to store backups (defaults to BACKUPS_PATH)
            db_path: Path to database file (defaults to SQLITE_VEC_PATH)
        """
        self.backups_dir = Path(backups_dir or BACKUPS_PATH)
        # Determine database path with clear fallback logic
        db_path_str = db_path or SQLITE_VEC_PATH
        self.db_path = Path(db_path_str) if db_path_str else None
        self.last_backup_time: float | None = None
        self.backup_count: int = 0
        self._lock = asyncio.Lock()  # Ensure thread-safe operations

        # Ensure backup directory exists
        self.backups_dir.mkdir(parents=True, exist_ok=True)

        # Load existing backup metadata
        self._load_backup_metadata()

        logger.info(
            f"BackupService initialized: backups_dir={self.backups_dir}, db_path={self.db_path}"
        )

    def _load_backup_metadata(self):
        """Load metadata about existing backups."""
        backups = self.list_backups()
        self.backup_count = len(backups)
        if backups:
            # Get most recent backup time
            latest = backups[0]
            self.last_backup_time = latest.get("created_timestamp", 0)

    def _get_memory_count(self) -> int:
        """Get memory count from the database."""
        if not self.db_path or not self.db_path.exists():
            return 0
        try:
            conn = sqlite3.connect(str(self.db_path))
            count = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            conn.close()
            return count
        except Exception:
            return 0

    async def _check_integrity(self) -> bool:
        """Run PRAGMA integrity_check on the database.

        Blue Team C-2 mitigation: prevents pushing corrupted DB to remote targets.
        """
        if not self.db_path or not self.db_path.exists():
            return False
        try:
            def _check():
                conn = sqlite3.connect(str(self.db_path))
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
                conn.close()
                return result
            result = await asyncio.to_thread(_check)
            if result != "ok":
                logger.error(f"Database integrity check FAILED: {result}")
                return False
            logger.debug("Database integrity check passed")
            return True
        except Exception as e:
            logger.error(f"Database integrity check error: {e}")
            return False

    async def _push_to_r2(self, backup_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        """Push backup file to Cloudflare R2.

        Best-effort: returns error dict on failure, never raises.
        """
        if not BACKUP_R2_ENABLED:
            return {"success": True, "skipped": True, "target": "r2"}

        if not CLOUDFLARE_API_TOKEN or not CLOUDFLARE_ACCOUNT_ID:
            logger.warning("R2 backup enabled but CLOUDFLARE credentials not set")
            return {"success": False, "error": "Cloudflare credentials not configured", "target": "r2"}

        try:
            import httpx

            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            object_key = f"backups/sqlite_vec_{timestamp}.db"
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
                f"/r2/buckets/{BACKUP_R2_BUCKET}/objects/{object_key}"
            )

            data = await asyncio.to_thread(lambda: backup_path.read_bytes())

            async with httpx.AsyncClient(timeout=httpx.Timeout(120.0)) as client:
                response = await client.put(
                    url,
                    content=data,
                    headers={
                        "Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}",
                        "Content-Type": "application/octet-stream",
                    },
                )
                response.raise_for_status()
                result = response.json()
                if not result.get("success"):
                    return {"success": False, "error": f"R2 API error: {result}", "target": "r2"}

            file_sha256 = hashlib.sha256(data).hexdigest()
            logger.info(f"R2 backup uploaded: {object_key} ({len(data)} bytes)")

            # Clean up old R2 backups after successful upload
            await self._r2_cleanup_old_backups()

            return {
                "success": True,
                "target": "r2",
                "object_key": object_key,
                "size_bytes": len(data),
                "sha256": file_sha256,
            }
        except Exception as e:
            logger.error(f"R2 backup failed: {e}")
            return {"success": False, "error": str(e), "target": "r2"}

    async def _r2_list_objects(self) -> list[dict[str, Any]]:
        """List all backup objects in R2 bucket."""
        if not BACKUP_R2_ENABLED or not CLOUDFLARE_API_TOKEN:
            return []
        try:
            import httpx
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
                f"/r2/buckets/{BACKUP_R2_BUCKET}/objects"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    url, headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("result", [])
        except Exception as e:
            logger.warning(f"R2 list objects failed: {e}")
            return []

    async def _r2_delete_object(self, key: str) -> bool:
        """Delete an object from R2 bucket."""
        try:
            import httpx
            url = (
                f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT_ID}"
                f"/r2/buckets/{BACKUP_R2_BUCKET}/objects/{key}"
            )
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.delete(
                    url, headers={"Authorization": f"Bearer {CLOUDFLARE_API_TOKEN}"}
                )
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.warning(f"R2 delete {key} failed: {e}")
            return False

    async def _r2_cleanup_old_backups(self) -> dict[str, Any]:
        """Clean up old R2 backups based on retention policy.

        Keeps: N daily + M weekly + K monthly snapshots.
        """
        objects = await self._r2_list_objects()
        if not objects:
            return {"deleted_count": 0, "kept_count": 0}

        now = datetime.now(timezone.utc)
        daily_cutoff = now - timedelta(days=BACKUP_R2_RETENTION_DAILY)
        monthly_window = now - timedelta(days=BACKUP_R2_RETENTION_MONTHLY * 30)
        max_window = now - timedelta(days=90)

        to_delete = []
        kept = []

        for obj in objects:
            key = obj.get("key", "")
            lm_str = obj.get("last_modified", "")
            try:
                lm = datetime.fromisoformat(lm_str.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue

            # Keep everything within daily retention window
            if lm >= daily_cutoff:
                kept.append(obj)
                continue

            # Keep weekly snapshots within monthly window (~every 7 days)
            if lm >= monthly_window:
                days_old = (now - lm).days
                if days_old % 7 < 1:
                    kept.append(obj)
                    continue

            # Keep monthly snapshots within 90-day window (~every 30 days)
            if lm >= max_window:
                days_old = (now - lm).days
                if days_old % 30 < 1:
                    kept.append(obj)
                    continue

            to_delete.append(key)

        deleted = 0
        for key in to_delete:
            if await self._r2_delete_object(key):
                deleted += 1
                logger.info(f"R2 cleanup: deleted {key}")

        logger.info(f"R2 cleanup: {deleted} deleted, {len(kept)} kept")
        return {"deleted_count": deleted, "kept_count": len(kept)}

    async def _push_to_github(self, backup_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        """Push backup manifest + checksum to GitHub repo (audit copy, no DB file).

        GitHub stores only metadata for verification, not the binary DB.
        R2 is the primary backup authority for full DB snapshots.
        Best-effort: returns error dict on failure, never raises.
        """
        if not BACKUP_GITHUB_ENABLED:
            return {"success": True, "skipped": True, "target": "github"}

        if not BACKUP_GITHUB_REPO:
            logger.warning("GitHub backup enabled but MCP_BACKUP_GITHUB_REPO not set")
            return {"success": False, "error": "GitHub repo not configured", "target": "github"}

        try:
            import tempfile

            repo_dir = BACKUP_GITHUB_LOCAL_DIR
            if not repo_dir:
                repo_dir = str(Path(tempfile.gettempdir()) / "mcp-memory-backup-repo")
            repo_dir = Path(repo_dir)

            def _git_init_or_pull():
                repo_dir.mkdir(parents=True, exist_ok=True)
                if not (repo_dir / ".git").exists():
                    token_url = (
                        f"https://x-access-token:{BACKUP_GITHUB_TOKEN}"
                        f"@github.com/{BACKUP_GITHUB_REPO}.git"
                    )
                    subprocess.run(
                        ["git", "clone", token_url, str(repo_dir)],
                        capture_output=True, text=True, timeout=120,
                    )
                else:
                    subprocess.run(
                        ["git", "pull", "--rebase"],
                        cwd=str(repo_dir), capture_output=True, text=True, timeout=60,
                    )
                (repo_dir / "data").mkdir(exist_ok=True)

            await asyncio.to_thread(_git_init_or_pull)

            # Write manifest only (no DB file — GitHub is audit copy)
            manifest_path = repo_dir / "data" / "backup_manifest.json"
            manifest_content = json.dumps(manifest, indent=2)
            tmp_manifest = manifest_path.with_suffix(".tmp")
            tmp_manifest.write_text(manifest_content, encoding="utf-8")
            os.replace(str(tmp_manifest), str(manifest_path))

            # Write checksum file
            sha = manifest.get("file_sha256", "")
            checksum_path = repo_dir / "data" / "checksum.txt"
            tmp_checksum = checksum_path.with_suffix(".tmp")
            tmp_checksum.write_text(f"{sha}\n", encoding="utf-8")
            os.replace(str(tmp_checksum), str(checksum_path))

            def _git_commit_push():
                subprocess.run(
                    ["git", "add", "data/"],
                    cwd=str(repo_dir), capture_output=True, text=True,
                )
                diff_result = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=str(repo_dir), capture_output=True,
                )
                if diff_result.returncode == 0:
                    return "no_changes"

                commit_msg = (
                    f"audit: {manifest.get('memory_count', '?')} memories, "
                    f"sha256={sha[:16]}..., "
                    f"{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')} UTC"
                )
                subprocess.run(
                    ["git", "commit", "-m", commit_msg],
                    cwd=str(repo_dir), capture_output=True, text=True,
                )

                token_url = (
                    f"https://x-access-token:{BACKUP_GITHUB_TOKEN}"
                    f"@github.com/{BACKUP_GITHUB_REPO}.git"
                )
                push_result = subprocess.run(
                    ["git", "push", token_url, BACKUP_GITHUB_BRANCH],
                    cwd=str(repo_dir), capture_output=True, text=True, timeout=120,
                )
                if push_result.returncode != 0:
                    raise RuntimeError(f"Git push failed: {push_result.stderr}")
                return "pushed"

            push_status = await asyncio.to_thread(_git_commit_push)
            logger.info(f"GitHub audit backup {push_status}: {BACKUP_GITHUB_REPO}")

            return {
                "success": True,
                "target": "github",
                "status": push_status,
                "sha256": sha,
            }
        except Exception as e:
            logger.error(f"GitHub audit backup failed: {e}")
            return {"success": False, "error": str(e), "target": "github"}

    async def _push_to_remote(self, backup_path: Path, manifest: dict[str, Any]) -> dict[str, Any]:
        """Push backup to all enabled remote targets.

        Blue Team C-2 mitigation: runs integrity check before pushing.
        If integrity check fails, aborts remote push to prevent corruption propagation.
        """
        results: dict[str, Any] = {"r2": None, "github": None}

        if not await self._check_integrity():
            logger.error(
                "Database integrity check failed — aborting remote backup "
                "to prevent corruption spread"
            )
            results["r2"] = {"success": False, "error": "integrity_check_failed", "target": "r2"}
            results["github"] = {"success": False, "error": "integrity_check_failed", "target": "github"}
            return results

        manifest["file_sha256"] = hashlib.sha256(
            await asyncio.to_thread(lambda: backup_path.read_bytes())
        ).hexdigest()
        manifest["db_size_bytes"] = backup_path.stat().st_size

        results["r2"] = await self._push_to_r2(backup_path, manifest)
        results["github"] = await self._push_to_github(backup_path, manifest)

        r2_status = "OK" if results["r2"]["success"] else "FAIL"
        gh_status = "OK" if results["github"]["success"] else "FAIL"
        logger.info(f"Remote backup: R2={r2_status}, GitHub={gh_status}")

        return results

    def _generate_backup_filename(self) -> str:
        """Generate a timestamped backup filename."""
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        return f"memory_backup_{timestamp}.db"

    async def create_backup(self, description: str | None = None) -> dict[str, Any]:
        """Create a new database backup.

        Args:
            description: Optional description for the backup

        Returns:
            Dict with backup details
        """
        if not self.db_path or not self.db_path.exists():
            return {
                "success": False,
                "error": f"Database file not found: {self.db_path}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        async with self._lock:  # Ensure atomic operations
            try:
                start_time = time.time()
                created_at = datetime.now(timezone.utc)

                # Generate backup filename
                backup_filename = self._generate_backup_filename()
                backup_path = self.backups_dir / backup_filename

                # Use SQLite's native backup API for safe, consistent backups
                # This handles active database connections properly
                def _do_backup():
                    source = sqlite3.connect(str(self.db_path))
                    dest = sqlite3.connect(str(backup_path))
                    try:
                        source.backup(dest)
                    finally:
                        source.close()
                        dest.close()

                await asyncio.to_thread(_do_backup)

                # Calculate backup duration (just the backup operation)
                backup_duration = time.time() - start_time

                # Get backup size
                backup_size = backup_path.stat().st_size

                # Update metadata
                self.last_backup_time = created_at.timestamp()
                self.backup_count += 1

                logger.info(
                    f"Created backup: {backup_filename} ({backup_size} bytes) in {backup_duration:.2f}s"
                )

                # Cleanup old backups (outside of duration calculation)
                await self.cleanup_old_backups()

                # Push to remote targets (R2, GitHub) if enabled
                # Get schema version from DB
                schema_version = "unknown"
                try:
                    conn = sqlite3.connect(str(self.db_path))
                    row = conn.execute(
                        "SELECT value FROM metadata WHERE key='schema_version'"
                    ).fetchone()
                    if row:
                        schema_version = row[0]
                    conn.close()
                except Exception:
                    pass

                # Get device ID (hostname-based)
                import socket
                device_id = socket.gethostname()

                # Determine backup type based on time
                backup_type = "daily"
                hour = created_at.hour
                if hour == 0 and created_at.weekday() == 0:
                    backup_type = "weekly"
                if hour == 0 and created_at.day == 1:
                    backup_type = "monthly"

                manifest = {
                    "timestamp": created_at.isoformat(),
                    "memory_count": self._get_memory_count(),
                    "db_size_bytes": backup_size,
                    "filename": backup_filename,
                    "schema_version": schema_version,
                    "device_id": device_id,
                    "backup_type": backup_type,
                }
                remote_results = await self._push_to_remote(backup_path, manifest)

                return {
                    "success": True,
                    "filename": backup_filename,
                    "path": str(backup_path),
                    "size_bytes": backup_size,
                    "description": description,
                    "created_at": created_at.isoformat(),
                    "duration_seconds": round(backup_duration, 3),
                    "remote": remote_results,
                }

            except Exception as e:
                logger.error(f"Failed to create backup: {e}")
                return {
                    "success": False,
                    "error": str(e),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }

    def list_backups(self) -> list[dict[str, Any]]:
        """List all available backups.

        Returns:
            List of backup info dicts, sorted by date (newest first)
        """
        backups = []

        try:
            for backup_file in self.backups_dir.glob("memory_backup_*.db"):
                stat = backup_file.stat()

                # Parse timestamp from filename
                try:
                    timestamp_str = backup_file.stem.replace("memory_backup_", "")
                    created_dt = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                    created_dt = created_dt.replace(tzinfo=timezone.utc)
                except ValueError:
                    created_dt = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)

                backups.append(
                    {
                        "filename": backup_file.name,
                        "path": str(backup_file),
                        "size_bytes": stat.st_size,
                        "created_at": created_dt.isoformat(),
                        "created_timestamp": created_dt.timestamp(),
                        "age_days": (datetime.now(timezone.utc) - created_dt).days,
                    }
                )

            # Sort by creation time, newest first
            backups.sort(key=lambda x: x["created_timestamp"], reverse=True)

        except Exception as e:
            logger.error(f"Error listing backups: {e}")

        return backups

    async def cleanup_old_backups(self) -> dict[str, Any]:
        """Remove old backups based on retention policy.

        Removes backups that are:
        - Older than BACKUP_RETENTION days
        - Exceed BACKUP_MAX_COUNT

        Returns:
            Dict with cleanup results
        """
        removed = []
        errors = []

        try:
            backups = self.list_backups()
            retention_cutoff = datetime.now(timezone.utc) - timedelta(
                days=BACKUP_RETENTION
            )

            for i, backup in enumerate(backups):
                should_remove = False
                reason = ""

                # Check if exceeds max count
                if i >= BACKUP_MAX_COUNT:
                    should_remove = True
                    reason = f"exceeds max count ({BACKUP_MAX_COUNT})"

                # Check if older than retention period
                try:
                    created_dt = datetime.fromisoformat(
                        backup["created_at"].replace("Z", "+00:00")
                    )
                    if created_dt < retention_cutoff:
                        should_remove = True
                        reason = f"older than {BACKUP_RETENTION} days"
                except (ValueError, KeyError) as e:
                    logger.warning(
                        f"Could not parse timestamp for backup {backup.get('filename', 'unknown')}: {e}"
                    )

                if should_remove:
                    try:
                        # Use asyncio.to_thread to avoid blocking the event loop
                        await asyncio.to_thread(Path(backup["path"]).unlink)
                        removed.append(
                            {"filename": backup["filename"], "reason": reason}
                        )
                        logger.info(
                            f"Removed old backup: {backup['filename']} ({reason})"
                        )
                    except Exception as e:
                        errors.append({"filename": backup["filename"], "error": str(e)})
                        logger.error(
                            f"Failed to remove backup {backup['filename']}: {e}"
                        )

            # Update count more efficiently by subtracting removed count
            self.backup_count = max(0, self.backup_count - len(removed))

        except Exception as e:
            logger.error(f"Error during backup cleanup: {e}")
            errors.append({"error": str(e)})

        return {"removed_count": len(removed), "removed": removed, "errors": errors}

    async def restore_backup(self, filename: str) -> dict[str, Any]:
        """Restore database from a backup.

        Args:
            filename: Name of backup file to restore

        Returns:
            Dict with restore results
        """
        backup_path = self.backups_dir / filename

        if not backup_path.exists():
            return {"success": False, "error": f"Backup file not found: {filename}"}

        if not self.db_path:
            return {"success": False, "error": "Database path not configured"}

        try:
            # Create a backup of current database first
            if self.db_path.exists():
                current_backup = self.db_path.with_suffix(".db.pre_restore")
                # Use asyncio.to_thread to avoid blocking the event loop
                await asyncio.to_thread(
                    shutil.copy2, str(self.db_path), str(current_backup)
                )
                logger.info(f"Created pre-restore backup: {current_backup}")

            # Restore from backup
            # Use asyncio.to_thread to avoid blocking the event loop
            await asyncio.to_thread(shutil.copy2, str(backup_path), str(self.db_path))

            logger.info(f"Restored database from backup: {filename}")

            return {
                "success": True,
                "filename": filename,
                "restored_at": datetime.now(timezone.utc).isoformat(),
            }

        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            return {"success": False, "error": str(e)}

    def get_status(self) -> dict[str, Any]:
        """Get current backup service status.

        Returns:
            Dict with backup service status
        """
        backups = self.list_backups()
        total_size = sum(b["size_bytes"] for b in backups)

        # Calculate time since last backup
        time_since_last = None
        if self.last_backup_time:
            time_since_last = time.time() - self.last_backup_time

        # Calculate next scheduled backup time
        next_backup = self._calculate_next_backup_time()

        return {
            "enabled": BACKUP_ENABLED,
            "interval": BACKUP_INTERVAL,
            "retention_days": BACKUP_RETENTION,
            "max_count": BACKUP_MAX_COUNT,
            "backup_count": len(backups),
            "total_size_bytes": total_size,
            "last_backup_time": self.last_backup_time,
            "time_since_last_seconds": time_since_last,
            "next_backup_at": next_backup.isoformat() if next_backup else None,
            "backups_dir": str(self.backups_dir),
            "db_path": str(self.db_path) if self.db_path else None,
            "remote_targets": {
                "r2": {
                    "enabled": BACKUP_R2_ENABLED,
                    "bucket": BACKUP_R2_BUCKET if BACKUP_R2_ENABLED else None,
                },
                "github": {
                    "enabled": BACKUP_GITHUB_ENABLED,
                    "repo": BACKUP_GITHUB_REPO if BACKUP_GITHUB_ENABLED else None,
                    "branch": BACKUP_GITHUB_BRANCH if BACKUP_GITHUB_ENABLED else None,
                },
            },
        }

    def _calculate_next_backup_time(self) -> datetime | None:
        """Calculate the next scheduled backup time.

        Ensures the returned time is always in the future by incrementing
        by the interval until a future time is found. This handles cases
        where the server was offline longer than the backup interval.
        """
        if not BACKUP_ENABLED or not self.last_backup_time:
            return None

        last_backup_dt = datetime.fromtimestamp(self.last_backup_time, tz=timezone.utc)

        # Determine interval
        if BACKUP_INTERVAL == "hourly":
            interval = timedelta(hours=1)
        elif BACKUP_INTERVAL == "daily":
            interval = timedelta(days=1)
        elif BACKUP_INTERVAL == "weekly":
            interval = timedelta(weeks=1)
        else:
            return None

        # Calculate next time, ensuring it's in the future
        next_time = last_backup_dt + interval
        now = datetime.now(timezone.utc)

        # Keep adding intervals until we get a future time
        while next_time <= now:
            next_time += interval

        return next_time


class BackupScheduler:
    """Scheduler for automatic database backups."""

    def __init__(self, backup_service: BackupService = None):
        """Initialize backup scheduler.

        Args:
            backup_service: BackupService instance (creates one if not provided)
        """
        self.backup_service = backup_service or BackupService()
        self.is_running = False
        self._task: asyncio.Task | None = None

        logger.info("BackupScheduler initialized")

    def _get_interval_seconds(self) -> int:
        """Get backup interval in seconds."""
        intervals = {
            "hourly": 3600,
            "daily": 86400,
            "weekly": 604800,
        }
        return intervals.get(BACKUP_INTERVAL, 86400)

    async def start(self):
        """Start the backup scheduler."""
        if self.is_running:
            logger.warning("BackupScheduler already running")
            return

        if not BACKUP_ENABLED:
            logger.info("Backups disabled, scheduler not started")
            return

        # Skip backup when no local SQLite database exists (Cloudflare/milvus backends)
        if not self.backup_service.db_path:
            logger.info("Backup scheduler skipped — no local SQLite database (non-sqlite backend)")
            return

        self.is_running = True
        self._task = asyncio.create_task(self._schedule_loop())
        logger.info(f"BackupScheduler started with {BACKUP_INTERVAL} interval")

    async def stop(self):
        """Stop the backup scheduler."""
        if not self.is_running:
            return

        self.is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # Expected when task is cancelled during shutdown

        logger.info("BackupScheduler stopped")

    async def _schedule_loop(self):
        """Main scheduling loop."""
        interval_seconds = self._get_interval_seconds()

        while self.is_running:
            try:
                # Check if it's time for a backup
                should_backup = False

                if not self.backup_service.last_backup_time:
                    # No previous backup, create one
                    should_backup = True
                else:
                    time_since_last = time.time() - self.backup_service.last_backup_time
                    if time_since_last >= interval_seconds:
                        should_backup = True

                if should_backup:
                    logger.info("Scheduled backup triggered")
                    result = await self.backup_service.create_backup(
                        description=f"Scheduled {BACKUP_INTERVAL} backup"
                    )
                    if result["success"]:
                        logger.info(f"Scheduled backup completed: {result['filename']}")
                    else:
                        logger.error(f"Scheduled backup failed: {result.get('error')}")

                # Sleep for a check interval (every 5 minutes)
                await asyncio.sleep(300)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in backup scheduler loop: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    def get_status(self) -> dict[str, Any]:
        """Get scheduler status.

        Returns:
            Dict with scheduler status and backup service status
        """
        status = self.backup_service.get_status()
        status["scheduler_running"] = self.is_running
        return status


# Global backup service instance
_backup_service: BackupService | None = None
_backup_scheduler: BackupScheduler | None = None


def get_backup_service() -> BackupService:
    """Get or create the global backup service instance."""
    global _backup_service
    if _backup_service is None:
        _backup_service = BackupService()
    return _backup_service


def get_backup_scheduler() -> BackupScheduler:
    """Get or create the global backup scheduler instance."""
    global _backup_scheduler
    if _backup_scheduler is None:
        _backup_scheduler = BackupScheduler(get_backup_service())
    return _backup_scheduler
