"""Whitebox unit tests for error handling and boundary paths.

Tests cover:
- Database locked/corrupted recovery (retry logic)
- Invalid input handling (None, empty strings, oversized content, illegal Unicode)
- Concurrent write conflict handling
- Connection management edge cases
- Embedding validation errors (NaN, inf, dimension mismatch)
- JSON deserialization edge cases
- SQLite constraint violations
- Path validation edge cases
"""

import asyncio
import sqlite3
import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from mcp_memory_service.compat import _sanitize_log_value
from mcp_memory_service.models.memory import Memory
from mcp_memory_service.storage.mixins.base import BaseMixin, deserialize_embedding
from mcp_memory_service.storage.mixins.embeddings import (
    _EMBEDDING_CACHE,
    _MODEL_CACHE,
)
from mcp_memory_service.storage.shared import (
    _safe_json_loads,
    _string_to_tags,
    _tags_to_string,
)
from mcp_memory_service.utils.hashing import generate_content_hash

# ---------------------------------------------------------------------------
# Database locked / busy recovery
# ---------------------------------------------------------------------------


class TestDatabaseLockRecovery:
    """Tests for database lock and busy error recovery."""

    @pytest.mark.asyncio
    async def test_retry_on_database_locked(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise sqlite3.OperationalError("database is locked")
            return "success"

        result = await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_database_busy(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise sqlite3.OperationalError("database is busy")
            return "recovered"

        result = await mixin._execute_with_retry(operation, max_retries=3, initial_delay=0.01)
        assert result == "recovered"

    @pytest.mark.asyncio
    async def test_no_retry_on_syntax_error(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))

        def operation():
            raise sqlite3.OperationalError("near 'SELCT': syntax error")

        with pytest.raises(sqlite3.OperationalError, match="syntax error"):
            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)

    @pytest.mark.asyncio
    async def test_no_retry_on_constraint_error(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))

        def operation():
            raise sqlite3.IntegrityError("UNIQUE constraint failed")

        with pytest.raises(sqlite3.IntegrityError):
            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)

    @pytest.mark.asyncio
    async def test_max_retries_exhausted(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        call_count = 0

        def operation():
            nonlocal call_count
            call_count += 1
            raise sqlite3.OperationalError("database is locked")

        with pytest.raises(sqlite3.OperationalError, match="locked"):
            await mixin._execute_with_retry(operation, max_retries=3, initial_delay=0.01)
        assert call_count == 4  # initial + 3 retries

    @pytest.mark.asyncio
    async def test_generic_exception_not_retried(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))

        def operation():
            raise RuntimeError("unexpected error")

        with pytest.raises(RuntimeError):
            await mixin._execute_with_retry(operation, max_retries=5, initial_delay=0.01)


# ---------------------------------------------------------------------------
# Invalid input handling
# ---------------------------------------------------------------------------


class TestInvalidInputHandling:
    """Tests for handling invalid inputs to various functions."""

    def test_generate_content_hash_none_raises(self):
        with pytest.raises(AttributeError):
            generate_content_hash(None)

    def test_generate_content_hash_integer_raises(self):
        with pytest.raises(AttributeError):
            generate_content_hash(42)

    def test_tags_to_string_with_non_string_items(self):
        result = _tags_to_string(["valid", 42, None, "also_valid"])
        assert "valid" in result
        assert "also_valid" in result
        assert "42" not in result  # Non-strings filtered out

    def test_string_to_tags_with_garbage(self):
        result = _string_to_tags(",,, ,  ,")
        assert result == []

    def test_safe_json_loads_with_bytes(self):
        result = _safe_json_loads(b'{"key": "value"}', "test")
        # bytes input may or may not work depending on json.loads version
        # but should not raise
        assert isinstance(result, dict)

    def test_safe_json_loads_with_very_long_string(self):
        long_str = "{" + "x" * 10000 + "}"
        result = _safe_json_loads(long_str, "test")
        assert result == {}

    def test_sanitize_log_value_with_complex_object(self):
        class CustomObj:
            def __str__(self):
                return "custom\nobject"

        result = _sanitize_log_value(CustomObj())
        assert "\\n" in result
        assert "\n" not in result

    def test_deserialize_embedding_corrupt_data(self):
        result = deserialize_embedding(b"\xff\xfe\xfd\xfc")
        # Should not crash, returns None or list
        # 4 bytes = 1 float32, so this might work
        assert result is None or isinstance(result, list)

    def test_deserialize_embedding_truncated(self):
        result = deserialize_embedding(b"\x01\x02")
        # 2 bytes is too short for float32
        assert result is None


