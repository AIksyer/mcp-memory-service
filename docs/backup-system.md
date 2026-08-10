# Backup System Documentation

This fork extends the upstream backup system with R2 remote backup, staging
restore, storage-pressure cleanup, sync version governance, conflict detection,
and backup quarantine.

## Configuration

All config is in `.env`. See `.env.example` for the full reference.

### Remote Backup Targets

| Variable | Default | Description |
|----------|---------|-------------|
| `MCP_BACKUP_R2_ENABLED` | `false` | Enable R2 backup uploads |
| `MCP_BACKUP_R2_BUCKET` | `mcp-memory-backup` | R2 bucket name |
| `MCP_BACKUP_R2_STORAGE_PRESSURE_THRESHOLD` | `8` (GB) | Delete old backups only when usage exceeds this |
| `MCP_BACKUP_R2_QUARANTINE_HOURS` | `24` | Hours before pending backups are promoted to available |
| `MCP_BACKUP_GITHUB_ENABLED` | `false` | Enable GitHub audit backup (manifest + checksum only) |
| `MCP_BACKUP_GITHUB_REPO` | (empty) | GitHub repo for audit copy |
| `MCP_BACKUP_GITHUB_TOKEN` | (empty) | GitHub personal access token |
| `MCP_BACKUP_REMOTE_ON_STARTUP` | `true` | Push to remote on server startup |
| `MCP_DEVICE_ID` | (random UUID) | Device identifier for sync tracking |

R2 backup reuses `CLOUDFLARE_API_TOKEN` and `CLOUDFLARE_ACCOUNT_ID` from the
Cloudflare storage config.

## How It Works

### Backup Flow

```
store() / update_memory_metadata()
    │ sync_version = 1 (new) or sync_version + 1 (update)
    │ device_id = MCP_DEVICE_ID
    ▼
create_backup()
    │ SQLite backup API → local .db file
    │ integrity_check gate
    ▼
_push_to_remote()
    ├── _push_to_r2() → pending/sqlite_vec_{timestamp}.db
    │   └── _r2_cleanup_under_pressure() (only if usage > threshold)
    │   └── _r2_promote_pending() (promote old pending → backups/)
    └── _push_to_github() → manifest.json + checksum.txt (audit only)
```

### Restore (v3)

`POST /api/backup/restore` — restore from R2 via staging:

1. Download R2 backup to staging path
2. PRAGMA integrity_check on staging
3. Schema version compatibility check (rejects older schemas)
4. Backup current DB to `.db.pre_r2_restore`
5. Replace primary DB
6. Return result with warning: **do NOT auto-reconcile**

Restore only scans `backups/` prefix (never `pending/`).

### Sync Version & Conflict Detection (v4)

Every write increments `sync_version`:
- `store()`: sets `sync_version = 1`
- `update_memory_metadata()`: `sync_version = sync_version + 1`

During bidirectional reconcile (`_reconcile_drift_in_both`):
1. Compare `sync_version` — higher version wins (no tolerance check)
2. If both sides have `sync_version > 0` and they differ → log conflict
3. If equal or one side is 0 (pre-v4) → fall back to `updated_at` comparison

Conflicts are deduped by `content_hash` — only one unresolved conflict per hash.

### Conflict Resolution

```bash
# List unresolved conflicts
curl -H "X-API-Key: $KEY" https://your-host/api/backup/conflicts

# Resolve a conflict
curl -X POST -H "X-API-Key: $KEY" \
  "https://your-host/api/backup/conflicts/resolve?conflict_id=1&resolution=manual"
```

### Backup Quarantine

New R2 uploads go to `pending/` prefix. After `MCP_BACKUP_R2_QUARANTINE_HOURS`
(default 24h), they are promoted to `backups/`:
1. Download from `pending/`
2. Re-upload to `backups/`
3. Verify HTTP success (R2 has no server-side copy)
4. Delete from `pending/`

This ensures backups are stable before being available for restore.

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/backup/now` | write | Trigger immediate local backup |
| `POST` | `/api/backup/push-remote` | write | Backup + push to R2/GitHub |
| `POST` | `/api/backup/restore` | write | Restore from R2 (staging) |
| `GET` | `/api/backup/status` | read | Backup service status |
| `GET` | `/api/backup/list` | read | List local backups |
| `GET` | `/api/backup/r2/list` | read | List R2 backup objects |
| `GET` | `/api/backup/conflicts` | read | List unresolved sync conflicts |
| `POST` | `/api/backup/conflicts/resolve` | write | Mark conflict resolved |

## Migrations

| Migration | Description |
|-----------|-------------|
| 013 | `backup_conflicts` table (audit trail) |
| 014 | `sync_version` + `device_id` columns on `memories` table |

Both migrations are applied automatically on startup (SQLite via MigrationRunner,
D1 via `_add_column_with_retry`).
