# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Coverage tests for ingestion modules previously omitted from .coveragerc.

Tests:
- TextChunker with various strategies (paragraph, sentence, character)
- Loader registry (registration, lookup, supported extensions)
- CSV, JSON, and Text loaders with real temp files
"""

import asyncio
import csv
import json
import os
import tempfile
from pathlib import Path

import pytest

from mcp_memory_service.ingestion.chunker import ChunkingStrategy, TextChunker
from mcp_memory_service.ingestion.registry import (
    get_loader_for_file,
    get_supported_extensions,
    is_supported_file,
    list_registered_loaders,
    register_loader,
)
from mcp_memory_service.ingestion.csv_loader import CSVLoader
from mcp_memory_service.ingestion.json_loader import JSONLoader
from mcp_memory_service.ingestion.text_loader import TextLoader


# --- TextChunker tests ---

class TestTextChunkerCharacter:
    """TextChunker with character-based strategy."""

    def test_chunk_short_text(self):
        chunker = TextChunker(ChunkingStrategy(
            chunk_size=100, chunk_overlap=20,
            respect_sentence_boundaries=False,
            respect_paragraph_boundaries=False,
            min_chunk_size=1,
        ))
        text = "This is a short text."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        assert chunks[0][0] == text  # content, metadata tuple

    def test_chunk_long_text(self):
        chunker = TextChunker(ChunkingStrategy(
            chunk_size=50, chunk_overlap=10,
            respect_sentence_boundaries=False,
            respect_paragraph_boundaries=False,
            min_chunk_size=1,
        ))
        text = "A" * 200
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 2
        # Each chunk should be at most chunk_size chars
        for content, _ in chunks:
            assert len(content) <= 50

    def test_chunk_empty_text(self):
        chunker = TextChunker(ChunkingStrategy(chunk_size=100, chunk_overlap=20, min_chunk_size=1))
        chunks = chunker.chunk_text("")
        assert len(chunks) == 0 or len(chunks) == 1

    def test_chunk_returns_tuples(self):
        chunker = TextChunker(ChunkingStrategy(chunk_size=100, chunk_overlap=20, min_chunk_size=1))
        text = "Hello world. " * 20
        chunks = chunker.chunk_text(text)
        for item in chunks:
            assert isinstance(item, tuple)
            assert len(item) == 2
            assert isinstance(item[0], str)
            assert isinstance(item[1], dict)


class TestTextChunkerParagraph:
    """TextChunker with paragraph-based strategy."""

    def test_chunk_by_paragraphs(self):
        chunker = TextChunker(ChunkingStrategy(
            chunk_size=100, chunk_overlap=20,
            respect_paragraph_boundaries=True,
            respect_sentence_boundaries=False,
            min_chunk_size=1,
        ))
        text = "First paragraph.\n\nSecond paragraph.\n\nThird paragraph."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        all_content = " ".join(c for c, _ in chunks)
        assert "First paragraph" in all_content

    def test_chunk_respects_paragraph_boundaries(self):
        chunker = TextChunker(ChunkingStrategy(
            chunk_size=30, chunk_overlap=5,
            respect_paragraph_boundaries=True,
            respect_sentence_boundaries=False,
            min_chunk_size=1,
        ))
        text = "Short one.\n\nA much longer paragraph that exceeds the chunk size limit."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1


class TestTextChunkerSentence:
    """TextChunker with sentence-based strategy."""

    def test_chunk_by_sentences(self):
        chunker = TextChunker(ChunkingStrategy(
            chunk_size=50, chunk_overlap=10,
            respect_sentence_boundaries=True,
            respect_paragraph_boundaries=False,
            min_chunk_size=1,
        ))
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        chunks = chunker.chunk_text(text)
        assert len(chunks) >= 1
        all_content = " ".join(c for c, _ in chunks)
        assert "First sentence" in all_content


class TestTextChunkerSections:
    """TextChunker section-aware chunking."""

    def test_chunk_by_sections(self):
        chunker = TextChunker(ChunkingStrategy(min_chunk_size=1))
        text = """# Section 1

