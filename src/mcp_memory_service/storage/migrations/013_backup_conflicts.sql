-- Copyright 2024 Heinrich Krupp
-- Modifications Copyright 2026 AIksyer
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
--     http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.
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
