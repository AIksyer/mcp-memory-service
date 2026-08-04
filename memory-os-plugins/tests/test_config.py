"""Tests for git_sync.config — GitSyncConfig and load_config()."""

from __future__ import annotations

import os

import pytest

from memory_os_plugins.git_sync.config import (
    GitSyncConfig,
    _parse_bool,
    _parse_config_file,
    load_config,
    save_config,
)


# --------------------------------------------------------------------------- #
#  GitSyncConfig defaults
# --------------------------------------------------------------------------- #

class TestGitSyncConfig:
    def test_defaults(self):
        c = GitSyncConfig()
        assert c.enabled is True
        assert c.repo_path == "~/AgentMemory"
        assert c.auto_push is False
        assert c.batch_size == 5
        assert c.batch_timeout == 30
        assert c.project_name == ""


# --------------------------------------------------------------------------- #
#  _parse_bool
# --------------------------------------------------------------------------- #

class TestParseBool:
    @pytest.mark.parametrize("value", ["true", "True", "TRUE", "yes", "on", "1"])
    def test_truthy(self, value):
        assert _parse_bool(value) is True

    @pytest.mark.parametrize("value", ["false", "no", "off", "0", "", "random"])
    def test_falsy(self, value):
        assert _parse_bool(value) is False


# --------------------------------------------------------------------------- #
#  _parse_config_file
# --------------------------------------------------------------------------- #

class TestParseConfigFile:
    def test_basic(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "enabled: false\n"
            "repo_path: /custom/path\n"
            "auto_push: true\n"
            "batch_size: 10\n"
            "batch_timeout: 60\n"
            "project_name: MyProject\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result["enabled"] is False
        assert result["repo_path"] == "/custom/path"
        assert result["auto_push"] is True
        assert result["batch_size"] == 10
        assert result["batch_timeout"] == 60
        assert result["project_name"] == "MyProject"

    def test_comments_and_blanks(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "# This is a comment\n"
            "\n"
            "enabled: true\n"
            "\n"
            "# Another comment\n"
            "batch_size: 3\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result == {"enabled": True, "batch_size": 3}

    def test_negative_int(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text("batch_timeout: -1\n", encoding="utf-8")
        result = _parse_config_file(f)
        assert result["batch_timeout"] == -1

    def test_no_colon_line_skipped(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text("enabled: true\nno colon line\nbatch_size: 5\n", encoding="utf-8")
        result = _parse_config_file(f)
        assert "no colon line" not in result
        assert result["enabled"] is True
        assert result["batch_size"] == 5


# --------------------------------------------------------------------------- #
#  load_config — priority: env > file > defaults
# --------------------------------------------------------------------------- #

class TestLoadConfig:
    def test_defaults_when_no_file_no_env(self, tmp_path, monkeypatch):
        """load_config() should return defaults when no file or env vars."""
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "nonexistent.yml"
        )
        # Clear any env vars from the test environment.
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is True
        assert config.repo_path == "~/AgentMemory"
        assert config.auto_push is False
        assert config.batch_size == 5
        assert config.batch_timeout == 30

    def test_file_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "config.yml"
        )
        (tmp_path / "config.yml").write_text(
            "enabled: false\nrepo_path: /from/file\nbatch_size: 99\n",
            encoding="utf-8",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is False
        assert config.repo_path == "/from/file"
        assert config.batch_size == 99

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "config.yml"
        )
        (tmp_path / "config.yml").write_text(
            "enabled: false\nrepo_path: /from/file\n", encoding="utf-8"
        )
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "true")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_REPO_PATH", "/from/env")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_SIZE", "42")

        config = load_config()
        assert config.enabled is True
        assert config.repo_path == "/from/env"
        assert config.batch_size == 42

    def test_env_overrides_defaults_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "nonexistent.yml"
        )
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "false")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_AUTO_PUSH", "true")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_PROJECT_NAME", "EnvProject")

        config = load_config()
        assert config.enabled is False
        assert config.auto_push is True
        assert config.project_name == "EnvProject"

    def test_invalid_env_value_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "nonexistent.yml"
        )
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_SIZE", "not_a_number")

        config = load_config()
        # Should fall back to default when env value is invalid.
        assert config.batch_size == 5

    def test_corrupt_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE", tmp_path / "config.yml"
        )
        # Write a file that will cause _parse_config_file to fail.
        # Actually _parse_config_file is robust; let's make the file unreadable
        # by making it a directory.
        (tmp_path / "config.yml").mkdir()

        config = load_config()
        # Should fall back to defaults.
        assert config.enabled is True


# --------------------------------------------------------------------------- #
#  Requested test names — additional coverage
# --------------------------------------------------------------------------- #

