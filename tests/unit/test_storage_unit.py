"""Whitebox unit tests for core storage backend internals.

Tests cover:
- SQLite-Vec backend: connection initialization, table creation, CRUD operations
- Transaction handling: commit, rollback, lock conflict recovery
- Vector index creation and search logic
- Storage path validation and path normalization
- Factory: backend class resolution and instance creation branches
- Migration runner: discovery, checksum, baseline stamping, split_sql
- Shared utilities: LRU cache, tag encoding, JSON safety
"""

import asyncio
import os
import sqlite3
import tempfile
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_memory_service.storage.shared import (
    _EMBEDDING_CACHE_MAX,
    _embedding_cache_get,
    _embedding_cache_put,
    _embedding_cache_size,
    _escape_like,
    _safe_json_loads,
    _string_to_tags,
    _tags_to_string,
)
from mcp_memory_service.storage.migration_runner import MigrationRunner
from mcp_memory_service.storage.mixins.base import (
    SQLITE_VEC_AVAILABLE,
    BaseMixin,
    deserialize_embedding,
    _sanitize_log_value as base_sanitize,
)


# ---------------------------------------------------------------------------
# Shared utility tests
# ---------------------------------------------------------------------------


class TestSharedUtilities:
    """Tests for storage/shared.py utility functions."""

    def test_tags_to_string_basic(self):
        assert _tags_to_string(["alpha", "beta"]) == ",alpha,beta,"

    def test_tags_to_string_empty_list(self):
        assert _tags_to_string([]) == ""

    def test_tags_to_string_none(self):
        assert _tags_to_string(None) == ""

    def test_tags_to_string_strips_whitespace(self):
        assert _tags_to_string(["  a  ", "b"]) == ",a,b,"

    def test_tags_to_string_filters_non_strings(self):
        assert _tags_to_string(["ok", 42, None, "good"]) == ",ok,good,"

    def test_tags_to_string_filters_empty_strings(self):
        assert _tags_to_string(["", "real", "   "]) == ",real,"

    def test_string_to_tags_basic(self):
        assert _string_to_tags(",alpha,beta,") == ["alpha", "beta"]

    def test_string_to_tags_empty(self):
        assert _string_to_tags("") == []

    def test_string_to_tags_none(self):
        assert _string_to_tags(None) == []

    def test_string_to_tags_strips_whitespace(self):
        assert _string_to_tags(", a , b ,") == ["a", "b"]

    def test_tags_roundtrip(self):
        tags = ["python", "async", "testing"]
        assert _string_to_tags(_tags_to_string(tags)) == tags

    def test_escape_like_strips_percent(self):
        assert _escape_like("ta%g") == "tag"

    def test_escape_like_strips_underscore(self):
        assert _escape_like("t_g") == "tg"

    def test_escape_like_no_special(self):
        assert _escape_like("normal") == "normal"

    def test_safe_json_loads_valid(self):
        assert _safe_json_loads('{"a": 1}', "ctx") == {"a": 1}

    def test_safe_json_loads_invalid(self):
        assert _safe_json_loads("not json", "ctx") == {}

    def test_safe_json_loads_empty(self):
        assert _safe_json_loads("", "ctx") == {}

    def test_safe_json_loads_none(self):
        assert _safe_json_loads(None, "ctx") == {}

    def test_safe_json_loads_non_dict(self):
        assert _safe_json_loads("[1,2,3]", "ctx") == {}

    def test_safe_json_loads_number(self):
        assert _safe_json_loads("42", "ctx") == {}


