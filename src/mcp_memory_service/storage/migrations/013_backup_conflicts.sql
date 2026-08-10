-- Backup conflicts table: audit trail for sync conflicts between local and remote
-- v3: table only, no sync_version/device_id columns on memories (deferred to v4)
CREATE TABLE IF NOT EXISTS backup_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    content_hash TEXT NOT NULL,
    local_version INTEGER,
    remote_version INTEGER,
    local_device_id TEXT,
    remote_device_id TEXT,
    conflict_type TEXT NOT NULL,
    local_updated_at REAL,
    remote_updated_at REAL,
    detected_at TEXT NOT NULL,
    resolved_at TEXT,
    resolution TEXT,
    metadata TEXT DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_conflicts_content_hash ON backup_conflicts(content_hash);
CREATE INDEX IF NOT EXISTS idx_conflicts_unresolved ON backup_conflicts(resolved_at) WHERE resolved_at IS NULL;
