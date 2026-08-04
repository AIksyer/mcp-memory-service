"""Tests for the r2_backup plugin — config, r2_ops, and plugin handlers."""

from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import MagicMock, patch

try:
    from unittest.mock import AsyncMock
except ImportError:
    class AsyncMock:
        def __init__(self, *args, **kwargs):
            self.call_args = None
            self.call_count = 0
            self._return_value = kwargs.get("return_value")

        async def __call__(self, *args, **kwargs):
            self.call_args = (args, kwargs)
            self.call_count += 1
            return self._return_value

        def assert_called_once_with(self, *args, **kwargs):
            assert self.call_count == 1
            assert self.call_args[0] == args

        def assert_not_called(self):
            assert self.call_count == 0

import pytest

from memory_os_plugins.r2_backup import plugin
from memory_os_plugins.r2_backup.config import (
    R2BackupConfig,
    _parse_bool,
    _parse_config_file,
    load_config,
    save_config,
)
from memory_os_plugins.r2_backup.r2_ops import (
    _get_s3_client,
    _s3_client_cache,
    delete_from_r2,
    download_from_r2,
    list_r2_objects,
    sync_directory_to_r2,
    upload_to_r2,
)


# --------------------------------------------------------------------------- #
#  Fake PluginContext
# --------------------------------------------------------------------------- #

class FakePluginContext:
    """Minimal PluginContext for testing — records hook subscriptions."""

    def __init__(self):
        self.storage = MagicMock()
        self.service = MagicMock()
        self.hooks: dict[str, list] = {}

    def on(self, hook_name, fn):
        self.hooks.setdefault(hook_name, []).append(fn)


# --------------------------------------------------------------------------- #
#  R2BackupConfig defaults
# --------------------------------------------------------------------------- #

class TestR2BackupConfig:
    def test_defaults(self):
        c = R2BackupConfig()
        assert c.enabled is False
        assert c.endpoint_url == ""
        assert c.access_key_id == ""
        assert c.secret_access_key == ""
        assert c.bucket_name == ""
        assert c.prefix == "memories/"
        assert c.batch_upload is True


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
#  _parse_config_file — only picks up r2_backup_* keys
# --------------------------------------------------------------------------- #