# ---------------------------------------------------------------------------
# Embedding validation errors
# ---------------------------------------------------------------------------


class TestEmbeddingValidationErrors:
    """Tests for embedding generation validation."""

    def setup_method(self):
        _EMBEDDING_CACHE.clear()
        _MODEL_CACHE.clear()

    def _create_mixin(self, tmp_path):
        from mcp_memory_service.storage.mixins.base import BaseMixin
        from mcp_memory_service.storage.mixins.embeddings import EmbeddingsMixin

        class TestStorage(BaseMixin, EmbeddingsMixin):
            pass

        mixin = TestStorage(str(tmp_path / "test.db"))
        return mixin

    def test_dimension_mismatch_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[0.1, 0.2]])  # 2 dims
        mixin.embedding_dimension = 384
        mixin.enable_cache = False

        with pytest.raises((ValueError, RuntimeError), match="dimension"):
            mixin._generate_embedding("test")

    def test_nan_embedding_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[float("nan")] * 384])
        mixin.embedding_dimension = 384
        mixin.enable_cache = False

        with pytest.raises((ValueError, RuntimeError)):
            mixin._generate_embedding("test")

    def test_inf_embedding_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[float("inf")] * 384])
        mixin.embedding_dimension = 384
        mixin.enable_cache = False

        with pytest.raises((ValueError, RuntimeError)):
            mixin._generate_embedding("test")

    def test_negative_inf_embedding_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[float("-inf")] * 384])
        mixin.embedding_dimension = 384
        mixin.enable_cache = False

        with pytest.raises((ValueError, RuntimeError)):
            mixin._generate_embedding("test")

    def test_empty_embedding_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = MagicMock()
        mixin.embedding_model.encode.return_value = np.array([[]])
        mixin.embedding_dimension = 384
        mixin.enable_cache = False

        with pytest.raises((ValueError, RuntimeError)):
            mixin._generate_embedding("test")

    def test_no_model_raises(self, tmp_path):
        mixin = self._create_mixin(tmp_path)
        mixin.embedding_model = None

        with pytest.raises(RuntimeError, match="No embedding model"):
            mixin._generate_embedding("test")


# ---------------------------------------------------------------------------
# Concurrent write conflict handling
# ---------------------------------------------------------------------------


@pytest.fixture
async def storage(tmp_path):
    """Create a real storage instance."""
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

    s = SqliteVecMemoryStorage(
        db_path=str(tmp_path / "concurrent.db"),
        embedding_model="all-MiniLM-L6-v2",
    )
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestConcurrentWriteConflicts:
    """Tests for concurrent write conflict handling."""

    async def test_concurrent_stores_different_content(self, storage):
        """Multiple stores with different content should all succeed."""
        memories = [
            Memory(
                content=f"Concurrent memory {i}",
                content_hash=generate_content_hash(f"Concurrent memory {i}"),
                tags=["concurrent"],
            )
            for i in range(10)
        ]
        results = await asyncio.gather(
            *(storage.store(m) for m in memories)
        )
        assert all(success for success, _ in results)

    async def test_concurrent_stores_same_content_dedup(self, storage):
        """Multiple stores with same content should dedup."""
        mem = Memory(
            content="Same concurrent content",
            content_hash=generate_content_hash("Same concurrent content"),
            tags=["concurrent"],
        )
        results = await asyncio.gather(
            storage.store(mem),
            storage.store(mem),
            storage.store(mem),
        )
        # At least one should succeed
        successes = [s for s, _ in results if s]
        assert len(successes) >= 1

    async def test_concurrent_store_and_delete(self, storage):
        """Store and delete happening concurrently."""
        mem = Memory(
            content="Store and delete concurrent",
            content_hash=generate_content_hash("Store and delete concurrent"),
            tags=["concurrent"],
        )
        await storage.store(mem)

        # Delete while storing new
        results = await asyncio.gather(
            storage.delete(mem.content_hash),
            storage.store(Memory(
                content="New concurrent memory",
                content_hash=generate_content_hash("New concurrent memory"),
                tags=["concurrent"],
            )),
        )
        # Both should complete without error
        assert isinstance(results[0][0], bool)
        assert isinstance(results[1][0], bool)