Content for section 1.

# Section 2

Content for section 2."""
        chunks = chunker.chunk_by_sections(text)
        assert len(chunks) >= 1

    def test_chunk_by_sections_with_metadata(self):
        chunker = TextChunker(ChunkingStrategy(min_chunk_size=1))
        text = "# Title\n\nSome content here."
        chunks = chunker.chunk_by_sections(text, metadata={"source": "test"})
        assert len(chunks) >= 1
        for _, meta in chunks:
            assert meta.get("source") == "test"


# --- Loader Registry tests ---

class TestLoaderRegistry:
    """Cover ingestion/registry.py functions."""

    def test_get_supported_extensions(self):
        exts = get_supported_extensions()
        assert isinstance(exts, list)
        # Extensions are stored without dots (e.g., "txt" not ".txt")
        assert "txt" in exts or "csv" in exts or "json" in exts

    def test_is_supported_file_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        assert is_supported_file(f) is True

    def test_is_supported_file_unsupported(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("hello")
        assert is_supported_file(f) is False

    def test_get_loader_for_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello world")
        loader = get_loader_for_file(f)
        assert loader is not None
        assert isinstance(loader, TextLoader)

    def test_get_loader_for_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        loader = get_loader_for_file(f)
        assert loader is not None
        assert isinstance(loader, CSVLoader)

    def test_get_loader_for_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        loader = get_loader_for_file(f)
        assert loader is not None
        assert isinstance(loader, JSONLoader)

    def test_get_loader_for_unsupported(self, tmp_path):
        f = tmp_path / "test.xyz"
        f.write_text("hello")
        loader = get_loader_for_file(f)
        assert loader is None

    def test_list_registered_loaders(self):
        loaders = list_registered_loaders()
        assert isinstance(loaders, dict)
        assert len(loaders) > 0

    def test_register_custom_loader(self):
        """Custom loaders can be registered."""
        from mcp_memory_service.ingestion.base import DocumentLoader

        class CustomLoader(DocumentLoader):
            async def extract_chunks(self, file_path, **kwargs):
                yield  # pragma: no cover

            def can_handle(self, file_path):
                return str(file_path).endswith(".custom")

        register_loader(CustomLoader, ["custom"])  # extensions without dots
        assert "custom" in get_supported_extensions()


# --- CSV Loader tests ---

class TestCSVLoader:
    """Cover ingestion/csv_loader.py."""

    def test_can_handle_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        loader = CSVLoader()
        assert loader.can_handle(f) is True

    def test_cannot_handle_non_csv(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        loader = CSVLoader()
        assert loader.can_handle(f) is False

    def test_extract_chunks(self, tmp_path):
        f = tmp_path / "data.csv"
        with open(f, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["name", "value"])
            writer.writerow(["alpha", "1"])
            writer.writerow(["beta", "2"])

        loader = CSVLoader(chunk_size=1000)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0
        for chunk in chunks:
            assert hasattr(chunk, "content")
            assert len(chunk.content) > 0

    def test_detect_delimiter(self):
        loader = CSVLoader()
        # The delimiter detection counts occurrences; comma is the most common
        result = loader._detect_delimiter("a,b,c\n1,2,3\n")
        assert isinstance(result, str)
        assert result in (",", ";", "\t", "|")

    def test_is_numeric(self):
        loader = CSVLoader()
        assert loader._is_numeric("123") is True
        assert loader._is_numeric("12.34") is True
        assert loader._is_numeric("abc") is False
        assert loader._is_numeric("") is False


# --- JSON Loader tests ---

class TestJSONLoader:
    """Cover ingestion/json_loader.py."""

    def test_can_handle_json(self, tmp_path):
        f = tmp_path / "test.json"
        f.write_text('{"key": "value"}')
        loader = JSONLoader()
        assert loader.can_handle(f) is True

    def test_cannot_handle_non_json(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        loader = JSONLoader()
        assert loader.can_handle(f) is False

    def test_extract_chunks_flat(self, tmp_path):
        f = tmp_path / "flat.json"
        f.write_text(json.dumps({"name": "test", "value": 42, "active": True}))

        loader = JSONLoader(chunk_size=1000)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0
        content = " ".join(c.content for c in chunks)
        assert "test" in content or "name" in content

    def test_extract_chunks_nested(self, tmp_path):
        f = tmp_path / "nested.json"
        f.write_text(json.dumps({
            "user": {"name": "Alice", "age": 30},
            "items": ["apple", "banana"],
        }))

        loader = JSONLoader(chunk_size=1000)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0

    def test_extract_chunks_array(self, tmp_path):
        f = tmp_path / "array.json"
        f.write_text(json.dumps([
            {"id": 1, "name": "first"},
            {"id": 2, "name": "second"},
        ]))

        loader = JSONLoader(chunk_size=1000)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0

    def test_count_keys(self):
        loader = JSONLoader()
        assert loader._count_keys({"a": 1, "b": 2}) == 2
        assert loader._count_keys({"a": {"b": 1}}) == 2
        assert loader._count_keys([1, 2, 3]) == 0
        assert loader._count_keys("string") == 0


# --- Text Loader tests ---

class TestTextLoader:
    """Cover ingestion/text_loader.py."""

    def test_can_handle_txt(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_text("hello")
        loader = TextLoader()
        assert loader.can_handle(f) is True

    def test_can_handle_md(self, tmp_path):
        f = tmp_path / "test.md"
        f.write_text("# Hello")
        loader = TextLoader()
        assert loader.can_handle(f) is True

    def test_cannot_handle_csv(self, tmp_path):
        f = tmp_path / "test.csv"
        f.write_text("a,b\n1,2\n")
        loader = TextLoader()
        assert loader.can_handle(f) is False

    def test_extract_chunks_plain_text(self, tmp_path):
        f = tmp_path / "plain.txt"
        f.write_text("This is a test. " * 100, encoding="utf-8")

        loader = TextLoader(chunk_size=100, chunk_overlap=20)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0
        for chunk in chunks:
            assert hasattr(chunk, "content")
            assert len(chunk.content) > 0

    def test_extract_chunks_markdown(self, tmp_path):
        """Markdown chunking with section-aware splitting produces chunks."""
        f = tmp_path / "doc.md"
        # Document must be large enough to exceed min_chunk_size (default 100)
        f.write_text(
            "# Title\n\n"
            "This is the first section with enough content to exceed the minimum "
            "chunk size threshold. It contains meaningful text about the topic.\n\n"
            "## Subsection\n\n"
            "This subsection provides additional details that should also be chunked "
            "properly. The content here is substantial enough to form a valid chunk.\n\n"
            "```python\nprint('hello world')\n```\n",
            encoding="utf-8",
        )

        loader = TextLoader(chunk_size=500, chunk_overlap=50)

        async def _collect():
            return [chunk async for chunk in loader.extract_chunks(f)]

        chunks = asyncio.run(_collect())
        assert len(chunks) > 0
        content = " ".join(c.content for c in chunks)
        assert "Title" in content or "section" in content

    def test_extract_headers(self):
        loader = TextLoader()
        content = "# H1\nText\n## H2\nMore text\n### H3\nEnd"
        headers = loader._extract_headers(content)
        assert len(headers) == 3
        # Headers are dicts with 'text' and 'level' keys
        h0 = headers[0]
        text_val = h0.get("text", h0.get(1, "")) if isinstance(h0, dict) else h0[1]
        assert text_val == "H1"

    def test_extract_code_blocks(self):
        loader = TextLoader()
        content = "```python\nprint('hello')\n```\n\nText\n```\ncode\n```"
        blocks = loader._extract_code_blocks(content)
        assert len(blocks) == 2
        assert blocks[0].get("language") == "python"

    def test_extract_links(self):
        loader = TextLoader()
        content = "[Example](https://example.com) and [Google](https://google.com)"
        links = loader._extract_links(content)
        assert len(links) == 2
        assert links[0].get("url") == "https://example.com"
