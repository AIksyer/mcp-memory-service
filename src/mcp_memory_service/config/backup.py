"""Backup and integrity check configuration."""

import logging
import os
import uuid

from .base import safe_get_bool_env, safe_get_int_env

logger = logging.getLogger(__name__)

# =============================================================================
# Automatic Backup Configuration
# =============================================================================

BACKUP_ENABLED = safe_get_bool_env("MCP_BACKUP_ENABLED", True)
BACKUP_INTERVAL = os.getenv(
    "MCP_BACKUP_INTERVAL", "daily"
).lower()  # 'hourly', 'daily', 'weekly'
BACKUP_RETENTION = safe_get_int_env(
    "MCP_BACKUP_RETENTION", 7, min_value=1, max_value=365
)  # days
BACKUP_MAX_COUNT = safe_get_int_env(
    "MCP_BACKUP_MAX_COUNT", 10, min_value=1, max_value=100
)  # max backups to keep

# Validate backup interval
if BACKUP_INTERVAL not in ["hourly", "daily", "weekly"]:
    logger.warning(
        f"Invalid backup interval: {BACKUP_INTERVAL}, falling back to 'daily'"
    )
    BACKUP_INTERVAL = "daily"

logger.info(
    f"Backup configuration: enabled={BACKUP_ENABLED}, interval={BACKUP_INTERVAL}, retention={BACKUP_RETENTION} days"
)

# =============================================================================
# End Automatic Backup Configuration
# =============================================================================

# =============================================================================
# Remote Backup Targets
# =============================================================================
# Each target is independently enabled. Credentials for R2 reuse
# CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from storage config.

BACKUP_R2_ENABLED = safe_get_bool_env("MCP_BACKUP_R2_ENABLED", False)
BACKUP_R2_BUCKET = os.getenv("MCP_BACKUP_R2_BUCKET", "mcp-memory-backup")

# R2 history retention (v2): keep N daily + M weekly + K monthly snapshots
BACKUP_R2_RETENTION_DAILY = safe_get_int_env("MCP_BACKUP_R2_RETENTION_DAILY", 7, min_value=1, max_value=90)
BACKUP_R2_RETENTION_WEEKLY = safe_get_int_env("MCP_BACKUP_R2_RETENTION_WEEKLY", 4, min_value=1, max_value=52)
BACKUP_R2_RETENTION_MONTHLY = safe_get_int_env("MCP_BACKUP_R2_RETENTION_MONTHLY", 3, min_value=1, max_value=12)

# R2 storage pressure threshold (GB, v3): only clean up old backups when R2
# bucket usage exceeds this. User explicitly requested "don't delete old backups
# until storage is tight". R2 free tier is 10GB; a ~5MB DB over a year is ~1.8GB.
BACKUP_R2_STORAGE_PRESSURE_THRESHOLD = safe_get_int_env(
    "MCP_BACKUP_R2_STORAGE_PRESSURE_THRESHOLD", 8, min_value=1, max_value=10
)

# R2 backup quarantine (v4): new backups go to pending/ prefix, promoted to backups/
# after this many hours. Ensures backups are stable before being available for restore.
BACKUP_R2_QUARANTINE_HOURS = safe_get_int_env(
    "MCP_BACKUP_R2_QUARANTINE_HOURS", 24, min_value=1, max_value=168
)

BACKUP_GITHUB_ENABLED = safe_get_bool_env("MCP_BACKUP_GITHUB_ENABLED", False)
BACKUP_GITHUB_REPO = os.getenv("MCP_BACKUP_GITHUB_REPO", "")
BACKUP_GITHUB_BRANCH = os.getenv("MCP_BACKUP_GITHUB_BRANCH", "master")
BACKUP_GITHUB_TOKEN = os.getenv("MCP_BACKUP_GITHUB_TOKEN", "")
BACKUP_GITHUB_LOCAL_DIR = os.getenv("MCP_BACKUP_GITHUB_LOCAL_DIR", "")

BACKUP_REMOTE_ON_STARTUP = safe_get_bool_env("MCP_BACKUP_REMOTE_ON_STARTUP", True)

# Device identifier (v4): used in sync_version tracking and backup manifests.
# Set MCP_DEVICE_ID in .env for persistence across restarts.
# Falls back to a short UUID generated per process if not set.
DEVICE_ID = os.getenv("MCP_DEVICE_ID") or str(uuid.uuid4())[:8]

logger.info(
    f"Remote backup targets: R2={BACKUP_R2_ENABLED}, GitHub={BACKUP_GITHUB_ENABLED}, "
    f"device_id={DEVICE_ID}"
)

# =============================================================================
# End Remote Backup Targets
# =============================================================================

# =============================================================================
# Database Integrity Health Monitoring
# =============================================================================
# Periodic PRAGMA integrity_check to detect SQLite corruption early.
# SQLite WAL mode is crash-resistant but not SIGKILL-resistant — process kills
# during writes can corrupt the WAL/SHM files or main database. Periodic
# integrity monitoring catches corruption within minutes rather than waiting
# for the next user operation to fail and lose data.
#
# Performance: integrity_check takes ~3.5ms on a typical database.
# At the default 30-minute interval, this adds 0.0002% overhead.

INTEGRITY_CHECK_ENABLED = safe_get_bool_env("MCP_MEMORY_INTEGRITY_CHECK_ENABLED", True)
INTEGRITY_CHECK_INTERVAL = safe_get_int_env(
    "MCP_MEMORY_INTEGRITY_CHECK_INTERVAL", 1800, min_value=60, max_value=86400
)  # seconds, default 30 min

logger.info(
    f"Integrity monitoring: enabled={INTEGRITY_CHECK_ENABLED}, interval={INTEGRITY_CHECK_INTERVAL}s"
)

# =============================================================================
# End Database Integrity Health Monitoring
# =============================================================================
