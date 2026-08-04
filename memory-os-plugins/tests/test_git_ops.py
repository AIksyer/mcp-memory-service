"""Tests for memory_os_plugins.git_sync.git_ops.

Covers low-level git helpers, GitSyncQueue batch/timeout, and
safe_git_operation retry logic.  All tests use tmp_path to avoid
touching the real filesystem.
"""

from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from memory_os_plugins.git_sync.git_ops import (
    GitSyncQueue,
    _do_flush,
    git_add,
    git_commit,
    git_init,
    git_push,
    git_remove_file,
    safe_git_operation,
)


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _git_config(repo_path: Path) -> None:
    """Set local git user identity so commits work in CI."""
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=str(repo_path),
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=str(repo_path),
        capture_output=True,
    )


def _init_repo(tmp_path: Path) -> Path:
    """Create and return a freshly-initialised git repo at tmp_path/repo."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=str(repo), capture_output=True)
    _git_config(repo)
    return repo


# --------------------------------------------------------------------------- #
#  git_init
# --------------------------------------------------------------------------- #

class TestGitInit:
    def test_git_init(self, tmp_path):
        """git_init() should create .git, memories/, and .gitignore."""
        repo = tmp_path / "newrepo"
        assert git_init(repo) is True

        assert (repo / ".git").exists()
        assert (repo / "memories").is_dir()
        assert (repo / ".gitignore").exists()

    def test_git_init_idempotent(self, tmp_path):
        """Running git_init twice should succeed (no-op on second call)."""
        repo = tmp_path / "repo"
        assert git_init(repo) is True
        assert git_init(repo) is True
        assert (repo / ".git").exists()

    def test_git_init_creates_gitignore_only_once(self, tmp_path):
        """An existing .gitignore should not be overwritten."""
        repo = tmp_path / "repo"
        repo.mkdir()
        custom_gitignore = repo / ".gitignore"
        custom_gitignore.write_text("custom content\n", encoding="utf-8")

        git_init(repo)
        assert custom_gitignore.read_text(encoding="utf-8") == "custom content\n"


# --------------------------------------------------------------------------- #
#  git_add + git_commit
# --------------------------------------------------------------------------- #

class TestGitAddAndCommit:
    def test_git_add_and_commit(self, tmp_path):
        """Full add + commit workflow should produce a commit."""
        repo = _init_repo(tmp_path)
        test_file = repo / "memories" / "test.md"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("hello", encoding="utf-8")

        assert git_add(repo, files=None) is True
        assert git_commit(repo, "test commit") is True

        # Verify commit exists.
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert "test commit" in result.stdout

    def test_git_commit_nothing_to_commit(self, tmp_path):
        """Committing with no changes should return True (idempotent)."""
        repo = _init_repo(tmp_path)
        assert git_commit(repo, "nothing here") is True


# --------------------------------------------------------------------------- #
#  git_push
# --------------------------------------------------------------------------- #

class TestGitPush:
    def test_git_push_no_remote(self, tmp_path):
        """Pushing with no remote configured should return True (local mode)."""
        repo = _init_repo(tmp_path)
        # Add a commit so there's something to push.
        (repo / "file.txt").write_text("content", encoding="utf-8")
        git_add(repo)
        git_commit(repo, "initial")

        assert git_push(repo) is True  # local-only mode, not an error


# --------------------------------------------------------------------------- #
#  git_remove_file
# --------------------------------------------------------------------------- #

class TestGitRemoveFile:
    def test_git_remove_file(self, tmp_path):
        """Removing an existing file should delete it and stage deletion."""
        repo = _init_repo(tmp_path)
        test_file = repo / "memories" / "ab" / "hash.md"
        test_file.parent.mkdir(parents=True, exist_ok=True)
        test_file.write_text("content", encoding="utf-8")

        git_add(repo)
        git_commit(repo, "add file")

        # Remove via relative path.
        rel_path = "memories/ab/hash.md"
        assert git_remove_file(repo, rel_path) is True
        assert not test_file.exists()

    def test_git_remove_nonexistent_file(self, tmp_path):
        """Removing a non-existent file should return True (idempotent)."""
        repo = _init_repo(tmp_path)
        assert git_remove_file(repo, "nonexistent/file.md") is True


# --------------------------------------------------------------------------- #
#  GitSyncQueue
# --------------------------------------------------------------------------- #

class TestGitSyncQueue:
    def test_gitsyncqueue_batch(self, tmp_path):
        """Queue should auto-flush when batch_size is reached."""
        repo = _init_repo(tmp_path)
        queue = GitSyncQueue(repo_path=repo, batch_size=3, timeout=999, auto_push=False)

        async def _run():
            with patch.object(
                GitSyncQueue, "_flush", new_callable=AsyncMock
            ) as mock_flush:
                await queue.enqueue("store", "hash1")
                await queue.enqueue("store", "hash2")
                assert mock_flush.call_count == 0  # not yet at batch_size

                await queue.enqueue("store", "hash3")  # reaches batch_size
                assert mock_flush.call_count == 1

        asyncio.run(_run())

    def test_gitsyncqueue_batch_flushes_and_commits(self, tmp_path):
        """Full end-to-end: enqueue batch_size items, verify git commit created."""
        repo = _init_repo(tmp_path)

        # Create memory files to commit.
        for i in range(3):
            md = repo / "memories" / f"hash{i}.md"
            md.parent.mkdir(parents=True, exist_ok=True)
            md.write_text(f"content {i}", encoding="utf-8")

        queue = GitSyncQueue(repo_path=repo, batch_size=3, timeout=999, auto_push=False)

        async def _run():
            await queue.enqueue("store", "hash0")
            await queue.enqueue("store", "hash1")
            await queue.enqueue("store", "hash2")  # triggers flush

        asyncio.run(_run())

        # Verify commit was created.
        result = subprocess.run(
            ["git", "log", "--oneline"],
            cwd=str(repo),
            capture_output=True,
            text=True,
        )
        assert "batch sync 3 changes" in result.stdout

    async def test_gitsyncqueue_timeout(self):
        """Queue should auto-flush after timeout seconds."""
        repo = MagicMock()
        repo.mkdir = MagicMock()
        queue = GitSyncQueue(repo_path=repo, batch_size=100, timeout=0.05, auto_push=False)

        with patch.object(
            GitSyncQueue, "_flush", new_callable=AsyncMock
        ) as mock_flush:
            await queue.enqueue("store", "hash1")
            assert mock_flush.call_count == 0

            # Wait for timer to fire.
            await asyncio.sleep(0.15)

            # _flush should have been called by the timer.
            assert mock_flush.call_count == 1


# --------------------------------------------------------------------------- #
#  safe_git_operation
# --------------------------------------------------------------------------- #

class TestSafeGitOperation:
    async def test_safe_git_operation_retry(self):
        """safe_git_operation should retry on failure and succeed eventually."""
        call_count = 0

        async def _flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return False
            return True

        with patch("memory_os_plugins.git_sync.git_ops.asyncio.sleep", new_callable=AsyncMock):
            result = await safe_git_operation(_flaky, "test_retry", max_retries=5)

        assert result is True
        assert call_count == 3

    async def test_safe_git_operation_all_fail(self):
        """safe_git_operation should return False after all retries exhausted."""
        async def _always_fail():
            return False

        with patch("memory_os_plugins.git_sync.git_ops.asyncio.sleep", new_callable=AsyncMock):
            result = await safe_git_operation(_always_fail, "test_all_fail", max_retries=3)

        assert result is False

    async def test_safe_git_operation_exception_retry(self):
        """safe_git_operation should retry on exceptions."""
        call_count = 0

        async def _raises():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("boom")
            return True

        with patch("memory_os_plugins.git_sync.git_ops.asyncio.sleep", new_callable=AsyncMock):
            result = await safe_git_operation(_raises, "test_exc_retry", max_retries=3)

        assert result is True
        assert call_count == 2

    async def test_do_flush_auto_push_true(self, tmp_path):
        """_do_flush with auto_push=True should call git_push."""
        repo = _init_repo(tmp_path)
        (repo / "test.txt").write_text("data", encoding="utf-8")

        with patch("memory_os_plugins.git_sync.git_ops.git_push", return_value=True) as mock_push:
            result = await _do_flush(repo, "test message", auto_push=True)
            assert result is True
            mock_push.assert_called_once()

    async def test_do_flush_auto_push_false(self, tmp_path):
        """_do_flush with auto_push=False should skip git_push."""
        repo = _init_repo(tmp_path)
        (repo / "test.txt").write_text("data", encoding="utf-8")

        with patch("memory_os_plugins.git_sync.git_ops.git_push", return_value=True) as mock_push:
            result = await _do_flush(repo, "test message", auto_push=False)
            assert result is True
            mock_push.assert_not_called()
