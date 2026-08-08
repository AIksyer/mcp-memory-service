#!/usr/bin/env python3
"""Tests for the setup wizard."""

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import click
from click.testing import CliRunner

# Add src to path
current_dir = Path(__file__).parent
src_dir = current_dir.parent.parent / "src"
sys.path.insert(0, str(src_dir))

from mcp_memory_service.cli.setup import SetupWizard, SetupConfig
from mcp_memory_service.cli.main import cli


class TestSetupConfig:
    """Tests for SetupConfig dataclass."""

    def test_defaults(self):
        config = SetupConfig()
        assert config.storage_backend == "sqlite_vec"
        assert config.backup_local is True
        assert config.backup_r2 is False
        assert config.backup_github is False
        assert config.mcp_client == ""
        assert config.http_port == 8000

    def test_custom_values(self):
        config = SetupConfig(
            storage_backend="hybrid",
            cf_api_token="test-token",
            backup_r2=True,
            mcp_client="claude-code",
        )
        assert config.storage_backend == "hybrid"
        assert config.cf_api_token == "test-token"
        assert config.backup_r2 is True
        assert config.mcp_client == "claude-code"


class TestEnvGeneration:
    """Tests for .env content generation."""

    def test_sqlite_vec_env(self, tmp_path):
        """SQLite-vec backend produces correct .env."""
        wizard = SetupWizard(SetupConfig(storage_backend="sqlite_vec"))
        content = wizard._generate_env_content()
        assert "MCP_MEMORY_STORAGE_BACKEND=sqlite_vec" in content
        assert "MCP_BACKUP_ENABLED=true" in content

    def test_hybrid_env_includes_cf(self):
        """Hybrid backend includes Cloudflare vars."""
        config = SetupConfig(
            storage_backend="hybrid",
            cf_api_token="test-token",
            cf_account_id="test-account",
            cf_d1_database_id="test-db",
        )
        wizard = SetupWizard(config)
        content = wizard._generate_env_content()
        assert "CLOUDFLARE_API_TOKEN=test-token" in content
        assert "CLOUDFLARE_ACCOUNT_ID=test-account" in content
        assert "MCP_HYBRID_SYNC_OWNER=http" in content
        assert "MCP_HYBRID_SYNC_ON_STARTUP=true" in content

    def test_backup_r2_env(self):
        """R2 backup generates correct env vars."""
        config = SetupConfig(backup_r2=True, backup_r2_bucket="my-bucket")
        wizard = SetupWizard(config)
        content = wizard._generate_env_content()
        assert "MCP_BACKUP_R2_ENABLED=true" in content
        assert "MCP_BACKUP_R2_BUCKET=my-bucket" in content

    def test_backup_github_env(self):
        """GitHub backup generates correct env vars."""
        config = SetupConfig(
            backup_github=True,
            backup_github_repo="user/repo",
            backup_github_token="ghp_test",
        )
        wizard = SetupWizard(config)
        content = wizard._generate_env_content()
        assert "MCP_BACKUP_GITHUB_ENABLED=true" in content
        assert "MCP_BACKUP_GITHUB_REPO=user/repo" in content
        assert "MCP_BACKUP_GITHUB_TOKEN=ghp_test" in content

    def test_sqlite_pragmas_included(self):
        """WAL mode pragmas are always included."""
        wizard = SetupWizard()
        content = wizard._generate_env_content()
        assert "journal_mode" in content
        assert "WAL" in content

    def test_sqlite_pragmas_format(self):
        """SQLite pragmas use key=value,key=value format, not JSON."""
        wizard = SetupWizard()
        content = wizard._generate_env_content()
        pragmas_line = [
            line for line in content.splitlines()
            if line.startswith("MCP_MEMORY_SQLITE_PRAGMAS")
        ][0]
        assert "journal_mode=WAL" in pragmas_line
        assert "synchronous=NORMAL" in pragmas_line
        assert "{" not in pragmas_line
        assert "}" not in pragmas_line