# ---------------------------------------------------------------------------
# SQLite constraint violations
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestSQLiteConstraintViolations:
    """Tests for SQLite constraint violation handling."""

    async def test_store_duplicate_hash_handled(self, storage):
        mem = Memory(
            content="Constraint test",
            content_hash=generate_content_hash("Constraint test"),
            tags=["constraint"],
        )
        success1, _ = await storage.store(mem)
        assert success1

        # Second store should return False, not raise
        success2, _msg = await storage.store(mem)
        assert success2 is False

    async def test_store_batch_with_duplicate(self, storage):
        """Batch store with duplicate should handle gracefully."""
        content = "Batch dup content"
        hash_val = generate_content_hash(content)
        mem1 = Memory(content=content, content_hash=hash_val, tags=["batch"])
        mem2 = Memory(content=content, content_hash=hash_val, tags=["batch"])

        results = await storage.store_batch([mem1, mem2])
        assert len(results) == 2
        assert results[0][0] is True
        # Second should fail due to dedup
        assert results[1][0] is False


# ---------------------------------------------------------------------------
# Connection management edge cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestConnectionEdgeCases:
    """Tests for connection management boundary conditions."""

    async def test_close_twice(self, tmp_path):
        from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

        storage = SqliteVecMemoryStorage(
            db_path=str(tmp_path / "double_close.db"),
        )
        await storage.initialize()
        await storage.close()
        # Second close should not raise
        await storage.close()

    async def test_initialize_twice(self, tmp_path):
        from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

        storage = SqliteVecMemoryStorage(
            db_path=str(tmp_path / "init_twice.db"),
        )
        await storage.initialize()
        # Second init should be no-op
        await storage.initialize()
        await storage.close()

    async def test_operations_after_close(self, tmp_path):
        from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

        storage = SqliteVecMemoryStorage(
            db_path=str(tmp_path / "after_close.db"),
        )
        await storage.initialize()
        await storage.close()

        # Operations after close should handle gracefully
        mem = Memory(content="test", content_hash="abc")
        success, _msg = await storage.store(mem)
        assert success is False


# ---------------------------------------------------------------------------
# Oversized content handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestOversizedContent:
    """Tests for handling oversized content."""

    async def test_store_large_content(self, storage):
        """Large but valid content should be storable."""
        large_content = "x" * 10000
        mem = Memory(
            content=large_content,
            content_hash=generate_content_hash(large_content),
            tags=["large"],
        )
        success, _ = await storage.store(mem)
        assert success is True

    async def test_store_very_large_content(self, storage):
        """Very large content should be handled."""
        very_large = "y" * 100000
        mem = Memory(
            content=very_large,
            content_hash=generate_content_hash(very_large),
            tags=["very_large"],
        )
        # Should not crash
        success, _ = await storage.store(mem)
        assert isinstance(success, bool)

    async def test_retrieve_large_content(self, storage):
        large_content = "z" * 50000
        mem = Memory(
            content=large_content,
            content_hash=generate_content_hash(large_content),
            tags=["large_retrieve"],
        )
        await storage.store(mem)

        result = await storage.get_by_hash(mem.content_hash)
        assert result is not None
        assert len(result.content) == 50000