class TestRequestedConfigTests:
    """Tests with exact names as specified in the task description."""

    def test_load_config_defaults(self, tmp_path, monkeypatch):
        """load_config() returns correct defaults with no file or env."""
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is True
        assert config.repo_path == "~/AgentMemory"
        assert config.auto_push is False
        assert config.batch_size == 5
        assert config.batch_timeout == 30
        assert config.project_name == ""

    def test_load_config_from_env(self, tmp_path, monkeypatch):
        """load_config() reads values from MEMORY_OS_GIT_SYNC_* env vars."""
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "false")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_REPO_PATH", "/custom/env/path")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_AUTO_PUSH", "true")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_SIZE", "20")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_TIMEOUT", "120")
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_PROJECT_NAME", "EnvProj")

        config = load_config()
        assert config.enabled is False
        assert config.repo_path == "/custom/env/path"
        assert config.auto_push is True
        assert config.batch_size == 20
        assert config.batch_timeout == 120
        assert config.project_name == "EnvProj"

    def test_load_config_type_conversion(self, tmp_path, monkeypatch):
        """Env var strings are converted to proper bool/int types."""
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)

        # Bool conversion: various truthy/falsy strings.
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "yes")
        config = load_config()
        assert config.enabled is True
        assert isinstance(config.enabled, bool)

        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "0")
        config = load_config()
        assert config.enabled is False
        assert isinstance(config.enabled, bool)

        # Int conversion.
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_SIZE", "42")
        config = load_config()
        assert config.batch_size == 42
        assert isinstance(config.batch_size, int)

        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_BATCH_TIMEOUT", "99")
        config = load_config()
        assert config.batch_timeout == 99
        assert isinstance(config.batch_timeout, int)


# --------------------------------------------------------------------------- #
#  save_config
# --------------------------------------------------------------------------- #

class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        cfg_path = tmp_path / "config.yml"
        original = GitSyncConfig(
            enabled=False,
            repo_path="/custom",
            auto_push=True,
            batch_size=10,
            batch_timeout=60,
            project_name="TestProj",
        )
        save_config(original, path=cfg_path)
        assert cfg_path.exists()

        loaded = _parse_config_file(cfg_path)
        assert loaded["enabled"] is False
        assert loaded["repo_path"] == "/custom"
        assert loaded["auto_push"] is True
        assert loaded["batch_size"] == 10
        assert loaded["batch_timeout"] == 60
        assert loaded["project_name"] == "TestProj"

    def test_no_project_name_omitted(self, tmp_path):
        cfg_path = tmp_path / "config.yml"
        original = GitSyncConfig(project_name="")
        save_config(original, path=cfg_path)
        content = cfg_path.read_text(encoding="utf-8")
        assert "project_name" not in content

    def test_creates_parent_dir(self, tmp_path):
        cfg_path = tmp_path / "subdir" / "config.yml"
        save_config(GitSyncConfig(), path=cfg_path)
        assert cfg_path.exists()

    def test_preserves_r2_backup_config(self, tmp_path):
        """save_config should not overwrite r2_backup lines in shared config."""
        cfg_path = tmp_path / "config.yml"
        # Write a config file that has both git_sync and r2_backup lines.
        cfg_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "auto_push: false\n"
            "batch_size: 5\n"
            "batch_timeout: 30\n"
            "\n"
            "# Memory OS R2 Backup configuration\n"
            "r2_backup_enabled: true\n"
            "r2_backup_endpoint_url: https://abc.r2.cloudflarestorage.com\n"
            "r2_backup_access_key_id: testkey\n"
            "r2_backup_secret_access_key: testsecret\n"
            "r2_backup_bucket_name: testbucket\n"
            "r2_backup_prefix: memories/\n"
            "r2_backup_batch_upload: true\n",
            encoding="utf-8",
        )

        # Re-save git_sync config — should preserve r2_backup lines.
        new_config = GitSyncConfig(
            enabled=False,
            repo_path="/new/path",
            auto_push=True,
            batch_size=10,
            batch_timeout=60,
        )
        save_config(new_config, path=cfg_path)

        content = cfg_path.read_text(encoding="utf-8")

        # r2_backup lines should be preserved.
        assert "r2_backup_enabled: true" in content
        assert "r2_backup_endpoint_url: https://abc.r2.cloudflarestorage.com" in content
        assert "r2_backup_access_key_id: testkey" in content
        assert "r2_backup_bucket_name: testbucket" in content

        # git_sync lines should be updated.
        assert "enabled: false" in content
        assert "repo_path: /new/path" in content
        assert "auto_push: true" in content
        assert "batch_size: 10" in content
        assert "batch_timeout: 60" in content