class TestNonInteractive:
    """Tests for non-interactive mode."""

    def test_non_interactive_writes_env(self, tmp_path):
        """Non-interactive setup writes .env file."""
        config = SetupConfig(storage_backend="sqlite_vec")
        wizard = SetupWizard(config)
        wizard._find_env_path = lambda: tmp_path / ".env"
        wizard.run_non_interactive()
        assert (tmp_path / ".env").exists()
        content = (tmp_path / ".env").read_text()
        assert "MCP_MEMORY_STORAGE_BACKEND=sqlite_vec" in content

    def test_non_interactive_applies_kwargs(self, tmp_path):
        """Non-interactive setup applies provided kwargs."""
        wizard = SetupWizard()
        wizard._find_env_path = lambda: tmp_path / ".env"
        wizard.run_non_interactive(
            storage_backend="hybrid", cf_api_token="tok", backup_r2=True
        )
        assert wizard.config.storage_backend == "hybrid"
        assert wizard.config.cf_api_token == "tok"
        assert wizard.config.backup_r2 is True

    def test_non_interactive_ignores_none_values(self, tmp_path):
        """None values don't override defaults."""
        wizard = SetupWizard()
        wizard._find_env_path = lambda: tmp_path / ".env"
        wizard.run_non_interactive(backend=None, cf_token=None)
        assert wizard.config.storage_backend == "sqlite_vec"


class TestEnvMerge:
    """Tests for .env merge and backup behaviour."""

    def test_merge_preserves_existing_env(self, tmp_path):
        """Re-running setup preserves unknown keys and managed keys with empty wizard values."""
        env_path = tmp_path / ".env"
        env_path.write_text(
            "CLOUDFLARE_API_TOKEN=real-token\n"
            "MCP_ALLOW_ANONYMOUS_ACCESS=true\n"
        )
        config = SetupConfig(storage_backend="sqlite_vec")
        wizard = SetupWizard(config)
        wizard._find_env_path = lambda: env_path
        wizard.run_non_interactive()
        content = env_path.read_text()
        assert "CLOUDFLARE_API_TOKEN=real-token" in content
        assert "MCP_ALLOW_ANONYMOUS_ACCESS=true" in content

    def test_backup_created(self, tmp_path):
        """Running setup on an existing .env creates a .env.bak backup."""
        env_path = tmp_path / ".env"
        original_content = "EXISTING_KEY=existing_value\n"
        env_path.write_text(original_content)
        wizard = SetupWizard(SetupConfig(storage_backend="sqlite_vec"))
        wizard._find_env_path = lambda: env_path
        wizard.run_non_interactive()
        backup_path = tmp_path / ".env.bak"
        assert backup_path.exists()
        assert backup_path.read_text() == original_content

    def test_non_interactive_hybrid_without_cf_token_fails(self, tmp_path):
        """Non-interactive hybrid setup without CF token and no existing .env fails."""
        wizard = SetupWizard(SetupConfig(storage_backend="hybrid"))
        wizard._find_env_path = lambda: tmp_path / ".env"
        with pytest.raises(click.ClickException):
            wizard.run_non_interactive()

    def test_non_interactive_hybrid_preserves_existing_cf_token(self, tmp_path):
        """Non-interactive hybrid setup preserves existing CF token from .env."""
        env_path = tmp_path / ".env"
        env_path.write_text("CLOUDFLARE_API_TOKEN=existing\n")
        wizard = SetupWizard(SetupConfig(storage_backend="hybrid"))
        wizard._find_env_path = lambda: env_path
        wizard.run_non_interactive()
        content = env_path.read_text()
        assert "CLOUDFLARE_API_TOKEN=existing" in content


class TestAtomicWrite:
    """Tests for atomic file writing."""

    def test_atomic_write_creates_file(self, tmp_path):
        """Atomic write creates the target file."""
        path = tmp_path / "test.txt"
        SetupWizard._atomic_write(path, "hello world")
        assert path.read_text() == "hello world"

    def test_atomic_write_overwrites(self, tmp_path):
        """Atomic write overwrites existing file."""
        path = tmp_path / "test.txt"
        path.write_text("old content")
        SetupWizard._atomic_write(path, "new content")
        assert path.read_text() == "new content"

    def test_no_tmp_file_left(self, tmp_path):
        """No temporary file remains after atomic write."""
        path = tmp_path / "test.txt"
        SetupWizard._atomic_write(path, "content")
        assert not (tmp_path / "test.txt.tmp").exists()


