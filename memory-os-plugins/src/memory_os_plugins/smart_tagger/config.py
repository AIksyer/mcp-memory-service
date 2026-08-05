"""Configuration loading for the smart_tagger plugin.

Priority order (highest to lowest):
1. Environment variables (prefix ``MEMORY_OS_SMART_TAGGER_``)
2. Config file at ``~/.memory-os/config.yml`` (``smart_tagger_*`` keys)
3. Built-in defaults
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict

logger = logging.getLogger(__name__)

CONFIG_DIR: Path = Path.home() / ".memory-os"
CONFIG_FILE: Path = CONFIG_DIR / "config.yml"

ENV_PREFIX = "MEMORY_OS_SMART_TAGGER_"

_CONFIG_KEY_PREFIX = "smart_tagger_"


@dataclass
class SmartTaggerConfig:
    """Configuration for the smart tagger plugin.

    Attributes:
        enabled: Whether the plugin is active.
        inject_date_tag: Whether to inject a ``date:YYYY-MM`` tag.
        inject_project_tag: Whether to inject ``project:xxx`` tags from
            detected paths in the content.
        inject_type_tag: Whether to inject ``type:xxx`` tags from content
            keywords.
    """

    enabled: bool = True
    inject_date_tag: bool = True
    inject_project_tag: bool = True
    inject_type_tag: bool = True


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in ("true", "yes", "on", "1")


def _parse_config_file(path: Path) -> Dict[str, Any]:
    """Parse the shared config file, returning only ``smart_tagger_*`` keys."""
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

        if not key.startswith(_CONFIG_KEY_PREFIX):
            continue
        key = key[len(_CONFIG_KEY_PREFIX):]

        if value.lower() in ("true", "yes", "on"):
            values[key] = True
        elif value.lower() in ("false", "no", "off"):
            values[key] = False
        else:
            values[key] = value
    return values


_ENV_MAPPINGS: Dict[str, tuple[str, Callable[[str], Any]]] = {
    "ENABLED": ("enabled", _parse_bool),
    "INJECT_DATE_TAG": ("inject_date_tag", _parse_bool),
    "INJECT_PROJECT_TAG": ("inject_project_tag", _parse_bool),
    "INJECT_TYPE_TAG": ("inject_type_tag", _parse_bool),
}


def load_config() -> SmartTaggerConfig:
    """Load smart tagger configuration.

    Returns:
        A fully-resolved SmartTaggerConfig instance.
    """
    config = SmartTaggerConfig()

    if CONFIG_FILE.exists():
        try:
            file_values = _parse_config_file(CONFIG_FILE)
            for key, value in file_values.items():
                if hasattr(config, key):
                    setattr(config, key, value)
        except Exception as exc:
            logger.warning("Failed to parse config file %s: %s", CONFIG_FILE, exc)

    for suffix, (attr, converter) in _ENV_MAPPINGS.items():
        env_key = ENV_PREFIX + suffix
        if env_key in os.environ:
            try:
                setattr(config, attr, converter(os.environ[env_key]))
            except (ValueError, TypeError) as exc:
                logger.warning("Invalid value for %s: %s", env_key, exc)

    return config
