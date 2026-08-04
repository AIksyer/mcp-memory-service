"""Tests for git_sync.plugin — register(), hook handlers, and sync logic."""

from __future__ import annotations

import asyncio
import os
import time
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

from memory_os_plugins.git_sync import plugin
from memory_os_plugins.git_sync.config import GitSyncConfig


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
#  register()
# --------------------------------------------------------------------------- #

class TestRegister:
    def setup_method(self):
        """Reset global state before each test."""
        plugin._config = None
        plugin._sync_queue = None

    def test_register_subscribes_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        # Clean env vars.
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_REPO_PATH", str(tmp_path / "repo"))

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert "on_store" in ctx.hooks
        assert "on_delete" in ctx.hooks
        assert len(ctx.hooks["on_store"]) == 1
        assert len(ctx.hooks["on_delete"]) == 1
        assert plugin._config is not None
        assert plugin._config.enabled is True
        assert plugin._sync_queue is not None

    def test_register_disabled_no_hooks(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "false")

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert ctx.hooks == {}
        assert plugin._config is not None
        assert plugin._config.enabled is False
        assert plugin._sync_queue is None


# --------------------------------------------------------------------------- #
#  on_store_handler / on_delete_handler
# --------------------------------------------------------------------------- #

class TestHookHandlers:
    def setup_method(self):
        plugin._config = GitSyncConfig(repo_path="/tmp/test_repo")
        plugin._sync_queue = MagicMock()

    def test_on_store_creates_task(self):
        """on_store_handler should not block — it creates a background task."""
        with patch.object(plugin, "_git_sync_store", new_callable=AsyncMock) as mock_sync:
            async def _run():
                await plugin.on_store_handler({"content_hash": "abc123"})
                await asyncio.sleep(0.01)  # let the background task run

            asyncio.run(_run())
            mock_sync.assert_called_once_with({"content_hash": "abc123"})

    def test_on_delete_creates_task(self):
        with patch.object(plugin, "_git_sync_delete", new_callable=AsyncMock) as mock_sync:
            async def _run():
                await plugin.on_delete_handler("abc123")
                await asyncio.sleep(0.01)  # let the background task run

            asyncio.run(_run())
            mock_sync.assert_called_once_with("abc123")


# --------------------------------------------------------------------------- #
#  _git_sync_store / _git_sync_delete
# --------------------------------------------------------------------------- #

class TestGitSyncStore:
    def setup_method(self):
        plugin._config = GitSyncConfig(repo_path="~/test_repo")
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

    def test_store_writes_markdown_and_enqueues(self, tmp_path):
        repo_path = tmp_path / "repo"
        repo_path.mkdir()
        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        memory_dict = {
            "content": "Test memory content",
            "content_hash": "abcdef1234567890",
            "tags": ["test"],
            "memory_type": "note",
            "metadata": {"importance": "high"},
            "created_at_iso": "2026-08-03T10:00:00",
        }

        asyncio.run(plugin._git_sync_store(memory_dict))

        # Check Markdown file was written.
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Test memory content" in content
        assert "abcdef1234567890" in content

        # Check enqueue was called.
        plugin._sync_queue.enqueue.assert_called_once_with("store", "abcdef1234567890")

    def test_store_empty_hash_skipped(self):
        asyncio.run(plugin._git_sync_store({"content_hash": ""}))
        plugin._sync_queue.enqueue.assert_not_called()

    def test_store_exception_does_not_propagate(self):
        """Errors in _git_sync_store should be caught, not raised."""
        with patch(
            "memory_os_plugins.git_sync.plugin.memory_to_markdown",
            side_effect=RuntimeError("boom"),
        ):
            # Should not raise.
            asyncio.run(plugin._git_sync_store({"content_hash": "abc123"}))

    def test_store_no_config_returns_silently(self):
        plugin._config = None
        asyncio.run(plugin._git_sync_store({"content_hash": "abc"}))
        # Should not raise.


