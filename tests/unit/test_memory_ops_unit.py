"""Whitebox unit tests for Memory model operations.

Tests cover:
- Memory dataclass: __post_init__ validation, timestamp sync, tag defaults
- Memory to_dict / from_dict round-trip with legacy fields
- MemoryQueryResult dataclass and properties
- Memory property accessors: quality_score, credibility clamping, access tracking
- store/retrieve/delete/consolidate behavior via storage integration
"""

import time
from datetime import datetime, timezone

import pytest

from mcp_memory_service.models.memory import Memory, MemoryQueryResult
from mcp_memory_service.utils.hashing import generate_content_hash

# ---------------------------------------------------------------------------
# Memory __post_init__ tests
# ---------------------------------------------------------------------------


class TestMemoryPostInit:
    """Tests for Memory.__post_init__ validation logic."""

    def test_basic_memory_creation(self):
        mem = Memory(
            content="test content",
            content_hash="abc123",
        )
        assert mem.content == "test content"
        assert mem.content_hash == "abc123"

    def test_empty_tags_defaults_to_untagged(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.tags == ["untagged"]

    def test_provided_tags_preserved(self):
        mem = Memory(content="test", content_hash="abc", tags=["python", "async"])
        assert mem.tags == ["python", "async"]

    def test_invalid_memory_type_defaults_to_observation(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            memory_type="invalid_type_xyz",
        )
        assert mem.memory_type == "observation"

    def test_valid_memory_type_preserved(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            memory_type="decision",
        )
        assert mem.memory_type == "decision"

    def test_none_memory_type_stays_none(self):
        mem = Memory(content="test", content_hash="abc", memory_type=None)
        assert mem.memory_type is None

    def test_subtype_memory_type_preserved(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            memory_type="bug",
        )
        assert mem.memory_type == "bug"

    def test_metadata_defaults_to_empty_dict(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.metadata == {}

    def test_embedding_defaults_to_none(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.embedding is None

    def test_timestamp_defaults_set(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.created_at is not None
        assert mem.created_at_iso is not None
        assert mem.updated_at is not None
        assert mem.updated_at_iso is not None


# ---------------------------------------------------------------------------
# Timestamp synchronization tests
# ---------------------------------------------------------------------------


class TestTimestampSync:
    """Tests for Memory._sync_timestamps logic."""

    def test_both_created_at_and_iso_provided_consistent(self):
        ts = 1700000000.0
        iso = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00", "Z")
        mem = Memory(
            content="test",
            content_hash="abc",
            created_at=ts,
            created_at_iso=iso,
        )
        assert mem.created_at == ts

    def test_only_created_at_provided(self):
        ts = 1700000000.0
        mem = Memory(content="test", content_hash="abc", created_at=ts)
        assert mem.created_at == ts
        assert mem.created_at_iso is not None

    def test_only_created_at_iso_provided(self):
        iso = "2023-11-14T22:13:20Z"
        mem = Memory(content="test", content_hash="abc", created_at_iso=iso)
        assert mem.created_at is not None
        assert mem.created_at > 0

    def test_neither_provided_uses_current_time(self):
        before = time.time()
        mem = Memory(content="test", content_hash="abc")
        after = time.time()
        assert before <= mem.created_at <= after

    def test_timestamp_mismatch_within_1s_keeps_both(self):
        """Small mismatch (< 1s) between float and ISO should be tolerated."""
        ts = 1700000000.5
        # ISO is 0.3s off
        iso = "2023-11-14T22:13:20.2Z"
        mem = Memory(
            content="test",
            content_hash="abc",
            created_at=ts,
            created_at_iso=iso,
        )
        # Should not raise, should set reasonable values
        assert mem.created_at is not None

    def test_updated_at_synced(self):
        ts = 1700000000.0
        mem = Memory(
            content="test",
            content_hash="abc",
            updated_at=ts,
        )
        assert mem.updated_at == ts
        assert mem.updated_at_iso is not None

    def test_touch_updates_updated_at(self):
        mem = Memory(content="test", content_hash="abc")
        old_updated = mem.updated_at
        time.sleep(0.01)
        mem.touch()
        assert mem.updated_at > old_updated
        assert mem.updated_at_iso is not None


# ---------------------------------------------------------------------------
# Memory property tests
# ---------------------------------------------------------------------------


class TestMemoryProperties:
    """Tests for Memory property accessors."""

    def test_quality_score_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.quality_score == 0.5

    def test_quality_score_from_metadata(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            metadata={"quality_score": 0.9},
        )
        assert mem.quality_score == 0.9

    def test_quality_provider_default_none(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.quality_provider is None

    def test_quality_provider_from_metadata(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            metadata={"quality_provider": "groq"},
        )
        assert mem.quality_provider == "groq"

    def test_access_count_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.access_count == 0

    def test_access_count_from_metadata(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            metadata={"access_count": 42},
        )
        assert mem.access_count == 42

    def test_source_type_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.source_type == "user"

    def test_source_type_setter(self):
        mem = Memory(content="test", content_hash="abc")
        mem.source_type = "document"
        assert mem.metadata["source_type"] == "document"
        assert mem.source_type == "document"

    def test_credibility_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.credibility == 1.0

    def test_credibility_setter_clamps_high(self):
        mem = Memory(content="test", content_hash="abc")
        mem.credibility = 1.5
        assert mem.credibility == 1.0

    def test_credibility_setter_clamps_low(self):
        mem = Memory(content="test", content_hash="abc")
        mem.credibility = -0.5
        assert mem.credibility == 0.0

    def test_credibility_setter_valid_range(self):
        mem = Memory(content="test", content_hash="abc")
        mem.credibility = 0.8
        assert mem.credibility == 0.8

    def test_emotional_valence_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.emotional_valence is None

    def test_emotional_valence_setter_clamps(self):
        mem = Memory(content="test", content_hash="abc")
        mem.emotional_valence = 2.0
        assert mem.emotional_valence == 1.0

        mem.emotional_valence = -2.0
        assert mem.emotional_valence == -1.0

    def test_emotional_arousal_default(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.emotional_arousal is None

    def test_emotional_arousal_setter_clamps(self):
        mem = Memory(content="test", content_hash="abc")
        mem.emotional_arousal = 1.5
        assert mem.emotional_arousal == 1.0

        mem.emotional_arousal = -0.5
        assert mem.emotional_arousal == 0.0

    def test_episode_id(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.episode_id is None
        mem.episode_id = "ep-123"
        assert mem.episode_id == "ep-123"

    def test_sequence_number(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.sequence_number is None
        mem.sequence_number = 5
        assert mem.sequence_number == 5

    def test_preceding_memory_id(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.preceding_memory_id is None
        mem.preceding_memory_id = "prev-hash"
        assert mem.preceding_memory_id == "prev-hash"

    def test_emotion(self):
        mem = Memory(content="test", content_hash="abc")
        assert mem.emotion is None
        mem.emotion = "happy"
        assert mem.emotion == "happy"


# ---------------------------------------------------------------------------
# record_access tests
# ---------------------------------------------------------------------------


class TestRecordAccess:
    """Tests for Memory.record_access."""

    def test_increments_access_count(self):
        mem = Memory(content="test", content_hash="abc")
        mem.record_access()
        assert mem.access_count == 1
        mem.record_access()
        assert mem.access_count == 2

    def test_sets_last_accessed_at(self):
        mem = Memory(content="test", content_hash="abc")
        mem.record_access()
        assert mem.last_accessed_at is not None

    def test_records_query(self):
        mem = Memory(content="test", content_hash="abc")
        mem.record_access("search query 1")
        mem.record_access("search query 2")
        queries = mem.metadata.get("access_queries", [])
        # Queries are stored as dicts with "query" and "timestamp" keys
        query_strings = [q["query"] for q in queries]
        assert "search query 1" in query_strings
        assert "search query 2" in query_strings

    def test_access_queries_capped_at_10(self):
        mem = Memory(content="test", content_hash="abc")
        for i in range(15):
            mem.record_access(f"query {i}")
        queries = mem.metadata.get("access_queries", [])
        assert len(queries) == 10
        # Should keep the last 10
        query_strings = [q["query"] for q in queries]
        assert "query 14" in query_strings
        assert "query 0" not in query_strings

    def test_record_access_none_query(self):
        mem = Memory(content="test", content_hash="abc")
        mem.record_access(None)
        assert mem.access_count == 1
        # None query should not be added to access_queries
        queries = mem.metadata.get("access_queries", [])
        assert None not in queries or len(queries) == 0


# ---------------------------------------------------------------------------
# to_dict / from_dict tests
# ---------------------------------------------------------------------------


class TestMemorySerialization:
    """Tests for Memory.to_dict and from_dict round-trip."""

    def test_to_dict_basic(self):
        mem = Memory(
            content="test content",
            content_hash="abc123",
            tags=["python", "test"],
            memory_type="observation",
        )
        d = mem.to_dict()
        assert d["content"] == "test content"
        assert d["content_hash"] == "abc123"
        assert d["tags"] == ["python", "test"]
        assert d["type"] == "observation"
        assert "timestamp" in d
        assert "created_at" in d
        assert "created_at_iso" in d

    def test_to_dict_includes_metadata(self):
        mem = Memory(
            content="test",
            content_hash="abc",
            metadata={"key": "value", "number": 42},
        )
        d = mem.to_dict()
        assert d["key"] == "value"
        assert d["number"] == 42

    def test_to_dict_tags_str(self):
        mem = Memory(content="test", content_hash="abc", tags=["a", "b"])
        d = mem.to_dict()
        assert d["tags_str"] == "a,b"

    def test_from_dict_basic(self):
        data = {
            "content": "test content",
            "content_hash": "abc123",
            "tags_str": "python,test",
            "type": "observation",
            "timestamp_float": 1700000000.0,
        }
        mem = Memory.from_dict(data)
        assert mem.content == "test content"
        assert mem.content_hash == "abc123"
        assert "python" in mem.tags
        assert "test" in mem.tags
        assert mem.memory_type == "observation"

    def test_from_dict_with_tags_list(self):
        # from_dict uses tags_str, not tags directly
        data = {
            "content": "test",
            "content_hash": "abc",
            "tags_str": "tag1,tag2",
            "type": "decision",
        }
        mem = Memory.from_dict(data)
        assert "tag1" in mem.tags
        assert "tag2" in mem.tags
        assert mem.memory_type == "decision"

    def test_from_dict_legacy_timestamp(self):
        data = {
            "content": "test",
            "content_hash": "abc",
            "timestamp": 1700000000.0,
        }
        mem = Memory.from_dict(data)
        assert mem.created_at == 1700000000.0

    def test_from_dict_created_at_iso(self):
        data = {
            "content": "test",
            "content_hash": "abc",
            "created_at_iso": "2023-11-14T22:13:20Z",
        }
        mem = Memory.from_dict(data)
        assert mem.created_at is not None
        assert mem.created_at > 0

    def test_from_dict_metadata_filtering(self):
        """Ensure internal keys are filtered from metadata."""
        data = {
            "content": "test",
            "content_hash": "abc",
            "tags_str": "a,b",
            "type": "observation",
            "timestamp": 1700000000.0,
            "timestamp_float": 1700000000.0,
            "timestamp_str": "2023-11-14",
            "created_at": 1700000000.0,
            "created_at_iso": "2023-11-14T22:13:20Z",
            "custom_field": "custom_value",
        }
        mem = Memory.from_dict(data)
        assert mem.metadata.get("custom_field") == "custom_value"
        assert "content" not in mem.metadata
        assert "content_hash" not in mem.metadata
        assert "tags_str" not in mem.metadata
        assert "type" not in mem.metadata

    def test_from_dict_empty_tags_str(self):
        data = {
            "content": "test",
            "content_hash": "abc",
            "tags_str": "",
        }
        mem = Memory.from_dict(data)
        assert mem.tags == ["untagged"]

    def test_from_dict_with_embedding(self):
        data = {
            "content": "test",
            "content_hash": "abc",
        }
        embedding = [0.1, 0.2, 0.3]
        mem = Memory.from_dict(data, embedding=embedding)
        assert mem.embedding == embedding

    def test_roundtrip_to_dict_from_dict(self):
        mem = Memory(
            content="roundtrip test",
            content_hash=generate_content_hash("roundtrip test"),
            tags=["roundtrip", "test"],
            memory_type="observation",
            metadata={"key": "value"},
        )
        d = mem.to_dict()
        restored = Memory.from_dict(d)
        assert restored.content == mem.content
        assert restored.content_hash == mem.content_hash
        assert restored.memory_type == mem.memory_type


# ---------------------------------------------------------------------------
# MemoryQueryResult tests
# ---------------------------------------------------------------------------


class TestMemoryQueryResult:
    """Tests for MemoryQueryResult dataclass."""

    def test_basic_creation(self):
        mem = Memory(content="test", content_hash="abc")
        result = MemoryQueryResult(memory=mem, relevance_score=0.95)
        assert result.memory == mem
        assert result.relevance_score == 0.95

    def test_similarity_score_alias(self):
        mem = Memory(content="test", content_hash="abc")
        result = MemoryQueryResult(memory=mem, relevance_score=0.8)
        assert result.similarity_score == 0.8

    def test_debug_info_default_empty(self):
        mem = Memory(content="test", content_hash="abc")
        result = MemoryQueryResult(memory=mem, relevance_score=0.5)
        assert result.debug_info == {}

    def test_debug_info_custom(self):
        mem = Memory(content="test", content_hash="abc")
        result = MemoryQueryResult(
            memory=mem,
            relevance_score=0.9,
            debug_info={"distance": 0.1, "backend": "sqlite_vec"},
        )
        assert result.debug_info["distance"] == 0.1
        assert result.debug_info["backend"] == "sqlite_vec"

    def test_to_dict(self):
        mem = Memory(content="test", content_hash="abc", tags=["t"])
        result = MemoryQueryResult(
            memory=mem,
            relevance_score=0.85,
            debug_info={"distance": 0.15},
        )
        d = result.to_dict()
        assert d["relevance_score"] == 0.85
        assert d["similarity_score"] == 0.85
        assert "memory" in d
        assert d["debug_info"]["distance"] == 0.15


# ---------------------------------------------------------------------------
# generate_content_hash tests
# ---------------------------------------------------------------------------


class TestGenerateContentHash:
    """Tests for generate_content_hash utility."""

    def test_deterministic(self):
        h1 = generate_content_hash("hello world")
        h2 = generate_content_hash("hello world")
        assert h1 == h2

    def test_case_insensitive(self):
        h1 = generate_content_hash("Hello")
        h2 = generate_content_hash("hello")
        assert h1 == h2

    def test_whitespace_stripped(self):
        h1 = generate_content_hash("  hello  ")
        h2 = generate_content_hash("hello")
        assert h1 == h2

    def test_different_content_different_hash(self):
        h1 = generate_content_hash("hello")
        h2 = generate_content_hash("world")
        assert h1 != h2

    def test_empty_string(self):
        h = generate_content_hash("")
        assert len(h) == 64  # SHA256 hex length

    def test_unicode_content(self):
        h = generate_content_hash("café")
        assert len(h) == 64

    def test_returns_hex_string(self):
        h = generate_content_hash("test")
        assert all(c in "0123456789abcdef" for c in h)


# ---------------------------------------------------------------------------
# Storage-level memory operation tests
# ---------------------------------------------------------------------------


@pytest.fixture
async def storage(tmp_path):
    """Create a real storage instance for integration tests."""
    from mcp_memory_service.storage.sqlite_vec import SqliteVecMemoryStorage

    s = SqliteVecMemoryStorage(
        db_path=str(tmp_path / "memops.db"),
        embedding_model="all-MiniLM-L6-v2",
    )
    await s.initialize()
    yield s
    await s.close()


@pytest.mark.asyncio
class TestStoreOperations:
    """Tests for store operation internals."""

    async def test_store_validates_connection(self, storage):
        from mcp_memory_service.models.memory import Memory

        mem = Memory(content="test", content_hash="abc")
        # Temporarily remove connection
        original_conn = storage.conn
        storage.conn = None
        success, _msg = await storage.store(mem)
        assert success is False
        storage.conn = original_conn

    async def test_store_skip_semantic_dedup(self, storage):
        mem = Memory(
            content="Skip dedup test content",
            content_hash=generate_content_hash("Skip dedup test content"),
            tags=["test"],
        )
        success, _msg = await storage.store(mem, skip_semantic_dedup=True)
        assert success is True

    async def test_store_with_metadata(self, storage):
        mem = Memory(
            content="Metadata store test",
            content_hash=generate_content_hash("Metadata store test"),
            tags=["test"],
            metadata={"source": "unit-test", "priority": 5},
        )
        success, _msg = await storage.store(mem)
        assert success is True

        retrieved = await storage.get_by_hash(mem.content_hash)
        assert retrieved is not None
        assert retrieved.metadata.get("source") == "unit-test"

    async def test_store_empty_content_hash(self, storage):
        from mcp_memory_service.models.memory import Memory

        mem = Memory(content="", content_hash="")
        # Should handle gracefully
        success, _msg = await storage.store(mem)
        # Empty content_hash should not crash
        assert isinstance(success, bool)


@pytest.mark.asyncio
class TestRetrieveOperations:
    """Tests for retrieve operation internals."""

    async def test_retrieve_with_tags(self, storage):
        mem = Memory(
            content="Retrieve with tags test",
            content_hash=generate_content_hash("Retrieve with tags test"),
            tags=["retrieve_test"],
        )
        await storage.store(mem)

        results = await storage.retrieve(
            "retrieve tags",
            n_results=5,
            tags=["retrieve_test"],
        )
        assert len(results) > 0

    async def test_retrieve_min_confidence(self, storage):
        results = await storage.retrieve(
            "nonexistent query content xyz123",
            n_results=5,
            min_confidence=0.99,
        )
        # With high confidence threshold, likely no results
        assert isinstance(results, list)

    async def test_retrieve_n_results_limit(self, storage):
        # Store multiple memories
        for i in range(5):
            mem = Memory(
                content=f"Limit test memory {i}",
                content_hash=generate_content_hash(f"Limit test memory {i}"),
                tags=["limit_test"],
            )
            await storage.store(mem)

        results = await storage.retrieve("limit test", n_results=2)
        assert len(results) <= 2

    async def test_retrieve_no_results(self, storage):
        results = await storage.retrieve("", n_results=5)
        assert isinstance(results, list)


@pytest.mark.asyncio
class TestDeleteOperations:
    """Tests for delete operation internals."""

    async def test_delete_removes_embedding(self, storage):
        mem = Memory(
            content="Delete embedding test",
            content_hash=generate_content_hash("Delete embedding test"),
            tags=["test"],
        )
        await storage.store(mem)

        # Verify embedding exists
        cursor = storage.conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE rowid IN "
            "(SELECT id FROM memories WHERE content_hash = ?)",
            (mem.content_hash,),
        )
        assert cursor.fetchone()[0] > 0

        await storage.delete(mem.content_hash)

        # Embedding should be removed
        cursor = storage.conn.execute(
            "SELECT COUNT(*) FROM memory_embeddings WHERE rowid IN "
            "(SELECT id FROM memories WHERE content_hash = ?)",
            (mem.content_hash,),
        )
        assert cursor.fetchone()[0] == 0

    async def test_delete_by_tag(self, storage):
        mem1 = Memory(
            content="Delete by tag 1",
            content_hash=generate_content_hash("Delete by tag 1"),
            tags=["del_tag_test"],
        )
        mem2 = Memory(
            content="Delete by tag 2",
            content_hash=generate_content_hash("Delete by tag 2"),
            tags=["del_tag_test"],
        )
        await storage.store(mem1)
        await storage.store(mem2)

        count, _msg = await storage.delete_by_tag("del_tag_test")
        assert count >= 2

    async def test_delete_by_tags(self, storage):
        mem1 = Memory(
            content="Multi delete 1",
            content_hash=generate_content_hash("Multi delete 1"),
            tags=["multi_del_a"],
        )
        mem2 = Memory(
            content="Multi delete 2",
            content_hash=generate_content_hash("Multi delete 2"),
            tags=["multi_del_b"],
        )
        await storage.store(mem1)
        await storage.store(mem2)

        count, _msg, hashes = await storage.delete_by_tags(["multi_del_a", "multi_del_b"])
        assert count >= 2
        assert len(hashes) >= 2

    async def test_delete_by_tag_nonexistent(self, storage):
        count, _msg = await storage.delete_by_tag("nonexistent_tag_xyz")
        assert count == 0


@pytest.mark.asyncio
class TestConsolidateOperations:
    """Tests for consolidation-related operations."""

    async def test_cleanup_duplicates_no_duplicates(self, storage):
        count, _msg = await storage.cleanup_duplicates()
        assert count == 0

    async def test_update_memory(self, storage):
        mem = Memory(
            content="Update test memory",
            content_hash=generate_content_hash("Update test memory"),
            tags=["update_test"],
            memory_type="observation",
        )
        await storage.store(mem)

        # Update tags
        mem.tags = ["updated_tag"]
        success = await storage.update_memory(mem)
        assert success is True

        retrieved = await storage.get_by_hash(mem.content_hash)
        assert "updated_tag" in retrieved.tags

    async def test_get_all_memories(self, storage):
        for i in range(3):
            mem = Memory(
                content=f"All memories test {i}",
                content_hash=generate_content_hash(f"All memories test {i}"),
                tags=["all_test"],
            )
            await storage.store(mem)

        all_mems = await storage.get_all_memories()
        assert len(all_mems) >= 3

    async def test_count_all_memories(self, storage):
        initial_count = await storage.count_all_memories()
        mem = Memory(
            content="Count test",
            content_hash=generate_content_hash("Count test"),
            tags=["count_test"],
        )
        await storage.store(mem)
        new_count = await storage.count_all_memories()
        assert new_count == initial_count + 1

    async def test_count_memories_by_tag(self, storage):
        mem = Memory(
            content="Tag count test",
            content_hash=generate_content_hash("Tag count test"),
            tags=["tag_count_test"],
        )
        await storage.store(mem)
        count = await storage.count_memories_by_tag(["tag_count_test"])
        assert count >= 1

    async def test_get_recent_memories(self, storage):
        mem = Memory(
            content="Recent memory test",
            content_hash=generate_content_hash("Recent memory test"),
            tags=["recent_test"],
        )
        await storage.store(mem)
        recent = await storage.get_recent_memories(n=5)
        assert len(recent) >= 1
        assert any(m.content == "Recent memory test" for m in recent)

    async def test_get_memory_timestamps(self, storage):
        mem = Memory(
            content="Timestamp test",
            content_hash=generate_content_hash("Timestamp test"),
            tags=["ts_test"],
        )
        await storage.store(mem)
        timestamps = await storage.get_memory_timestamps()
        assert len(timestamps) >= 1
        assert all(isinstance(ts, (int, float)) for ts in timestamps)
