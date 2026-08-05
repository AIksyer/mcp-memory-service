"""Configuration loading for the smart_tagger plugin.

Priority order (highest to lowest):
1. Environment variables (prefix ``MEMORY_OS_SMART_TAGGER_``)
2. Config file at ``~/.memory-os/config.yml`` (simple key: value, no PyYAML needed)
3. Built-in defaults

Configuration fields:
    - ``enabled`` — master switch
    - ``project_name`` — project tag to inject into memories
    - ``project_filter`` — boost same-project results on retrieve
    - ``auto_tags`` — whether to auto-generate content-based tags
    - ``mistake_boost`` — score boost for mistake-note/error-replay results
    - ``inject_date_tag`` — whether to inject a ``date:YYYY-MM`` tag
    - ``inject_project_tag`` — whether to inject ``project:xxx`` tags from
        detected paths in the content
    - ``inject_type_tag`` — whether to inject ``type:xxx`` tags from content
        keywords
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

# Path to the config directory and file (shared with other memory-os plugins).
CONFIG_DIR: Path = Path.home() / ".memory-os"
CONFIG_FILE: Path = CONFIG_DIR / "config.yml"

# Environment variable prefix.
ENV_PREFIX = "MEMORY_OS_SMART_TAGGER_"


@dataclass
class SmartTaggerConfig:
    """Configuration for the smart tagger plugin.

    Attributes:
        enabled: Whether the plugin is active.
        project_name: Optional project name tag injected into all memories.
        project_filter: When True, boost same-project results on retrieve.
        auto_tags: Whether to auto-generate content-based tags.
        mistake_boost: Score boost for mistake-note/error-replay results.
        inject_date_tag: Whether to inject a ``date:YYYY-MM`` tag.
        inject_project_tag: Whether to inject ``project:xxx`` tags from
            detected paths in the content.
        inject_type_tag: Whether to inject ``type:xxx`` tags from content
            keywords.
    """

    enabled: bool = True
    project_name: str = ""
    project_filter: bool = False
    auto_tags: bool = True
    mistake_boost: float = 0.15
    inject_date_tag: bool = True
    inject_project_tag: bool = True
    inject_type_tag: bool = True


# --------------------------------------------------------------------------- #
#  Internal helpers
# --------------------------------------------------------------------------- #

def _parse_bool(value: str) -> bool:
    """Convert a string to a boolean value."""
    return value.strip().lower() in ("true", "yes", "on", "1")


def _parse_float(value: str) -> float:
    """Convert a string to a float value."""
    return float(value)


def _parse_config_file(path: Path) -> Dict[str, Any]:
    """Parse a simple ``key: value`` config file (no PyYAML dependency).

    Handles booleans (true/false/yes/no), integers, floats, and strings.
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
        elif _is_float(value):
            values[key] = float(value)
        elif value.lstrip("-").isdigit():
            values[key] = int(value)
        else:
            values[key] = value
    return values


def _is_float(value: str) -> bool:
    """Check if a string can be parsed as a float."""
    try:
        float(value)
        return True
    except ValueError:
        return False


# Mapping: env suffix -> (config attr, type converter)
_ENV_MAPPINGS: Dict[str, tuple[str, Callable[[str], Any]]] = {
    "ENABLED": ("enabled", _parse_bool),
    "PROJECT_NAME": ("project_name", str),
    "PROJECT_FILTER": ("project_filter", _parse_bool),
    "AUTO_TAGS": ("auto_tags", _parse_bool),
    "MISTAKE_BOOST": ("mistake_boost", _parse_float),
    "INJECT_DATE_TAG": ("inject_date_tag", _parse_bool),
    "INJECT_PROJECT_TAG": ("inject_project_tag", _parse_bool),
    "INJECT_TYPE_TAG": ("inject_type_tag", _parse_bool),
}

# Config file keys recognised by this plugin (smart_tagger_ prefix).
_FILE_KEY_ALIASES: Dict[str, str] = {
    "smart_tagger_enabled": "enabled",
    "smart_tagger_project_name": "project_name",
    "smart_tagger_project_filter": "project_filter",
    "smart_tagger_auto_tags": "auto_tags",
    "smart_tagger_mistake_boost": "mistake_boost",
    "smart_tagger_inject_date_tag": "inject_date_tag",
    "smart_tagger_inject_project_tag": "inject_project_tag",
    "smart_tagger_inject_type_tag": "inject_type_tag",
}


def load_config() -> SmartTaggerConfig:
    """Load smart tagger configuration.

    Merges defaults, config file values, and environment variables.
    Environment variables take the highest priority.

    Returns:
        A fully-resolved SmartTaggerConfig instance.
    """
    config = SmartTaggerConfig()

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
    "smart_tagger_enabled", "smart_tagger_project_name",
    "smart_tagger_project_filter", "smart_tagger_auto_tags",
    "smart_tagger_mistake_boost",
    "smart_tagger_inject_date_tag", "smart_tagger_inject_project_tag",
    "smart_tagger_inject_type_tag",
})


def save_config(config: SmartTaggerConfig, path: Path | None = None) -> None:
    """Write smart tagger config values to the shared config file.

    Reads the existing config file (if any), removes old smart_tagger keys
    and the smart_tagger section comment, then appends the updated section.
    This preserves other plugins' config (e.g. git_sync, r2_backup).

    Args:
        config: The configuration to persist.
        path: Override path for the config file (defaults to CONFIG_FILE).
    """
    target = path or CONFIG_FILE
    target.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content and filter out old smart_tagger lines.
    existing_lines: list[str] = []
    if target.exists():
        for line in target.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "# Memory OS Smart Tagger configuration":
                continue
            if ":" in stripped and not stripped.startswith("#"):
                key = stripped.partition(":")[0].strip()
                if key in _SAVE_KEYS:
                    continue
            existing_lines.append(line)

    # Build smart_tagger section.
    tagger_lines = [
        "# Memory OS Smart Tagger configuration",
        f"smart_tagger_enabled: {'true' if config.enabled else 'false'}",
        f"smart_tagger_project_filter: {'true' if config.project_filter else 'false'}",
        f"smart_tagger_auto_tags: {'true' if config.auto_tags else 'false'}",
        f"smart_tagger_mistake_boost: {config.mistake_boost}",
        f"smart_tagger_inject_date_tag: {'true' if config.inject_date_tag else 'false'}",
        f"smart_tagger_inject_project_tag: {'true' if config.inject_project_tag else 'false'}",
        f"smart_tagger_inject_type_tag: {'true' if config.inject_type_tag else 'false'}",
    ]
    if config.project_name:
        tagger_lines.append(f"smart_tagger_project_name: {config.project_name}")

    # Combine: existing content + blank line + smart_tagger section.
    all_lines = existing_lines
    if all_lines and all_lines[-1].strip():
        all_lines.append("")
    all_lines.extend(tagger_lines)

    target.write_text("\n".join(all_lines) + "\n", encoding="utf-8")
