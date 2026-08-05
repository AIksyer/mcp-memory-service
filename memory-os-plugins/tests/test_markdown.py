"""Tests for memory_os_plugins.git_sync.markdown."""

from pathlib import Path

from memory_os_plugins.git_sync.markdown import (
    MemoryToMarkdown,
    convert,
    find_md_path,
    generate_readme_index,
    get_md_path,
    memory_to_markdown,
    markdown_to_memory_dict,
)


# ─── memory_to_markdown ──────────────────────────────────────────────


class TestMemoryToMarkdown:
    """Tests for memory_to_markdown()."""

    def test_full_memory(self):
        """A memory with all fields and rich metadata."""
        memory_dict = {
            "content": "Use JWT for authentication.",
            "content_hash": "abc123def456",
            "tags": ["auth", "security"],
            "memory_type": "decision",
            "metadata": {
                "quality_score": 0.85,
                "access_count": 3,
                "source_type": "user",
            },
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T12:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        # Front matter
        assert "---" in result
        assert "id: abc123def456" in result
        assert "tags: [auth, security]" in result
        assert "created_at: 2026-08-03T10:00:00Z" in result
        assert "updated_at: 2026-08-03T12:00:00Z" in result
        assert "type: decision" in result

        # Content in body
        assert "Use JWT for authentication." in result

        # Tags section
        assert "## Tags" in result
        assert "#auth" in result
        assert "#security" in result

        # Metadata section
        assert "## Metadata" in result
        assert "- **quality_score**: 0.85" in result
        assert "- **access_count**: 3" in result
        assert "- **source_type**: user" in result

    def test_empty_metadata(self):
        """When metadata is empty, the ## Metadata section should be omitted."""
        memory_dict = {
            "content": "Hello world",
            "content_hash": "hash123",
            "tags": [],
            "memory_type": None,
            "metadata": {},
            "created_at_iso": "2026-08-03T12:00:00Z",
            "updated_at_iso": "2026-08-03T12:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        assert "## Metadata" not in result
        assert "type:" not in result
        assert "tags: []" in result

    def test_none_metadata(self):
        """When metadata is None, the ## Metadata section should be omitted."""
        memory_dict = {
            "content": "No metadata here",
            "content_hash": "hash456",
            "tags": ["note"],
            "memory_type": "note",
            "metadata": None,
            "created_at_iso": "",
            "updated_at_iso": "",
        }
        result = memory_to_markdown(memory_dict)

        assert "## Metadata" not in result
        assert "No metadata here" in result

    def test_metadata_with_empty_values(self):
        """Empty values in metadata should be skipped."""
        memory_dict = {
            "content": "Content here",
            "content_hash": "hash789",
            "tags": ["test"],
            "memory_type": "observation",
            "metadata": {
                "quality_score": 0.9,
                "empty_str": "",
                "none_val": None,
                "empty_list": [],
                "empty_dict": {},
                "access_count": 5,
            },
            "created_at_iso": "2026-08-03T15:00:00Z",
            "updated_at_iso": "2026-08-03T15:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        assert "- **quality_score**: 0.9" in result
        assert "- **access_count**: 5" in result
        assert "empty_str" not in result
        assert "none_val" not in result
        assert "empty_list" not in result
        assert "empty_dict" not in result

    def test_embedding_hash(self):
        """When embedding is present, embedding_hash should appear in front matter."""
        memory_dict = {
            "content": "Test with embedding",
            "content_hash": "hash_emb",
            "tags": ["test"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
            "embedding": [0.1, 0.2, 0.3],
        }
        result = memory_to_markdown(memory_dict)
        assert "embedding_hash:" in result

    def test_no_embedding_hash_when_absent(self):
        """When embedding is absent, embedding_hash should not appear."""
        memory_dict = {
            "content": "No embedding",
            "content_hash": "hash_no_emb",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        result = memory_to_markdown(memory_dict)
        assert "embedding_hash:" not in result

    def test_missing_fields(self):
        """A dict with minimal fields should not raise."""
        result = memory_to_markdown({"content": "Minimal"})
        assert "Minimal" in result

    def test_output_ends_with_newline(self):
        """Output should end with a newline for clean file writing."""
        result = memory_to_markdown({"content": "Test", "content_hash": "h"})
        assert result.endswith("\n")

    def test_multiline_content(self):
        """Multi-line content should be handled via YAML block scalar."""
        memory_dict = {
            "content": "Line 1\nLine 2\nLine 3",
            "content_hash": "multi001",
            "tags": ["multi"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        result = memory_to_markdown(memory_dict)
        # Block scalar indicator
        assert "content: |" in result
        # All lines present in body
        assert "Line 1" in result
        assert "Line 2" in result
        assert "Line 3" in result


# ─── get_md_path ─────────────────────────────────────────────────────


class TestGetMdPath:
    """Tests for get_md_path()."""

    def test_standard_path(self, tmp_path):
        """File path uses YYYY/MM/mem-<short_id>.md format."""
        memory = {
            "content_hash": "abcdef1234567890",
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = get_md_path(memory, tmp_path)
        assert result == tmp_path / "memories" / "2026" / "08" / "mem-abcdef12.md"

    def test_short_hash(self, tmp_path):
        """Very short hash uses what's available."""
        memory = {
            "content_hash": "a",
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = get_md_path(memory, tmp_path)
        assert result == tmp_path / "memories" / "2026" / "08" / "mem-a.md"

    def test_long_hash(self, tmp_path):
        """Typical SHA-256 hash truncated to 8 chars in filename."""
        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        memory = {
            "content_hash": sha,
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = get_md_path(memory, tmp_path)
        assert result == tmp_path / "memories" / "2026" / "08" / "mem-e3b0c442.md"

    def test_missing_timestamp(self, tmp_path):
        """Missing created_at_iso falls back to 1970/01."""
        memory = {"content_hash": "abcdef12"}
        result = get_md_path(memory, tmp_path)
        assert result == tmp_path / "memories" / "1970" / "01" / "mem-abcdef12.md"

    def test_different_dates(self, tmp_path):
        """Different dates produce different paths."""
        mem1 = {"content_hash": "hash0001", "created_at_iso": "2025-12-01T00:00:00Z"}
        mem2 = {"content_hash": "hash0002", "created_at_iso": "2026-03-15T00:00:00Z"}
        path1 = get_md_path(mem1, tmp_path)
        path2 = get_md_path(mem2, tmp_path)
        assert path1 != path2
        assert "2025" in str(path1) and "12" in str(path1)
        assert "2026" in str(path2) and "03" in str(path2)

    def test_path_is_within_base(self, tmp_path):
        """Path should be within the base_dir/memories/ directory."""
        memory = {
            "content_hash": "abcdef123456",
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = get_md_path(memory, tmp_path)
        assert result.is_relative_to(tmp_path / "memories")


# ─── find_md_path ────────────────────────────────────────────────────


class TestFindMdPath:
    """Tests for find_md_path()."""

    def test_find_existing_file(self, tmp_path):
        """find_md_path locates a file written by convert()."""
        memory = {
            "content": "Test content",
            "content_hash": "abcdef1234567890",
            "tags": ["test"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        convert(memory, tmp_path)

        found = find_md_path("abcdef1234567890", tmp_path)
        assert found is not None
        assert found.exists()
        assert "mem-abcdef12.md" in found.name

    def test_find_nonexistent(self, tmp_path):
        """find_md_path returns None when no file exists."""
        result = find_md_path("nonexistent_hash", tmp_path)
        assert result is None

    def test_find_no_memories_dir(self, tmp_path):
        """find_md_path returns None when memories dir doesn't exist."""
        result = find_md_path("anyhash", tmp_path)
        assert result is None


# ─── MemoryToMarkdown class ──────────────────────────────────────────


class TestMemoryToMarkdownClass:
    """Tests for the MemoryToMarkdown class."""

    def test_convert_writes_file(self, tmp_path):
        """convert() writes a Markdown file to the correct path."""
        converter = MemoryToMarkdown()
        memory = {
            "content": "Test content",
            "content_hash": "abcdef0123456789",
            "tags": ["tag1", "tag2"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        path = converter.convert(memory, tmp_path)

        assert path.exists()
        assert path.parent == tmp_path / "memories" / "2026" / "08"
        assert path.name == "mem-abcdef01.md"

        # Verify file content
        content = path.read_text(encoding="utf-8")
        assert "---" in content
        assert "id: abcdef0123456789" in content
        assert "Test content" in content

    def test_to_markdown_returns_string(self):
        """to_markdown() returns a string without writing to disk."""
        converter = MemoryToMarkdown()
        memory = {
            "content": "Hello",
            "content_hash": "h",
            "tags": ["test"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        result = converter.to_markdown(memory)
        assert isinstance(result, str)
        assert "Hello" in result

    def test_get_path_returns_path(self, tmp_path):
        """get_path() returns the expected path."""
        converter = MemoryToMarkdown()
        memory = {
            "content_hash": "abcdef123456",
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        path = converter.get_path(memory, tmp_path)
        assert isinstance(path, Path)
        assert path == tmp_path / "memories" / "2026" / "08" / "mem-abcdef12.md"


# ─── convert standalone function ────────────────────────────────────


class TestConvertFunction:
    """Tests for the standalone convert() function."""

    def test_convert_writes_file(self, tmp_path):
        """convert() writes a file and returns the path."""
        memory = {
            "content": "Standalone test",
            "content_hash": "abcde1234567890a",
            "tags": ["func"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-07-15T08:00:00Z",
            "updated_at_iso": "2026-07-15T08:00:00Z",
        }
        path = convert(memory, tmp_path)

        assert path.exists()
        assert "mem-abcde123.md" in path.name
        assert "2026" in str(path)
        assert "07" in str(path)

    def test_convert_utf8_no_bom(self, tmp_path):
        """File must be UTF-8 without BOM."""
        memory = {
            "content": "UTF-8 test with émojis 🎉",
            "content_hash": "utf8test1234567",
            "tags": ["utf8"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        path = convert(memory, tmp_path)
        raw_bytes = path.read_bytes()
        # UTF-8 BOM is EF BB BF
        assert not raw_bytes.startswith(b"\xef\xbb\xbf"), "File must not have UTF-8 BOM"

    def test_convert_creates_parent_dirs(self, tmp_path):
        """convert() creates parent directories as needed."""
        memory = {
            "content": "Deep path test",
            "content_hash": "deeppath1234567",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2025-01-15T08:00:00Z",
            "updated_at_iso": "2025-01-15T08:00:00Z",
        }
        path = convert(memory, tmp_path)
        assert path.exists()
        assert path.parent.exists()


# ─── generate_readme_index ──────────────────────────────────────────


class TestGenerateReadmeIndex:
    """Tests for generate_readme_index()."""

    def test_empty_dir(self, tmp_path):
        """An empty memories directory produces an empty table."""
        result = generate_readme_index(tmp_path)
        assert "# Memory Index" in result
        assert "Total memories: 0" in result
        assert "| Date | Hash | Tags | Preview |" in result

    def test_with_files(self, tmp_path):
        """Files with front matter are listed in the index."""
        # Create memory files using convert()
        mem1 = {
            "content": "This is a test memory about Python.",
            "content_hash": "abc123def45678901",
            "tags": ["python", "test"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        mem2 = {
            "content": "Use SQLite for local storage.",
            "content_hash": "cde456fgh78901234",
            "tags": ["architecture"],
            "memory_type": "decision",
            "metadata": {},
            "created_at_iso": "2026-08-02T08:00:00Z",
            "updated_at_iso": "2026-08-02T08:00:00Z",
        }
        convert(mem1, tmp_path)
        convert(mem2, tmp_path)

        result = generate_readme_index(tmp_path / "memories")

        assert "Total memories: 2" in result
        assert "abc123de" in result
        assert "cde456fg" in result
        # More recent entry should appear first
        abc_pos = result.index("abc123de")
        cde_pos = result.index("cde456fg")
        assert abc_pos < cde_pos

    def test_preview_truncation(self, tmp_path):
        """Long content is truncated in the preview column."""
        long_content = "A" * 200
        mem = {
            "content": long_content,
            "content_hash": "longprev12345678",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        convert(mem, tmp_path)

        result = generate_readme_index(tmp_path / "memories")
        assert "\u2026" in result

    def test_pipe_escaping_in_preview(self, tmp_path):
        """Pipe characters in content are escaped to not break the table."""
        mem = {
            "content": "Use command: echo a | grep b",
            "content_hash": "pipe1234567890ab",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T10:00:00Z",
        }
        convert(mem, tmp_path)

        result = generate_readme_index(tmp_path / "memories")
        assert "\\|" in result

    def test_file_without_front_matter(self, tmp_path):
        """Files without front matter still get indexed (uses filename as hash)."""
        (tmp_path / "nohash.md").write_text(
            "Just some content without front matter.",
            encoding="utf-8",
        )

        result = generate_readme_index(tmp_path)
        assert "Total memories: 1" in result
        assert "nohash" in result


# ─── markdown_to_memory_dict ─────────────────────────────────────────


class TestMarkdownToMemoryDict:
    """Tests for markdown_to_memory_dict() — the inverse of memory_to_markdown()."""

    def test_round_trip(self):
        """Converting to Markdown and back should preserve key fields."""
        original = {
            "content": "Use JWT for authentication.",
            "content_hash": "abc123def456789",
            "tags": ["auth", "security"],
            "memory_type": "decision",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T12:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]
        assert parsed["updated_at_iso"] == original["updated_at_iso"]

    def test_empty_tags(self):
        """Empty tags should parse to an empty list."""
        md = (
            "---\n"
            "id: abc123\n"
            "content: |\n"
            "  Some content.\n"
            "tags: []\n"
            "created_at: 2026-08-03T10:00:00Z\n"
            "updated_at: 2026-08-03T10:00:00Z\n"
            "---\n\n"
            "Some content."
        )
        parsed = markdown_to_memory_dict(md)
        assert parsed["tags"] == []

    def test_single_tag(self):
        """A single tag should parse correctly."""
        md = (
            "---\n"
            "id: abc123\n"
            "content: |\n"
            "  Content here.\n"
            "tags: [only-tag]\n"
            "created_at: 2026-08-03T10:00:00Z\n"
            "updated_at: 2026-08-03T10:00:00Z\n"
            "---\n\n"
            "Content here."
        )
        parsed = markdown_to_memory_dict(md)
        assert parsed["tags"] == ["only-tag"]

    def test_no_front_matter(self):
        """Text without front matter should return empty fields and full content."""
        parsed = markdown_to_memory_dict("Just plain text, no front matter.")
        assert parsed["content"] == "Just plain text, no front matter."
        assert parsed["content_hash"] == ""
        assert parsed["tags"] == []

    def test_embedding_hash_parsed(self):
        """embedding_hash should be parsed into metadata."""
        md = (
            "---\n"
            "id: abc\n"
            "content: |\n"
            "  Content.\n"
            "tags: []\n"
            "created_at: 2026-08-03T10:00:00Z\n"
            "updated_at: 2026-08-03T10:00:00Z\n"
            "embedding_hash: abcdef1234567890\n"
            "---\n\n"
            "Content."
        )
        parsed = markdown_to_memory_dict(md)
        assert parsed["metadata"]["embedding_hash"] == "abcdef1234567890"


# ─── Round-trip tests ───────────────────────────────────────────────


class TestRoundTrip:
    """Round-trip tests: memory_to_markdown() → markdown_to_memory_dict()."""

    def test_basic_round_trip(self):
        """Core fields survive a to-Markdown / from-Markdown round trip."""
        original = {
            "content": "Use JWT for authentication.",
            "content_hash": "abc123def456789",
            "tags": ["auth", "security"],
            "memory_type": "decision",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
            "updated_at_iso": "2026-08-03T12:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]
        assert parsed["updated_at_iso"] == original["updated_at_iso"]

    def test_complex_metadata_round_trip(self):
        """metadata fields are written to ## Metadata section."""
        original = {
            "content": "Important architectural decision.",
            "content_hash": "deadbeef12345678",
            "tags": ["architecture", "decision"],
            "memory_type": "decision",
            "metadata": {
                "quality_score": 0.85,
                "access_count": 3,
                "source_type": "user",
            },
            "created_at_iso": "2026-08-03T12:00:00Z",
            "updated_at_iso": "2026-08-03T12:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        # Core fields survive.
        assert original["content"] in parsed["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]

        # ## Metadata section is written but not parsed back.
        assert "- **quality_score**: 0.85" in md
        assert "- **access_count**: 3" in md
        assert "- **source_type**: user" in md

    def test_empty_tags_round_trip(self):
        """Empty tags list survives the round trip."""
        original = {
            "content": "A memory with no tags.",
            "content_hash": "hash000100000000",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T08:00:00Z",
            "updated_at_iso": "2026-08-03T08:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == []
        assert parsed["memory_type"] == original["memory_type"]

    def test_special_chars_content(self):
        """Content with newlines, quotes, and Markdown special characters."""
        original = {
            "content": 'Line 1\nLine 2 with "quotes"\n# Not a heading\n* not a list',
            "content_hash": "face1234face5678",
            "tags": ["test", "special"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T09:00:00Z",
            "updated_at_iso": "2026-08-03T09:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]

    def test_full_convert_round_trip(self, tmp_path):
        """Full round-trip: convert() → read file → markdown_to_memory_dict()."""
        original = {
            "content": "Round trip via file system.",
            "content_hash": "roundtrip12345678",
            "tags": ["round", "trip"],
            "memory_type": "note",
            "metadata": {"quality_score": 0.7},
            "created_at_iso": "2026-06-15T14:30:00Z",
            "updated_at_iso": "2026-06-15T14:30:00Z",
        }
        path = convert(original, tmp_path)
        md_text = path.read_text(encoding="utf-8")
        parsed = markdown_to_memory_dict(md_text)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]