class TestParseConfigFile:
    def test_basic(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "\n"
            "# Memory OS R2 Backup configuration\n"
            "r2_backup_enabled: true\n"
            "r2_backup_endpoint_url: https://abc.r2.cloudflarestorage.com\n"
            "r2_backup_access_key_id: mykey\n"
            "r2_backup_secret_access_key: mysecret\n"
            "r2_backup_bucket_name: mybucket\n"
            "r2_backup_prefix: memories/\n"
            "r2_backup_batch_upload: false\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result["enabled"] is True
        assert result["endpoint_url"] == "https://abc.r2.cloudflarestorage.com"
        assert result["access_key_id"] == "mykey"
        assert result["secret_access_key"] == "mysecret"
        assert result["bucket_name"] == "mybucket"
        assert result["prefix"] == "memories/"
        assert result["batch_upload"] is False
        # git_sync keys should NOT appear (filtered by prefix).
        assert "repo_path" not in result

    def test_comments_and_blanks(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "# Comment\n"
            "\n"
            "r2_backup_enabled: true\n"
            "\n"
            "# Another\n"
            "r2_backup_bucket_name: test\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result == {"enabled": True, "bucket_name": "test"}

    def test_no_r2_keys_returns_empty(self, tmp_path):
        f = tmp_path / "config.yml"
        f.write_text(
            "enabled: true\nrepo_path: ~/repo\n",
            encoding="utf-8",
        )
        result = _parse_config_file(f)
        assert result == {}


# --------------------------------------------------------------------------- #
#  load_config — priority: env > file > defaults
# --------------------------------------------------------------------------- #

class TestLoadConfig:
    def test_defaults_when_no_file_no_env(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is False
        assert config.endpoint_url == ""
        assert config.bucket_name == ""
        assert config.prefix == "memories/"

    def test_file_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").write_text(
            "r2_backup_enabled: true\n"
            "r2_backup_endpoint_url: https://xyz.r2.cloudflarestorage.com\n"
            "r2_backup_bucket_name: mybucket\n",
            encoding="utf-8",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        config = load_config()
        assert config.enabled is True
        assert config.endpoint_url == "https://xyz.r2.cloudflarestorage.com"
        assert config.bucket_name == "mybucket"

    def test_env_overrides_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").write_text(
            "r2_backup_enabled: false\n"
            "r2_backup_bucket_name: file_bucket\n",
            encoding="utf-8",
        )
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "true")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_BUCKET_NAME", "env_bucket")

        config = load_config()
        assert config.enabled is True
        assert config.bucket_name == "env_bucket"

    def test_env_overrides_defaults_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "true")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENDPOINT_URL", "https://env.r2.cloudflarestorage.com")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ACCESS_KEY_ID", "envkey")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_SECRET_ACCESS_KEY", "envsecret")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_BUCKET_NAME", "envbucket")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_PREFIX", "backups/")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_BATCH_UPLOAD", "false")

        config = load_config()
        assert config.enabled is True
        assert config.endpoint_url == "https://env.r2.cloudflarestorage.com"
        assert config.access_key_id == "envkey"
        assert config.secret_access_key == "envsecret"
        assert config.bucket_name == "envbucket"
        assert config.prefix == "backups/"
        assert config.batch_upload is False

    def test_invalid_env_value_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "not_a_bool")
        # _parse_bool returns False for unrecognized strings, so this won't
        # raise, but let's test an invalid int-like env (no int fields in R2 config).
        config = load_config()
        assert config.enabled is False  # _parse_bool("not_a_bool") == False

    def test_type_conversion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "yes")
        config = load_config()
        assert config.enabled is True
        assert isinstance(config.enabled, bool)

        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "0")
        config = load_config()
        assert config.enabled is False
        assert isinstance(config.enabled, bool)

    def test_corrupt_file_falls_back(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "config.yml",
        )
        (tmp_path / "config.yml").mkdir()  # Not a file — will cause read error

        config = load_config()
        assert config.enabled is False  # Default


# --------------------------------------------------------------------------- #
#  save_config — merge with existing config.yml
# --------------------------------------------------------------------------- #

class TestSaveConfig:
    def test_round_trip(self, tmp_path):
        cfg_path = tmp_path / "config.yml"
        original = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="key123",
            secret_access_key="secret123",
            bucket_name="mybucket",
            prefix="backups/",
            batch_upload=False,
        )
        save_config(original, path=cfg_path)
        assert cfg_path.exists()

        loaded = _parse_config_file(cfg_path)
        assert loaded["enabled"] is True
        assert loaded["endpoint_url"] == "https://abc.r2.cloudflarestorage.com"
        assert loaded["access_key_id"] == "key123"
        assert loaded["secret_access_key"] == "secret123"
        assert loaded["bucket_name"] == "mybucket"
        assert loaded["prefix"] == "backups/"
        assert loaded["batch_upload"] is False

    def test_creates_parent_dir(self, tmp_path):
        cfg_path = tmp_path / "subdir" / "config.yml"
        save_config(R2BackupConfig(), path=cfg_path)
        assert cfg_path.exists()

    def test_merge_preserves_git_sync_config(self, tmp_path):
        """save_config should not clobber existing git_sync config."""
        cfg_path = tmp_path / "config.yml"
        # Pre-existing git_sync config.
        cfg_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "auto_push: false\n"
            "batch_size: 5\n",
            encoding="utf-8",
        )

        r2_config = R2BackupConfig(
            enabled=True,
            bucket_name="r2bucket",
            endpoint_url="https://abc.r2.cloudflarestorage.com",
        )
        save_config(r2_config, path=cfg_path)

        content = cfg_path.read_text(encoding="utf-8")
        # git_sync config should be preserved.
        assert "enabled: true" in content
        assert "repo_path: ~/AgentMemory" in content
        assert "auto_push: false" in content
        assert "batch_size: 5" in content
        # R2 config should be appended.
        assert "r2_backup_enabled: true" in content
        assert "r2_backup_bucket_name: r2bucket" in content
        assert "r2_backup_endpoint_url: https://abc.r2.cloudflarestorage.com" in content

    def test_save_replaces_old_r2_config(self, tmp_path):
        """save_config should replace existing r2_backup_* lines."""
        cfg_path = tmp_path / "config.yml"
        cfg_path.write_text(
            "# Memory OS Git Sync configuration\n"
            "enabled: true\n"
            "repo_path: ~/AgentMemory\n"
            "\n"
            "# Memory OS R2 Backup configuration\n"
            "r2_backup_enabled: false\n"
            "r2_backup_bucket_name: old_bucket\n",
            encoding="utf-8",
        )

        new_config = R2BackupConfig(
            enabled=True,
            bucket_name="new_bucket",
        )
        save_config(new_config, path=cfg_path)

        content = cfg_path.read_text(encoding="utf-8")
        assert "old_bucket" not in content
        assert "r2_backup_bucket_name: new_bucket" in content
        assert "r2_backup_enabled: true" in content
        # Only one R2 section comment.
        assert content.count("# Memory OS R2 Backup configuration") == 1


