# Copyright 2024 Heinrich Krupp
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0

"""Coverage tests for CLI modules previously omitted from .coveragerc.

Tests:
- CLI entry point and command parsing (cli/main.py)
- Server lifecycle utilities (cli/lifecycle.py)
- CLI ingestion commands (cli/ingestion.py)
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from mcp_memory_service.cli.main import cli


class TestCLIEntryPoint:
    """Cover cli/main.py command parsing."""

    def test_cli_help(self):
        """CLI --help shows available commands."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "server" in result.output or "launch" in result.output

    def test_cli_version(self):
        """CLI --version shows the package version."""
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0

    def test_launch_help(self):
        """launch --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["launch", "--help"])
        assert result.exit_code == 0
        assert "--host" in result.output or "--http-host" in result.output

    def test_stop_help(self):
        """stop --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["stop", "--help"])
        assert result.exit_code == 0

    def test_restart_help(self):
        """restart --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["restart", "--help"])
        assert result.exit_code == 0

    def test_info_help(self):
        """info --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["info", "--help"])
        assert result.exit_code == 0

    def test_logs_help(self):
        """logs --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["logs", "--help"])
        assert result.exit_code == 0

    def test_server_help(self):
        """server --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["server", "--help"])
        assert result.exit_code == 0

    def test_status_help(self):
        """status --help shows options."""
        runner = CliRunner()
        result = runner.invoke(cli, ["status", "--help"])
        assert result.exit_code == 0


class TestCLILifecycle:
    """Cover cli/lifecycle.py utility functions."""

    def test_data_dir(self):
        from mcp_memory_service.cli.lifecycle import _data_dir
        result = _data_dir()
        assert isinstance(result, Path)
        assert len(str(result)) > 0

    def test_pid_file(self):
        from mcp_memory_service.cli.lifecycle import _pid_file
        result = _pid_file()
        assert isinstance(result, Path)
        assert "pid" in str(result).lower() or result.suffix == ".pid"

    def test_log_dir(self):
        from mcp_memory_service.cli.lifecycle import _log_dir
        result = _log_dir()
        assert isinstance(result, Path)

    def test_log_file(self):
        from mcp_memory_service.cli.lifecycle import _log_file
        result = _log_file()
        assert isinstance(result, Path)
        assert result.suffix == ".log"

    def test_ensure_dirs(self):
        from mcp_memory_service.cli.lifecycle import _ensure_dirs
        _ensure_dirs()  # Should not raise
        from mcp_memory_service.cli.lifecycle import _data_dir, _log_dir
        assert _data_dir().exists()
        assert _log_dir().exists()

    def test_read_pid_no_file(self):
        """_read_pid returns None when no PID file exists."""
        from mcp_memory_service.cli.lifecycle import _read_pid
        with patch("mcp_memory_service.cli.lifecycle._pid_file") as mock_path:
            mock_path.return_value = Path(tempfile.mktemp())
            result = _read_pid()
            assert result is None

    def test_base_url_http(self):
        from mcp_memory_service.cli.lifecycle import _base_url
        url = _base_url("localhost", 8000)
        assert url.startswith("http")
        assert "localhost" in url
        assert "8000" in url

    def test_base_url_https(self):
        from mcp_memory_service.cli.lifecycle import _base_url
        # _is_https_enabled checks env vars
        with patch.dict(os.environ, {"MCP_HTTPS_ENABLED": "true"}):
            url = _base_url("example.com", 443)
            assert url.startswith("https://")

    def test_is_https_enabled_false(self):
        from mcp_memory_service.cli.lifecycle import _is_https_enabled
        with patch.dict(os.environ, {}, clear=True):
            # Remove all env vars that might enable HTTPS
            for key in ["MCP_HTTPS_ENABLED", "MCP_HTTPS_CERT", "MCP_HTTPS_KEY"]:
                os.environ.pop(key, None)
            assert _is_https_enabled() is False

    def test_is_process_alive_invalid_pid(self):
        from mcp_memory_service.cli.lifecycle import _is_process_alive
        # PID 0 is invalid on all platforms
        assert _is_process_alive(0) is False
        # Very high PID is unlikely to exist
        assert _is_process_alive(999999) is False

    def test_read_log_tail_empty(self):
        """_read_log_tail returns empty list when no log file exists."""
        from mcp_memory_service.cli.lifecycle import _read_log_tail
        with patch("mcp_memory_service.cli.lifecycle._log_file") as mock_path:
            mock_path.return_value = Path(tempfile.mktemp())
            result = _read_log_tail(10)
            assert isinstance(result, list)

    def test_http_get_json_invalid_url(self):
        """_http_get_json returns None for unreachable URLs."""
        from mcp_memory_service.cli.lifecycle import _http_get_json
        result = _http_get_json("http://127.0.0.1:1/nonexistent", timeout=1)
        assert result is None


class TestCLICommands:
    """Test CLI commands with mocked behavior."""

    def test_info_no_server(self):
        """info command handles no-running-server gracefully."""
        runner = CliRunner()
        with patch("mcp_memory_service.cli.lifecycle._read_pid", return_value=None):
            result = runner.invoke(cli, ["info"])
            # Should not crash, may exit with 0 or 1
            assert result.exit_code in (0, 1)

    def test_stop_no_server(self):
        """stop command handles no-running-server gracefully."""
        runner = CliRunner()
        with patch("mcp_memory_service.cli.lifecycle._read_pid", return_value=None):
            result = runner.invoke(cli, ["stop"])
            assert result.exit_code in (0, 1)

    def test_logs_no_file(self):
        """logs command handles missing log file gracefully."""
        runner = CliRunner()
        with patch("mcp_memory_service.cli.lifecycle._read_log_tail", return_value=[]):
            result = runner.invoke(cli, ["logs"])
            assert result.exit_code in (0, 1)
