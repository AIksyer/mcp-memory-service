# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Server package for MCP Memory Service.

Modular server components for better maintainability:
- client_detection: MCP client detection (Claude Desktop, LM Studio, etc.)
- logging_config: Client-aware logging configuration
- environment: Python path setup, version checks, performance config
- cache_manager: Global caching for storage and service instances
"""

# ruff: noqa: I001
# Import order is critical: cache_manager and other submodules MUST be imported
# before server_impl to avoid a circular import (server_impl imports from this
# package, so this package's submodules must be initialized first).

# Client Detection
from .client_detection import MCP_CLIENT, detect_mcp_client

# Logging Configuration
from .logging_config import DualStreamHandler, configure_logging, logger

# Environment Configuration
from .environment import (
    check_uv_environment,
    check_version_consistency,
    configure_environment,
    configure_performance_environment,
    setup_python_paths,
)

# Cache Management
from .cache_manager import (
    _CACHE_LOCK,
    _CACHE_STATS,
    _MEMORY_SERVICE_CACHE,
    _STORAGE_CACHE,
    _get_cache_lock,
    _get_or_create_memory_service,
    _log_cache_performance,
)

# Backward compatibility: Import main functions from server_impl.py
# server_impl.py (formerly server.py) contains main() and async_main()
# We re-export them for backward compatibility: from mcp_memory_service.server import main
# MUST come after cache_manager import — server_impl imports _CACHE_STATS etc. from this package
from ..server_impl import MemoryServer, async_main, main

__all__ = [
    # Client Detection
    "MCP_CLIENT",
    "_CACHE_LOCK",
    "_CACHE_STATS",
    "_MEMORY_SERVICE_CACHE",
    # Cache
    "_STORAGE_CACHE",
    # Logging
    "DualStreamHandler",
    "MemoryServer",
    "_get_cache_lock",
    "_get_or_create_memory_service",
    "_log_cache_performance",
    "async_main",
    "check_uv_environment",
    "check_version_consistency",
    "configure_environment",
    "configure_logging",
    "configure_performance_environment",
    "detect_mcp_client",
    "logger",
    # Entry points and core classes (for backward compatibility)
    "main",
    # Environment
    "setup_python_paths",
]