# --------------------------------------------------------------------------- #
#  r2_ops — with mocked boto3 client
# --------------------------------------------------------------------------- #

class TestR2Ops:
    """Test r2_ops functions with a mocked S3 client."""

    def setup_method(self):
        self.config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="testkey",
            secret_access_key="testsecret",
            bucket_name="testbucket",
            prefix="memories/",
        )
        # Clear the S3 client cache between tests.
        _s3_client_cache.clear()

    def test_get_s3_client(self):
        """_get_s3_client should create a boto3 S3 client with R2 config."""
        mock_boto3 = MagicMock()
        mock_client = MagicMock()
        mock_boto3.client.return_value = mock_client

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            client = _get_s3_client(self.config)

        assert client is mock_client
        mock_boto3.client.assert_called_once_with(
            "s3",
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            aws_access_key_id="testkey",
            aws_secret_access_key="testsecret",
            region_name="auto",
        )

    def test_get_s3_client_caching(self):
        """_get_s3_client should cache and reuse the client for same config."""
        mock_boto3 = MagicMock()
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_boto3.client.side_effect = [mock_client1, mock_client2]

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            client1 = _get_s3_client(self.config)
            client2 = _get_s3_client(self.config)

        assert client1 is mock_client1
        assert client2 is mock_client1  # Same cached client
        mock_boto3.client.assert_called_once()  # Only called once

    def test_get_s3_client_different_config_no_cache(self):
        """_get_s3_client should create new client for different config."""
        mock_boto3 = MagicMock()
        mock_client1 = MagicMock()
        mock_client2 = MagicMock()
        mock_boto3.client.side_effect = [mock_client1, mock_client2]

        config2 = R2BackupConfig(
            enabled=True,
            endpoint_url="https://def.r2.cloudflarestorage.com",
            access_key_id="otherkey",
            secret_access_key="othersecret",
            bucket_name="otherbucket",
        )

        with patch.dict(sys.modules, {"boto3": mock_boto3}):
            client1 = _get_s3_client(self.config)
            client2 = _get_s3_client(config2)

        assert client1 is mock_client1
        assert client2 is mock_client2
        assert mock_boto3.client.call_count == 2

    def test_upload_to_r2_success(self, tmp_path):
        """upload_to_r2 should call S3 upload_file and return True."""
        local_file = tmp_path / "test.md"
        local_file.write_text("content", encoding="utf-8")

        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = upload_to_r2(self.config, local_file, "memories/ab/test.md")

        assert result is True
        mock_client.upload_file.assert_called_once_with(
            str(local_file), "testbucket", "memories/ab/test.md"
        )

    def test_upload_to_r2_failure(self, tmp_path):
        """upload_to_r2 should return False on exception."""
        local_file = tmp_path / "test.md"
        local_file.write_text("content", encoding="utf-8")

        mock_client = MagicMock()
        mock_client.upload_file.side_effect = Exception("Network error")
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = upload_to_r2(self.config, local_file, "memories/ab/test.md")

        assert result is False

    def test_download_from_r2_success(self, tmp_path):
        """download_from_r2 should call S3 download_file and return True."""
        local_file = tmp_path / "downloaded" / "test.md"

        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = download_from_r2(self.config, "memories/ab/test.md", local_file)

        assert result is True
        mock_client.download_file.assert_called_once_with(
            "testbucket", "memories/ab/test.md", str(local_file)
        )
        # Parent directory should be created.
        assert local_file.parent.exists()

    def test_download_from_r2_failure(self, tmp_path):
        """download_from_r2 should return False on exception."""
        mock_client = MagicMock()
        mock_client.download_file.side_effect = Exception("Not found")
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = download_from_r2(self.config, "memories/ab/test.md", tmp_path / "out.md")

        assert result is False

    def test_delete_from_r2_success(self):
        """delete_from_r2 should call S3 delete_object and return True."""
        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = delete_from_r2(self.config, "memories/ab/test.md")

        assert result is True
        mock_client.delete_object.assert_called_once_with(
            Bucket="testbucket", Key="memories/ab/test.md"
        )

    def test_delete_from_r2_failure(self):
        """delete_from_r2 should return False on exception."""
        mock_client = MagicMock()
        mock_client.delete_object.side_effect = Exception("Access denied")
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = delete_from_r2(self.config, "memories/ab/test.md")

        assert result is False

    def test_list_r2_objects_success(self):
        """list_r2_objects should return a list of object keys."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {
            "Contents": [
                {"Key": "memories/ab/hash1.md"},
                {"Key": "memories/cd/hash2.md"},
            ]
        }
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = list_r2_objects(self.config)

        assert result == ["memories/ab/hash1.md", "memories/cd/hash2.md"]
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="testbucket", Prefix="memories/"
        )

    def test_list_r2_objects_empty(self):
        """list_r2_objects should return empty list when bucket is empty."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {}
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = list_r2_objects(self.config)

        assert result == []

    def test_list_r2_objects_with_custom_prefix(self):
        """list_r2_objects should use provided prefix over config.prefix."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.return_value = {"Contents": [{"Key": "backups/x.md"}]}
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = list_r2_objects(self.config, prefix="backups/")

        assert result == ["backups/x.md"]
        mock_client.list_objects_v2.assert_called_once_with(
            Bucket="testbucket", Prefix="backups/"
        )

    def test_list_r2_objects_failure(self):
        """list_r2_objects should return empty list on exception."""
        mock_client = MagicMock()
        mock_client.list_objects_v2.side_effect = Exception("Connection error")
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = list_r2_objects(self.config)

        assert result == []

    def test_sync_directory_to_r2_success(self, tmp_path):
        """sync_directory_to_r2 should upload all files in a directory."""
        local_dir = tmp_path / "memories"
        (local_dir / "ab").mkdir(parents=True)
        (local_dir / "ab" / "hash1.md").write_text("content1", encoding="utf-8")
        (local_dir / "cd").mkdir()
        (local_dir / "cd" / "hash2.md").write_text("content2", encoding="utf-8")

        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = sync_directory_to_r2(self.config, local_dir, "memories")

        assert result is True
        assert mock_client.upload_file.call_count == 2

    def test_sync_directory_not_a_directory(self, tmp_path):
        """sync_directory_to_r2 should return False if path is not a directory."""
        not_a_dir = tmp_path / "file.txt"
        not_a_dir.write_text("content", encoding="utf-8")

        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=MagicMock(),
        ):
            result = sync_directory_to_r2(self.config, not_a_dir, "memories")

        assert result is False

    def test_sync_directory_empty(self, tmp_path):
        """sync_directory_to_r2 should return True for empty directory."""
        local_dir = tmp_path / "empty"
        local_dir.mkdir()

        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=MagicMock(),
        ):
            result = sync_directory_to_r2(self.config, local_dir, "memories")

        assert result is True

    def test_sync_directory_batch_upload_false(self, tmp_path):
        """sync_directory_to_r2 should work with batch_upload=False (sequential)."""
        local_dir = tmp_path / "memories"
        (local_dir / "ab").mkdir(parents=True)
        (local_dir / "ab" / "hash1.md").write_text("content1", encoding="utf-8")
        (local_dir / "ab" / "hash2.md").write_text("content2", encoding="utf-8")

        config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="testkey",
            secret_access_key="testsecret",
            bucket_name="testbucket",
            prefix="memories/",
            batch_upload=False,
        )

        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = sync_directory_to_r2(config, local_dir, "memories")

        assert result is True
        assert mock_client.upload_file.call_count == 2

    def test_sync_directory_batch_upload_true(self, tmp_path):
        """sync_directory_to_r2 should use ThreadPoolExecutor when batch_upload=True."""
        local_dir = tmp_path / "memories"
        (local_dir / "ab").mkdir(parents=True)
        (local_dir / "ab" / "hash1.md").write_text("content1", encoding="utf-8")
        (local_dir / "ab" / "hash2.md").write_text("content2", encoding="utf-8")
        (local_dir / "ab" / "hash3.md").write_text("content3", encoding="utf-8")

        mock_client = MagicMock()
        with patch(
            "memory_os_plugins.r2_backup.r2_ops._get_s3_client",
            return_value=mock_client,
        ):
            result = sync_directory_to_r2(self.config, local_dir, "memories")

        assert result is True
        assert mock_client.upload_file.call_count == 3
#  Plugin register()
# --------------------------------------------------------------------------- #

class TestRegister:
    def setup_method(self):
        plugin._config = None

    def test_register_disabled(self, tmp_path, monkeypatch):
        """When disabled, register() should not subscribe any hooks."""
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert ctx.hooks == {}
        assert plugin._config is not None
        assert plugin._config.enabled is False

    def test_register_enabled_with_boto3(self, tmp_path, monkeypatch):
        """When enabled and boto3 is available, should subscribe hooks."""
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "true")
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_BUCKET_NAME", "testbucket")

        # Inject mock boto3 into sys.modules.
        mock_boto3 = MagicMock()
        monkeypatch.setitem(sys.modules, "boto3", mock_boto3)

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert "on_store" in ctx.hooks
        assert "on_delete" in ctx.hooks
        assert len(ctx.hooks["on_store"]) == 1
        assert len(ctx.hooks["on_delete"]) == 1
        assert plugin._config is not None
        assert plugin._config.enabled is True

    def test_register_enabled_without_boto3(self, tmp_path, monkeypatch):
        """When enabled but boto3 missing, should skip with warning."""
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_R2_BACKUP_ENABLED", "true")

        # Block boto3 import by setting sys.modules entry to None.
        monkeypatch.setitem(sys.modules, "boto3", None)

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert ctx.hooks == {}
        assert plugin._config is not None
        assert plugin._config.enabled is True

    def test_register_disabled_without_boto3(self, tmp_path, monkeypatch):
        """When disabled and boto3 missing, should skip silently."""
        monkeypatch.setattr(
            "memory_os_plugins.r2_backup.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_R2_BACKUP_"):
                monkeypatch.delenv(key, raising=False)

        monkeypatch.setitem(sys.modules, "boto3", None)

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert ctx.hooks == {}
        assert plugin._config is not None
        assert plugin._config.enabled is False


# --------------------------------------------------------------------------- #
#  _compute_r2_key
# --------------------------------------------------------------------------- #

class TestComputeR2Key:
    def test_basic(self):
        key = plugin._compute_r2_key("abcdef1234567890", "memories/")
        assert key == "memories/ab/abcdef1234567890.md"

    def test_short_hash(self):
        """Short hashes (< 2 chars) should use '00' as prefix dir."""
        key = plugin._compute_r2_key("a", "memories/")
        assert key == "memories/00/a.md"

    def test_custom_prefix(self):
        key = plugin._compute_r2_key("abcdef1234567890", "backups/")
        assert key == "backups/ab/abcdef1234567890.md"


# --------------------------------------------------------------------------- #
#  on_store_handler / on_delete_handler
# --------------------------------------------------------------------------- #

class TestHookHandlers:
    def setup_method(self):
        plugin._config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            prefix="memories/",
        )

    def test_on_store_creates_task(self):
        """on_store_handler should not block — it creates a background task."""
        with patch.object(plugin, "_r2_backup_store", new_callable=AsyncMock) as mock_store:
            async def _run():
                await plugin.on_store_handler({"content_hash": "abc123"})
                await asyncio.sleep(0.01)

            asyncio.run(_run())
            mock_store.assert_called_once_with({"content_hash": "abc123"})

    def test_on_delete_creates_task(self):
        with patch.object(plugin, "_r2_backup_delete", new_callable=AsyncMock) as mock_delete:
            async def _run():
                await plugin.on_delete_handler("abc123")
                await asyncio.sleep(0.01)

            asyncio.run(_run())
            mock_delete.assert_called_once_with("abc123")


# --------------------------------------------------------------------------- #
#  _r2_backup_store / _r2_backup_delete
# --------------------------------------------------------------------------- #

class TestR2BackupStore:
    def setup_method(self):
        plugin._config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            prefix="memories/",
        )

    def test_store_uploads_existing_file(self, tmp_path):
        """_r2_backup_store should upload when the Markdown file exists."""
        # Create the Markdown file at the expected git_sync path.
        repo_path = tmp_path / "repo"
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content", encoding="utf-8")

        # Mock git_sync config to return our repo_path.
        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            return_value=MagicMock(repo_path=str(repo_path)),
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.upload_to_r2",
                return_value=True,
            ) as mock_upload:
                asyncio.run(
                    plugin._r2_backup_store({"content_hash": "abcdef1234567890"})
                )

        r2_key = "memories/ab/abcdef1234567890.md"
        mock_upload.assert_called_once_with(
            plugin._config, md_path, r2_key
        )

    def test_store_skips_nonexistent_file(self, tmp_path):
        """_r2_backup_store should skip when the Markdown file doesn't exist."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            return_value=MagicMock(repo_path=str(tmp_path / "nonexistent")),
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.upload_to_r2",
            ) as mock_upload:
                asyncio.run(
                    plugin._r2_backup_store({"content_hash": "nonexistent123"})
                )

        mock_upload.assert_not_called()

    def test_store_empty_hash_skipped(self):
        asyncio.run(plugin._r2_backup_store({"content_hash": ""}))
        # Should not raise.

    def test_store_no_config_returns_silently(self):
        plugin._config = None
        asyncio.run(plugin._r2_backup_store({"content_hash": "abc"}))
        # Should not raise.

    def test_store_exception_does_not_propagate(self, tmp_path):
        """Errors in _r2_backup_store should be caught, not raised."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            side_effect=RuntimeError("boom"),
        ):
            asyncio.run(plugin._r2_backup_store({"content_hash": "abc123"}))
            # Should not raise.

    def test_store_uses_to_thread(self, tmp_path):
        """_r2_backup_store should use asyncio.to_thread for the sync upload."""
        repo_path = tmp_path / "repo"
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content", encoding="utf-8")

        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            return_value=MagicMock(repo_path=str(repo_path)),
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.upload_to_r2",
                return_value=True,
            ):
                with patch(
                    "memory_os_plugins.r2_backup.plugin.asyncio.to_thread",
                    new_callable=AsyncMock,
                ) as mock_to_thread:
                    asyncio.run(
                        plugin._r2_backup_store({"content_hash": "abcdef1234567890"})
                    )

        mock_to_thread.assert_called_once()


class TestR2BackupDelete:
    def setup_method(self):
        plugin._config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            prefix="memories/",
        )

    def test_delete_calls_delete_from_r2(self):
        """_r2_backup_delete should delete the corresponding R2 object."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.delete_from_r2",
            return_value=True,
        ) as mock_delete:
            asyncio.run(plugin._r2_backup_delete("abcdef1234567890"))

        r2_key = "memories/ab/abcdef1234567890.md"
        mock_delete.assert_called_once_with(plugin._config, r2_key)

    def test_delete_no_config_returns_silently(self):
        plugin._config = None
        asyncio.run(plugin._r2_backup_delete("abc"))
        # Should not raise.

    def test_delete_exception_does_not_propagate(self):
        """Errors in _r2_backup_delete should be caught, not raised."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.delete_from_r2",
            side_effect=RuntimeError("boom"),
        ):
            asyncio.run(plugin._r2_backup_delete("abc123"))
            # Should not raise.

    def test_delete_uses_to_thread(self):
        """_r2_backup_delete should use asyncio.to_thread for the sync delete."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.delete_from_r2",
            return_value=True,
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.asyncio.to_thread",
                new_callable=AsyncMock,
            ) as mock_to_thread:
                asyncio.run(plugin._r2_backup_delete("abcdef1234567890"))

        mock_to_thread.assert_called_once()


