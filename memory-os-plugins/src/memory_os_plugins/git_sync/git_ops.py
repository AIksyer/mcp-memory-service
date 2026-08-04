"""Git operations and batch commit queue for memory-os-plugins.

All git commands use subprocess (no GitPython dependency).
Every function is designed to be idempotent where possible and
returns bool: True on success (including no-op), False on real failure.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
from pathlib import Path
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
#  Low-level git helpers
# --------------------------------------------------------------------------- #

def _run_git(
    args: list[str],
    repo_path: Path,
) -> subprocess.CompletedProcess[str]:
    """Run a git command and return the CompletedProcess.

    Args:
        args: Git sub-command and arguments (e.g. ["add", "-A"]).
        repo_path: Working directory for the git command.

    Returns:
        CompletedProcess with captured stdout/stderr.
    """
    full_args = ["git"] + args
    return subprocess.run(
        full_args,
        capture_output=True,
        text=True,
        cwd=str(repo_path),
    )


def _is_git_repo(repo_path: Path) -> bool:
    """Check whether *repo_path* is inside a git repository."""
    result = _run_git(["rev-parse", "--git-dir"], repo_path)
    return result.returncode == 0


def _has_remote(repo_path: Path, remote: str) -> bool:
    """Check whether *remote* is configured in the repo."""
    result = _run_git(["remote"], repo_path)
    if result.returncode != 0:
        return False
    remotes = result.stdout.split()
    return remote in remotes


# --------------------------------------------------------------------------- #
#  Public API
# --------------------------------------------------------------------------- #

def git_init(repo_path: Path) -> bool:
    """Initialise a git repository at *repo_path* if needed.

    Creates the ``memories/`` directory and a ``.gitignore`` file
    (only if the file does not already exist).

    Args:
        repo_path: Directory to initialise.

    Returns:
        True on success, False on failure.
    """
    try:
        repo_path.mkdir(parents=True, exist_ok=True)

        if not _is_git_repo(repo_path):
            result = _run_git(["init"], repo_path)
            if result.returncode != 0:
                logger.error(
                    "git init failed in %s: %s",
                    repo_path,
                    result.stderr.strip(),
                )
                return False
            logger.info("git init succeeded in %s", repo_path)
        else:
            logger.debug("%s is already a git repository", repo_path)

        memories_dir = repo_path / "memories"
        memories_dir.mkdir(parents=True, exist_ok=True)

        gitignore = repo_path / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# Memory OS git sync\n*.lock\n__pycache__/\n",
                encoding="utf-8",
            )
            logger.info("Created .gitignore in %s", repo_path)

        return True

    except Exception as exc:
        logger.error("git_init failed for %s: %s", repo_path, exc)
        return False


def git_add(repo_path: Path, files: list[str] | None = None) -> bool:
    """Stage files into the git index.

    Args:
        repo_path: Git repository root.
        files: List of file paths to stage.  If ``None``, stages all
            changes (``git add -A``).

    Returns:
        True on success, False on failure.
    """
    try:
        if files is None:
            result = _run_git(["add", "-A"], repo_path)
        else:
            result = _run_git(["add"] + files, repo_path)

        if result.returncode != 0:
            logger.error(
                "git add failed in %s: %s",
                repo_path,
                result.stderr.strip(),
            )
            return False

        logger.debug("git add succeeded in %s", repo_path)
        return True

    except Exception as exc:
        logger.error("git_add failed for %s: %s", repo_path, exc)
        return False


def git_commit(repo_path: Path, message: str) -> bool:
    """Create a git commit.

    If there is nothing to commit (exit code 1 and the appropriate
    message), the function returns ``True`` — the operation is
    idempotent.

    Args:
        repo_path: Git repository root.
        message: Commit message.

    Returns:
        True on success or no-op, False on failure.
    """
    try:
        result = _run_git(["commit", "-m", message], repo_path)

        if result.returncode == 0:
            logger.info("git commit succeeded: %s", message)
            return True

        # exit code 1 — check for "nothing to commit"
        combined = (result.stdout + result.stderr).lower()
        if "nothing to commit" in combined:
            logger.debug("Nothing to commit (idempotent): %s", message)
            return True

        logger.error(
            "git commit failed (rc=%d): %s",
            result.returncode,
            result.stderr.strip(),
        )
        return False

    except Exception as exc:
        logger.error("git_commit failed for %s: %s", repo_path, exc)
        return False


def git_push(
    repo_path: Path,
    remote: str = "origin",
    branch: str = "main",
) -> bool:
    """Push the local branch to a remote.

    If *remote* is not configured, logs a warning and returns ``True``
    (local-only mode — not an error).

    Args:
        repo_path: Git repository root.
        remote: Remote name.
        branch: Branch name.

    Returns:
        True on success or local-only mode, False on push failure.
    """
    try:
        if not _has_remote(repo_path, remote):
            logger.warning(
                "No remote '%s' configured in %s — skipping push (local mode)",
                remote,
                repo_path,
            )
            return True

        result = _run_git(["push", remote, branch], repo_path)
        if result.returncode != 0:
            logger.error(
                "git push failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False

        logger.info("git push succeeded: %s/%s", remote, branch)
        return True

    except Exception as exc:
        logger.error("git_push failed for %s: %s", repo_path, exc)
        return False


def git_pull(
    repo_path: Path,
    remote: str = "origin",
    branch: str = "main",
) -> bool:
    """Pull from a remote with rebase for cross-device sync.

    If *remote* is not configured, logs a warning and returns ``True``
    (local-only mode).

    Args:
        repo_path: Git repository root.
        remote: Remote name.
        branch: Branch name.

    Returns:
        True on success or local-only mode, False on pull failure.
    """
    try:
        if not _has_remote(repo_path, remote):
            logger.warning(
                "No remote '%s' configured in %s — skipping pull (local mode)",
                remote,
                repo_path,
            )
            return True

        result = _run_git(["pull", "--rebase", remote, branch], repo_path)
        if result.returncode != 0:
            logger.error(
                "git pull failed (rc=%d): %s",
                result.returncode,
                result.stderr.strip(),
            )
            return False

        logger.info("git pull succeeded: %s/%s", remote, branch)
        return True

    except Exception as exc:
        logger.error("git_pull failed for %s: %s", repo_path, exc)
        return False


def git_remove_file(repo_path: Path, file_path: str) -> bool:
    """Remove a file from the working tree and stage its deletion.

    If the file does not exist, returns ``True`` (idempotent).

    Args:
        repo_path: Git repository root.
        file_path: Path to the file, relative to *repo_path*.

    Returns:
        True on success or file already gone, False on failure.
    """
    try:
        full_path = repo_path / file_path

        if not full_path.exists():
            logger.debug("File %s does not exist (idempotent)", full_path)
            return True

        full_path.unlink()
        logger.debug("Deleted file %s", full_path)

        # Stage the deletion
        result = _run_git(["add", file_path], repo_path)
        if result.returncode != 0:
            logger.error(
                "git add (deletion) failed for %s: %s",
                file_path,
                result.stderr.strip(),
            )
            return False

        logger.info("Removed and staged deletion of %s", file_path)
        return True

    except Exception as exc:
        logger.error("git_remove_file failed for %s: %s", file_path, exc)
        return False


# --------------------------------------------------------------------------- #
#  Batch commit queue
# --------------------------------------------------------------------------- #

class GitSyncQueue:
    """Async batch queue that groups memory changes into git commits.

    Items are enqueued via :meth:`enqueue`.  When the queue reaches
    *batch_size* or *timeout* seconds elapse since the first item was
    added, :meth:`_flush` is called automatically to perform
    ``git add -A`` → ``git commit`` → ``git push``.

    Attributes:
        repo_path: Git repository root.
        batch_size: Maximum items before auto-flush.
        timeout: Seconds before auto-flush if batch_size not reached.
    """

    def __init__(
        self,
        repo_path: Path,
        batch_size: int = 5,
        timeout: int = 30,
        auto_push: bool = False,
    ) -> None:
        """Initialise the queue.

        Args:
            repo_path: Git repository root.
            batch_size: Flush when this many items are queued.
            timeout: Flush after this many seconds (since first item).
            auto_push: If True, push to remote after each batch commit.
        """
        self.repo_path = repo_path
        self.batch_size = batch_size
        self.timeout = timeout
        self.auto_push = auto_push
        self._queue: list[tuple[str, str]] = []
        self._lock = asyncio.Lock()
        self._timer_task: asyncio.Task[None] | None = None

    async def enqueue(self, action: str, content_hash: str) -> None:
        """Add an item to the sync queue.

        Triggers an auto-flush when the queue reaches *batch_size* or
        starts a countdown timer for *timeout* seconds.

        Args:
            action: Type of change (e.g. "store", "delete").
            content_hash: Hash of the affected memory.
        """
        async with self._lock:
            self._queue.append((action, content_hash))
            count = len(self._queue)
            logger.debug(
                "Enqueued %s (%s), queue size=%d", action, content_hash, count
            )

            if count >= self.batch_size:
                await self._flush()
            elif count == 1:
                # Start countdown timer on first item
                self._timer_task = asyncio.create_task(self._timer())

    async def _timer(self) -> None:
        """Wait for *timeout* seconds then trigger a flush."""
        try:
            await asyncio.sleep(self.timeout)
            async with self._lock:
                if self._queue:
                    logger.debug("Timer expired, flushing %d items", len(self._queue))
                    await self._flush()
        except asyncio.CancelledError:
            pass

    async def _flush(self) -> None:
        """Flush the queue: git add -A → commit → push.

        Must be called while holding ``self._lock``.
        Clears the timer task and the queue on completion.
        """
        if not self._queue:
            return

        # Cancel pending timer
        if self._timer_task is not None:
            self._timer_task.cancel()
            self._timer_task = None

        count = len(self._queue)
        message = f"memory: batch sync {count} changes"
        self._queue.clear()

        await safe_git_operation(
            lambda: _do_flush(self.repo_path, message, self.auto_push),
            name="GitSyncQueue._flush",
        )


async def _do_flush(repo_path: Path, message: str, auto_push: bool = True) -> bool:
    """Execute the full flush sequence: add → commit → (optionally) push.

    Args:
        repo_path: Git repository root.
        message: Commit message.
        auto_push: If True, push to remote after commit. If False, skip push.

    Returns:
        True if all steps succeeded (or were no-ops), False otherwise.
    """
    if not git_add(repo_path, files=None):
        return False
    if not git_commit(repo_path, message):
        return False
    if auto_push:
        if not git_push(repo_path):
            return False
    return True


# --------------------------------------------------------------------------- #
#  Safe operation wrapper
# --------------------------------------------------------------------------- #

async def safe_git_operation(
    coro: Callable[[], Awaitable[bool]],
    name: str,
    max_retries: int = 3,
) -> bool:
    """Wrap a git operation with retry and exponential backoff.

    *coro* is a **callable** that returns a fresh coroutine on each
    call.  This is necessary because a coroutine object can only be
    awaited once — the factory lets us create a new one per retry.

    On failure the function logs a warning and retries up to
    *max_retries* times.  After all retries are exhausted, logs an
    error and returns ``False``.  Never raises — fire-and-forget mode.

    Args:
        coro: Zero-arg callable returning a coroutine that performs the
            git operation and returns bool.
        name: Human-readable name for logging.
        max_retries: Maximum number of attempts.

    Returns:
        True if any attempt succeeded, False if all attempts failed.
    """
    for attempt in range(1, max_retries + 1):
        try:
            result = await coro()
            if result:
                logger.debug("%s succeeded on attempt %d", name, attempt)
                return True
            logger.warning(
                "%s returned False on attempt %d/%d",
                name,
                attempt,
                max_retries,
            )
        except Exception as exc:
            logger.warning(
                "%s raised on attempt %d/%d: %s",
                name,
                attempt,
                max_retries,
                exc,
            )

        if attempt < max_retries:
            backoff = 2 ** (attempt - 1)
            logger.debug("%s backing off %ds", name, backoff)
            await asyncio.sleep(backoff)

    logger.error("%s failed after %d attempts", name, max_retries)
    return False
