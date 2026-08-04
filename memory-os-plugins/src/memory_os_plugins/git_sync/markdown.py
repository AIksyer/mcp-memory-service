"""Convert memory dictionaries to human-readable Markdown files.

This module provides functions to serialize a memory dict (as produced by
``_format_memory_response`` in mcp-memory-service) into a Markdown file with
YAML front matter, and to build a README index that lists all stored memories.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

# Maximum number of entries shown in the README index table.
README_MAX_ENTRIES = 100
# Maximum character length of the content preview column.
PREVIEW_LENGTH = 80


def memory_to_markdown(memory_dict: dict) -> str:
    """Render a memory dictionary as a Markdown string with YAML front matter.

    Args:
        memory_dict: A dictionary with keys ``content``, ``content_hash``,
            ``tags``, ``memory_type``, ``metadata``, ``created_at_iso`` and
            optional ``updated_at_iso`` (as produced by
            ``MemoryService._format_memory_response``).

    Returns:
        A Markdown string with a YAML front-matter block followed by the
        memory content and an optional ``## Metadata`` section.
    """
    content_hash: str = memory_dict.get("content_hash", "")
    memory_type: str = memory_dict.get("memory_type") or "observation"
    tags: List[str] = memory_dict.get("tags") or []
    created_at_iso: str = memory_dict.get("created_at_iso") or ""
    content: str = memory_dict.get("content", "")
    metadata: Dict[str, Any] = memory_dict.get("metadata") or {}

    tags_str = f"[{', '.join(tags)}]" if tags else "[]"

    # ``importance`` is a metadata field that deserves prominence in the
    # front matter; fall back to "N/A" when absent.
    importance = metadata.get("importance", "N/A")

    lines: List[str] = [
        "---",
        f"hash: {content_hash}",
        f"type: {memory_type}",
        f"tags: {tags_str}",
        f"created: {created_at_iso}",
        f"importance: {importance}",
        "---",
        "",
        content,
    ]

    # Build the ## Metadata section from non-empty metadata values.
    # Skip ``importance`` since it is already shown in the front matter.
    meta_entries = _format_metadata_entries(metadata, skip_keys={"importance"})
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
        A list of Markdown bullet-point strings, e.g.
        ``["- **quality_score**: 0.85", ...]``.  Returns an empty list if
        no entries qualify.
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


def get_md_path(content_hash: str, repo_path: Path) -> Path:
    """Return the Markdown file path for a memory inside a sync repo.

    Uses the first two characters of *content_hash* as a sub-directory name
    (similar to Git's object storage) to avoid placing too many files in a
    single directory.

    Args:
        content_hash: The SHA-256 content hash of the memory.
        repo_path: The root directory of the git sync repository.

    Returns:
        ``repo_path / "memories" / content_hash[:2] / f"{content_hash}.md"``
    """
    # Sanitize content_hash to prevent path traversal (e.g. "../../etc/passwd").
    # Valid hex hashes pass through unchanged; anything else is SHA-256 hashed.
    if not re.match(r'^[a-f0-9]+$', content_hash):
        content_hash = hashlib.sha256(content_hash.encode()).hexdigest()

    prefix = content_hash[:2] if len(content_hash) >= 2 else "00"
    return repo_path / "memories" / prefix / f"{content_hash}.md"


def markdown_to_memory_dict(md_text: str) -> dict:
    """Parse a Markdown file (with YAML front matter) back to a memory dict.

    This is the inverse of :func:`memory_to_markdown`.  It extracts the
    front-matter fields (hash, type, tags, created, importance) and the
    body content, returning a dict suitable for storage operations.

    Args:
        md_text: The full text content of a memory Markdown file.

    Returns:
        A dictionary with keys ``content``, ``content_hash``, ``tags``,
        ``memory_type``, ``metadata``, and ``created_at_iso``.
    """
    front_matter, body = _parse_front_matter(md_text)

    # Parse tags from "[tag1, tag2]" format.
    tags_str = front_matter.get("tags", "[]")
    tags_str = tags_str.strip().lstrip("[").rstrip("]")
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # Build metadata dict from importance (the only front-matter field
    # that maps to metadata rather than a top-level attribute).
    metadata: Dict[str, Any] = {}
    importance = front_matter.get("importance", "N/A")
    if importance and importance != "N/A":
        metadata["importance"] = importance

    return {
        "content": body.strip(),
        "content_hash": front_matter.get("hash", ""),
        "tags": tags,
        "memory_type": front_matter.get("type", "observation"),
        "metadata": metadata,
        "created_at_iso": front_matter.get("created", ""),
    }


def generate_readme_index(memories_dir: Path) -> str:
    """Generate a README.md index listing recent memories as a table.

    Scans *memories_dir* recursively for ``.md`` files, parses each file's
    YAML front matter for metadata (date, hash, tags), extracts a content
    preview, sorts by date (most recent first), and returns the full
    Markdown content for a ``README.md`` file.

    Args:
        memories_dir: Path to the ``memories/`` directory inside the sync
            repo (i.e. ``repo_path / "memories"``).

    Returns:
        A Markdown string suitable for writing to ``README.md``.
    """
    md_files = sorted(memories_dir.rglob("*.md"))
    entries: List[Tuple[str, str, str, str]] = []  # (date, hash, tags, preview)

    for md_file in md_files:
        front_matter, body = _parse_front_matter(md_file.read_text(encoding="utf-8"))
        date = front_matter.get("created", "")
        hash_val = front_matter.get("hash", md_file.stem)
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
        # Truncate fields that could break the table layout.
        hash_short = hash_val[:12] if len(hash_val) > 12 else hash_val
        lines.append(
            f"| {date} | `{hash_short}` | {tags_val} | {preview} |"
        )

    return "\n".join(lines) + "\n"


def _parse_front_matter(text: str) -> Tuple[Dict[str, str], str]:
    """Split a Markdown file into YAML front-matter dict and body.

    Args:
        text: The full content of a Markdown file.

    Returns:
        A tuple ``(front_matter, body)`` where *front_matter* is a dict of
        key-value pairs from the YAML block and *body* is the remaining
        Markdown text.  If no front matter is found, returns ``({}, text)``.
    """
    if not text.startswith("---"):
        return {}, text

    # Find the closing ``---`` of the front-matter block.
    match = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if not match:
        return {}, text

    raw_fm = match.group(1)
    body = match.group(2)

    front_matter: Dict[str, str] = {}
    for line in raw_fm.splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            front_matter[key.strip()] = value.strip()

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
        text = text[:length] + "…"
    # Escape pipe characters so they don't break the table.
    text = text.replace("|", "\\|")
    return text
