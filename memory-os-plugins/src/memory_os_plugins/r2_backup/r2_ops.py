"""S3-compatible operations for Cloudflare R2 using boto3.

All functions are synchronous (boto3 is a sync library).  They return
``bool`` (or ``list[str]`` for listing) and never raise — errors are
caught and logged as warnings.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import R2BackupConfig

logger = logging.getLogger(__name__)

# Module-level cache for the S3 client, keyed by (endpoint_url, access_key_id).
# Avoids creating a new boto3 client on every operation call.
_s3_client_cache: dict[tuple[str, str], object] = {}


def _get_s3_client(config: R2BackupConfig):
    """Get a cached boto3 S3 client pointing at the R2 endpoint.

    The client is cached per (endpoint_url, access_key_id) pair so
    repeated operations reuse the same connection pool.

    Args:
        config: R2 backup configuration with credentials and endpoint.

    Returns:
        A ``boto3.client("s3", ...)`` instance.

    Raises:
        ImportError: If boto3 is not installed.
        Exception: If client creation fails (caught by callers).
    """
    cache_key = (config.endpoint_url, config.access_key_id)
    cached = _s3_client_cache.get(cache_key)
    if cached is not None:
        return cached

    import boto3  # noqa: WPS433 — lazy import for optional dependency

    client = boto3.client(
        "s3",
        endpoint_url=config.endpoint_url,
        aws_access_key_id=config.access_key_id,
        aws_secret_access_key=config.secret_access_key,
        region_name="auto",
    )
    _s3_client_cache[cache_key] = client
    return client


def upload_to_r2(config: R2BackupConfig, local_path: Path | str, r2_key: str) -> bool:
    """Upload a single file to R2.

    Args:
        config: R2 backup configuration.
        local_path: Path to the local file to upload.
        r2_key: R2 object key (e.g. ``memories/ab/hash.md``).

    Returns:
        True on success, False on failure.
    """
    try:
        client = _get_s3_client(config)
        client.upload_file(str(local_path), config.bucket_name, r2_key)
        logger.debug("Uploaded %s to R2 as %s", local_path, r2_key)
        return True
    except Exception as exc:
        logger.warning("upload_to_r2 failed for %s: %s", r2_key, exc)
        return False


def download_from_r2(config: R2BackupConfig, r2_key: str, local_path: Path | str) -> bool:
    """Download a single file from R2.

    Args:
        config: R2 backup configuration.
        r2_key: R2 object key to download.
        local_path: Destination path for the downloaded file.

    Returns:
        True on success, False on failure.
    """
    try:
        local = Path(local_path)
        local.parent.mkdir(parents=True, exist_ok=True)
        client = _get_s3_client(config)
        client.download_file(config.bucket_name, r2_key, str(local))
        logger.debug("Downloaded %s from R2 to %s", r2_key, local)
        return True
    except Exception as exc:
        logger.warning("download_from_r2 failed for %s: %s", r2_key, exc)
        return False


def delete_from_r2(config: R2BackupConfig, r2_key: str) -> bool:
    """Delete a single object from R2.

    Args:
        config: R2 backup configuration.
        r2_key: R2 object key to delete.

    Returns:
        True on success, False on failure.
    """
    try:
        client = _get_s3_client(config)
        client.delete_object(Bucket=config.bucket_name, Key=r2_key)
        logger.debug("Deleted %s from R2", r2_key)
        return True
    except Exception as exc:
        logger.warning("delete_from_r2 failed for %s: %s", r2_key, exc)
        return False


def list_r2_objects(config: R2BackupConfig, prefix: str | None = None) -> list[str]:
    """List objects in the R2 bucket.

    Args:
        config: R2 backup configuration.
        prefix: Optional key prefix to filter by.  Defaults to
            ``config.prefix``.

    Returns:
        A list of object keys.  Returns an empty list on error.
    """
    try:
        client = _get_s3_client(config)
        key_prefix = prefix if prefix is not None else config.prefix
        response = client.list_objects_v2(
            Bucket=config.bucket_name,
            Prefix=key_prefix,
        )
        contents = response.get("Contents", [])
        keys = [obj["Key"] for obj in contents]
        logger.debug("Listed %d objects in R2 (prefix=%s)", len(keys), key_prefix)
        return keys
    except Exception as exc:
        logger.warning("list_r2_objects failed: %s", exc)
        return []


def sync_directory_to_r2(
    config: R2BackupConfig,
    local_dir: Path | str,
    r2_prefix: str,
) -> bool:
    """Batch-sync a local directory to R2.

    Walks *local_dir* recursively and uploads every file to R2 under
    *r2_prefix*.  If ``config.batch_upload`` is True, uses a
    ``ThreadPoolExecutor`` for concurrent uploads; otherwise uploads
    sequentially.

    Args:
        config: R2 backup configuration.
        local_dir: Local directory to sync.
        r2_prefix: R2 key prefix for uploaded objects.

    Returns:
        True if all files uploaded successfully, False if any failed.
    """
    try:
        local = Path(local_dir)
        if not local.is_dir():
            logger.warning("sync_directory_to_r2: %s is not a directory", local_dir)
            return False

        files: list[Path] = list(local.rglob("*"))
        files = [f for f in files if f.is_file()]
        if not files:
            logger.debug("sync_directory_to_r2: no files in %s", local_dir)
            return True

        # Build (local_path, r2_key) pairs.
        upload_pairs: list[tuple[Path, str]] = []
        for f in files:
            rel = f.relative_to(local)
            r2_key = r2_prefix.rstrip("/") + "/" + str(rel).replace("\\", "/")
            upload_pairs.append((f, r2_key))

        all_ok = True

        if config.batch_upload:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            max_workers = min(8, len(upload_pairs))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(upload_to_r2, config, local, key): (local, key)
                    for local, key in upload_pairs
                }
                for future in as_completed(futures):
                    if not future.result():
                        all_ok = False
        else:
            for local_file, r2_key in upload_pairs:
                if not upload_to_r2(config, local_file, r2_key):
                    all_ok = False

        if all_ok:
            logger.info("Synced %d files from %s to R2", len(files), local_dir)
        return all_ok
    except Exception as exc:
        logger.warning("sync_directory_to_r2 failed: %s", exc)
        return False
