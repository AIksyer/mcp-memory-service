# Copyright 2024 Heinrich Krupp
# Modifications Copyright 2026 AIksyer
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
"""Tests for migration 014: sync_version + device_id columns on memories."""

import sqlite3
from pathlib import Path

import pytest

MIGRATION_FILE = (
    Path(__file__).parent.parent.parent
    / "src"
    / "mcp_memory_service"
    / "storage"
    / "migrations"
    / "014_sync_version_device_id.sql"
)


@pytest.fixture
def db_with_memories():
    """Create an in-memory SQLite DB with memories table and existing rows."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    conn.execute(
        "CREATE TABLE memories ("
        "content_hash TEXT UNIQUE, content TEXT, tags TEXT, memory_type TEXT, "
        "metadata TEXT, created_at REAL, updated_at REAL, "
        "created_at_iso TEXT, updated_at_iso TEXT, store TEXT, "
        "deleted_at REAL, superseded_by TEXT)"
    )
    # Insert a row that should get sync_version=1 default
    conn.execute(
        "INSERT INTO memories (content_hash, content) VALUES (?, ?)",
        ("abc123", "test content"),
    )
    yield conn
    conn.close()


@pytest.mark.unit
def test_migration_014_adds_sync_version_column(db_with_memories):
    """Migration 014 adds sync_version column."""
    sql = MIGRATION_FILE.read_text()
    db_with_memories.executescript(sql)

    cursor = db_with_memories.execute("PRAGMA table_info(memories)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert "sync_version" in columns
    assert columns["sync_version"] == "INTEGER"


@pytest.mark.unit
def test_migration_014_adds_device_id_column(db_with_memories):
    """Migration 014 adds device_id column."""
    sql = MIGRATION_FILE.read_text()
    db_with_memories.executescript(sql)

    cursor = db_with_memories.execute("PRAGMA table_info(memories)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}
    assert "device_id" in columns
    assert columns["device_id"] == "TEXT"


@pytest.mark.unit
def test_migration_014_existing_rows_get_defaults(db_with_memories):
    """Existing rows get sync_version=1 and device_id=NULL."""
    sql = MIGRATION_FILE.read_text()
    db_with_memories.executescript(sql)

    cursor = db_with_memories.execute(
        "SELECT sync_version, device_id FROM memories WHERE content_hash = ?",
        ("abc123",),
    )
    row = cursor.fetchone()
    assert row[0] == 1
    assert row[1] is None


@pytest.mark.unit
def test_migration_014_can_insert_with_new_columns(db_with_memories):
    """Can insert and query rows with sync_version and device_id set."""
    sql = MIGRATION_FILE.read_text()
    db_with_memories.executescript(sql)

    db_with_memories.execute(
        "INSERT INTO memories (content_hash, content, sync_version, device_id) "
        "VALUES (?, ?, ?, ?)",
        ("def456", "new content", 5, "device-001"),
    )
    db_with_memories.commit()

    cursor = db_with_memories.execute(
        "SELECT sync_version, device_id FROM memories WHERE content_hash = ?",
        ("def456",),
    )
    row = cursor.fetchone()
    assert row[0] == 5
    assert row[1] == "device-001"
