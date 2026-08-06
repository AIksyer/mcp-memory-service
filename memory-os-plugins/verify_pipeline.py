"""Plugin pipeline integrity verification script.

Verifies the complete plugin lifecycle:
1. Plugin discovery via entry_points (3 plugins: git_sync, r2_backup, smart_tagger)
2. before_store hook (smart_tagger auto-tags memory_dict)
3. on_store hook (git_sync writes .md file)
4. on_retrieve hook (smart_tagger boosts/filters results)
5. on_delete hook (git_sync deletes .md file)

Uses a temp directory with a real git init — no external services required.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# Add src directories to path:
# 1. This worktree's memory-os-plugins/src (git_sync, r2_backup)
# 2. Main project's memory-os-plugins/src (smart_tagger — not in this worktree)
# 3. Main project's src/ (mcp_memory_service)
SCRIPT_DIR = Path(__file__).parent
WORKTREE_SRC = SCRIPT_DIR / "src"
MAIN_PLUGINS_SRC = Path("G:/Project/mcp-memory-service/memory-os-plugins/src")
MAIN_SRC = SCRIPT_DIR.parent / "src"

for p in [str(WORKTREE_SRC), str(MAIN_PLUGINS_SRC), str(MAIN_SRC)]:
    if p not in sys.path:
        sys.path.insert(0, p)


async def main() -> None:
    results: list[tuple[str, bool, str]] = []

    with tempfile.TemporaryDirectory(prefix="pipeline-test-") as tmpdir:
        tmp_path = Path(tmpdir)

        # Initialize a git repo so git_sync's GitSyncQueue doesn't fail
        subprocess.run(
            ["git", "init"], cwd=tmpdir, capture_output=True, check=False
        )
        subprocess.run(
            ["git", "config", "user.email", "test@test.com"],
            cwd=tmpdir, capture_output=True, check=False
        )
        subprocess.run(
            ["git", "config", "user.name", "Test"],
            cwd=tmpdir, capture_output=True, check=False
        )

        # Configure git_sync plugin via env vars
        os.environ["MEMORY_OS_GIT_SYNC_ENABLED"] = "true"
        os.environ["MEMORY_OS_GIT_SYNC_BASE_DIR"] = str(tmp_path)
        os.environ["MEMORY_OS_GIT_SYNC_AUTO_PUSH"] = "false"
        os.environ["MEMORY_OS_GIT_SYNC_BATCH_SIZE"] = "1"
        os.environ["MEMORY_OS_GIT_SYNC_BATCH_TIMEOUT"] = "1"

        # Ensure r2_backup is disabled (no boto3 credentials)
        os.environ["MEMORY_OS_R2_BACKUP_ENABLED"] = "false"

        # Enable smart_tagger
        os.environ["MEMORY_OS_SMART_TAGGER_ENABLED"] = "true"
        os.environ["MEMORY_OS_SMART_TAGGER_AUTO_TAGS"] = "true"

        # --- Step 1: Plugin Discovery ---
        from mcp_memory_service.plugins.context import PluginContext
        from mcp_memory_service.plugins.registry import PluginRegistry

        ctx = PluginContext(storage=None, service=None)
        registry = PluginRegistry(ctx)
        registry.discover_and_register()

        loaded = registry.loaded_plugins
        # Expect 2 loaded (git_sync + smart_tagger).
        # r2_backup should fail or be disabled (no boto3).
        has_git_sync = "git_sync" in loaded
        has_smart_tagger = "smart_tagger" in loaded
        results.append((
            "Plugin discovery (git_sync + smart_tagger)",
            has_git_sync and has_smart_tagger,
            f"Loaded plugins: {loaded}",
        ))

        # --- Step 2: before_store hook (smart_tagger auto-tags) ---
        test_memory = {
            "content": "Test memory for pipeline verification with Python keywords",
            "content_hash": "a" * 64,
            "tags": ["existing-tag"],
            "memory_type": "observation",
            "metadata": {"source": "verify_pipeline.py"},
            "created_at_iso": "2026-08-06T00:00:00Z",
            "updated_at_iso": "2026-08-06T00:00:00Z",
        }

        # Fire before_store — smart_tagger should add auto-generated tags
        modified = await registry.fire("before_store", test_memory)

        # Check that tags were modified
        original_tags = ["existing-tag"]
        modified_tags = []
        if isinstance(modified, dict):
            modified_tags = modified.get("tags", [])

        tags_changed = (
            isinstance(modified, dict)
            and len(modified_tags) > len(original_tags)
        )
        results.append((
            "before_store hook (smart_tagger modifies tags)",
            tags_changed,
            f"Original tags: {original_tags}, Modified tags: {modified_tags}",
        ))

        # Use the modified memory for subsequent steps
        if isinstance(modified, dict):
            test_memory = modified

        # --- Step 3: on_store hook (git_sync writes .md file) ---
        await registry.fire("on_store", test_memory)
        # Give background asyncio.create_task time to complete
        await asyncio.sleep(1.0)

        # Find the .md file (exclude README.md)
        md_files = [
            f for f in tmp_path.rglob("*.md")
            if f.name != "README.md"
        ]
        md_exists = len(md_files) > 0

        # Also verify the content_hash is in the file
        hash_in_file = False
        if md_files:
            content = md_files[0].read_text(encoding="utf-8")
            hash_in_file = "a" * 64 in content

        results.append((
            "on_store hook (.md file generated)",
            md_exists and hash_in_file,
            f"Files found: {len(md_files)}, hash in file: {hash_in_file}",
        ))

        # --- Step 4: on_retrieve hook (smart_tagger filters/boosts) ---
        test_results = [
            {
                "content": "Normal result",
                "content_hash": "b" * 64,
                "tags": ["general"],
                "similarity": 0.9,
            },
            {
                "content": "Mistake note about a bug",
                "content_hash": "c" * 64,
                "tags": ["mistake-note", "error-replay"],
                "similarity": 0.5,
            },
        ]

        retrieved = await registry.fire("on_retrieve", "test query", test_results)

        # smart_tagger should boost the mistake-note result
        # Check if the mistake-note result's score was boosted
        mistake_boosted = False
        if isinstance(retrieved, list) and len(retrieved) == 2:
            for r in retrieved:
                tags = r.get("tags", [])
                if "mistake-note" in tags:
                    original_score = 0.5
                    new_score = r.get("similarity", r.get("score", 0))
                    mistake_boosted = new_score > original_score

        results.append((
            "on_retrieve hook (smart_tagger boosts mistake-notes)",
            mistake_boosted,
            f"Retrieved {len(retrieved) if retrieved else 0} results, "
            f"mistake boosted: {mistake_boosted}",
        ))

        # --- Step 5: on_delete hook (git_sync deletes .md file) ---
        await registry.fire("on_delete", "a" * 64)
        # Give background asyncio.create_task time to complete
        await asyncio.sleep(1.0)

        # Check that the mem-*.md file was deleted
        md_files_after = list(tmp_path.rglob("mem-*.md"))
        md_deleted = len(md_files_after) == 0

        results.append((
            "on_delete hook (.md file deleted)",
            md_deleted,
            f"Remaining mem-*.md files: {len(md_files_after)}",
        ))

    # --- Summary ---
    print("\n" + "=" * 60)
    print("PLUGIN PIPELINE INTEGRITY VERIFICATION")
    print("=" * 60)

    all_passed = True
    for name, passed, detail in results:
        status = "[PASS]" if passed else "[FAIL]"
        print(f"\n{status} {name}")
        print(f"  {detail}")
        if not passed:
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print(f"OVERALL: ALL {len(results)} CHECKS PASSED")
    else:
        failed = sum(1 for _, p, _ in results if not p)
        print(f"OVERALL: {failed}/{len(results)} CHECKS FAILED")
    print("=" * 60)

    sys.exit(0 if all_passed else 1)


if __name__ == "__main__":
    asyncio.run(main())
