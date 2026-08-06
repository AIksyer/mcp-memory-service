"""Smart tagger plugin — registers before_store + on_retrieve hooks.

The ``before_store`` hook fires BEFORE memory storage, so tag modifications
are persisted to the database.  This fixes the bug in the legacy example
plugin which used ``on_store`` (post-storage, changes lost).

The ``on_retrieve`` hook boosts mistake-note/error-replay results and
optionally prioritizes same-project memories.
"""

from __future__ import annotations

import logging

from .config import SmartTaggerConfig, load_config
from .tagger import auto_generate_tags, extract_project_from_content, get_project_name, inject_project_tag

logger = logging.getLogger(__name__)

# Global state — initialised by register(), read by hook handlers.
_config: SmartTaggerConfig | None = None


def register(ctx) -> None:
    """Plugin registration entry point.

    Called automatically by PluginRegistry.discover_and_register().
    Subscribes to ``before_store`` and ``on_retrieve`` hooks if enabled.

    Args:
        ctx: PluginContext from mcp_memory_service.  Provides ``on(hook, fn)``
            for hook subscription, plus ``storage`` and ``service`` references.
    """
    global _config

    _config = load_config()

    if not _config.enabled:
        logger.info("smart_tagger plugin is disabled by configuration")
        return

    ctx.on("before_store", before_store_handler)
    ctx.on("on_retrieve", on_retrieve_handler)

    logger.info(
        "smart_tagger plugin registered (auto_tags=%s, project_filter=%s, mistake_boost=%.2f)",
        _config.auto_tags,
        _config.project_filter,
        _config.mistake_boost,
    )


# --------------------------------------------------------------------------- #
#  Hook handlers
# --------------------------------------------------------------------------- #

async def before_store_handler(memory_dict: dict) -> dict:
    """Handle before_store hook — auto-tag memory BEFORE it is stored.

    **Critical**: must return the modified memory_dict.  The before_store hook
    is chain-processed — the returned dict's ``tags`` and ``metadata`` override
    the final values used to construct the Memory object.

    Generates content-based tags, injects project tag, and merges with
    any existing tags (deduplicates, does not overwrite).

    Args:
        memory_dict: Pre-store dict with ``content``, ``content_hash``,
            ``tags``, ``memory_type``, ``metadata``.

    Returns:
        Modified memory_dict with auto-generated tags merged in.
    """
    if _config is None:
        return memory_dict
    if not _config.enabled:
        return None

    try:
        if _config.auto_tags:
            # Generate tags and merge into memory_dict.
            new_tags = auto_generate_tags(memory_dict)
            memory_dict["tags"] = new_tags

        # Inject project tag (from config or env or cwd).
        project = get_project_name(_config.project_name)
        inject_project_tag(memory_dict, project)

        logger.debug(
            "before_store: tagged memory %s with %d tags",
            memory_dict.get("content_hash", "")[:12],
            len(memory_dict.get("tags", [])),
        )
    except Exception as exc:
        logger.warning("smart_tagger before_store failed: %s", exc)

    return memory_dict


async def on_retrieve_handler(query: str, results: list[dict]) -> list[dict]:
    """Handle on_retrieve hook — boost relevant results and optionally filter.

    Two behaviors:
    1. **Mistake-note boost**: results tagged ``mistake-note`` or ``error-replay``
       get a configurable score boost, then results are re-sorted.
    2. **Project filter** (if enabled): results tagged with the current project
       are boosted to the top.  Cross-project results are still returned
       (not filtered out) to avoid blocking cross-project retrieval.

    Args:
        query: The search query string.
        results: List of result dicts, each with ``tags``, ``similarity``
            (or ``score``), etc.

    Returns:
        Re-ranked (and optionally project-prioritized) results list.
    """
    if _config is None or not results:
        return results

    try:
        # 1. Boost mistake-note / error-replay results.
        for result in results:
            tags = result.get("tags", [])
            if "mistake-note" in tags or "error-replay" in tags:
                current_score = result.get("similarity", result.get("score", 0.5))
                result["similarity"] = min(1.0, current_score + _config.mistake_boost)

        # 2. Query-based project filtering: extract project from query string.
        query_project = extract_project_from_content(query)
        if query_project:
            project_tag = f"project:{query_project}"
            same_project = [r for r in results if project_tag in r.get("tags", [])]
            other = [r for r in results if project_tag not in r.get("tags", [])]
            if same_project:
                same_project.sort(
                    key=lambda r: r.get("similarity", r.get("score", 0)),
                    reverse=True,
                )
                other.sort(
                    key=lambda r: r.get("similarity", r.get("score", 0)),
                    reverse=True,
                )
                results = same_project + other
                logger.debug(
                    "on_retrieve: query-based project filter (%s)", query_project
                )
                return results

        # 3. Config-based project filtering (if enabled).
        if _config.project_filter:
            project = get_project_name(_config.project_name)
            project_tag = f"project:{project}" if project else ""

            if project_tag:
                same_project = []
                other = []
                for result in results:
                    tags = result.get("tags", [])
                    if project_tag in tags:
                        same_project.append(result)
                    else:
                        other.append(result)

                if same_project:
                    # Sort each partition by score, then concatenate.
                    same_project.sort(
                        key=lambda r: r.get("similarity", r.get("score", 0)),
                        reverse=True,
                    )
                    other.sort(
                        key=lambda r: r.get("similarity", r.get("score", 0)),
                        reverse=True,
                    )
                    results = same_project + other
                    logger.debug(
                        "on_retrieve: config-based project filter (%s)", project
                    )
                    return results

        # 4. Sort by boosted scores.
        results.sort(
            key=lambda r: r.get("similarity", r.get("score", 0)),
            reverse=True,
        )

        logger.debug("on_retrieve: re-ranked %d results", len(results))
    except Exception as exc:
        logger.warning("smart_tagger on_retrieve failed: %s", exc)

    return results
