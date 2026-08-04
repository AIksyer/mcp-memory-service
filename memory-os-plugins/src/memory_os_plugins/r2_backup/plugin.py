"""R2 backup plugin — registers on_store/on_delete hooks to sync
memory Markdown files to Cloudflare R2 via S3-compatible API.

The plugin piggybacks on the git_sync plugin's output: it looks for the
Markdown file written by git_sync at the expected path and uploads it
to R2.  All upload work is done in background asyncio tasks — hooks
return immediately without blocking.

boto3 is an optional dependency.  If boto3 is not installed and the
plugin is disabled (the default), it silently skips.  If enabled but
boto3 is missing, a warning is logged and the plugin skips.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from ..git_sync.config import load_config as load_git_config
from ..git_sync.markdown import get_md_path
from .config import R2BackupConfig, load_config
from .r2_ops import delete_from_r2, upload_to_r2

logger = logging.getLogger(__name__)

# Global state — initialised by register(), read by hook handlers.
_config: R2BackupConfig | None = None


def register(ctx) -> None:
    """Plugin registration entry point.

    Called automatically by PluginRegistry.discover_and_register().
    Loads R2 backup config, checks for boto3 availability, and
    subscribes to ``on_store`` and ``on_delete`` hooks if enabled.

    Args:
        ctx: PluginContext from mcp_memory_service.  Provides ``on(hook, fn)``
            for hook subscription, plus ``storage`` and ``service`` references.
    """
    global _config

    _config = load_config()

    if not _config.enabled:
        logger.info("r2_backup plugin is disabled by configuration")
        return

    # Check for boto3 (optional dependency).
    try:
        import boto3  # noqa: F401 — import check only
    except ImportError:
        logger.warning(
            "r2_backup plugin is enabled but boto3 is not installed — "
            "install with: pip install memory-os-plugins[r2]"
        )
        return

    ctx.on("on_store", on_store_handler)
    ctx.on("on_delete", on_delete_handler)

    logger.info(
        "r2_backup plugin registered (bucket: %s, prefix: %s)",
        _config.bucket_name,
        _config.prefix,
    )


# --------------------------------------------------------------------------- #
#  Hook handlers — async, fire-and-forget via asyncio.create_task
# --------------------------------------------------------------------------- #

async def on_store_handler(memory_dict: dict) -> None:
    """Handle on_store hook.

    Spawns a background task to upload the memory's Markdown file to R2.
    Returns immediately without blocking the caller.

    Args:
        memory_dict: Memory dict from _format_memory_response(). Contains
            content, content_hash, tags, memory_type, metadata,
            created_at_iso, etc.
    """
    asyncio.create_task(_r2_backup_store(memory_dict))


async def on_delete_handler(content_hash: str) -> None:
    """Handle on_delete hook.

    Spawns a background task to delete the memory's object from R2.
    Returns immediately.

    Args:
        content_hash: SHA-256 hash of the deleted memory.
    """
    asyncio.create_task(_r2_backup_delete(content_hash))


# --------------------------------------------------------------------------- #
#  Background sync logic
# --------------------------------------------------------------------------- #

def _compute_r2_key(content_hash: str, prefix: str) -> str:
    """Build the R2 object key for a memory.

    Key format: ``{prefix}{hash[:2]}/{hash}.md``

    Args:
        content_hash: SHA-256 content hash of the memory.
        prefix: R2 object key prefix (e.g. ``memories/``).

    Returns:
        The R2 object key string.
    """
    short = content_hash[:2] if len(content_hash) >= 2 else "00"
    return f"{prefix}{short}/{content_hash}.md"


async def _r2_backup_store(memory_dict: dict) -> None:
    """Upload a memory's Markdown file to R2.

    Computes the Markdown file path (reusing git_sync's ``get_md_path``),
    checks if the file exists (written by git_sync plugin), and uploads
    it to R2.  All errors are caught and logged as warnings — never
    propagates.

    Args:
        memory_dict: Memory dict from _format_memory_response().
    """
    try:
        if _config is None:
            return

        content_hash = memory_dict.get("content_hash", "")
        if not content_hash:
            return

        # Compute the Markdown file path (same path git_sync would write).
        git_config = load_git_config()
        repo_path = Path(git_config.repo_path).expanduser()
        md_path = get_md_path(content_hash, repo_path)

        if not md_path.exists():
            logger.debug(
                "Markdown file %s does not exist yet — skipping R2 upload",
                md_path,
            )
            return

        r2_key = _compute_r2_key(content_hash, _config.prefix)
        await asyncio.to_thread(upload_to_r2, _config, md_path, r2_key)
        logger.debug("Synced memory %s to R2", content_hash[:12])
    except Exception as exc:
        logger.warning("r2_backup_store failed: %s", exc)


async def _r2_backup_delete(content_hash: str) -> None:
    """Delete a memory's object from R2.

    All errors are caught and logged as warnings — never propagates.

    Args:
        content_hash: SHA-256 hash of the deleted memory.
    """
    try:
        if _config is None:
            return

        r2_key = _compute_r2_key(content_hash, _config.prefix)
        await asyncio.to_thread(delete_from_r2, _config, r2_key)
        logger.debug("Deleted memory %s from R2", content_hash[:12])
    except Exception as exc:
        logger.warning("r2_backup_delete failed: %s", exc)
