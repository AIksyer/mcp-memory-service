"""Smart tagger plugin — auto-tags memories before storage and filters
retrieval results by project context.

Hooks:
    - ``before_store``: analyzes memory content, injects auto-generated tags
      (project:xxx, type:bug-fix, date:YYYY-MM).
    - ``on_retrieve``: if the query mentions a project path, boosts results
      that have the matching ``project:`` tag.
"""

from __future__ import annotations

import datetime
import logging
import re
from typing import Any, List

from .config import SmartTaggerConfig, load_config

logger = logging.getLogger(__name__)

_config: SmartTaggerConfig | None = None

# Windows path pattern: drive letter + path, e.g. G:\Project\my-project
_WIN_PATH_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\s\\]+\\)*([^\s\\]+)", re.IGNORECASE
)
# POSIX path pattern: /path/to/project-name
_POSIX_PATH_RE = re.compile(r"/(?:[^\s/]+/)+([^\s/]+)")

# Bug-fix keyword patterns (case-insensitive).
_BUG_FIX_PATTERNS = [
    re.compile(r"fix(?:ed|ing)?\s*(?:a)?\s*bug", re.IGNORECASE),
    re.compile(r"\u4fee\u590d\u4e86?\s*bug", re.IGNORECASE),
    re.compile(r"bug\s*fix", re.IGNORECASE),
]

# Decision/learning patterns.
_DECISION_PATTERNS = [
    re.compile(r"decided?\s+to", re.IGNORECASE),
    re.compile(r"\u51b3\u5b9a", re.IGNORECASE),
]
_LEARNING_PATTERNS = [
    re.compile(r"learned?\s+(?:that|from)", re.IGNORECASE),
    re.compile(r"\u5b66\u5230\u4e86", re.IGNORECASE),
]

# Pattern to extract project name from a project: tag in query context.
_PROJECT_TAG_RE = re.compile(r"project:([a-zA-Z0-9_-]+)")


def register(ctx) -> None:
    """Plugin registration entry point.

    Subscribes to ``before_store`` and ``on_retrieve`` hooks if enabled.

    Args:
        ctx: PluginContext from mcp_memory_service.
    """
    global _config
    _config = load_config()

    if not _config.enabled:
        logger.info("smart_tagger plugin is disabled by configuration")
        return

    ctx.on("before_store", before_store_handler)
    ctx.on("on_retrieve", on_retrieve_handler)

    logger.info("smart_tagger plugin registered")


# --------------------------------------------------------------------------- #
#  Tag extraction logic
# --------------------------------------------------------------------------- #

def _extract_project_tags(content: str) -> List[str]:
    """Extract project tags from path patterns in content.

    Scans for Windows and POSIX path patterns and extracts the last
    path component as a project name.

    Args:
        content: Memory content text.

    Returns:
        List of ``project:xxx`` tags (deduplicated, max 3).
    """
    tags: list[str] = []
    seen: set[str] = set()

    for pattern in (_WIN_PATH_RE, _POSIX_PATH_RE):
        for match in pattern.finditer(content):
            project_name = match.group(1).lower()
            tag = f"project:{project_name}"
            if tag not in seen:
                seen.add(tag)
                tags.append(tag)
            if len(tags) >= 3:
                return tags

    return tags


def _extract_type_tags(content: str) -> List[str]:
    """Extract type tags from keyword patterns in content.

    Detects bug-fix, decision, and learning patterns.

    Args:
        content: Memory content text.

    Returns:
        List of ``type:xxx`` tags.
    """
    tags: list[str] = []

    for pattern in _BUG_FIX_PATTERNS:
        if pattern.search(content):
            tags.append("type:bug-fix")
            break

    for pattern in _DECISION_PATTERNS:
        if pattern.search(content):
            tags.append("type:decision")
            break

    for pattern in _LEARNING_PATTERNS:
        if pattern.search(content):
            tags.append("type:learning")
            break

    return tags


def _extract_date_tag() -> str:
    """Generate a date tag from the current date.

    Returns:
        ``date:YYYY-MM`` string.
    """
    now = datetime.datetime.now(datetime.timezone.utc)
    return f"date:{now.year:04d}-{now.month:02d}"


def auto_tag(content: str) -> List[str]:
    """Generate auto-tags for a memory content string.

    Args:
        content: Memory content text.

    Returns:
        List of auto-generated tags.
    """
    tags: list[str] = []

    if _config is None:
        return tags

    if _config.inject_project_tag:
        tags.extend(_extract_project_tags(content))

    if _config.inject_type_tag:
        tags.extend(_extract_type_tags(content))

    if _config.inject_date_tag:
        tags.append(_extract_date_tag())

    return tags


# --------------------------------------------------------------------------- #
#  Hook handlers
# --------------------------------------------------------------------------- #

async def before_store_handler(memory_dict: dict) -> dict | None:
    """Handle before_store hook.

    Injects auto-generated tags into the memory's tag list.  Existing
    tags are preserved; only new tags are appended.

    Args:
        memory_dict: Memory dict with ``content``, ``tags``, etc.

    Returns:
        Modified memory dict with updated tags, or None if no changes.
    """
    if _config is None or not _config.enabled:
        return None

    content = memory_dict.get("content", "")
    existing_tags: list[str] = list(memory_dict.get("tags") or [])

    new_tags = auto_tag(content)
    existing_set = set(existing_tags)
    added = [t for t in new_tags if t not in existing_set]

    if not added:
        return None

    result = dict(memory_dict)
    result["tags"] = existing_tags + added
    logger.debug("smart_tagger injected %d tags: %s", len(added), added)
    return result


async def on_retrieve_handler(query: str, results: list[dict]) -> list[dict] | None:
    """Handle on_retrieve hook.

    If the query contains a project path or ``project:xxx`` tag, boosts
    results that have the matching project tag by moving them to the
    front of the list.

    Args:
        query: The search query string.
        results: List of memory result dicts.

    Returns:
        Reordered results list, or None if no reordering was needed.
    """
    if _config is None or not _config.enabled:
        return None

    # Extract project name from query.
    project_name = None

    # Check for explicit project:xxx tag in query.
    tag_match = _PROJECT_TAG_RE.search(query)
    if tag_match:
        project_name = tag_match.group(1).lower()
    else:
        # Check for path patterns in the query.
        for pattern in (_WIN_PATH_RE, _POSIX_PATH_RE):
            match = pattern.search(query)
            if match:
                project_name = match.group(1).lower()
                break

    if not project_name:
        return None

    project_tag = f"project:{project_name}"

    # Partition results: tagged first, then others.
    tagged: list[dict] = []
    untagged: list[dict] = []

    for r in results:
        r_tags = r.get("tags") or []
        if project_tag in r_tags:
            tagged.append(r)
        else:
            untagged.append(r)

    if not tagged:
        return None

    logger.debug(
        "smart_tagger boosted %d/%d results for project:%s",
        len(tagged), len(results), project_name,
    )
    return tagged + untagged