# ---------------------------------------------------------------------------
# Unicode and special character handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestUnicodeHandling:
    """Tests for Unicode and special character handling."""

    async def test_store_unicode_content(self, storage):
        content = "Hello 世界 🌍 café ☕ 日本語"
        mem = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["unicode"],
        )
        success, _ = await storage.store(mem)
        assert success is True

        result = await storage.get_by_hash(mem.content_hash)
        assert result is not None
        assert result.content == content

    async def test_store_emoji_tags(self, storage):
        content = "Emoji tags test"
        mem = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["🚀", "test"],
        )
        success, _ = await storage.store(mem)
        assert success is True

    async def test_store_null_bytes_in_content(self, storage):
        # Null bytes should be handled (SQLite handles them)
        content = "Before\x00After"
        mem = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["null_test"],
        )
        success, _ = await storage.store(mem)
        assert success is True

    async def test_store_control_chars_in_tags(self, storage):
        content = "Control char tags"
        mem = Memory(
            content=content,
            content_hash=generate_content_hash(content),
            tags=["tag\nwith\nnewlines", "tab\there"],
        )
        success, _ = await storage.store(mem)
        assert success is True


# ---------------------------------------------------------------------------
# Memory model boundary tests
# ---------------------------------------------------------------------------


class TestMemoryBoundaryConditions:
    """Tests for Memory model with boundary inputs."""

    def test_empty_content(self):
        mem = Memory(content="", content_hash="")
        assert mem.content == ""
        assert mem.tags == ["untagged"]

    def test_very_long_content(self):
        long_content = "x" * 100000
        mem = Memory(content=long_content, content_hash="hash")
        assert mem.content == long_content

    def test_special_chars_in_content(self):
        content = "Special: \x00\x01\x02 chars"
        mem = Memory(content=content, content_hash="hash")
        assert mem.content == content

    def test_empty_tags_list(self):
        mem = Memory(content="test", content_hash="hash", tags=[])
        assert mem.tags == ["untagged"]

    def test_none_tags(self):
        mem = Memory(content="test", content_hash="hash")
        # tags field defaults to factory list
        assert mem.tags == ["untagged"]

    def test_large_metadata(self):
        large_metadata = {f"key_{i}": f"value_{i}" for i in range(100)}
        mem = Memory(content="test", content_hash="hash", metadata=large_metadata)
        assert len(mem.metadata) == 100

    def test_nested_metadata(self):
        nested = {"level1": {"level2": {"level3": "deep"}}}
        mem = Memory(content="test", content_hash="hash", metadata=nested)
        assert mem.metadata["level1"]["level2"]["level3"] == "deep"

    def test_to_dict_with_none_memory_type(self):
        mem = Memory(content="test", content_hash="hash", memory_type=None)
        d = mem.to_dict()
        assert d["type"] is None

    def test_from_dict_missing_content_hash(self):
        data = {"content": "test"}
        # from_dict accesses data["content_hash"] directly, so missing key raises KeyError
        with pytest.raises(KeyError):
            Memory.from_dict(data)

    def test_from_dict_empty_dict(self):
        # from_dict accesses data["content"] directly, so empty dict raises KeyError
        with pytest.raises(KeyError):
            Memory.from_dict({})

    def test_credibility_boundary_zero(self):
        mem = Memory(content="test", content_hash="hash")
        mem.credibility = 0.0
        assert mem.credibility == 0.0

    def test_credibility_boundary_one(self):
        mem = Memory(content="test", content_hash="hash")
        mem.credibility = 1.0
        assert mem.credibility == 1.0


# ---------------------------------------------------------------------------
# JSON deserialization edge cases
# ---------------------------------------------------------------------------


