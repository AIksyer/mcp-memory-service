"""Whitebox unit tests for Knowledge Graph storage.

Tests cover:
- normalize_entity_id: slugification, Unicode fallback, edge cases
- store_association: symmetric vs asymmetric edges, validation, self-loop prevention
- find_connected: BFS traversal, direction filtering, cycle prevention
- shortest_path: pathfinding, same-node edge case, depth limits
- get_subgraph: node/edge extraction, deduplication, JSON fallback
- Entity operations: store_entity_link, list_entities, find_memories_by_entity
- transitive_closure: multi-hop reachability, distance filtering
- common_neighbors: shared neighbor discovery
- Association CRUD: get, delete, count
"""

import asyncio
import json
import sqlite3
import tempfile
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from mcp_memory_service.storage.graph import GraphStorage, normalize_entity_id
from mcp_memory_service.models.ontology import (
    is_symmetric_relationship,
    validate_relationship,
)


# ---------------------------------------------------------------------------
# normalize_entity_id tests
# ---------------------------------------------------------------------------


class TestNormalizeEntityId:
    """Tests for entity ID normalization/slugification."""

    def test_ascii_basic(self):
        assert normalize_entity_id("Hello World") == "hello-world"

    def test_ascii_with_special_chars(self):
        assert normalize_entity_id("Hello, World!") == "hello-world"

    def test_ascii_multiple_separators(self):
        assert normalize_entity_id("a---b") == "a-b"

    def test_strips_leading_trailing_hyphens(self):
        assert normalize_entity_id("---test---") == "test"

    def test_empty_string_falls_back_to_hash(self):
        result = normalize_entity_id("")
        assert result.startswith("e-")
        assert len(result) == 10  # "e-" + 8 hex chars

    def test_none_falls_back_to_hash(self):
        result = normalize_entity_id(None)
        assert result.startswith("e-")
        assert len(result) == 10

    def test_unicode_with_combining_marks(self):
        # "café" → NFKD → "cafe"
        result = normalize_entity_id("café")
        assert result == "cafe"

    def test_cjk_falls_back_to_hash(self):
        result = normalize_entity_id("日本語")
        assert result.startswith("e-")
        assert len(result) == 10

    def test_cyrillic_falls_back_to_hash(self):
        result = normalize_entity_id("Привет")
        assert result.startswith("e-")
        assert len(result) == 10

    def test_deterministic(self):
        assert normalize_entity_id("Test Entity") == normalize_entity_id("Test Entity")

    def test_numbers_preserved(self):
        assert normalize_entity_id("Entity 123") == "entity-123"

    def test_mixed_alphanumeric(self):
        assert normalize_entity_id("Test123 ABC") == "test123-abc"


# ---------------------------------------------------------------------------
# Ontology validation tests
# ---------------------------------------------------------------------------


class TestRelationshipValidation:
    """Tests for relationship type validation."""

    @pytest.mark.parametrize("rel_type", [
        "causes", "fixes", "contradicts", "supports",
        "follows", "related", "derived_from", "shares_entity",
    ])
    def test_valid_relationship_types(self, rel_type):
        assert validate_relationship(rel_type) is True

    def test_invalid_relationship_type(self):
        assert validate_relationship("invalid_type") is False

    def test_empty_relationship_type(self):
        assert validate_relationship("") is False

    @pytest.mark.parametrize("rel_type", ["related", "contradicts", "shares_entity"])
    def test_symmetric_relationships(self, rel_type):
        assert is_symmetric_relationship(rel_type) is True

    @pytest.mark.parametrize("rel_type", ["causes", "fixes", "supports", "follows"])
    def test_asymmetric_relationships(self, rel_type):
        assert is_symmetric_relationship(rel_type) is False

    def test_is_symmetric_invalid_raises(self):
        with pytest.raises(ValueError):
            is_symmetric_relationship("invalid_type")


# ---------------------------------------------------------------------------
# GraphStorage fixture
# ---------------------------------------------------------------------------


