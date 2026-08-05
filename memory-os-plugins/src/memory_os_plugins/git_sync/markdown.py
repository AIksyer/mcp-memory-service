"""Convert memory records to human-readable Markdown files.

This module provides functions and a class to serialize a memory dict (as
produced by ``_format_memory_response`` in mcp-memory-service) into a Markdown
file with YAML front matter, and to build a README index that lists all
stored memories.

File organization: ``memories/YYYY/MM/mem-<short_id>.md``
Front matter: ``id, content, tags, created_at, updated_at, embedding_hash?``
Body: content text + ``## Tags`` section
All files are written UTF-8 without BOM.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Maximum number of entries shown in the README index table.
README_MAX_ENTRIES = 100
# Maximum character length of the content preview column.
PREVIEW_LENGTH = 80
# Length of short ID used in filenames.
SHORT_ID_LENGTH = 8


class MemoryToMarkdown:
    """Convert Memory records to Markdown files with YAML front matter.

    Files are organized as ``memories/YYYY/MM/mem-<short_id>.md`` where
    *YYYY* and *MM* are derived from the memory's ``created_at_iso``.

    Front matter fields:
        - ``id`` — the content hash
        - ``content`` — the memory content (block scalar)
        - ``tags`` — list of tags
        - ``created_at`` — ISO 8601 creation timestamp
        - ``updated_at`` — ISO 8601 update timestamp
        - ``embedding_hash`` — optional hash of the embedding vector
        - ``type`` — optional memory type

    The body contains the memory content followed by a ``## Tags`` section.
    """

    def convert(self, memory: dict, base_dir: str | Path) -> Path:
        """Convert a memory dict to a Markdown file and write it to disk.

        Args:
            memory: Memory dict with ``content``, ``content_hash``,
                ``tags``, ``created_at_iso``, ``updated_at_iso``, etc.
            base_dir: Base directory for the markdown file tree.

        Returns:
            Path to the written file.
        """
        md_content = memory_to_markdown(memory)
        file_path = self.get_path(memory, base_dir)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        # UTF-8 without BOM — Python's default for encoding="utf-8".
        file_path.write_text(md_content, encoding="utf-8")
        return file_path

    def to_markdown(self, memory: dict) -> str:
        """Render a memory dict as a Markdown string.

        Args:
            memory: Memory dict.

        Returns:
            Markdown string with YAML front matter and body.
        """
        return memory_to_markdown(memory)

    def get_path(self, memory: dict, base_dir: str | Path) -> Path:
        """Compute the file path for a memory.

        Uses ``created_at_iso`` to derive ``YYYY/MM`` subdirectories.
        Falls back to the current date if the timestamp is missing or
        unparseable.

        Args:
            memory: Memory dict (must contain ``content_hash`` and
                ideally ``created_at_iso``).
            base_dir: Base directory for the markdown file tree.

        Returns:
            ``base_dir / memories / YYYY / MM / mem-<short_id>.md``
        """
        return get_md_path(memory, base_dir)


def convert(memory: dict, base_dir: str | Path) -> Path:
    """Standalone function: convert a memory dict to a Markdown file.

    Args:
        memory: Memory dict with ``content``, ``content_hash``,
            ``tags``, ``created_at_iso``, etc.
        base_dir: Base directory for the markdown file tree.

    Returns:
        Path to the written file.
    """
    return MemoryToMarkdown().convert(memory, base_dir)


def memory_to_markdown(memory_dict: dict) -> str:
    """Render a memory dictionary as a Markdown string with YAML front matter.

    Args:
        memory_dict: A dictionary with keys ``content``, ``content_hash``,
            ``tags``, ``memory_type``, ``metadata``, ``created_at_iso``,
            ``updated_at_iso``, and optional ``embedding``.

    Returns:
        A Markdown string with a YAML front-matter block followed by the
        memory content and a ``## Tags`` section.
    """
    content_hash: str = memory_dict.get("content_hash", "")
    content: str = memory_dict.get("content", "")
    tags: List[str] = memory_dict.get("tags") or []
    created_at: str = memory_dict.get("created_at_iso") or ""
    updated_at: str = memory_dict.get("updated_at_iso") or ""
    memory_type: str | None = memory_dict.get("memory_type")
    metadata: Dict[str, Any] = memory_dict.get("metadata") or {}

    # Compute embedding hash if embedding vector is present.
    embedding_hash = ""
    embedding = memory_dict.get("embedding")
    if embedding:
        embedding_hash = hashlib.sha256(
            json.dumps(embedding).encode()
        ).hexdigest()[:16]

    tags_str = f"[{', '.join(tags)}]" if tags else "[]"

    lines: List[str] = ["---"]

    # Front matter: id, content, tags, created_at, updated_at, embedding_hash?
    lines.append(f"id: {content_hash}")

    # Content as YAML block scalar for multi-line safety.
    lines.append("content: |")
    if content:
        for content_line in content.split("\n"):
            lines.append(f"  {content_line}")
    else:
        lines.append("  ")

    lines.append(f"tags: {tags_str}")
    lines.append(f"created_at: {created_at}")
    lines.append(f"updated_at: {updated_at}")

    if embedding_hash:
        lines.append(f"embedding_hash: {embedding_hash}")

    if memory_type:
        lines.append(f"type: {memory_type}")

    lines.append("---")
    lines.append("")

    # Body: content text
    lines.append(content)

    # Tags section
    if tags:
        lines.append("")
        lines.append("## Tags")
        lines.append(" ".join(f"#{t}" for t in tags))

    # Metadata section (for fields not represented in front matter)
    meta_entries = _format_metadata_entries(
        metadata,
        skip_keys={"embedding"},
    )
    if meta_entries:
        lines.append("")
        lines.append("## Metadata")
        lines.extend(meta_entries)

    return "\n".join(lines) + "\n"


def _format_metadata_entries(
    metadata: Dict[str, Any], skip_keys: set | None = None
) -> List[str]:
    """Format metadata dict into Markdown bullet list items.

    Only non-empty values are included.  Keys in *skip_keys* are omitted.

    Args:
        metadata: The metadata dictionary from a memory dict.
        skip_keys: Set of keys to exclude from the output.

    Returns:
        A list of Markdown bullet-point strings.  Returns an empty list
        if no entries qualify.
    """
    if not metadata:
        return []

    skip = skip_keys or set()
    entries: List[str] = []
    for key, value in metadata.items():
        if key in skip:
            continue
        if value is None or value == "" or value == [] or value == {}:
            continue
        entries.append(f"- **{key}**: {value}")
    return entries


def get_md_path(memory: dict, base_dir: str | Path) -> Path:
    """Return the Markdown file path for a memory inside a sync repo.

    Uses ``created_at_iso`` to derive ``YYYY/MM`` subdirectories.
    Falls back to ``1970/01`` if the timestamp is missing or unparseable.

    Args:
        memory: Memory dict (must contain ``content_hash`` and ideally
            ``created_at_iso``).
        base_dir: Base directory for the markdown file tree.

    Returns:
        ``base_dir / memories / YYYY / MM / mem-<short_id>.md``
    """
    base = Path(base_dir)
    content_hash: str = memory.get("content_hash", "") if isinstance(memory, dict) else str(memory)

    # Sanitize content_hash to prevent path traversal.
    if not re.match(r"^[a-fA-F0-9]+$", content_hash):
        content_hash = hashlib.sha256(content_hash.encode()).hexdigest()

    short_id = content_hash[:SHORT_ID_LENGTH] if len(content_hash) >= SHORT_ID_LENGTH else content_hash

    # Extract YYYY/MM from created_at_iso.
    created_at_iso = ""
    if isinstance(memory, dict):
        created_at_iso = memory.get("created_at_iso") or ""
    year, month = _parse_year_month(created_at_iso)

    return base / "memories" / year / month / f"mem-{short_id}.md"


def find_md_path(content_hash: str, base_dir: str | Path) -> Path | None:
    """Find the Markdown file for a memory by content_hash.

    Searches the ``memories/`` directory for a file whose name starts with
    ``mem-<short_id>`` and whose front-matter ``id`` matches *content_hash*.

    Args:
        content_hash: The SHA-256 content hash of the memory.
        base_dir: Base directory for the markdown file tree.

    Returns:
        Path to the file if found, ``None`` otherwise.
    """
    base = Path(base_dir)
    memories_dir = base / "memories"
    if not memories_dir.exists():
        return None

    short_id = content_hash[:SHORT_ID_LENGTH] if len(content_hash) >= SHORT_ID_LENGTH else content_hash
    pattern = f"mem-{short_id}*.md"

    for md_file in memories_dir.rglob(pattern):
        try:
            text = md_file.read_text(encoding="utf-8")
            front_matter, _ = _parse_front_matter(text)
            if front_matter.get("id", "") == content_hash:
                return md_file
        except Exception:
            continue

    return None


def markdown_to_memory_dict(md_text: str) -> dict:
    """Parse a Markdown file (with YAML front matter) back to a memory dict.

    This is the inverse of :func:`memory_to_markdown`.  It extracts the
    front-matter fields (id, tags, created_at, updated_at, type,
    embedding_hash) and the body content.

    Args:
        md_text: The full text content of a memory Markdown file.

    Returns:
        A dictionary with keys ``content``, ``content_hash``, ``tags``,
        ``memory_type``, ``metadata``, ``created_at_iso``, and
        ``updated_at_iso``.
    """
    front_matter, body = _parse_front_matter(md_text)

    # Parse tags from "[tag1, tag2]" format.
    tags_str = front_matter.get("tags", "[]")
    tags_str = tags_str.strip().lstrip("[").rstrip("]")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # Build metadata dict from embedding_hash and other metadata.
    metadata: Dict[str, Any] = {}
    embedding_hash = front_matter.get("embedding_hash", "")
    if embedding_hash:
        metadata["embedding_hash"] = embedding_hash

    # Backward compat: accept both new (id, created_at, updated_at)
    # and legacy (hash, created, updated) front-matter field names.
    content_hash = front_matter.get("id", "") or front_matter.get("hash", "")
    created_at = front_matter.get("created_at", "") or front_matter.get("created", "")
    updated_at = front_matter.get("updated_at", "") or front_matter.get("updated", "")

    # Extract content from body — everything before ## Tags or ## Metadata.
    content = body
    for marker in ["\n## Tags", "\n## Metadata"]:
        idx = content.find(marker)
        if idx != -1:
            content = content[:idx]
    content = content.strip()

    return {
        "content": content,
        "content_hash": content_hash,
        "tags": tags,
        "memory_type": front_matter.get("type") or None,
        "metadata": metadata,
        "created_at_iso": created_at,
        "updated_at_iso": updated_at,
    }


def generate_readme_index(memories_dir: Path) -> str:
    """Generate a README.md index listing recent memories as a table.

    Scans *memories_dir* recursively for ``.md`` files, parses each file's
    YAML front matter for metadata (date, id, tags), extracts a content
    preview, sorts by date (most recent first), and returns the full
    Markdown content for a ``README.md`` file.

    Args:
        memories_dir: Path to the ``memories/`` directory inside the sync
            repo.

    Returns:
        A Markdown string suitable for writing to ``README.md``.
    """
    md_files = sorted(memories_dir.rglob("*.md"))
    entries: List[Tuple[str, str, str, str]] = []  # (date, hash, tags, preview)

    for md_file in md_files:
        front_matter, body = _parse_front_matter(md_file.read_text(encoding="utf-8"))
        date = front_matter.get("created_at", "")
        hash_val = front_matter.get("id", md_file.stem)
        tags_val = front_matter.get("tags", "[]")
        preview = _make_preview(body)
        entries.append((date, hash_val, tags_val, preview))

    # Sort by date descending (most recent first).
    entries.sort(key=lambda e: e[0], reverse=True)
    entries = entries[:README_MAX_ENTRIES]

    lines: List[str] = [
        "# Memory Index",
        "",
        f"Total memories: {len(md_files)}",
        "",
        "| Date | Hash | Tags | Preview |",
        "|------|------|------|---------|",
    ]

    for date, hash_val, tags_val, preview in entries:
        hash_short = hash_val[:12] if len(hash_val) > 12 else hash_val
        lines.append(
            f"| {date} | `{hash_short}` | {tags_val} | {preview} |"
        )

    return "\n".join(lines) + "\n"


def _parse_year_month(iso_str: str) -> Tuple[str, str]:
    """Extract year and month from an ISO 8601 string.

    Args:
        iso_str: ISO 8601 timestamp (e.g. ``2026-08-03T10:00:00Z``).

    Returns:
        Tuple ``(year, month)`` as zero-padded strings, e.g.
        ``("2026", "08")``.  Returns ``("1970", "01")`` if parsing fails.
    """
    if not iso_str:
        return "1970", "01"
    # Match YYYY-MM from the beginning of the string.
    match = re.match(r"^(\d{4})-(\d{2})", iso_str)
    if match:
        return match.group(1), match.group(2)
    return "1970", "01"


def _parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """Split a Markdown file into YAML front-matter dict and body.

    Handles block scalars (``key: |``) by collecting indented lines.

    Args:
        text: The full content of a Markdown file.

    Returns:
        A tuple ``(front_matter, body)`` where *front_matter* is a dict
        of key-value pairs and *body* is the remaining Markdown text.
        If no front matter is found, returns ``({}, text)``.
    """
    if not text.startswith("---"):
        return {}, text

    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    raw_fm = match.group(1)
    body = match.group(2)

    front_matter: Dict[str, str] = {}
    lines = raw_fm.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if ":" in line:
            key, _, value = line.partition(":")
            key = key.strip()
            value = value.strip()

            # Handle block scalar (e.g. content: |)
            if value == "|":
                block_lines: List[str] = []
                i += 1
                while i < len(lines) and (lines[i].startswith("  ") or lines[i] == ""):
                    if lines[i].startswith("  "):
                        block_lines.append(lines[i][2:])
                    else:
                        block_lines.append("")
                    i += 1
                front_matter[key] = "\n".join(block_lines).strip()
                continue

            front_matter[key] = value
        i += 1

    return front_matter, body


def _make_preview(body: str, length: int = PREVIEW_LENGTH) -> str:
    """Create a short single-line preview from Markdown body text.

    Strips Markdown formatting, collapses whitespace, and truncates to
    *length* characters.

    Args:
        body: The body text of a memory Markdown file (without front matter).
        length: Maximum number of characters in the preview.

    Returns:
        A cleaned, truncated preview string.
    """
    # Remove Markdown headings and extra whitespace.
    text = re.sub(r"^#+\s*", "", body, flags=re.MULTILINE)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > length:
        text = text[:length] + "\u2026"
    # Escape pipe characters so they don't break the table.
    text = text.replace("|", "\\|")
    return text
