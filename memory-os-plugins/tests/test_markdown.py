"""Tests for memory_os_plugins.git_sync.markdown."""

from pathlib import Path

from memory_os_plugins.git_sync.markdown import (
    get_md_path,
    generate_readme_index,
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
                "importance": "high",
            },
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        # Front matter
        assert "---" in result
        assert "hash: abc123def456" in result
        assert "type: decision" in result
        assert "tags: [auth, security]" in result
        assert "created: 2026-08-03T10:00:00Z" in result
        assert "importance: high" in result

        # Content
        assert "Use JWT for authentication." in result

        # Metadata section
        assert "## Metadata" in result
        assert "- **quality_score**: 0.85" in result
        assert "- **access_count**: 3" in result
        assert "- **source_type**: user" in result
        # importance is in front matter, not Metadata section
        assert "- **importance**:" not in result

    def test_empty_metadata(self):
        """When metadata is empty, the ## Metadata section should be omitted."""
        memory_dict = {
            "content": "Hello world",
            "content_hash": "hash123",
            "tags": [],
            "memory_type": None,
            "metadata": {},
            "created_at_iso": "2026-08-03T12:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        assert "## Metadata" not in result
        # memory_type defaults to "observation"
        assert "type: observation" in result
        # empty tags → tags: []
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
        }
        result = memory_to_markdown(memory_dict)

        assert "- **quality_score**: 0.9" in result
        assert "- **access_count**: 5" in result
        assert "empty_str" not in result
        assert "none_val" not in result
        assert "empty_list" not in result
        assert "empty_dict" not in result

    def test_importance_not_in_metadata_section(self):
        """importance goes to front matter, should not appear in Metadata section."""
        memory_dict = {
            "content": "Test",
            "content_hash": "h",
            "tags": [],
            "memory_type": "observation",
            "metadata": {"importance": "low", "quality_score": 0.1},
            "created_at_iso": "2026-01-01T00:00:00Z",
        }
        result = memory_to_markdown(memory_dict)
        assert "importance: low" in result
        assert "- **importance**:" not in result.split("## Metadata")[1]

    def test_missing_fields(self):
        """A dict with minimal fields should not raise."""
        result = memory_to_markdown({"content": "Minimal"})
        assert "type: observation" in result
        assert "tags: []" in result
        assert "Minimal" in result

    def test_output_ends_with_newline(self):
        """Output should end with a newline for clean file writing."""
        result = memory_to_markdown({"content": "Test", "content_hash": "h"})
        assert result.endswith("\n")

    # ── Requested test names ────────────────────────────────────────

    def test_memory_to_markdown_basic(self):
        """Basic Markdown generation: content, tags, hash."""
        memory_dict = {
            "content": "Use JWT for authentication.",
            "content_hash": "abc123def456",
            "tags": ["auth", "security"],
            "memory_type": "decision",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        assert "abc123def456" in result
        assert "Use JWT for authentication." in result
        assert "tags: [auth, security]" in result
        assert "type: decision" in result
        assert "---" in result

    def test_memory_to_markdown_with_metadata(self):
        """Markdown with metadata should include ## Metadata section."""
        memory_dict = {
            "content": "Important decision",
            "content_hash": "hash789",
            "tags": ["test"],
            "memory_type": "observation",
            "metadata": {
                "quality_score": 0.9,
                "source_type": "user",
                "importance": "high",
            },
            "created_at_iso": "2026-08-03T15:00:00Z",
        }
        result = memory_to_markdown(memory_dict)

        assert "## Metadata" in result
        assert "- **quality_score**: 0.9" in result
        assert "- **source_type**: user" in result
        assert "importance: high" in result  # in front matter
        assert "- **importance**:" not in result  # not in Metadata section

    def test_memory_to_markdown_empty_tags(self):
        """Empty tags should render as tags: []."""
        memory_dict = {
            "content": "No tags here",
            "content_hash": "h1",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T12:00:00Z",
        }
        result = memory_to_markdown(memory_dict)
        assert "tags: []" in result

    def test_memory_to_markdown_no_metadata(self):
        """When metadata is empty/None, ## Metadata section should be omitted."""
        for metadata in [{}, None]:
            memory_dict = {
                "content": "Content",
                "content_hash": "h2",
                "tags": ["note"],
                "memory_type": "note",
                "metadata": metadata,
                "created_at_iso": "2026-08-03T12:00:00Z",
            }
            result = memory_to_markdown(memory_dict)
            assert "## Metadata" not in result


# ─── get_md_path ─────────────────────────────────────────────────────


class TestGetMdPath:
    """Tests for get_md_path()."""

    def test_standard_hash(self):
        repo = Path("/tmp/repo")
        result = get_md_path("abcdef123456", repo)
        assert result == Path("/tmp/repo/memories/ab/abcdef123456.md")

    def test_short_hash(self):
        """Very short hash uses '00' as prefix."""
        repo = Path("/tmp/repo")
        result = get_md_path("a", repo)
        assert result == Path("/tmp/repo/memories/00/a.md")

    def test_long_hash(self):
        """Typical SHA-256 hash."""
        sha = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        repo = Path("/repo")
        result = get_md_path(sha, repo)
        assert result == Path(f"/repo/memories/e3/{sha}.md")

    # ── Requested test names ────────────────────────────────────────

    def test_get_md_path(self, tmp_path):
        """File path uses first 2 chars of hash as sub-directory name."""
        repo = tmp_path / "repo"
        result = get_md_path("abcdef123456", repo)
        assert result == repo / "memories" / "ab" / "abcdef123456.md"

    def test_get_md_path_special_chars(self, tmp_path):
        """Normal content hashes are hex (0-9a-f); path should be safe."""
        repo = tmp_path / "repo"
        hex_hash = "e3b0c44298fc1c149afbf4c8996fb924"
        result = get_md_path(hex_hash, repo)
        assert result == repo / "memories" / "e3" / f"{hex_hash}.md"
        # Verify the path doesn't escape the memories/ directory.
        assert result.is_relative_to(repo / "memories")


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
        # Create two memory files
        subdir = tmp_path / "ab"
        subdir.mkdir()
        (subdir / "abc123.md").write_text(
            "---\n"
            "hash: abc123\n"
            "type: note\n"
            "tags: [python, test]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "---\n\n"
            "This is a test memory about Python.",
            encoding="utf-8",
        )

        subdir2 = tmp_path / "cd"
        subdir2.mkdir()
        (subdir2 / "cde456.md").write_text(
            "---\n"
            "hash: cde456\n"
            "type: decision\n"
            "tags: [architecture]\n"
            "created: 2026-08-02T08:00:00Z\n"
            "---\n\n"
            "Use SQLite for local storage.",
            encoding="utf-8",
        )

        result = generate_readme_index(tmp_path)

        assert "Total memories: 2" in result
        assert "abc123" in result
        assert "cde456" in result
        # More recent entry should appear first
        abc_pos = result.index("abc123")
        cde_pos = result.index("cde456")
        assert abc_pos < cde_pos

    def test_preview_truncation(self, tmp_path):
        """Long content is truncated in the preview column."""
        long_content = "A" * 200
        subdir = tmp_path / "ab"
        subdir.mkdir()
        (subdir / "abc.md").write_text(
            "---\n"
            "hash: abc\n"
            "type: note\n"
            "tags: []\n"
            "created: 2026-08-03T10:00:00Z\n"
            "---\n\n"
            f"{long_content}",
            encoding="utf-8",
        )

        result = generate_readme_index(tmp_path)
        assert "…" in result

    def test_pipe_escaping_in_preview(self, tmp_path):
        """Pipe characters in content are escaped to not break the table."""
        subdir = tmp_path / "ab"
        subdir.mkdir()
        (subdir / "abc.md").write_text(
            "---\n"
            "hash: abc\n"
            "type: note\n"
            "tags: []\n"
            "created: 2026-08-03T10:00:00Z\n"
            "---\n\n"
            "Use command: echo a | grep b",
            encoding="utf-8",
        )

        result = generate_readme_index(tmp_path)
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
            "metadata": {"importance": "high"},
            "created_at_iso": "2026-08-03T10:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["metadata"]["importance"] == "high"
        assert parsed["created_at_iso"] == original["created_at_iso"]

    def test_empty_tags(self):
        """Empty tags should parse to an empty list."""
        md = (
            "---\n"
            "hash: abc123\n"
            "type: note\n"
            "tags: []\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
            "---\n\n"
            "Some content."
        )
        parsed = markdown_to_memory_dict(md)
        assert parsed["tags"] == []

    def test_single_tag(self):
        """A single tag should parse correctly."""
        md = (
            "---\n"
            "hash: abc123\n"
            "type: note\n"
            "tags: [only-tag]\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: N/A\n"
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

    def test_importance_in_metadata(self):
        """Importance should be extracted into metadata dict."""
        md = (
            "---\n"
            "hash: abc\n"
            "type: note\n"
            "tags: []\n"
            "created: 2026-08-03T10:00:00Z\n"
            "importance: critical\n"
            "---\n\n"
            "Important content."
        )
        parsed = markdown_to_memory_dict(md)
        assert parsed["metadata"]["importance"] == "critical"


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
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]

    def test_complex_metadata_round_trip(self):
        """importance (front matter) survives; other metadata fields are
        written to the ## Metadata section but not parsed back."""
        original = {
            "content": "Important architectural decision.",
            "content_hash": "deadbeef1234",
            "tags": ["architecture", "decision"],
            "memory_type": "decision",
            "metadata": {
                "quality_score": 0.85,
                "access_count": 3,
                "source_type": "user",
                "importance": "high",
            },
            "created_at_iso": "2026-08-03T12:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        # Core fields survive.
        assert original["content"] in parsed["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
        assert parsed["memory_type"] == original["memory_type"]
        assert parsed["created_at_iso"] == original["created_at_iso"]

        # importance is stored in front matter and parsed back.
        assert parsed["metadata"].get("importance") == "high"

        # The ## Metadata section is written but not parsed back by the
        # current implementation — verify the Markdown contains them.
        assert "- **quality_score**: 0.85" in md
        assert "- **access_count**: 3" in md
        assert "- **source_type**: user" in md

    def test_empty_tags_round_trip(self):
        """Empty tags list survives the round trip."""
        original = {
            "content": "A memory with no tags.",
            "content_hash": "hash0001",
            "tags": [],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T08:00:00Z",
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
            "content_hash": "face1234",
            "tags": ["test", "special"],
            "memory_type": "note",
            "metadata": {},
            "created_at_iso": "2026-08-03T09:00:00Z",
        }
        md = memory_to_markdown(original)
        parsed = markdown_to_memory_dict(md)

        assert parsed["content"] == original["content"]
        assert parsed["content_hash"] == original["content_hash"]
        assert parsed["tags"] == original["tags"]
