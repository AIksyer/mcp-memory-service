"""Tests for DEVICE_ID config and D1 migration additions (v4)."""

import os
from unittest.mock import patch

import pytest


class TestDeviceIdConfig:
    """Tests for DEVICE_ID configuration."""

    def test_device_id_returns_env_value(self):
        """DEVICE_ID returns MCP_DEVICE_ID env var when set."""
        with patch.dict(os.environ, {"MCP_DEVICE_ID": "my-device-123"}):
            # Re-import to pick up env var
            import importlib
            import mcp_memory_service.config.backup as backup_config
            importlib.reload(backup_config)
            assert backup_config.DEVICE_ID == "my-device-123"

    def test_device_id_generates_uuid_when_not_set(self):
        """DEVICE_ID generates a short UUID when env var not set."""
        # Ensure MCP_DEVICE_ID is not set
        env = os.environ.copy()
        env.pop("MCP_DEVICE_ID", None)
        with patch.dict(os.environ, env, clear=True):
            import importlib
            import mcp_memory_service.config.backup as backup_config
            importlib.reload(backup_config)
            # Should be an 8-char hex string from uuid4
            assert len(backup_config.DEVICE_ID) == 8
            int(backup_config.DEVICE_ID, 16)  # Valid hex


class TestD1MigrationColumns:
    """Tests for D1 schema migration additions."""

    def test_column_spec_includes_sync_version_and_device_id(self):
        """_add_column_with_retry column_spec includes v4 columns."""
        # The column_spec is inside the method, so we verify via inspection
        # that the cloudflare.py source contains the new column definitions
        import inspect
        from mcp_memory_service.storage.cloudflare import CloudflareStorage

        source = inspect.getsource(CloudflareStorage._add_column_with_retry)
        assert "sync_version" in source
        assert "device_id" in source
        assert "INTEGER NOT NULL DEFAULT 1" in source
