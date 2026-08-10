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
"""Tests for migration 013: backup_conflicts table."""

import sqlite3
from pathlib import Path

import pytest

MIGRATION_FILE = (
    Path(__file__).parent.parent.parent
    / "src"
    / "mcp_memory_service"
    / "storage"
    / "migrations"
    / "013_backup_conflicts.sql"
)


@pytest.fixture
def db_conn():
    """Create an in-memory SQLite DB with metadata table."""
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    yield conn
    conn.close()


@pytest.mark.unit
def test_migration_013_creates_backup_conflicts_table(db_conn):
    """Migration 013 creates the backup_conflicts table."""
    sql = MIGRATION_FILE.read_text()
    db_conn.executescript(sql)

    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_conflicts'"
    )
    assert cursor.fetchone() is not None


@pytest.mark.unit
def test_migration_013_creates_indexes(db_conn):
    """Migration 013 creates content_hash and unresolved indexes."""
    sql = MIGRATION_FILE.read_text()
    db_conn.executescript(sql)

    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_conflicts%'"
    )
    indexes = [row[0] for row in cursor.fetchall()]
    assert "idx_conflicts_content_hash" in indexes
    assert "idx_conflicts_unresolved" in indexes


@pytest.mark.unit
def test_migration_013_table_schema(db_conn):
    """backup_conflicts table has all expected columns."""
    sql = MIGRATION_FILE.read_text()
    db_conn.executescript(sql)

    cursor = db_conn.execute("PRAGMA table_info(backup_conflicts)")
    columns = {row[1]: row[2] for row in cursor.fetchall()}

    assert "id" in columns
    assert "content_hash" in columns
    assert "local_version" in columns
    assert "remote_version" in columns
    assert "local_device_id" in columns
    assert "remote_device_id" in columns
    assert "conflict_type" in columns
    assert "local_updated_at" in columns
    assert "remote_updated_at" in columns
    assert "detected_at" in columns
    assert "resolved_at" in columns
    assert "resolution" in columns
    assert "metadata" in columns


@pytest.mark.unit
def test_migration_013_idempotent(db_conn):
    """Migration 013 can be applied multiple times without error."""
    sql = MIGRATION_FILE.read_text()
    db_conn.executescript(sql)
    db_conn.executescript(sql)  # Should not raise

    cursor = db_conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='backup_conflicts'"
    )
    assert cursor.fetchone() is not None


@pytest.mark.unit
def test_migration_013_can_insert_and_query(db_conn):
    """Can insert and query conflict records."""
    sql = MIGRATION_FILE.read_text()
    db_conn.executescript(sql)

    db_conn.execute(
        "INSERT INTO backup_conflicts "
        "(content_hash, conflict_type, detected_at, metadata) "
        "VALUES (?, ?, ?, ?)",
        ("abc123", "version_mismatch", "2026-08-10T00:00:00Z", '{"source": "test"}'),
    )
    db_conn.commit()

    cursor = db_conn.execute(
        "SELECT content_hash, conflict_type, resolved_at FROM backup_conflicts "
        "WHERE content_hash = ?",
        ("abc123",),
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "abc123"
    assert row[1] == "version_mismatch"
    assert row[2] is None  # unresolved