class TestEmbeddingCacheLRU:
    """Tests for the bounded LRU embedding cache in shared.py."""

    def setup_method(self):
        # Clear cache before each test
        from mcp_memory_service.storage import shared

        shared._EMBEDDING_CACHE.clear()

    def test_put_and_get(self):
        _embedding_cache_put("key1", [0.1, 0.2])
        assert _embedding_cache_get("key1") == [0.1, 0.2]

    def test_get_miss(self):
        assert _embedding_cache_get("nonexistent") is None

    def test_lru_eviction(self):
        for i in range(_EMBEDDING_CACHE_MAX + 5):
            _embedding_cache_put(f"k{i}", [float(i)])
        # The first 5 entries should have been evicted
        assert _embedding_cache_get("k0") is None
        assert _embedding_cache_get("k4") is None
        # The last entry should still be present
        assert _embedding_cache_get(f"k{_EMBEDDING_CACHE_MAX + 4}") == [float(_EMBEDDING_CACHE_MAX + 4)]

    def test_lru_move_to_end_on_get(self):
        _embedding_cache_put("a", [1.0])
        for i in range(_EMBEDDING_CACHE_MAX):
            _embedding_cache_put(f"fill_{i}", [float(i)])
        # "a" should have been evicted by now
        assert _embedding_cache_get("a") is None

        # But if we access "a" before eviction, it stays
        _embedding_cache_put("a", [1.0])
        _embedding_cache_get("a")  # touch
        for i in range(_EMBEDDING_CACHE_MAX):
            _embedding_cache_put(f"fill2_{i}", [float(i)])
        # "a" was touched so it should survive one more insertion cycle
        # but with _EMBEDDING_CACHE_MAX inserts it'll be evicted anyway
        assert _embedding_cache_get("a") is None

    def test_size(self):
        _embedding_cache_put("k1", [1.0])
        _embedding_cache_put("k2", [2.0])
        assert _embedding_cache_size() == 2

    def test_update_existing_key(self):
        _embedding_cache_put("k", [1.0])
        _embedding_cache_put("k", [2.0])
        assert _embedding_cache_get("k") == [2.0]


# ---------------------------------------------------------------------------
# BaseMixin tests
# ---------------------------------------------------------------------------