class TestMcpClientDetection:
    """Tests for MCP client detection."""

    def test_detect_returns_list(self):
        """_detect_mcp_clients returns a list."""
        wizard = SetupWizard()
        result = wizard._detect_mcp_clients()
        assert isinstance(result, list)

    def test_get_config_path_claude_desktop(self):
        """_get_client_config_path returns path for claude-desktop."""
        wizard = SetupWizard()
        path = wizard._get_client_config_path("claude-desktop")
        assert "claude_desktop_config.json" in path

    def test_get_config_path_cursor(self):
        """_get_client_config_path returns path for cursor."""
        wizard = SetupWizard()
        path = wizard._get_client_config_path("cursor")
        assert "mcp.json" in path

    def test_get_config_path_none(self):
        """_get_client_config_path returns empty for unknown client."""
        wizard = SetupWizard()
        path = wizard._get_client_config_path("unknown")
        assert path == ""


class TestMcpClientConfigWriting:
    """Tests for MCP client config file writing."""

    def test_creates_new_config(self, tmp_path):
        """Writing MCP config creates a new file if none exists."""
        config_path = tmp_path / "mcp.json"
        wizard = SetupWizard(
            SetupConfig(mcp_client="cursor", mcp_client_config_path=str(config_path))
        )
        wizard._find_env_path = lambda: tmp_path / ".env"
        wizard._write_mcp_client_config()
        assert config_path.exists()
        data = json.loads(config_path.read_text())
        assert "mcpServers" in data
        assert "memory" in data["mcpServers"]

    def test_preserves_existing_servers(self, tmp_path):
        """Writing MCP config preserves existing server entries."""
        config_path = tmp_path / "mcp.json"
        existing = {"mcpServers": {"other-server": {"command": "other"}}}
        config_path.write_text(json.dumps(existing))
        wizard = SetupWizard(
            SetupConfig(mcp_client="cursor", mcp_client_config_path=str(config_path))
        )
        wizard._find_env_path = lambda: tmp_path / ".env"
        wizard._write_mcp_client_config()
        data = json.loads(config_path.read_text())
        assert "other-server" in data["mcpServers"]
        assert "memory" in data["mcpServers"]


class TestSetupCommand:
    """Integration tests for the 'memory setup' CLI command."""

    def test_non_interactive_sqlite(self, tmp_path):
        """Non-interactive setup with sqlite_vec backend."""
        runner = CliRunner()
        with patch(
            "mcp_memory_service.cli.setup.SetupWizard._find_env_path",
            return_value=tmp_path / ".env",
        ):
            result = runner.invoke(
                cli, ["setup", "--non-interactive", "--backend", "sqlite_vec"]
            )
            assert result.exit_code == 0
            assert (tmp_path / ".env").exists()
            content = (tmp_path / ".env").read_text()
            assert "MCP_MEMORY_STORAGE_BACKEND=sqlite_vec" in content

    def test_non_interactive_hybrid_with_backup(self, tmp_path):
        """Non-interactive setup with hybrid + R2 backup."""
        runner = CliRunner()
        with patch(
            "mcp_memory_service.cli.setup.SetupWizard._find_env_path",
            return_value=tmp_path / ".env",
        ):
            result = runner.invoke(
                cli,
                [
                    "setup",
                    "--non-interactive",
                    "--backend",
                    "hybrid",
                    "--cf-token",
                    "test-token",
                    "--cf-account",
                    "test-account",
                    "--cf-d1",
                    "test-db-id",
                    "--backup-r2",
                ],
            )
            assert result.exit_code == 0
            content = (tmp_path / ".env").read_text()
            assert "CLOUDFLARE_API_TOKEN=test-token" in content
            assert "MCP_BACKUP_R2_ENABLED=true" in content
            assert "MCP_HYBRID_SYNC_OWNER=http" in content

    def test_interactive_flow_sqlite(self, tmp_path):
        """Interactive setup with simulated input for sqlite_vec."""
        runner = CliRunner()
        # Inputs: backend=1(sqlite), local_backup=y, R2=n, GitHub=n,
        # host=default, port=default, no clients detected, client=none, confirm=y
        inputs = "1\ny\nn\nn\n\n\nnone\ny\n"
        with patch(
            "mcp_memory_service.cli.setup.SetupWizard._find_env_path",
            return_value=tmp_path / ".env",
        ), patch(
            "mcp_memory_service.cli.setup.SetupWizard._detect_mcp_clients",
            return_value=[],
        ):
            result = runner.invoke(cli, ["setup"], input=inputs)
            assert result.exit_code == 0
            assert (tmp_path / ".env").exists()