# --------------------------------------------------------------------------- #
#  Integration: on_store_handler → _r2_backup_store
# --------------------------------------------------------------------------- #

class TestHandlerIntegration:
    def setup_method(self):
        plugin._config = R2BackupConfig(
            enabled=True,
            endpoint_url="https://abc.r2.cloudflarestorage.com",
            access_key_id="key",
            secret_access_key="secret",
            bucket_name="bucket",
            prefix="memories/",
        )

    def test_on_store_handler_uploads_file(self, tmp_path):
        """Full flow: on_store_handler → file exists → upload to R2."""
        repo_path = tmp_path / "repo"
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content", encoding="utf-8")

        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            return_value=MagicMock(repo_path=str(repo_path)),
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.upload_to_r2",
                return_value=True,
            ) as mock_upload:
                async def _run():
                    await plugin.on_store_handler({"content_hash": "abcdef1234567890"})
                    await asyncio.sleep(0.05)  # let background task complete

                asyncio.run(_run())

        r2_key = "memories/ab/abcdef1234567890.md"
        mock_upload.assert_called_once_with(plugin._config, md_path, r2_key)

    def test_on_delete_handler_deletes_from_r2(self):
        """Full flow: on_delete_handler → delete from R2."""
        with patch(
            "memory_os_plugins.r2_backup.plugin.delete_from_r2",
            return_value=True,
        ) as mock_delete:
            async def _run():
                await plugin.on_delete_handler("abcdef1234567890")
                await asyncio.sleep(0.05)

            asyncio.run(_run())

        r2_key = "memories/ab/abcdef1234567890.md"
        mock_delete.assert_called_once_with(plugin._config, r2_key)

    def test_handler_error_isolation(self, tmp_path):
        """Handler exceptions should not propagate to the caller."""
        plugin._config = R2BackupConfig(enabled=True, prefix="memories/")

        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            side_effect=RuntimeError("synthetic failure"),
        ):
            async def _run():
                await plugin.on_store_handler({"content_hash": "abc123"})
                await asyncio.sleep(0.01)

            asyncio.run(_run())  # no exception raised

    def test_handler_is_async_fire_and_forget(self, tmp_path):
        """on_store_handler should return immediately without blocking."""
        import time

        repo_path = tmp_path / "repo"
        md_path = repo_path / "memories" / "a1" / "a1b2c3d4e5f6.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content", encoding="utf-8")

        with patch(
            "memory_os_plugins.r2_backup.plugin.load_git_config",
            return_value=MagicMock(repo_path=str(repo_path)),
        ):
            with patch(
                "memory_os_plugins.r2_backup.plugin.upload_to_r2",
                return_value=True,
            ):
                async def _run():
                    start = time.monotonic()
                    await plugin.on_store_handler({"content_hash": "a1b2c3d4e5f6"})
                    elapsed = time.monotonic() - start
                    assert elapsed < 0.1  # fire-and-forget
                    await asyncio.sleep(0.1)  # let background task complete

                asyncio.run(_run())