class TestJSONEdgeCases:
    """Tests for JSON deserialization edge cases."""

    def test_safe_json_loads_nested_dict(self):
        result = _safe_json_loads('{"a": {"b": {"c": [1, 2, 3]}}}', "test")
        assert result["a"]["b"]["c"] == [1, 2, 3]

    def test_safe_json_loads_null_value(self):
        result = _safe_json_loads("null", "test")
        assert result == {}

    def test_safe_json_loads_boolean(self):
        result = _safe_json_loads("true", "test")
        assert result == {}

    def test_safe_json_loads_number(self):
        result = _safe_json_loads("42", "test")
        assert result == {}

    def test_safe_json_loads_string(self):
        result = _safe_json_loads('"hello"', "test")
        assert result == {}

    def test_safe_json_loads_array(self):
        result = _safe_json_loads('[1, 2, 3]', "test")
        assert result == {}

    def test_safe_json_loads_with_bom(self):
        result = _safe_json_loads('\xef\xbb\xbf{"key": "value"}', "test")
        # BOM may cause parse failure
        assert isinstance(result, dict)

    def test_safe_json_loads_with_trailing_comma(self):
        result = _safe_json_loads('{"key": "value",}', "test")
        assert result == {}

    def test_base_mixin_safe_json_loads_truncated(self, tmp_path):
        mixin = BaseMixin(str(tmp_path / "test.db"))
        long_text = '{"a": "' + "x" * 200 + '"'
        result = mixin._safe_json_loads(long_text, "test")
        assert result == {}


# ---------------------------------------------------------------------------
# Migration runner error paths
# ---------------------------------------------------------------------------


class TestMigrationErrorPaths:
    """Tests for migration runner error handling."""

    def test_run_pending_with_invalid_sql(self, tmp_path):
        from mcp_memory_service.storage.migration_runner import MigrationRunner

        (tmp_path / "001_bad.sql").write_text("THIS IS NOT VALID SQL;")
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        result = runner.run_pending(conn)
        assert result["error"] is not None
        conn.close()

    def test_run_pending_rolls_back_on_error(self, tmp_path):
        from mcp_memory_service.storage.migration_runner import MigrationRunner

        (tmp_path / "001_create_and_fail.sql").write_text(
            "CREATE TABLE good_table (id INTEGER);\n"
            "THIS WILL FAIL;"
        )
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        runner = MigrationRunner(tmp_path)
        result = runner.run_pending(conn)
        assert result["error"] is not None
        # good_table should NOT exist (rollback)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='good_table'"
        )
        assert cursor.fetchone() is None
        conn.close()

    def test_discover_migrations_ignores_non_sql(self, tmp_path):
        from mcp_memory_service.storage.migration_runner import MigrationRunner

        (tmp_path / "001_valid.sql").write_text("SELECT 1;")
        (tmp_path / "readme.txt").write_text("not a migration")
        (tmp_path / "002_also.sql.bak").write_text("not a migration either")

        runner = MigrationRunner(tmp_path)
        migrations = runner._discover_migrations()
        assert len(migrations) == 1
        assert migrations[0][0] == 1

    def test_checksum_different_files(self, tmp_path):
        from mcp_memory_service.storage.migration_runner import MigrationRunner

        f1 = tmp_path / "a.sql"
        f2 = tmp_path / "b.sql"
        f1.write_text("SELECT 1;")
        f2.write_text("SELECT 2;")
        runner = MigrationRunner(tmp_path)
        assert runner._checksum(f1) != runner._checksum(f2)


# ---------------------------------------------------------------------------
# Factory error paths
# ---------------------------------------------------------------------------


class TestFactoryErrorPaths:
    """Tests for storage factory error handling."""

    def test_hybrid_import_error_falls_back(self, monkeypatch):
        """When hybrid module fails to import, factory should fall back to SQLite-vec."""
        from mcp_memory_service.storage import factory

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "hybrid")

        import types

        class BrokenModule(types.ModuleType):
            def __getattr__(self, name):
                if name == "HybridMemoryStorage":
                    raise ImportError("mock: HybridMemoryStorage not available")
                raise AttributeError(name)

        monkeypatch.setitem(sys.modules, "mcp_memory_service.storage.hybrid", BrokenModule("hybrid"))

        cls = factory.get_storage_backend_class()
        # Should fall back to SQLite-vec
        assert cls.__name__ == "SqliteVecMemoryStorage"

    def test_unknown_backend_defaults_to_sqlite(self, monkeypatch):
        """Unknown backend should default to SQLite-vec."""
        from mcp_memory_service.storage import factory

        monkeypatch.setenv("MCP_MEMORY_STORAGE_BACKEND", "totally_unknown_backend")
        cls = factory.get_storage_backend_class()
        assert cls.__name__ == "SqliteVecMemoryStorage"

    def test_fallback_helper_returns_sqlite(self):
        """_fallback_to_sqlite_vec returns SqliteVecMemoryStorage."""
        from mcp_memory_service.storage.factory import _fallback_to_sqlite_vec

        cls = _fallback_to_sqlite_vec()
        assert cls.__name__ == "SqliteVecMemoryStorage"