@pytest.fixture
async def graph_storage(tmp_path):
    """Create a GraphStorage with a real SQLite database."""
    storage = GraphStorage(str(tmp_path / "graph.db"))
    # Initialize the table
    conn = await storage._get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memory_graph (
            source_hash TEXT NOT NULL,
            target_hash TEXT NOT NULL,
            similarity REAL DEFAULT 0.0,
            connection_types TEXT,
            metadata TEXT,
            created_at REAL,
            relationship_type TEXT DEFAULT 'related'
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_source ON memory_graph(source_hash)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_graph_target ON memory_graph(target_hash)")
    conn.commit()
    yield storage
    if storage._connection:
        storage._connection.close()


# ---------------------------------------------------------------------------
# store_association tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestStoreAssociation:
    """Tests for GraphStorage.store_association."""

    async def test_store_basic_association(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.8,
            connection_types=["semantic"],
        )
        assert result is True

    async def test_store_symmetric_creates_both_directions(self, graph_storage):
        await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.7,
            connection_types=["semantic"],
            relationship_type="related",
        )
        # Should have both A→B and B→A
        conn = await graph_storage._get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM memory_graph WHERE source_hash = ? AND target_hash = ?",
            ("hash_a", "hash_b"),
        )
        assert cursor.fetchone()[0] == 1
        cursor = conn.execute(
            "SELECT COUNT(*) FROM memory_graph WHERE source_hash = ? AND target_hash = ?",
            ("hash_b", "hash_a"),
        )
        assert cursor.fetchone()[0] == 1

    async def test_store_asymmetric_creates_one_direction(self, graph_storage):
        await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.7,
            connection_types=["semantic"],
            relationship_type="causes",
        )
        conn = await graph_storage._get_connection()
        cursor = conn.execute(
            "SELECT COUNT(*) FROM memory_graph WHERE source_hash = ? AND target_hash = ?",
            ("hash_a", "hash_b"),
        )
        assert cursor.fetchone()[0] == 1
        cursor = conn.execute(
            "SELECT COUNT(*) FROM memory_graph WHERE source_hash = ? AND target_hash = ?",
            ("hash_b", "hash_a"),
        )
        assert cursor.fetchone()[0] == 0

    async def test_store_empty_source_returns_false(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="",
            target_hash="hash_b",
            similarity=0.8,
            connection_types=["semantic"],
        )
        assert result is False

    async def test_store_empty_target_returns_false(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="",
            similarity=0.8,
            connection_types=["semantic"],
        )
        assert result is False

    async def test_store_self_loop_returns_false(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_a",
            similarity=0.8,
            connection_types=["semantic"],
        )
        assert result is False

    async def test_store_invalid_similarity_high(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=1.5,
            connection_types=["semantic"],
        )
        assert result is False

    async def test_store_invalid_similarity_negative(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=-0.1,
            connection_types=["semantic"],
        )
        assert result is False

    async def test_store_invalid_relationship_type_returns_false(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.8,
            connection_types=["semantic"],
            relationship_type="invalid_type",
        )
        assert result is False

    async def test_store_with_metadata(self, graph_storage):
        result = await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.8,
            connection_types=["semantic", "temporal"],
            metadata={"source": "consolidation", "confidence": 0.9},
        )
        assert result is True

    async def test_store_with_custom_created_at(self, graph_storage):
        ts = 1700000000.0
        await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.8,
            connection_types=["semantic"],
            created_at=ts,
        )
        conn = await graph_storage._get_connection()
        cursor = conn.execute(
            "SELECT created_at FROM memory_graph WHERE source_hash = ? AND target_hash = ?",
            ("hash_a", "hash_b"),
        )
        assert cursor.fetchone()[0] == ts

    async def test_store_upsert_replaces_existing(self, graph_storage):
        # Store an association, then store again with different similarity
        await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.5,
            connection_types=["semantic"],
            relationship_type="causes",
        )
        await graph_storage.store_association(
            source_hash="hash_a",
            target_hash="hash_b",
            similarity=0.9,
            connection_types=["semantic"],
            relationship_type="causes",
        )
        conn = await graph_storage._get_connection()
        cursor = conn.execute(
            "SELECT similarity FROM memory_graph WHERE source_hash = ? AND target_hash = ? ORDER BY similarity DESC",
            ("hash_a", "hash_b"),
        )
        rows = cursor.fetchall()
        # At least one row should have the updated similarity
        assert len(rows) >= 1
        assert any(row["similarity"] == 0.9 for row in rows)


