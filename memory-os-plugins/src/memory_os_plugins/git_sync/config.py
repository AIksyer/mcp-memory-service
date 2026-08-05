"""Configuration loading for the git_sync plugin.

Priority order (highest to lowest):
1. Environment variables (prefix ``MEMORY_OS_GIT_SYNC_``)
2. Config file at ``~/.memory-os/config.yml`` (simple key: value, no PyYAML needed)
3. Built-in defaults

Configuration fields:
    - ``base_dir`` — base directory for Markdown file tree (alias: ``repo_path``)
    - ``batch_size`` — commit queue size (flush after N changes)
    - ``batch_timeout`` — seconds before auto-flush if batch_size not reached
    - ``auto_push`` — push to remote after each batch commit
    - ``enabled`` — master switch
    - ``project_name`` — optional project tag
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Path to the config directory and file.
CONFIG_DIR: Path = Path.home() / ".memory-os"
CONFIG_FILE: Path = CONFIG_DIR / "config.yml"

# Environment variable prefix.
ENV_PREFIX = "MEMORY_OS_GIT_SYNC_"


@dataclass
class GitSyncConfig:
    """Configuration for the git sync plugin.

    Attributes:
        enabled: Whether the plugin is active.
        base_dir: Base directory for the Markdown file tree.
        auto_push: Whether to push after every batch commit.
        batch_size: Number of changes before auto-flush (commit queue size).
        batch_timeout: Seconds before auto-flush if batch_size not reached.
        project_name: Optional project name tag for this repository.
    """

    enabled: bool = True
    base_dir: str = "~/AgentMemory"
    auto_push: bool = False
    batch_size: int = 5
    batch_timeout: int = 30
    project_name: str = ""

    @property
    def repo_path(self) -> str:
        """Backward-compat alias for ``base_dir``."""
        return self.base_dir

    @repo_path.setter
    def repo_path(self, value: str) -> None:
        self.base_dir = value


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _parse_bool(value: str) -> bool:
    """Convert a string to a boolean value."""
    return value.strip().lower() in ("true", "yes", "on", "1")


def _parse_config_file(path: Path) -> Dict[str, Any]:
    """Parse a simple ``key: value`` config file (no PyYAML dependency).

    Handles booleans (true/false/yes/no), integers, and strings.
    Lines starting with ``#`` are treated as comments.

    Args:
        path: Path to the config file.

    Returns:
        A dictionary of parsed key-value pairs.
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
    "BASE_DIR": ("base_dir", str),
    "REPO_PATH": ("base_dir", str),  # backward compat
    "AUTO_PUSH": ("auto_push", _parse_bool),
    "BATCH_SIZE": ("batch_size", int),
    "BATCH_TIMEOUT": ("batch_timeout", int),
    "PROJECT_NAME": ("project_name", str),
}

# Config file keys recognised by this plugin (both new and legacy).
_FILE_KEY_ALIASES: Dict[str, str] = {
    "base_dir": "base_dir",
    "repo_path": "base_dir",  # backward compat
    "enabled": "enabled",
    "auto_push": "auto_push",
    "batch_size": "batch_size",
    "batch_timeout": "batch_timeout",
    "project_name": "project_name",
}


def load_config() -> GitSyncConfig:
    """Load git sync configuration.

    Merges defaults, config file values, and environment variables.
    Environment variables take the highest priority.

    Returns:
        A fully-resolved GitSyncConfig instance.
    """
    config = GitSyncConfig()

    # Layer 1: config file
    if CONFIG_FILE.exists():
        try:
            file_values = _parse_config_file(CONFIG_FILE)
            for key, value in file_values.items():
                attr = _FILE_KEY_ALIASES.get(key)
                if attr and hasattr(config, attr):
                    setattr(config, attr, value)
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


# Keys managed by this plugin (used to filter old lines on save).
_SAVE_KEYS = frozenset({
    "enabled", "base_dir", "repo_path", "auto_push", "batch_size",
    "batch_timeout", "project_name",
})


def save_config(config: GitSyncConfig, path: Path | None = None) -> None:
    """Write git sync config values to the shared config file.

    Reads the existing config file (if any), removes old git_sync keys
    and the git_sync section comment, then appends the updated section.
    This preserves other plugins' config (e.g. r2_backup).

    Args:
        config: The configuration to persist.
        path: Override path for the config file (defaults to CONFIG_FILE).
    """
    target = path or CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content and filter out old git_sync lines.
    existing_lines: list[str] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "# Memory OS Git Sync configuration":
                continue
            # Check if this line's key is one of ours.
            if ":" in stripped and not stripped.startswith("#"):
                key = stripped.partition(":")[0].strip()
                if key in _SAVE_KEYS:
                    continue
            existing_lines.append(line)

    # Build git_sync section.
    git_lines = [
        "# Memory OS Git Sync configuration",
        f"enabled: {'true' if config.enabled else 'false'}",
        f"base_dir: {config.base_dir}",
        f"auto_push: {'true' if config.auto_push else 'false'}",
        f"batch_size: {config.batch_size}",
        f"batch_timeout: {config.batch_timeout}",
    ]
    if config.project_name:
        git_lines.append(f"project_name: {config.project_name}")

    # Combine: existing content + blank line + git_sync section.
    all_lines = existing_lines
    if all_lines and all_lines[-1].strip():
        all_lines.append("")
    all_lines.extend(git_lines)

    target.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