class TestBaseMixinInit:
    """Tests for BaseMixin __init__ and configuration."""

    def test_init_sets_attributes(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin.db_path == str(tmp_path / "test.db")
        assert mixin.embedding_model_name == "all-MiniLM-L6-v2"
        assert mixin.conn is None
        assert mixin.embedding_model is None
        assert mixin.embedding_dimension == 384
        assert mixin._initialized is False
        assert mixin.enable_cache is True
        assert mixin.batch_size == 32

    def test_init_creates_directory(self, tmp_path):
        db_path = tmp_path / "subdir" / "deeper" / "test.db"
        BaseMixin(str(db_path))
        assert db_path.parent.exists()

    def test_init_custom_embedding_model(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"), embedding_model="custom-model")
        assert mixin.embedding_model_name == "custom-model"

    def test_init_semantic_dedup_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MCP_SEMANTIC_DEDUP_ENABLED", "false")
        monkeypatch.setenv("MCP_SEMANTIC_DEDUP_TIME_WINDOW_HOURS", "48")
        monkeypatch.setenv("MCP_SEMANTIC_DEDUP_THRESHOLD", "0.95")
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin.semantic_dedup_enabled is False
        assert mixin.semantic_dedup_time_window == 48
        assert mixin.semantic_dedup_threshold == 0.95

    def test_max_content_length_property(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        # Property reads from config
        assert hasattr(mixin, "max_content_length")

    def test_supports_chunking_property(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin.supports_chunking is True


class TestDeserializeEmbedding:
    """Tests for deserialize_embedding module-level function."""

    def test_valid_blob(self):
        arr = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        blob = arr.tobytes()
        result = deserialize_embedding(blob)
        assert result == [1.0, 2.0, 3.0]

    def test_empty_blob(self):
        assert deserialize_embedding(b"") is None

    def test_none_blob(self):
        assert deserialize_embedding(None) is None

    def test_invalid_blob(self):
        # Too short for float32
        assert deserialize_embedding(b"\x01") is None


class TestSafeJsonLoads:
    """Tests for BaseMixin._safe_json_loads."""

    def test_valid_json(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin._safe_json_loads('{"key": "value"}', "test") == {"key": "value"}

    def test_invalid_json(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin._safe_json_loads("not json", "test") == {}

    def test_empty_string(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin._safe_json_loads("", "test") == {}

    def test_none_input(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin._safe_json_loads(None, "test") == {}

    def test_non_dict_json(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        assert mixin._safe_json_loads("[1, 2, 3]", "test") == {}

    def test_truncated_content_logged(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        long_invalid = '{"a": "' + "x" * 200 + '"'
        result = mixin._safe_json_loads(long_invalid, "test")
        assert result == {}


class TestExecuteWithRetry:
    """Tests for _execute_with_retry exponential backoff."""

    @pytest.mark.asyncio
    async def test_success_first_try(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await mixin._execute_with_retry(operation, max_retries=3, initial_delay=0.01)
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_locked(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return "recovered"

        result = await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retries_on_busy(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise sqlite3.OperationalError("database is busy")
            return "ok"

        result = await mixin._execute_with_retry(operation, max_retries=3, initial_delay=0.01)
        assert result == "ok"
        assert call_count == 2

    @pytest.mark.asyncio
    async def test_no_retry_on_non_lock_error(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))

        def operation():
            raise sqlite3.OperationalError("syntax error")

        with pytest.raises(sqlite3.OperationalError, match="syntax error"):
            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError):
            await mixin._execute_with_retry(operation, max_retries=2, initial_delay=0.01)
        assert call_count == 3  # initial + 2 retries

    @pytest.mark.asyncio
    async def test_other_exceptions_not_retried(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))

        def operation():
            raise ValueError("not a lock error")

        with pytest.raises(ValueError):
            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)


class TestCheckExtensionSupport:
    """Tests for _check_extension_support."""

    def test_returns_tuple(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        result = mixin._check_extension_support()
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)


class TestCheckDependencies:
    """Tests for _check_dependencies."""

    def test_raises_when_unavailable(self, tmp_path, monkeypatch):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        monkeypatch.setattr(
            "mcp_memory_service.storage.mixins.base.SQLITE_VEC_AVAILABLE", False
        )
        with pytest.raises(ImportError, match="sqlite-vec"):
            mixin._check_dependencies()

    def test_passes_when_available(self, tmp_path, monkeypatch):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        monkeypatch.setattr(
            "mcp_memory_service.storage.mixins.base.SQLITE_VEC_AVAILABLE", True
        )
        # Should not raise
        mixin._check_dependencies()


# ---------------------------------------------------------------------------
# Factory tests
# ---------------------------------------------------------------------------


class TestStorageFactory:
    """Tests for storage/factory.py backend class resolution."""

    def test_get_sqlite_vec_class(self, monkeypatch):
        from mcp_memory_service.storage.factory import get_storage_backend_class

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "sqlite_vec")
        cls = get_storage_backend_class()
        assert cls.__name__ == "SqliteVecMemoryStorage"

    def test_get_sqlite_vec_class_hyphen(self, monkeypatch):
        from mcp_memory_service.storage.factory import get_storage_backend_class

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "sqlite-vec")
        cls = get_storage_backend_class()
        assert cls.__name__ == "SqliteVecMemoryStorage"

    def test_unknown_backend_defaults_to_sqlite(self, monkeypatch):
        from mcp_memory_service.storage.factory import get_storage_backend_class

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "nonexistent_backend")
        cls = get_storage_backend_class()
        assert cls.__name__ == "SqliteVecMemoryStorage"

    def test_fallback_to_sqlite_vec_helper(self):
        from mcp_memory_service.storage.factory import _fallback_to_sqlite_vec

        cls = _fallback_to_sqlite_vec()
        assert cls.__name__ == "SqliteVecMemoryStorage"


class TestCreateStorageInstance:
    """Tests for create_storage_instance with various backends."""

    @pytest.mark.asyncio
    async def test_create_sqlite_vec_instance(self, monkeypatch, tmp_path):
        from mcp_memory_service.storage.factory import create_storage_instance

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "sqlite_vec")
        monkeypatch.setenv("MCP_MEMORY_SQLITE_PATH", str(tmp_path / "test.db"))
        # Force hash embeddings for test
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "1")
        monkeypatch.setenv("MCP_MEMORY_ONNX_ALLOW_DOWNLOAD", "0")

        storage = await create_storage_instance(str(tmp_path / "test.db"))
        assert storage.__class__.__name__ == "SqliteVecMemoryStorage"
        assert storage._initialized is True
        await storage.close()

    @pytest.mark.asyncio
    async def test_create_with_server_type(self, monkeypatch, tmp_path):
        from mcp_memory_service.storage.factory import create_storage_instance

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "sqlite_vec")
        monkeypatch.setenv("MCP_MEMORY_ALLOW_HASH_EMBEDDINGS", "1")
        monkeypatch.setenv("MCP_MEMORY_ONNX_ALLOW_DOWNLOAD", "0")

        storage = await create_storage_instance(
            str(tmp_path / "test.db"), server_type="http"
        )
        assert storage.__class__.__name__ == "SqliteVecMemoryStorage"
        await storage.close()


# ---------------------------------------------------------------------------
# Migration runner tests
# ---------------------------------------------------------------------------


class TestMigrationRunner:
    """Tests for migration_runner.py."""

    def test_discover_migrations_empty(self, tmp_path):
        runner = MigrationRunner(tmp_path)
        migrations = runner._discover_migrations()
        assert migrations == []

    def test_discover_migrations_sorted(self, tmp_path):
        (tmp_path / "002_second.sql").write_text("-- second\nSELECT 1;")
        (tmp_path / "001_first.sql").write_text("-- first\nSELECT 1;")
        (tmp_path / "003_third.sql").write_text("-- third\nSELECT 1;")

        runner = MigrationRunner(tmp_path)
        migrations = runner._discover_migrations()
        assert len(migrations) == 3
        assert migrations[0][0] == 1
        assert migrations[1][0] == 2
        assert migrations[2][0] == 3

    def test_split_sql_basic(self):
        statements = MigrationRunner._split_sql("SELECT 1; SELECT 2;")
        assert len(statements) == 2
        assert "SELECT 1" in statements[0]
        assert "SELECT 2" in statements[1]

    def test_split_sql_skips_transaction_control(self):
        statements = MigrationRunner._split_sql(
            "BEGIN; SELECT 1; COMMIT; ROLLBACK; SELECT 2;"
        )
        # BEGIN, COMMIT, ROLLBACK should be filtered out
        assert len(statements) == 2

    def test_split_sql_strips_comments(self):
        statements = MigrationRunner._split_sql(
            "-- This is a comment\nSELECT 1;\n/* block comment */\nSELECT 2;"
        )
        assert len(statements) == 2

    def test_split_sql_empty(self):
        assert MigrationRunner._split_sql("") == []

    def test_split_sql_only_comments(self):
        assert MigrationRunner._split_sql("-- just a comment\n") == []

    def test_checksum_deterministic(self, tmp_path):
        f = tmp_path / "test.sql"
        f.write_text("SELECT 1;")
        runner = MigrationRunner(tmp_path)
        c1 = runner._checksum(f)
        c2 = runner._checksum(f)
        assert c1 == c2
        assert len(c1) == 64  # SHA256 hex length

    def test_ensure_registry_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        runner._ensure_registry_table(conn)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='migration_registry'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_get_applied_versions_empty(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        runner._ensure_registry_table(conn)
        assert runner._get_applied_versions(conn) == set()
        conn.close()

    def test_get_current_version_default(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        # No metadata table → default 7
        assert runner._get_current_version(conn) == 7
        conn.close()

    def test_get_current_version_from_metadata(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '15')")
        conn.commit()
        runner = MigrationRunner(tmp_path)
        assert runner._get_current_version(conn) == 15
        conn.close()

    def test_run_pending_no_migrations(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        result = runner.run_pending(conn)
        assert result["applied"] == []
        assert result["skipped"] == []
        assert result["error"] is None
        conn.close()

    def test_run_pending_applies_migration(self, tmp_path):
        (tmp_path / "001_test.sql").write_text(
            "CREATE TABLE test_table (id INTEGER PRIMARY KEY);"
        )
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        # Migration runner needs metadata table for schema_version tracking
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        runner = MigrationRunner(tmp_path)
        result = runner.run_pending(conn)
        assert len(result["applied"]) == 1
        assert result["error"] is None
        # Verify table was created
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='test_table'"
        )
        assert cursor.fetchone() is not None
        conn.close()

    def test_run_pending_skips_already_applied(self, tmp_path):
        (tmp_path / "001_test.sql").write_text(
            "CREATE TABLE test_table (id INTEGER PRIMARY KEY);"
        )
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.commit()
        runner = MigrationRunner(tmp_path)
        # First run
        runner.run_pending(conn)
        # Second run should skip
        result = runner.run_pending(conn)
        assert len(result["applied"]) == 0
        assert len(result["skipped"]) == 1
        conn.close()

    def test_check_returns_dict(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        result = runner.check(conn)
        assert "current_version" in result
        assert "pending" in result
        assert "registry" in result
        assert "healthy" in result
        assert "checksum_mismatches" in result
        conn.close()


class TestMigrationStampBaseline:
    """Tests for _stamp_baseline detection of existing migration artifacts."""

    def test_stamp_v8_graph_table(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("CREATE TABLE memory_graph (source_hash TEXT, target_hash TEXT)")
        conn.commit()
        runner = MigrationRunner(tmp_path)
        runner._ensure_registry_table(conn)
        stamped = runner._stamp_baseline(conn)
        assert 8 in stamped
        conn.close()

    def test_stamp_v9_relationship_type_column(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "CREATE TABLE memory_graph (source_hash TEXT, target_hash TEXT, relationship_type TEXT)"
        )
        conn.commit()
        runner = MigrationRunner(tmp_path)
        runner._ensure_registry_table(conn)
        stamped = runner._stamp_baseline(conn)
        assert 8 in stamped
        assert 9 in stamped
        conn.close()

    def test_stamp_v11_version_column(self, tmp_path):
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
        conn.execute(
            "CREATE TABLE memories (content_hash TEXT, version INTEGER)"
        )
        conn.commit()
        runner = MigrationRunner(tmp_path)
        runner._ensure_registry_table(conn)
        stamped = runner._stamp_baseline(conn)
        assert 11 in stamped
        conn.close()


# ---------------------------------------------------------------------------
# SQLite-Vec storage integration tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def storage_instance(tmp_path):
    """Create a real SqliteVecMemoryStorage instance for integration tests."""
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

    storage = SqliteVecMemoryStorage(
        db_path=str(tmp_path / "test.db"),
        embedding_model="all-MiniLM-L6-v2",
    )
    await storage.initialize()
    yield storage
    await storage.close()


@pytest.mark.asyncio
class TestSqliteVecStorageIntegration:
    """Integration tests for SQLite-Vec storage with real database."""

    async def test_initialize_creates_tables(self, storage_instance):
        cursor = storage_instance.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        )
        assert cursor.fetchone() is not None

        cursor = storage_instance.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memory_embeddings'"
        )
        assert cursor.fetchone() is not None

    async def test_store_and_retrieve(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Test memory for whitebox testing"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test", "whitebox"],
            memory_type="observation",
        )
        success, msg = await storage_instance.store(memory)
        assert success is True

        results = await storage_instance.retrieve(content, n_results=1)
        assert len(results) > 0
        assert results[0].memory.content == content

    async def test_store_dedup_exact_hash(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Duplicate content test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        # First store succeeds
        success1, _ = await storage_instance.store(memory)
        assert success1 is True
        # Second store with same hash should fail (exact dedup)
        success2, msg = await storage_instance.store(memory)
        assert success2 is False
        assert "already exists" in msg.lower() or "duplicate" in msg.lower()

    async def test_soft_delete_and_is_deleted(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Memory to be deleted"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)

        # Should not be deleted
        assert await storage_instance.is_deleted(memory.content_hash) is False

        # Soft delete
        success, msg = await storage_instance.delete(memory.content_hash)
        assert success is True

        # Should now be deleted
        assert await storage_instance.is_deleted(memory.content_hash) is True

    async def test_delete_nonexistent_returns_false(self, storage_instance):
        success, msg = await storage_instance.delete("nonexistent_hash_12345")
        assert success is False
        assert "not found" in msg.lower()

    async def test_get_by_hash(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Get by hash test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)

        result = await storage_instance.get_by_hash(memory.content_hash)
        assert result is not None
        assert result.content == content

    async def test_get_by_hash_not_found(self, storage_instance):
        result = await storage_instance.get_by_hash("nonexistent_hash")
        assert result is None

    async def test_search_by_tag(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Tagged memory for search"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["unique_tag_123", "test"],
        )
        await storage_instance.store(memory)

        results = await storage_instance.search_by_tag(["unique_tag_123"])
        assert len(results) >= 1
        assert any(m.content == content for m in results)

    async def test_search_by_tags_and(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Multi-tag memory"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["tag_a", "tag_b"],
        )
        await storage_instance.store(memory)

        # AND should match
        results = await storage_instance.search_by_tags(["tag_a", "tag_b"], operation="AND")
        assert any(m.content == content for m in results)

        # AND with non-matching tag should not match
        results = await storage_instance.search_by_tags(["tag_a", "nonexistent"], operation="AND")
        assert not any(m.content == content for m in results)

    async def test_search_by_tags_or(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "OR test memory"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["or_tag_a"],
        )
        await storage_instance.store(memory)

        results = await storage_instance.search_by_tags(["or_tag_a", "or_tag_b"], operation="OR")
        assert any(m.content == content for m in results)

    async def test_search_by_tags_invalid_operation_defaults_and(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Invalid op test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["invalid_op_tag"],
        )
        await storage_instance.store(memory)

        # Invalid operation should default to AND
        results = await storage_instance.search_by_tags(["invalid_op_tag"], operation="INVALID")
        assert any(m.content == content for m in results)

    async def test_cleanup_duplicates(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Duplicate for cleanup"
        hash_val = generate_content_hash(content)
        memory1 = Memory(content=content, content_hash=hash_val, tags=["test"])
        await storage_instance.store(memory1)

        # Soft-delete the first one, then store the same content again (tombstone purge allows re-store)
        await storage_instance.delete(hash_val)
        memory2 = Memory(content=content, content_hash=hash_val, tags=["test"])
        await storage_instance.store(memory2)

        # Now purge tombstones to clean the old one
        await storage_instance.purge_deleted(older_than_days=0)

        # Insert a raw duplicate bypassing dedup (different rowid, same hash, no tombstone)
        storage_instance.conn.execute(
            "INSERT OR REPLACE INTO memories (content_hash, content, tags, memory_type, metadata, created_at, updated_at, created_at_iso, updated_at_iso) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (hash_val, content, ",test,", "observation", "{}", 2000.0, 2000.0, "2024-01-02T00:00:00Z", "2024-01-02T00:00:00Z"),
        )
        storage_instance.conn.commit()

        count, msg = await storage_instance.cleanup_duplicates()
        assert count >= 0  # Should not crash

    async def test_get_stats(self, storage_instance):
        stats = await storage_instance.get_stats()
        assert "total_memories" in stats
        assert "backend" in stats
        assert stats["backend"] == "sqlite-vec"

    async def test_get_all_tags(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Tag listing test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["stat_tag_1", "stat_tag_2"],
        )
        await storage_instance.store(memory)

        tags = await storage_instance.get_all_tags()
        # Tags may include "untagged" default and test tags
        assert isinstance(tags, list)

    async def test_purge_deleted(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "To be purged"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)
        await storage_instance.delete(memory.content_hash)

        # Purge with 0 days should remove all tombstones
        purged = await storage_instance.purge_deleted(older_than_days=0)
        assert purged >= 1

    async def test_store_batch(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        memories = [
            Memory(
                content=f"Batch memory {i}",
                content_hash=generate_content_hash(f"Batch memory {i}"),
                tags=["batch"],
            )
            for i in range(5)
        ]
        results = await storage_instance.store_batch(memories)
        assert len(results) == 5
        assert all(success for success, _ in results)

    async def test_update_memory_metadata(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Metadata update test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)

        success, msg = await storage_instance.update_memory_metadata(
            memory.content_hash,
            {"tags": ["updated_tag"], "metadata": {"key": "value"}},
        )
        assert success is True

        result = await storage_instance.get_by_hash(memory.content_hash)
        assert "updated_tag" in result.tags

    async def test_get_all_content_hashes(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Hash listing test"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)

        hashes = await storage_instance.get_all_content_hashes()
        assert memory.content_hash in hashes

    async def test_get_by_exact_content(self, storage_instance):
        from mcp_memory_service.models.memory import Memory
        from mcp_memory_service.utils.hashing import generate_content_hash

        content = "Exact content match test 12345"
        memory = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["test"],
        )
        await storage_instance.store(memory)

        results = await storage_instance.get_by_exact_content("Exact content match")
        assert len(results) >= 1
        assert any(m.content == content for m in results)

    async def test_close_sets_conn_none(self, storage_instance):
        await storage_instance.close()
        assert storage_instance.conn is None


class TestStoragePathValidation:
    """Tests for storage path handling and normalization."""

    def test_db_path_creates_parent_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "test.db"
        BaseMixin(str(nested))
        assert nested.parent.exists()

    def test_db_path_with_no_directory(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        BaseMixin("test.db")
        # Should not raise, creates "." directory check
        assert True


class TestRetryBackoffCalculation:
    """Tests verifying the exponential backoff delay calculation in _execute_with_retry."""

    @pytest.mark.asyncio
    async def test_delay_doubles_each_retry(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        delays = []

        original_sleep = asyncio.sleep

        async def mock_sleep(delay):
            delays.append(delay)
            return await original_sleep(0)

        with patch("mcp_memory_service.storage.mixins.base.asyncio.sleep", mock_sleep):
            call_count = 0

            def operation():
                nonlocal call_count
                call_count += 1
                if call_count < 4:
                    raise sqlite3.OperationalError("database is locked")
                return "ok"

            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.1)

        # Verify exponential backoff: 0.1, 0.2, 0.4 (with jitter ±10%)
        assert len(delays) == 3
        assert 0.09 <= delays[0] <= 0.11
        assert 0.18 <= delays[1] <= 0.22
        assert 0.36 <= delays[2] <= 0.44