# ---------------------------------------------------------------------------
# find_connected tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestFindConnected:
    """Tests for GraphStorage.find_connected BFS traversal."""

    async def test_find_connected_empty_hash(self, graph_storage):
        result = await graph_storage.find_connected("")
        assert result == []

    async def test_find_connected_invalid_direction(self, graph_storage):
        result = await graph_storage.find_connected("hash_a", direction="invalid")
        assert result == []

    async def test_find_connected_no_edges(self, graph_storage):
        result = await graph_storage.find_connected("lonely_hash")
        assert result == []

    async def test_find_connected_one_hop(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.find_connected("node_a", max_hops=1)
        assert len(result) >= 1
        assert any(h == "node_b" for h, d in result)
        assert all(d == 1 for h, d in result if h == "node_b")

    async def test_find_connected_two_hops(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="related"
        )
        await graph_storage.store_association(
            "node_b", "node_c", 0.7, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.find_connected("node_a", max_hops=2)
        hashes = [h for h, d in result]
        assert "node_b" in hashes
        assert "node_c" in hashes

    async def test_find_connected_cycle_prevention(self, graph_storage):
        """Test that cycles don't cause infinite loops."""
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="related"
        )
        await graph_storage.store_association(
            "node_b", "node_a", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.find_connected("node_a", max_hops=3)
        # Should not loop infinitely
        assert len(result) >= 1

    async def test_find_connected_with_relationship_filter(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "node_a", "node_c", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.find_connected(
            "node_a", max_hops=1, relationship_type="causes"
        )
        hashes = [h for h, d in result]
        assert "node_b" in hashes
        assert "node_c" not in hashes

    async def test_find_connected_outgoing_direction(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="causes"
        )
        result = await graph_storage.find_connected("node_a", direction="outgoing")
        assert any(h == "node_b" for h, d in result)

    async def test_find_connected_incoming_direction(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="causes"
        )
        result = await graph_storage.find_connected("node_b", direction="incoming")
        assert any(h == "node_a" for h, d in result)


# ---------------------------------------------------------------------------
# shortest_path tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestShortestPath:
    """Tests for GraphStorage.shortest_path."""

    async def test_same_node(self, graph_storage):
        result = await graph_storage.shortest_path("node_a", "node_a")
        assert result == ["node_a"]

    async def test_empty_hash1(self, graph_storage):
        result = await graph_storage.shortest_path("", "node_b")
        assert result is None

    async def test_empty_hash2(self, graph_storage):
        result = await graph_storage.shortest_path("node_a", "")
        assert result is None

    async def test_no_path(self, graph_storage):
        result = await graph_storage.shortest_path("node_a", "node_b")
        assert result is None

    async def test_direct_path(self, graph_storage):
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="causes"
        )
        result = await graph_storage.shortest_path("node_a", "node_b")
        assert result is not None
        assert result[0] == "node_a"
        assert result[-1] == "node_b"

    async def test_multi_hop_path(self, graph_storage):
        await graph_storage.store_association(
            "a", "b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "b", "c", 0.8, ["semantic"], relationship_type="causes"
        )
        result = await graph_storage.shortest_path("a", "c")
        assert result is not None
        assert result[0] == "a"
        assert result[-1] == "c"
        assert len(result) == 3  # a → b → c

    async def test_path_with_relationship_filter(self, graph_storage):
        await graph_storage.store_association(
            "a", "b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "b", "c", 0.8, ["semantic"], relationship_type="related"
        )
        # Filter to only "causes" — should not find path a→b→c
        result = await graph_storage.shortest_path(
            "a", "c", relationship_types=["causes"]
        )
        assert result is None

    async def test_max_depth_limit(self, graph_storage):
        await graph_storage.store_association(
            "a", "b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "b", "c", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "c", "d", 0.8, ["semantic"], relationship_type="causes"
        )
        # Path a→b→c→d is depth 3, max_depth=2 should not find it
        result = await graph_storage.shortest_path("a", "d", max_depth=2)
        assert result is None


# ---------------------------------------------------------------------------
# get_subgraph tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetSubgraph:
    """Tests for GraphStorage.get_subgraph."""

    async def test_empty_hash(self, graph_storage):
        result = await graph_storage.get_subgraph("")
        assert result == {"nodes": [], "edges": []}

    async def test_no_edges(self, graph_storage):
        result = await graph_storage.get_subgraph("lonely_node")
        assert "lonely_node" in result["nodes"]
        assert len(result["edges"]) == 0

    async def test_subgraph_includes_center_node(self, graph_storage):
        await graph_storage.store_association(
            "center", "neighbor", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.get_subgraph("center", radius=1)
        assert "center" in result["nodes"]
        assert "neighbor" in result["nodes"]

    async def test_subgraph_edge_deduplication(self, graph_storage):
        """Symmetric relationship creates both A→B and B→A; subgraph should deduplicate."""
        await graph_storage.store_association(
            "node_a", "node_b", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.get_subgraph("node_a", radius=1)
        # Should have exactly 1 edge (deduplicated)
        assert len(result["edges"]) == 1

    async def test_subgraph_json_fallback_connection_types(self, graph_storage):
        """Test legacy bare-string connection_types fallback."""
        conn = await graph_storage._get_connection()
        conn.execute(
            "INSERT INTO memory_graph (source_hash, target_hash, similarity, connection_types, metadata, created_at, relationship_type) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("x", "y", 0.5, "semantic", "{}", 1700000000.0, "related"),
        )
        conn.commit()

        result = await graph_storage.get_subgraph("x", radius=1)
        # Should not crash, should parse legacy connection_types
        assert len(result["edges"]) >= 1
        edge = result["edges"][0]
        assert "semantic" in edge["connection_types"]


# ---------------------------------------------------------------------------
# Association CRUD tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAssociationCRUD:
    """Tests for get/delete association operations."""

    async def test_get_association_exists(self, graph_storage):
        await graph_storage.store_association(
            "hash_a", "hash_b", 0.75, ["semantic", "temporal"],
            metadata={"context": "test"},
            relationship_type="related",
        )
        result = await graph_storage.get_association("hash_a", "hash_b")
        assert result is not None
        assert result["similarity"] == 0.75
        assert "semantic" in result["connection_types"]

    async def test_get_association_reverse_direction(self, graph_storage):
        """Should find association regardless of direction."""
        await graph_storage.store_association(
            "hash_a", "hash_b", 0.8, ["semantic"],
            relationship_type="causes",
        )
        # Search reverse direction
        result = await graph_storage.get_association("hash_b", "hash_a")
        assert result is not None

    async def test_get_association_not_found(self, graph_storage):
        result = await graph_storage.get_association("nonexistent_a", "nonexistent_b")
        assert result is None

    async def test_get_association_empty_hashes(self, graph_storage):
        result = await graph_storage.get_association("", "hash_b")
        assert result is None

    async def test_delete_association(self, graph_storage):
        await graph_storage.store_association(
            "del_a", "del_b", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.delete_association("del_a", "del_b")
        assert result is True

        # Verify deleted
        verify = await graph_storage.get_association("del_a", "del_b")
        assert verify is None

    async def test_delete_association_not_found(self, graph_storage):
        result = await graph_storage.delete_association("nonexistent", "also_nonexistent")
        assert result is False

    async def test_get_association_count(self, graph_storage):
        await graph_storage.store_association(
            "hub", "spoke1", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "hub", "spoke2", 0.7, ["semantic"], relationship_type="fixes"
        )
        count = await graph_storage.get_association_count("hub")
        assert count == 2

    async def test_get_association_count_empty(self, graph_storage):
        count = await graph_storage.get_association_count("nonexistent")
        assert count == 0


# ---------------------------------------------------------------------------
# Relationship types tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetRelationshipTypes:
    """Tests for GraphStorage.get_relationship_types."""

    async def test_get_relationship_types(self, graph_storage):
        await graph_storage.store_association(
            "hub", "a", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "hub", "b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "hub", "c", 0.8, ["semantic"], relationship_type="fixes"
        )
        result = await graph_storage.get_relationship_types("hub")
        assert result.get("causes", 0) == 2
        assert result.get("fixes", 0) == 1

    async def test_get_relationship_types_empty_hash(self, graph_storage):
        result = await graph_storage.get_relationship_types("")
        assert result == {}

    async def test_get_relationship_types_no_edges(self, graph_storage):
        result = await graph_storage.get_relationship_types("lonely_node")
        assert result == {}


# ---------------------------------------------------------------------------
# Entity linking tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestEntityLinking:
    """Tests for entity-linking operations."""

    async def test_store_entity_link(self, graph_storage):
        result = await graph_storage.store_entity_link(
            memory_hash="mem_123",
            entity_name="Python",
            entity_type="language",
        )
        assert result is True

    async def test_list_entities(self, graph_storage):
        await graph_storage.store_entity_link("mem_1", "Python", "language")
        await graph_storage.store_entity_link("mem_2", "Python", "language")
        await graph_storage.store_entity_link("mem_3", "Rust", "language")

        entities = await graph_storage.list_entities()
        assert len(entities) >= 2
        # Find Python entity
        python_entities = [e for e in entities if e["entity_name"] == "Python"]
        assert len(python_entities) >= 1
        assert python_entities[0]["count"] >= 2

    async def test_find_memories_by_entity(self, graph_storage):
        await graph_storage.store_entity_link("mem_1", "Docker", "tool")
        await graph_storage.store_entity_link("mem_2", "Docker", "tool")

        memories = await graph_storage.find_memories_by_entity("Docker")
        assert len(memories) >= 2
        assert "mem_1" in memories
        assert "mem_2" in memories

    async def test_get_entities_for_memory(self, graph_storage):
        await graph_storage.store_entity_link("mem_1", "Python", "language")
        await graph_storage.store_entity_link("mem_1", "Docker", "tool")

        entities = await graph_storage.get_entities_for_memory("mem_1")
        assert len(entities) >= 2
        assert "Python" in entities
        assert "Docker" in entities

    async def test_get_entity_profile(self, graph_storage):
        await graph_storage.store_entity_link("mem_1", "Kubernetes", "tool")
        await graph_storage.store_entity_link("mem_2", "Kubernetes", "platform")

        profile = await graph_storage.get_entity_profile("Kubernetes")
        assert profile is not None
        assert profile["memory_count"] >= 2
        assert "tool" in profile["entity_types"] or "platform" in profile["entity_types"]


# ---------------------------------------------------------------------------
# transitive_closure tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestTransitiveClosure:
    """Tests for GraphStorage.transitive_closure."""

    async def test_transitive_closure_finds_indirect(self, graph_storage):
        # a → b → c (direct: a→b, b→c; indirect: a→c)
        await graph_storage.store_association(
            "tc_a", "tc_b", 0.8, ["semantic"], relationship_type="causes"
        )
        await graph_storage.store_association(
            "tc_b", "tc_c", 0.8, ["semantic"], relationship_type="causes"
        )
        result = await graph_storage.transitive_closure("causes", max_hops=2)
        # Should find (tc_a, tc_c, 2) — the indirect connection
        indirect = [r for r in result if r[0] == "tc_a" and r[1] == "tc_c"]
        assert len(indirect) >= 1
        assert indirect[0][2] == 2

    async def test_transitive_closure_max_hops_clamped(self, graph_storage):
        """max_hops should be clamped to [2, 4]."""
        result = await graph_storage.transitive_closure("causes", max_hops=1)
        # Should still work (clamped to 2)
        assert isinstance(result, list)

    async def test_transitive_closure_max_hops_4(self, graph_storage):
        result = await graph_storage.transitive_closure("causes", max_hops=10)
        # Should work (clamped to 4)
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# common_neighbors tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCommonNeighbors:
    """Tests for GraphStorage.common_neighbors."""

    async def test_common_neighbors_finds_shared(self, graph_storage):
        # hub connects to both a and b
        await graph_storage.store_association(
            "hub", "a", 0.8, ["semantic"], relationship_type="related"
        )
        await graph_storage.store_association(
            "hub", "b", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.common_neighbors("hub", min_shared=1)
        assert isinstance(result, list)

    async def test_common_neighbors_min_shared_filter(self, graph_storage):
        await graph_storage.store_association(
            "hub", "a", 0.8, ["semantic"], relationship_type="related"
        )
        result = await graph_storage.common_neighbors("hub", min_shared=5)
        # Should find nothing with high threshold
        assert len(result) == 0
