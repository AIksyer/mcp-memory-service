"""Configuration loading for the r2_backup plugin.

Shares ``~/.memory-os/config.yml`` with the git_sync plugin.  All R2
keys are prefixed with ``r2_backup_`` to avoid collisions with
git_sync keys (e.g. ``enabled`` vs ``r2_backup_enabled``).

Priority order (highest to lowest):
1. Environment variables (prefix ``MEMORY_OS_R2_BACKUP_``)
2. Config file at ``~/.memory-os/config.yml`` (``r2_backup_*`` keys)
3. Built-in defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Path to the shared config directory and file (same as git_sync).
CONFIG_DIR: Path = Path.home() / ".memory-os"
CONFIG_FILE: Path = CONFIG_DIR / "config.yml"

# Environment variable prefix.
ENV_PREFIX = "MEMORY_OS_R2_BACKUP_"

# Prefix used for keys in the shared config file.
_CONFIG_KEY_PREFIX = "r2_backup_"


@dataclass
class R2BackupConfig:
    """Configuration for the R2 backup plugin.

    Attributes:
        enabled: Whether the plugin is active (default False — user must
            explicitly configure R2 credentials before enabling).
        endpoint_url: R2 S3-compatible endpoint
            (``https://{account_id}.r2.cloudflarestorage.com``).
        access_key_id: R2 access key ID.
        secret_access_key: R2 secret access key.
        bucket_name: R2 bucket name.
        prefix: Object key prefix inside the bucket (e.g. ``memories/``).
        batch_upload: Whether to batch-upload directory contents.
    """

    enabled: bool = False
    endpoint_url: str = ""
    access_key_id: str = ""
    secret_access_key: str = ""
    bucket_name: str = ""
    prefix: str = "memories/"
    batch_upload: bool = True


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _parse_bool(value: str) -> bool:
    """Convert a string to a boolean value."""
    return value.strip().lower() in ("true", "yes", "on", "1")


def _parse_config_file(path: Path) -> Dict[str, Any]:
    """Parse the shared config file, returning only ``r2_backup_*`` keys.

    Strips the ``r2_backup_`` prefix so the returned dict keys match
    :class:`R2BackupConfig` attribute names directly.

    Args:
        path: Path to the config file.

    Returns:
        A dictionary of parsed key-value pairs (prefix stripped).
    """
    values: Dict[str, Any] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()

        # Only pick up keys with our prefix.
        if not key.startswith(_CONFIG_KEY_PREFIX):
            continue
        key = key[len(_CONFIG_KEY_PREFIX):]

        if value.lower() in ("true", "yes", "on"):
            values[key] = True
        elif value.lower() in ("false", "no", "off"):
            values[key] = False
        elif value.lstrip("-").isdigit():
            values[key] = int(value)
        else:
            values[key] = value
    return values


# Mapping: env suffix -> (config attr, type converter)
_ENV_MAPPINGS: Dict[str, tuple[str, Callable[[str], Any]]] = {
    "ENABLED": ("enabled", _parse_bool),
    "ENDPOINT_URL": ("endpoint_url", str),
    "ACCESS_KEY_ID": ("access_key_id", str),
    "SECRET_ACCESS_KEY": ("secret_access_key", str),
    "BUCKET_NAME": ("bucket_name", str),
    "PREFIX": ("prefix", str),
    "BATCH_UPLOAD": ("batch_upload", _parse_bool),
}


def load_config() -> R2BackupConfig:
    """Load R2 backup configuration.

    Merges defaults, config file values, and environment variables.
    Environment variables take the highest priority.

    Returns:
        A fully-resolved :class:`R2BackupConfig` instance.
    """
    config = R2BackupConfig()

    # Layer 1: config file
    if CONFIG_FILE.exists():
        try:
            file_values = _parse_config_file(CONFIG_FILE)
            for key, value in file_values.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        except Exception as exc:
            logger.warning("Failed to parse config file %s: %s", CONFIG_FILE, exc)

    # Layer 2: environment variables (override file values)
    for suffix, (attr, converter) in _ENV_MAPPINGS.items():
        env_key = ENV_PREFIX + suffix
        if env_key in os.environ:
            try:
                setattr(config, attr, converter(os.environ[env_key]))
            except (ValueError, TypeError) as exc:
                logger.warning("Invalid value for %s: %s", env_key, exc)

    return config


def save_config(config: R2BackupConfig, path: Path | None = None) -> None:
    """Write R2 config values to the shared config file.

    Reads the existing config file (if any), removes old ``r2_backup_*``
    lines and the R2 section comment, then appends the updated R2
    section.  This preserves git_sync and other plugins' config.

    Args:
        config: The configuration to persist.
        path: Override path for the config file (defaults to CONFIG_FILE).
    """
    target = path or CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content and filter out old R2 lines.
    existing_lines: list[str] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(_CONFIG_KEY_PREFIX):
                continue
            if stripped == "# Memory OS R2 Backup configuration":
                continue
            existing_lines.append(line)

    # Build R2 section.
    r2_lines = [
        "# Memory OS R2 Backup configuration",
        f"r2_backup_enabled: {'true' if config.enabled else 'false'}",
        f"r2_backup_endpoint_url: {config.endpoint_url}",
        f"r2_backup_access_key_id: {config.access_key_id}",
        f"r2_backup_secret_access_key: {config.secret_access_key}",
        f"r2_backup_bucket_name: {config.bucket_name}",
        f"r2_backup_prefix: {config.prefix}",
        f"r2_backup_batch_upload: {'true' if config.batch_upload else 'false'}",
    ]

    # Combine: existing content + blank line + R2 section.
    all_lines = existing_lines
    if all_lines and all_lines[-1].strip():
        all_lines.append("")
    all_lines.extend(r2_lines)

    target.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
