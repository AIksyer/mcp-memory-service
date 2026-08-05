"""Tag generation logic for the smart_tagger plugin.

Provides:
- ``auto_generate_tags(memory_dict)`` — content-based tag extraction + merge
- ``inject_project_tag(memory_dict, project_name)`` — project-level tagging
- ``extract_project_from_content(content)`` — path-based project detection
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

# --------------------------------------------------------------------------- #
#  Tag rules: (compiled regex, tag to add)
# --------------------------------------------------------------------------- #

TAG_RULES: list[tuple[re.Pattern, str]] = [
    # --- Memory type detection (extended) ---
    (re.compile(r"\b(decided|decision|chose|picked|choosing)\b", re.I), "decision"),
    (re.compile(r"\b(bug|fix|error|crash|broke|broken|failure)\b", re.I), "bug"),
    (re.compile(r"\b(fix(es|ed)?|resolved|patched|hotfix)\b", re.I), "bug-fix"),
    (re.compile(r"\b(convention|pattern|always|never|must|should)\b", re.I), "convention"),
    (re.compile(r"\b(learned|lesson|mistake|wrong|pitfall|gotcha)\b", re.I), "learning"),
    (re.compile(r"\b(prefers?|preference|like|dislike|workflow)\b", re.I), "preference"),
    (re.compile(r"\b(reference|documentation|docs?|manual|spec)\b", re.I), "reference"),
    # --- Tech stack tags ---
    (re.compile(r"\b(postgresql|postgres|redis|sqlite|mysql|database|db)\b", re.I), "database"),
    (re.compile(r"\b(docker|k8s|kubernetes|helm|deploy|terraform|ansible)\b", re.I), "infra"),
    (re.compile(r"\b(react|vue|angular|frontend|css|html|svelte)\b", re.I), "frontend"),
    (re.compile(r"\b(fastapi|spring|express|backend|api|endpoint|flask|django)\b", re.I), "backend"),
    (re.compile(r"\b(auth|oauth|jwt|token|password|credential|security)\b", re.I), "security"),
    (re.compile(r"\b(test|pytest|jest|mocha|coverage|unit.?test)\b", re.I), "testing"),
]

# Path patterns for project name extraction.
# Windows: drive letter + path segments
_WIN_PATH_RE = re.compile(r"[A-Z]:\\([^:\s]+)", re.IGNORECASE)
# Unix: /home/user/xxx or /Users/xxx
_UNIX_PATH_RE = re.compile(r"/(?:home|Users)/[^/]+/(.+)")
# Generic: after "path:" or "directory:" or "project:" prefix
_PREFIX_RE = re.compile(r"(?:path|directory|project)[:\s]+([^\s,]+)", re.I)

# Directories to skip when extracting project names from paths.
_SKIP_DIRS = frozenset({
    "src", "lib", "test", "tests", "docs", "doc", "config", "scripts",
    "node_modules", ".git", "venv", ".venv", "build", "dist", "tmp",
    "assets", "bin", "pkg", "vendor",
})


def _is_file_segment(seg: str) -> bool:
    """Check if a path segment looks like a file (has a short extension)."""
    return bool(re.search(r"\.\w{1,5}$", seg))


def _extract_project_from_segments(segments: list[str]) -> str | None:
    """Return the last meaningful (non-skip, non-file) path segment.

    Args:
        segments: Path segments split by separator.

    Returns:
        Project name, or None if no meaningful segment found.
    """
    for seg in reversed(segments):
        name = seg.strip().strip("\"'()[]")
        if not name:
            continue
        if name.lower() in _SKIP_DIRS:
            continue
        if _is_file_segment(name):
            continue
        return name
    return None


def extract_project_from_content(content: str) -> str | None:
    """Extract a project name from memory content by searching for path patterns.

    Scans content for Windows paths (``G:\\Project\\xxx``), Unix paths
    (``/home/user/xxx``), and explicit ``project:`` / ``path:`` prefixes.
    Returns the last meaningful path segment (not a common subdirectory
    or file).  When multiple paths are found, the last match wins.

    Args:
        content: Memory content string.

    Returns:
        Project name if found, or None.
    """
    candidates: list[str] = []

    # Windows paths: G:\Project\MyApp\file.py
    for m in _WIN_PATH_RE.finditer(content):
        segments = m.group(1).split("\\")
        name = _extract_project_from_segments(segments)
        if name:
            candidates.append(name)

    # Unix paths: /home/user/myapp/src/main.py
    for m in _UNIX_PATH_RE.finditer(content):
        segments = m.group(1).split("/")
        name = _extract_project_from_segments(segments)
        if name:
            candidates.append(name)

    # Explicit prefix: project: xxx, path: xxx, directory: xxx
    for m in _PREFIX_RE.finditer(content):
        raw = m.group(1).strip().strip("\"'()[]")
        if "\\" in raw:
            segments = raw.split("\\")
            name = _extract_project_from_segments(segments)
        elif "/" in raw:
            segments = raw.split("/")
            name = _extract_project_from_segments(segments)
        elif raw and raw.lower() not in _SKIP_DIRS and not _is_file_segment(raw):
            name = raw
        else:
            name = None
        if name:
            candidates.append(name)

    if candidates:
        return candidates[-1]
    return None


def _extract_date_tag(memory_dict: dict) -> str | None:
    """Extract a ``date:YYYY-MM`` tag from the memory's timestamp.

    Uses ``created_at_iso`` if present, otherwise falls back to current time.

    Args:
        memory_dict: Memory dict with optional ``created_at_iso`` field.

    Returns:
        Date tag string (e.g. ``date:2026-08``) or None.
    """
    iso_str = memory_dict.get("created_at_iso", "")
    if iso_str:
        try:
            # Parse ISO timestamp, extract year-month.
            dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
            return f"date:{dt.year:04d}-{dt.month:02d}"
        except (ValueError, TypeError):
            pass

    # Fallback: current date.
    now = datetime.now(timezone.utc)
    return f"date:{now.year:04d}-{now.month:02d}"


def auto_generate_tags(memory_dict: dict) -> list[str]:
    """Generate tags from memory content using pattern matching.

    Applies TAG_RULES to detect content categories, extracts project name
    from path patterns, and generates a date tag.  Merges with any existing
    tags (deduplicates, does not overwrite).

    Args:
        memory_dict: Memory dict with ``content``, optional ``tags``,
            and optional ``created_at_iso``.

    Returns:
        Merged list of tags (existing + auto-generated, deduplicated).
    """
    content = memory_dict.get("content", "")
    existing_tags = list(memory_dict.get("tags", []))
    tag_set: set[str] = set(existing_tags)

    # 1. Apply content-based tag rules.
    for pattern, tag in TAG_RULES:
        if pattern.search(content):
            tag_set.add(tag)

    # 2. Extract project name from content paths.
    project = extract_project_from_content(content)
    if project:
        tag_set.add(f"project:{project}")

    # 3. Generate date tag.
    date_tag = _extract_date_tag(memory_dict)
    if date_tag:
        tag_set.add(date_tag)

    return list(tag_set)


def inject_project_tag(memory_dict: dict, project_name: str) -> dict:
    """Inject a ``project:{project_name}`` tag into a memory dict.

    If ``project_name`` is empty, no tag is added.  Existing project tags
    are preserved; the new tag is only added if not already present.

    Args:
        memory_dict: Memory dict to modify (modified in-place).
        project_name: Project name to inject.

    Returns:
        The modified memory_dict (same object, for chaining).
    """
    if not project_name:
        return memory_dict

    tag = f"project:{project_name}"
    tags = list(memory_dict.get("tags", []))

    if tag not in tags:
        tags.append(tag)

    memory_dict["tags"] = tags
    return memory_dict


def get_project_name(config_project_name: str = "") -> str:
    """Determine the current project name.

    Priority:
    1. ``MEMORY_OS_PROJECT_NAME`` environment variable
    2. ``config_project_name`` from config file
    3. Current working directory's basename

    Args:
        config_project_name: Project name from config file.

    Returns:
        The resolved project name.
    """
    env_name = os.environ.get("MEMORY_OS_PROJECT_NAME", "")
    if env_name:
        return env_name

    if config_project_name:
        return config_project_name

    # Fallback: cwd basename.
    return os.path.basename(os.getcwd())