class TestGitSyncDelete:
    def setup_method(self):
        plugin._config = GitSyncConfig(repo_path="~/test_repo")
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

    def test_delete_removes_file_and_enqueues(self, tmp_path):
        repo_path = tmp_path / "repo"
        # Create a markdown file to delete.
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content", encoding="utf-8")

        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        asyncio.run(plugin._git_sync_delete("abcdef1234567890"))

        assert not md_path.exists()
        plugin._sync_queue.enqueue.assert_called_once_with("delete", "abcdef1234567890")

    def test_delete_nonexistent_file_still_enqueues(self, tmp_path):
        """Deleting a non-existent file should still enqueue (idempotent)."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        asyncio.run(plugin._git_sync_delete("nonexistent_hash"))

        plugin._sync_queue.enqueue.assert_called_once_with("delete", "nonexistent_hash")

    def test_delete_exception_does_not_propagate(self):
        """Errors in _git_sync_delete should be caught, not raised."""
        with patch(
            "memory_os_plugins.git_sync.plugin.get_md_path",
            side_effect=RuntimeError("boom"),
        ):
            asyncio.run(plugin._git_sync_delete("abc123"))

    def test_delete_no_config_returns_silently(self):
        plugin._config = None
        asyncio.run(plugin._git_sync_delete("abc"))
        # Should not raise.


# --------------------------------------------------------------------------- #
#  Requested test names — additional coverage
# --------------------------------------------------------------------------- #

class TestRequestedPluginTests:
    """Tests with exact names as specified in the task description."""

    def setup_method(self):
        plugin._config = None
        plugin._sync_queue = None

    def test_register_disabled(self, tmp_path, monkeypatch):
        """When enabled=False, register() should not subscribe any hooks."""
        monkeypatch.setattr(
            "memory_os_plugins.git_sync.config.CONFIG_FILE",
            tmp_path / "nonexistent.yml",
        )
        for key in list(os.environ):
            if key.startswith("MEMORY_OS_GIT_SYNC_"):
                monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("MEMORY_OS_GIT_SYNC_ENABLED", "false")

        ctx = FakePluginContext()
        plugin.register(ctx)

        assert ctx.hooks == {}
        assert plugin._config is not None
        assert plugin._config.enabled is False
        assert plugin._sync_queue is None

    def test_on_store_handler_creates_markdown(self, tmp_path):
        """on_store_handler should create a markdown file at the expected path."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        memory_dict = {
            "content": "Test memory content",
            "content_hash": "abcdef1234567890",
            "tags": ["test"],
            "memory_type": "note",
            "metadata": {"importance": "high"},
            "created_at_iso": "2026-08-03T10:00:00",
        }

        async def _run():
            await plugin.on_store_handler(memory_dict)
            await asyncio.sleep(0.01)  # let background task complete

        asyncio.run(_run())

        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        assert md_path.exists()
        content = md_path.read_text(encoding="utf-8")
        assert "Test memory content" in content
        assert "abcdef1234567890" in content
        assert "tags: [test]" in content

    def test_on_delete_handler_removes_markdown(self, tmp_path):
        """on_delete_handler should remove the markdown file."""
        repo_path = tmp_path / "repo"
        md_path = repo_path / "memories" / "ab" / "abcdef1234567890.md"
        md_path.parent.mkdir(parents=True)
        md_path.write_text("content to delete", encoding="utf-8")

        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        async def _run():
            await plugin.on_delete_handler("abcdef1234567890")
            await asyncio.sleep(0.01)  # let background task complete

        asyncio.run(_run())

        assert not md_path.exists()
        plugin._sync_queue.enqueue.assert_called_once_with("delete", "abcdef1234567890")

    def test_handler_error_isolation(self, tmp_path):
        """Handler exceptions should not propagate to the caller."""
        plugin._config = GitSyncConfig(repo_path=str(tmp_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        with patch(
            "memory_os_plugins.git_sync.plugin.memory_to_markdown",
            side_effect=RuntimeError("synthetic failure"),
        ):
            async def _run():
                # Should not raise — error is caught inside _git_sync_store.
                await plugin.on_store_handler({"content_hash": "abc123"})
                await asyncio.sleep(0.01)  # let background task run

            asyncio.run(_run())  # no exception raised

    def test_handler_is_async_fire_and_forget(self, tmp_path):
        """on_store_handler should return immediately without blocking."""
        repo_path = tmp_path / "repo"
        repo_path.mkdir()

        plugin._config = GitSyncConfig(repo_path=str(repo_path))
        plugin._sync_queue = MagicMock()
        plugin._sync_queue.enqueue = AsyncMock()

        memory_dict = {
            "content": "Test",
            "content_hash": "a1b2c3d4e5f6",
            "tags": [],
            "memory_type": "observation",
            "metadata": {},
            "created_at_iso": "2026-08-03T10:00:00",
        }

        async def _run():
            start = time.monotonic()
            await plugin.on_store_handler(memory_dict)
            elapsed = time.monotonic() - start
            # Handler should return in well under 100ms (fire-and-forget).
            assert elapsed < 0.1
            # Give the background task time to complete.
            await asyncio.sleep(0.1)
            # Now the file should exist.
            md_path = repo_path / "memories" / "a1" / "a1b2c3d4e5f6.md"
            assert md_path.exists()

        asyncio.run(_run())
