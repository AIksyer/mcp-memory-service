"""Git sync plugin — registers on_store/on_delete hooks to sync memories to git.

The plugin converts each memory to a Markdown file (via markdown.py) and
enqueues batch git commits (via git_ops.py).  All sync work is done in
background asyncio tasks — hooks return immediately without blocking.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .config import GitSyncConfig, load_config
from .git_ops import GitSyncQueue
from .markdown import generate_readme_index, get_md_path, memory_to_markdown

logger = logging.getLogger(__name__)

# Global state — initialised by register(), read by hook handlers.
_config: GitSyncConfig | None = None
_sync_queue: GitSyncQueue | None = None


def register(ctx) -> None:
    """Plugin registration entry point.

    Called automatically by PluginRegistry.discover_and_register().
    Subscribes to ``on_store`` and ``on_delete`` hooks if the plugin is enabled.

    Args:
        ctx: PluginContext from mcp_memory_service.  Provides ``on(hook, fn)``
            for hook subscription, plus ``storage`` and ``service`` references.
    """
    global _config, _sync_queue

    _config = load_config()

    if not _config.enabled:
        logger.info("git_sync plugin is disabled by configuration")
        return

    repo_path = Path(_config.repo_path).expanduser()
    _sync_queue = GitSyncQueue(
        repo_path=repo_path,
        batch_size=_config.batch_size,
        timeout=_config.batch_timeout,
        auto_push=_config.auto_push,
    )

    ctx.on("on_store", on_store_handler)
    ctx.on("on_delete", on_delete_handler)

    logger.info("git_sync plugin registered (repo: %s)", repo_path)


# --------------------------------------------------------------------------- #
#  Hook handlers — async, fire-and-forget via asyncio.create_task
# --------------------------------------------------------------------------- #

async def on_store_handler(memory_dict: dict) -> None:
    """Handle on_store hook.

    Spawns a background task to write the memory to Markdown and enqueue
    a git sync.  Returns immediately without blocking the caller.

    Args:
        memory_dict: Memory dict from _format_memory_response(). Contains
            content, content_hash, tags, memory_type, metadata,
            created_at_iso, etc.
    """
    asyncio.create_task(_git_sync_store(memory_dict))


async def on_delete_handler(content_hash: str) -> None:
    """Handle on_delete hook.

    Spawns a background task to remove the Markdown file and enqueue a
    git sync.  Returns immediately.

    Args:
        content_hash: SHA-256 hash of the deleted memory.
    """
    asyncio.create_task(_git_sync_delete(content_hash))


# --------------------------------------------------------------------------- #
#  Background sync logic
# --------------------------------------------------------------------------- #

async def _git_sync_store(memory_dict: dict) -> None:
    """Write a memory to Markdown and enqueue git sync.

    Converts the memory dict to Markdown via markdown.memory_to_markdown(),
    writes it to the repo, then enqueues a batch commit via GitSyncQueue.
    All errors are caught and logged as warnings — never propagates.

    Args:
        memory_dict: Memory dict from _format_memory_response().
    """
    try:
        if _config is None or _sync_queue is None:
            return

        content_hash = memory_dict.get("content_hash", "")
        if not content_hash:
            return

        md_content = memory_to_markdown(memory_dict)
        repo_path = Path(_config.repo_path).expanduser()
        md_path = get_md_path(content_hash, repo_path)

        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        try:
            memories_dir = repo_path / "memories"
            readme_content = generate_readme_index(memories_dir)
            (repo_path / "README.md").write_text(readme_content, encoding="utf-8")
        except Exception as exc:
            logger.warning("Failed to update README index: %s", exc)

        await _sync_queue.enqueue("store", content_hash)
        logger.debug("Synced memory %s to git", content_hash[:12])
    except Exception as exc:
        logger.warning("git_sync_store failed: %s", exc)


async def _git_sync_delete(content_hash: str) -> None:
    """Delete a memory's Markdown file and enqueue git sync.

    Removes the Markdown file from the repo, then enqueues a batch commit.
    All errors are caught and logged as warnings — never propagates.

    Args:
        content_hash: SHA-256 hash of the deleted memory.
    """
    try:
        if _config is None or _sync_queue is None:
            return

        repo_path = Path(_config.repo_path).expanduser()
        md_path = get_md_path(content_hash, repo_path)

        if md_path.exists():
            md_path.unlink()

        await _sync_queue.enqueue("delete", content_hash)
        logger.debug("Deleted memory %s from git", content_hash[:12])
    except Exception as exc:
        logger.warning("git_sync_delete failed: %s", exc)
