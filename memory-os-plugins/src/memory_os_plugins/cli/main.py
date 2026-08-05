"""CLI for memory-os — manage the git sync plugin.

Commands:
    init     Initialize a git sync repository and write config.
    status   Show plugin status, repo path, last commit, file count.
    export   Export memories from the database to a JSON file.
    import   Import memories from one or more JSON files into the database.
    pull     Pull memories from git remote and import into the database.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import subprocess
from pathlib import Path
from typing import Any

import click

from ..git_sync.config import CONFIG_FILE, GitSyncConfig, _parse_config_file, load_config, save_config
from ..git_sync.git_ops import git_commit, git_init, git_pull
from ..git_sync.markdown import markdown_to_memory_dict
from .templates import R2_SYNC_WORKFLOW

logger = logging.getLogger(__name__)


@click.group()
def cli() -> None:
    """Memory OS CLI — manage the git sync plugin."""


@cli.command()
@click.option(
    "--repo",
    default=None,
    help="Repository path (default: ~/AgentMemory).",
)
@click.option(
    "--project",
    default=None,
    help="Project name to tag this repository.",
)
@click.option(
    "--enable-r2-sync",
    is_flag=True,
    default=False,
    help="Copy the R2 backup GitHub Actions workflow to the repo.",
)
def init(repo: str | None, project: str | None, enable_r2_sync: bool) -> None:
    """Initialize a git sync repository.

    Creates the repo directory, initialises git, creates memories/ and
    .gitignore, and writes a config file to ~/.memory-os/config.yml.
    Optionally adds a GitHub Actions workflow for R2 backup sync.
    """
    # Determine repo path.
    repo_path = Path(repo).expanduser() if repo else Path.home() / "AgentMemory"

    # Initialise git repo (creates memories/ and .gitignore too).
    if not git_init(repo_path):
        click.echo(
            f"Error: Failed to initialise git repository at {repo_path}",
            err=True,
        )
        raise SystemExit(1)

    # Build and persist config.
    config = GitSyncConfig(
        enabled=True,
        base_dir=str(repo_path),
        auto_push=False,
        batch_size=5,
        batch_timeout=30,
        project_name=project or "",
    )
    save_config(config)

    # Optionally copy R2 sync workflow.
    if enable_r2_sync:
        workflows_dir = repo_path / ".github" / "workflows"
        workflows_dir.mkdir(parents=True, exist_ok=True)
        workflow_file = workflows_dir / "r2-sync.yml"
        workflow_file.write_text(R2_SYNC_WORKFLOW, encoding="utf-8")

    # Initial commit with .gitignore (+ workflow if added).
    git_commit(repo_path, "memory: initial repository setup")

    click.echo(f"Git sync repository initialized at: {repo_path}")
    click.echo(f"Configuration written to: {CONFIG_FILE}")
    if project:
        click.echo(f"Project name: {project}")
    if enable_r2_sync:
        click.echo("")
        click.echo("R2 sync workflow copied to .github/workflows/r2-sync.yml")
        click.echo("")
        click.echo("Configure these GitHub Secrets in your repository:")
        click.echo("  R2_ACCESS_KEY_ID      — R2 S3 Access Key ID")
        click.echo("  R2_SECRET_ACCESS_KEY  — R2 S3 Secret Access Key")
        click.echo("  R2_ACCOUNT_ID          — Cloudflare Account ID")
        click.echo("  R2_BUCKET_NAME         — R2 bucket name")
        click.echo("")
        click.echo("See docs/R2-SETUP.md for detailed instructions.")
    click.echo("")
    click.echo("To enable the plugin, ensure mcp-memory-service is installed")
    click.echo("and the git_sync plugin is discoverable via entry-points.")
    click.echo("The plugin auto-activates on server startup.")


@cli.command()
def status() -> None:
    """Show git sync plugin status."""
    config = load_config()

    click.echo("Memory OS Git Sync Status")
    click.echo("=" * 40)
    click.echo(f"  Enabled:       {'yes' if config.enabled else 'no'}")

    repo_path = Path(config.repo_path).expanduser()
    click.echo(f"  Repo path:     {repo_path}")
    click.echo(f"  Auto push:     {'yes' if config.auto_push else 'no'}")
    click.echo(f"  Batch size:    {config.batch_size}")
    click.echo(f"  Batch timeout: {config.batch_timeout}s")
    if config.project_name:
        click.echo(f"  Project:       {config.project_name}")
    click.echo("")

    # Check repo existence.
    if not repo_path.exists():
        click.echo(f"  Repository not found at {repo_path}")
        click.echo("  Run 'memory-os init' to create it.")
        return

    # Recent git commit.
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            click.echo(f"  Last commit:   {result.stdout.strip()}")
        else:
            click.echo("  Last commit:   (no commits yet)")
    except Exception:
        click.echo("  Last commit:   (unable to read)")

    # Markdown file count.
    memories_dir = repo_path / "memories"
    if memories_dir.exists():
        md_count = len(list(memories_dir.rglob("*.md")))
        click.echo(f"  MD files:      {md_count}")
    else:
        click.echo("  MD files:      0 (memories/ directory not found)")


# --------------------------------------------------------------------------- #
#  Storage helper
# --------------------------------------------------------------------------- #

def _get_sqlite_path() -> str:
    """Resolve the SQLite database path from env vars or upstream defaults."""
    for env_var in ("MCP_MEMORY_SQLITE_PATH", "MCP_MEMORY_SQLITEVEC_PATH"):
        if path := os.getenv(env_var):
            return path
    from mcp_memory_service.config import BASE_DIR

    return os.path.join(BASE_DIR, "sqlite_vec.db")


async def _create_storage() -> Any:
    """Create and initialise a storage backend for CLI use.

    Uses the upstream factory so the active backend (sqlite_vec, hybrid,
    etc.) is respected.  The caller is responsible for cleanup.
    """
    from mcp_memory_service.storage.factory import create_storage_instance

    sqlite_path = _get_sqlite_path()
    if not os.path.exists(sqlite_path):
        raise FileNotFoundError(
            f"Database file not found: {sqlite_path}\n"
            "Make sure mcp-memory-service is configured and has been run at least once."
        )
    return await create_storage_instance(sqlite_path)


async def _close_storage(storage: Any) -> None:
    """Close a storage backend if it has a close method."""
    close = getattr(storage, "close", None)
    if close is None:
        return
    if inspect.iscoroutinefunction(close):
        await close()
    else:
        close()


# --------------------------------------------------------------------------- #
#  export command
# --------------------------------------------------------------------------- #

@cli.command()
@click.option(
    "--output",
    "-o",
    required=True,
    type=click.Path(dir_okay=False),
    help="Output JSON file path.",
)
@click.option(
    "--include-embeddings",
    is_flag=True,
    default=False,
    help="Include embedding vectors in the export (larger file).",
)
@click.option(
    "--filter-tags",
    default=None,
    help="Comma-separated tags to filter (e.g. 'tag1,tag2').",
)
def export(output: str, include_embeddings: bool, filter_tags: str | None) -> None:
    """Export memories from the database to a JSON file."""
    from mcp_memory_service.sync import MemoryExporter

    tag_list: list[str] | None = None
    if filter_tags:
        tag_list = [t.strip() for t in filter_tags.split(",") if t.strip()]
        if not tag_list:
            tag_list = None

    output_path = Path(output)

    async def _run() -> dict[str, Any]:
        storage = await _create_storage()
        try:
            exporter = MemoryExporter(storage)
            return await exporter.export_to_json(
                output_path,
                include_embeddings=include_embeddings,
                filter_tags=tag_list,
            )
        finally:
            await _close_storage(storage)

    try:
        result = asyncio.run(_run())
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    except Exception as exc:
        click.echo(f"Error during export: {exc}", err=True)
        raise SystemExit(1)

    file_size_mb = result["file_size_bytes"] / (1024 * 1024)
    click.echo(f"Export complete: {result['exported_count']} memories")
    click.echo(f"Output: {result['output_file']}")
    click.echo(f"File size: {file_size_mb:.2f} MB")
    click.echo(f"Source: {result['source_machine']}")


# --------------------------------------------------------------------------- #
#  import command
# --------------------------------------------------------------------------- #

@cli.command("import")
@click.option(
    "--input",
    "-i",
    multiple=True,
    required=True,
    type=click.Path(exists=True, dir_okay=False),
    help="Input JSON file(s) (repeat -i for multiple files).",
)
@click.option(
    "--no-deduplicate",
    is_flag=True,
    default=False,
    help="Skip deduplication (may create duplicates).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Analyze only; do not import.",
)
@click.option(
    "--no-source-tags",
    is_flag=True,
    default=False,
    help="Do not add source machine tags.",
)
def import_cmd(
    input: tuple[str, ...],
    no_deduplicate: bool,
    dry_run: bool,
    no_source_tags: bool,
) -> None:
    """Import memories from one or more JSON files into the database."""
    from mcp_memory_service.sync import MemoryImporter

    input_files = [Path(f) for f in input]

    async def _run() -> dict[str, Any]:
        storage = await _create_storage()
        try:
            importer = MemoryImporter(storage)
            if dry_run:
                return await importer.analyze_import(input_files)
            return await importer.import_from_json(
                input_files,
                deduplicate=not no_deduplicate,
                add_source_tags=not no_source_tags,
                dry_run=False,
            )
        finally:
            await _close_storage(storage)

    try:
        result = asyncio.run(_run())
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    except Exception as exc:
        click.echo(f"Error during import: {exc}", err=True)
        raise SystemExit(1)

    if dry_run:
        click.echo("Dry-run analysis complete:")
        click.echo(f"  Total memories:   {result['total_memories']}")
        click.echo(f"  Unique (new):    {result['unique_memories']}")
        click.echo(f"  Duplicates:       {result['potential_duplicates']}")
        if result.get("conflicts"):
            click.echo(f"  Import conflicts: {len(result['conflicts'])}")
        for source, stats in result.get("sources", {}).items():
            click.echo(f"  Source {source}: {stats['new_memories']} new / {stats['total_memories']} total")
    else:
        click.echo("Import complete:")
        click.echo(f"  Files processed:    {result['files_processed']}")
        click.echo(f"  Total processed:    {result['total_processed']}")
        click.echo(f"  Imported:           {result['imported']}")
        click.echo(f"  Duplicates skipped: {result['duplicates_skipped']}")
        click.echo(f"  Errors:             {result['errors']}")
        for source, stats in result.get("sources", {}).items():
            click.echo(f"  Source {source}: {stats['imported']}/{stats['total']} imported")


# --------------------------------------------------------------------------- #
#  pull command
# --------------------------------------------------------------------------- #

@cli.command()
@click.option(
    "--remote",
    default="origin",
    help="Git remote name (default: origin).",
)
@click.option(
    "--branch",
    default="main",
    help="Git branch to pull from (default: main).",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Analyze only; do not write to the database.",
)
def pull(remote: str, branch: str, dry_run: bool) -> None:
    """Pull memories from a git remote and import into the database.

    Performs ``git pull --rebase`` on the sync repository, then scans
    all ``*.md`` files under ``memories/`` and stores them in the
    database.  Existing memories (matched by content hash) are skipped.
    """
    config = load_config()
    repo_path = Path(config.repo_path).expanduser()

    if not repo_path.exists():
        click.echo(f"Error: Repository not found at {repo_path}", err=True)
        click.echo("Run 'memory-os init' first.", err=True)
        raise SystemExit(1)

    # Step 1: git pull.
    click.echo(f"Pulling from {remote}/{branch}...")
    if not git_pull(repo_path, remote=remote, branch=branch):
        click.echo(
            f"Warning: git pull failed (continuing with local files)",
            err=True,
        )

    # Step 2: scan memories/ for .md files.
    memories_dir = repo_path / "memories"
    if not memories_dir.exists():
        click.echo("No memories/ directory found — nothing to import.")
        return

    md_files = sorted(memories_dir.rglob("*.md"))
    # Exclude README.md index file.
    md_files = [f for f in md_files if f.name != "README.md"]
    if not md_files:
        click.echo("No memory Markdown files found.")
        return

    click.echo(f"Found {len(md_files)} memory files.")

    if dry_run:
        click.echo("Dry-run mode: would import the following memories:")
        for md_file in md_files:
            text = md_file.read_text(encoding="utf-8")
            mem = markdown_to_memory_dict(text)
            hash_short = mem["content_hash"][:12] if mem["content_hash"] else "?"
            click.echo(f"  {hash_short}  {mem['content'][:60]}...")
        return

    # Step 3: import each memory into the database.
    async def _run() -> dict[str, Any]:
        storage = await _create_storage()
        try:
            imported = 0
            skipped = 0
            errors = 0
            for md_file in md_files:
                try:
                    text = md_file.read_text(encoding="utf-8")
                    mem = markdown_to_memory_dict(text)
                    if not mem["content"] or not mem["content_hash"]:
                        logger.warning("Skipping %s: missing content or hash", md_file)
                        skipped += 1
                        continue

                    result = await storage.store(
                        content=mem["content"],
                        tags=mem["tags"] or None,
                        memory_type=mem["memory_type"] or "observation",
                        metadata=mem["metadata"] or None,
                    )
                    if result.success:
                        imported += 1
                    elif "duplicate" in (result.message or "").lower():
                        skipped += 1
                    else:
                        errors += 1
                        click.echo(
                            f"  Warning: store failed for {mem['content_hash'][:12]}: {result.message}",
                            err=True,
                        )
                except Exception as exc:
                    errors += 1
                    click.echo(f"  Error processing {md_file.name}: {exc}", err=True)
            return {"imported": imported, "skipped": skipped, "errors": errors}
        finally:
            await _close_storage(storage)

    try:
        result = asyncio.run(_run())
    except FileNotFoundError as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)
    except Exception as exc:
        click.echo(f"Error during pull: {exc}", err=True)
        raise SystemExit(1)

    click.echo("Pull complete:")
    click.echo(f"  Imported:  {result['imported']}")
    click.echo(f"  Skipped:   {result['skipped']} (duplicates or invalid)")
    click.echo(f"  Errors:    {result['errors']}")


# --------------------------------------------------------------------------- #
#  switch command
# --------------------------------------------------------------------------- #

_PROJECT_SCOPE_PREFIX = "project_scope_"
_PROJECT_SCOPE_SECTION_COMMENT = "# Memory OS Project Scope configuration"
_DEFAULT_SCOPE_PRIORITY = "project, user"


def _read_project_scope_config() -> dict[str, str]:
    """Read ``project_scope_*`` values from the shared config file.

    Returns a dict mapping stripped key names (without the
    ``project_scope_`` prefix) to their string values.
    """
    if not CONFIG_FILE.exists():
        return {}
    try:
        all_values = _parse_config_file(CONFIG_FILE)
    except Exception as exc:
        logger.warning("Failed to parse config file %s: %s", CONFIG_FILE, exc)
        return {}
    result: dict[str, str] = {}
    for key, value in all_values.items():
        if key.startswith(_PROJECT_SCOPE_PREFIX):
            stripped_key = key[len(_PROJECT_SCOPE_PREFIX):]
            result[stripped_key] = str(value)
    return result


def _save_project_scope_config(updates: dict[str, str]) -> None:
    """Write ``project_scope_*`` values to the shared config file.

    Preserves other plugins' config lines using the same filter + append
    pattern as git_sync and r2_backup ``save_config``.
    """
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Read existing content and filter out old project_scope lines.
    existing_lines: list[str] = []
    if CONFIG_FILE.exists():
        for line in CONFIG_FILE.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith(_PROJECT_SCOPE_PREFIX):
                continue
            if stripped == _PROJECT_SCOPE_SECTION_COMMENT:
                continue
            existing_lines.append(line)

    # Build project_scope section.
    scope_lines = [_PROJECT_SCOPE_SECTION_COMMENT]
    for key, value in updates.items():
        scope_lines.append(f"{_PROJECT_SCOPE_PREFIX}{key}: {value}")

    # Combine: existing content + blank line + scope section.
    all_lines = existing_lines
    if all_lines and all_lines[-1].strip():
        all_lines.append("")
    all_lines.extend(scope_lines)

    CONFIG_FILE.write_text("\n".join(all_lines) + "\n", encoding="utf-8")


def _switch_list_projects() -> None:
    """List known projects from memory files in the git sync repo."""
    config = load_config()
    repo_path = Path(config.repo_path).expanduser()
    memories_dir = repo_path / "memories"

    if not memories_dir.exists():
        click.echo("No projects found")
        return

    projects: set[str] = set()

    for md_file in memories_dir.rglob("*.md"):
        if md_file.name == "README.md":
            continue
        try:
            text = md_file.read_text(encoding="utf-8")
            mem = markdown_to_memory_dict(text)
            for tag in mem.get("tags", []):
                if tag.startswith("proj:"):
                    projects.add(tag[len("proj:"):])
        except Exception:
            continue

    if not projects:
        click.echo("No projects found")
        return

    click.echo("Known Projects")
    click.echo("=" * 14)
    for proj in sorted(projects):
        click.echo(f"  {proj}")


@cli.command()
@click.option(
    "--project",
    "-p",
    default=None,
    help="Switch to project name.",
)
@click.option(
    "--user",
    "-u",
    default=None,
    help="Set user name.",
)
@click.option(
    "--list",
    "list_projects",
    is_flag=True,
    help="List known projects from memory files.",
)
def switch(
    project: str | None,
    user: str | None,
    list_projects: bool,
) -> None:
    """Switch current project/user context for scope-aware memory."""
    try:
        if list_projects:
            _switch_list_projects()
            return

        current = _read_project_scope_config()

        if project is None and user is None:
            # Display current context.
            proj_name = current.get("current_project") or "(none)"
            user_name = current.get("user_name") or "(none)"
            priority = current.get("scope_priority") or _DEFAULT_SCOPE_PRIORITY
            click.echo("Current Project Context")
            click.echo("=" * 23)
            click.echo(f"  Project:    {proj_name}")
            click.echo(f"  User:       {user_name}")
            click.echo(f"  Priority:   {priority}")
            return

        # Update config — start from current values, override changed ones.
        updates = dict(current)
        changed = False

        if project is not None:
            if current.get("current_project") == project:
                click.echo(f"Already on project: {project}")
            else:
                updates["current_project"] = project
                changed = True
                click.echo(f"Switched to project: {project}")

        if user is not None:
            updates["user_name"] = user
            changed = True
            click.echo(f"Set user: {user}")

        if changed:
            _save_project_scope_config(updates)
    except Exception as exc:
        click.echo(f"Error: {exc}", err=True)
        raise SystemExit(1)


def main() -> None:
    """CLI entry point (wired in pyproject.toml [project.scripts])."""
    cli()


if __name__ == "__main__":
    main()