# ---------------------------------------------------------------------------
# Graph storage error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGraphErrorPaths:
    """Tests for graph storage error handling."""

    async def test_store_association_sql_error_handled(self, tmp_path):
        from mcp_memory_service.storage.graph import GraphStorage

        storage = GraphStorage(str(tmp_path / "graph.db"))
        # Don't create the table — store should fail gracefully
        result = await storage.store_association(
            "hash_a", "hash_b", 0.8, ["semantic"]
        )
        assert result is False
        if storage._connection:
            storage._connection.close()

    async def test_find_connected_sql_error_returns_empty(self, tmp_path):
        from mcp_memory_service.storage.graph import GraphStorage

        storage = GraphStorage(str(tmp_path / "graph.db"))
        result = await storage.find_connected("hash_a")
        assert result == []
        if storage._connection:
            storage._connection.close()

    async def test_shortest_path_sql_error_returns_none(self, tmp_path):
        from mcp_memory_service.storage.graph import GraphStorage

        storage = GraphStorage(str(tmp_path / "graph.db"))
        result = await storage.shortest_path("hash_a", "hash_b")
        assert result is None
        if storage._connection:
            storage._connection.close()

    async def test_get_subgraph_sql_error_returns_empty(self, tmp_path):
        from mcp_memory_service.storage.graph import GraphStorage

        storage = GraphStorage(str(tmp_path / "graph.db"))
        result = await storage.get_subgraph("hash_a")
        assert result == {"nodes": [], "edges": []}
        if storage._connection:
            storage._connection.close()


# ---------------------------------------------------------------------------
# External embedding API error paths
# ---------------------------------------------------------------------------


class TestExternalEmbeddingErrorPaths:
    """Tests for external embedding API error handling."""

    def test_encode_with_key_error_raises_runtime(self):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
        model.api_url = "http://test/api"
        model.model_name = "test"
        model.api_key = None
        model.timeout = 30
        model.embedding_dimension = 4

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"data": [{"index": 0}]}  # Missing "embedding"
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            with pytest.raises(RuntimeError, match="missing the 'embedding' field"):
                model.encode(["hello"])

    def test_encode_with_index_error_raises_runtime(self):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
        model.api_url = "http://test/api"
        model.model_name = "test"
        model.api_key = None
        model.timeout = 30
        model.embedding_dimension = 4

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 200
            # data[0] exists but has no "embedding" key and "index" is out of range
            mock_response.json.return_value = {"data": []}
            mock_response.raise_for_status = MagicMock()
            mock_post.return_value = mock_response

            with pytest.raises(RuntimeError):
                model.encode(["hello"])

    def test_verify_connection_non_200_with_text_error(self):
        from mcp_memory_service.embeddings.external_api import ExternalEmbeddingModel

        model = ExternalEmbeddingModel.__new__(ExternalEmbeddingModel)
        model.api_url = "http://test/api"
        model.model_name = "test"
        model.api_key = None
        model.timeout = 30
        model.embedding_dimension = 768

        with patch("mcp_memory_service.embeddings.external_api.requests.post") as mock_post:
            mock_response = MagicMock()
            mock_response.status_code = 503
            mock_response.json.side_effect = Exception("can't parse")
            mock_response.text = "Service Unavailable"
            mock_post.return_value = mock_response

            with pytest.raises(ConnectionError, match="503"):
                model._verify_connection()
