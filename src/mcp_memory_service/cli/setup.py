"""Interactive setup wizard for MCP Memory Service."""

import json
import os
import platform
import shutil
from dataclasses import dataclass
from pathlib import Path

import click


@dataclass
class SetupConfig:
    """Configuration collected by the setup wizard."""

    # Storage
    storage_backend: str = "sqlite_vec"  # sqlite_vec | cloudflare | hybrid

    # Cloudflare (required for cloudflare/hybrid)
    cf_api_token: str = ""
    cf_account_id: str = ""
    cf_d1_database_id: str = ""
    cf_vectorize_index: str = "mcp-memory-index"

    # Backup targets
    backup_local: bool = True
    backup_r2: bool = False
    backup_r2_bucket: str = "mcp-memory-backup"
    backup_github: bool = False
    backup_github_repo: str = ""
    backup_github_branch: str = "master"
    backup_github_token: str = ""
    backup_github_local_dir: str = ""

    # HTTP server
    http_port: int = 8000
    http_host: str = "127.0.0.1"

    # MCP client
    mcp_client: str = ""  # "claude-desktop" | "claude-code" | "cursor" | "none"
    mcp_client_config_path: str = ""


class SetupWizard:
    """Interactive setup wizard for MCP Memory Service."""

    BANNER = """
╔══════════════════════════════════════════════════════════╗
║           MCP Memory Service — Setup Wizard              ║
╚══════════════════════════════════════════════════════════╝
"""

    def __init__(self, config: SetupConfig | None = None):
        self.config = config or SetupConfig()

    def run_interactive(self) -> SetupConfig:
        """Run the interactive setup wizard. Returns collected config."""
        click.echo(self.BANNER)
        self._step_storage_backend()
        if self.config.storage_backend in ("cloudflare", "hybrid"):
            self._step_cloudflare_credentials()
        self._step_backup_targets()
        self._step_http_server()
        self._step_mcp_client()
        self._step_review()
        self._write_config()
        return self.config

    def run_non_interactive(self, **kwargs) -> SetupConfig:
        """Run non-interactively using provided kwargs. Returns config."""
        for key, value in kwargs.items():
            if hasattr(self.config, key) and value is not None:
                setattr(self.config, key, value)
        click.echo("Running non-interactive setup...")

        # Validate CF credentials for cloudflare/hybrid backends.
        # If the wizard doesn't have a token, check whether the existing .env
        # already has one — the merge will preserve it.
        if self.config.storage_backend in ("cloudflare", "hybrid") and not self.config.cf_api_token:
            env_path = self._find_env_path()
            existing_token = ""
            if env_path.exists():
                existing = self._parse_env_content(
                    env_path.read_text(encoding="utf-8")
                )
                existing_token = existing.get("CLOUDFLARE_API_TOKEN", "")
            if not existing_token:
                raise click.ClickException(
                    "Hybrid/Cloudflare backend requires CLOUDFLARE_API_TOKEN. "
                    "Pass --cf-token or set it in .env first."
                )

        self._write_config()
        return self.config

    # ── Interactive steps ──────────────────────────────────────

    def _step_storage_backend(self):
        """Step 1: Choose storage backend."""
        click.echo("\n📋 Step 1: Storage Backend")
        click.echo("  [1] SQLite-vec (local only, fastest, zero config)")
        click.echo("  [2] Cloudflare (cloud, requires CF account)")
        click.echo("  [3] Hybrid (local + cloud sync, recommended for multi-device)")
        choice = click.prompt(
            "Select backend", default="1", type=click.Choice(["1", "2", "3"])
        )
        backends = {"1": "sqlite_vec", "2": "cloudflare", "3": "hybrid"}
        self.config.storage_backend = backends[choice]
        click.echo(f"  ✓ Selected: {self.config.storage_backend}")

    def _step_cloudflare_credentials(self):
        """Step 2: Collect Cloudflare credentials."""
        click.echo("\n🔑 Step 2: Cloudflare Credentials")
        click.echo("  Get these from: https://dash.cloudflare.com/profile/api-tokens")
        self.config.cf_api_token = click.prompt(
            "  API Token", hide_input=True, default=""
        )
        self.config.cf_account_id = click.prompt("  Account ID", default="")
        self.config.cf_d1_database_id = click.prompt("  D1 Database ID", default="")
        self.config.cf_vectorize_index = click.prompt(
            "  Vectorize Index", default="mcp-memory-index"
        )
        if self.config.cf_api_token:
            click.echo("  ✓ Credentials collected")
        else:
            click.echo("  ⚠️  No token provided — cloud features will not work")

    def _step_backup_targets(self):
        """Step 3: Choose backup targets."""
        click.echo("\n💾 Step 3: Backup Targets")
        self.config.backup_local = click.confirm("  Local backup?", default=True)
        self.config.backup_r2 = click.confirm("  Cloudflare R2 backup?", default=False)
        if self.config.backup_r2:
            self.config.backup_r2_bucket = click.prompt(
                "  R2 bucket name", default="mcp-memory-backup"
            )
        self.config.backup_github = click.confirm(
            "  GitHub private repo backup?", default=False
        )
        if self.config.backup_github:
            self.config.backup_github_repo = click.prompt("  GitHub repo (user/repo)")
            self.config.backup_github_branch = click.prompt(
                "  Branch", default="master"
            )
            self.config.backup_github_token = click.prompt(
                "  GitHub token", hide_input=True
            )
        click.echo("  ✓ Backup targets configured")

    def _step_http_server(self):
        """Step 3b: HTTP server settings."""
        click.echo("\n🌐 Step 3b: HTTP Server")
        self.config.http_host = click.prompt("  Host", default="127.0.0.1")
        self.config.http_port = click.prompt("  Port", default=8000, type=int)

    def _step_mcp_client(self):
        """Step 4: Detect and configure MCP client."""
        click.echo("\n🔌 Step 4: MCP Client Configuration")
        detected = self._detect_mcp_clients()
        if detected:
            click.echo(f"  Detected clients: {', '.join(detected)}")
            for client in detected:
                if click.confirm(f"  Configure for {client}?", default=True):
                    self.config.mcp_client = client
                    break
            if not self.config.mcp_client:
                self.config.mcp_client = "none"
        else:
            click.echo("  No MCP clients detected")
            choice = click.prompt(
                "  Configure for which client?",
                type=click.Choice(
                    ["claude-desktop", "claude-code", "cursor", "none"]
                ),
                default="none",
            )
            self.config.mcp_client = choice
        if self.config.mcp_client != "none":
            self.config.mcp_client_config_path = self._get_client_config_path(
                self.config.mcp_client
            )
        click.echo(f"  ✓ MCP client: {self.config.mcp_client}")

    def _step_review(self):
        """Step 5: Review and confirm."""
        click.echo("\n✅ Step 5: Review Configuration")
        click.echo(f"  Storage backend: {self.config.storage_backend}")
        if self.config.storage_backend in ("cloudflare", "hybrid"):
            if self.config.cf_account_id:
                click.echo(f"  CF Account ID: {self.config.cf_account_id[:8]}...")
            if self.config.cf_d1_database_id:
                click.echo(f"  D1 Database: {self.config.cf_d1_database_id[:8]}...")
        backup_parts = []
        if self.config.backup_local:
            backup_parts.append("local")
        if self.config.backup_r2:
            backup_parts.append(f"R2({self.config.backup_r2_bucket})")
        if self.config.backup_github:
            backup_parts.append(f"GitHub({self.config.backup_github_repo})")
        click.echo(f"  Backup: {', '.join(backup_parts) or 'none'}")
        click.echo(f"  HTTP: {self.config.http_host}:{self.config.http_port}")
        click.echo(f"  MCP client: {self.config.mcp_client}")
        if not click.confirm("\n  Apply this configuration?", default=True):
            click.echo("  Setup cancelled.")
            raise SystemExit(0)

    # ── Config writing ────────────────────────────────────────

    def _write_config(self):
        """Write .env file and MCP client config."""
        env_path = self._find_env_path()

        # Read existing .env if present (for merge + backup)
        existing = {}
        if env_path.exists():
            existing = self._parse_env_content(
                env_path.read_text(encoding="utf-8")
            )
            # Backup existing .env before overwriting
            backup_path = env_path.parent / (env_path.name + ".bak")
            shutil.copy2(env_path, backup_path)
            click.echo(f"  Backed up existing .env to {backup_path}")

        # Generate new content and merge with existing
        new_content = self._generate_env_content()
        new_values = self._parse_env_content(new_content)

        # Merge: preserve existing keys, overwrite with new non-empty values.
        # Managed keys with empty wizard values are preserved from existing.
        merged = dict(existing)
        for key, value in new_values.items():
            if value:  # non-empty new value overwrites
                merged[key] = value

        # Build output: header + managed keys (in wizard order) + unknown keys
        lines = ["# MCP Memory Service configuration (generated by setup wizard)"]
        written = set()
        for key in new_values:
            if key in merged:
                lines.append(f"{key}={merged[key]}")
                written.add(key)
        for key, value in merged.items():
            if key not in written:
                lines.append(f"{key}={value}")

        env_content = "\n".join(lines) + "\n"
        self._atomic_write(env_path, env_content)
        click.echo(f"\n  ✓ .env written to {env_path}")

        if self.config.mcp_client and self.config.mcp_client != "none":
            self._write_mcp_client_config()

        self._print_post_setup_guide()

    def _print_post_setup_guide(self):
        """Print usage guide after setup completes."""
        click.echo("\n" + "=" * 60)
        click.echo("  Setup complete! Here's how to use it:")
        click.echo("=" * 60)

        click.echo("\n  1. Start the server:")
        click.echo("     memory launch")

        click.echo("\n  2. Verify it's running:")
        click.echo("     memory info")
        click.echo("     curl http://127.0.0.1:8000/api/health")

        click.echo("\n  3. MCP client configuration:")

        if self.config.mcp_client == "claude-code":
            click.echo("     Claude Code is configured with 'memory' MCP server.")
            click.echo("     The config was written to: ~/.claude/settings.json")
            click.echo("     Restart Claude Code to activate memory tools.")
        elif self.config.mcp_client == "claude-desktop":
            click.echo("     Claude Desktop is configured with 'memory' MCP server.")
            click.echo("     The config was written to: claude_desktop_config.json")
            click.echo("     Restart Claude Desktop to activate memory tools.")
        elif self.config.mcp_client == "cursor":
            click.echo("     Cursor is configured with 'memory' MCP server.")
            click.echo("     The config was written to: mcp.json")
            click.echo("     Restart Cursor to activate memory tools.")
        else:
            click.echo("     No MCP client was configured.")
            click.echo("     To add memory to your AI client manually:")
            click.echo('     {"mcpServers":{"memory":{"command":"memory","args":["server"]}}}')

        click.echo("\n  4. Available MCP tools (after restart):")
        click.echo("     - memory_store: Save a memory")
        click.echo("     - memory_search: Search memories semantically")
        click.echo("     - memory_retrieve: Get memories by query")
        click.echo("     - memory_delete: Delete a memory")
        click.echo("     - memory_list: List all memories")

        if self.config.storage_backend == "hybrid":
            click.echo("\n  5. Cloud deployment (optional):")
            click.echo("     Deploy to Render/Railway/etc for a cloud MCP endpoint.")
            click.echo("     Then add a second MCP server to your client:")
            click.echo('     {"mcpServers":{')
            click.echo('       "memory": {"command":"memory","args":["server"]},')
            click.echo('       "memory-cloud": {"url":"https://your-cloud-url/mcp"}')
            click.echo('     }}')
            click.echo("     The local 'memory' is primary (fast).")
            click.echo("     The 'memory-cloud' provides fallback when local is offline.")

        if self.config.backup_r2 or self.config.backup_github:
            click.echo("\n  6. Backup configuration:")
            if self.config.backup_r2:
                click.echo(f"     R2 backup: enabled (bucket: {self.config.backup_r2_bucket})")
            if self.config.backup_github:
                click.echo(f"     GitHub backup: enabled (repo: {self.config.backup_github_repo})")
            click.echo("     Backups run automatically on schedule (daily by default).")
            click.echo("     Trigger manually: POST /api/backup/push-remote")

        click.echo("\n" + "=" * 60)
        click.echo("  Need help? Check the docs: https://github.com/AIksyer/mcp-memory-service")
        click.echo("=" * 60)

    @staticmethod
    def _parse_env_content(content: str) -> dict:
        """Parse .env content (string or file text) into an ordered dict.

        Skips comments and blank lines.  Values are taken verbatim after the
        first ``=`` so that ``a=b=c`` correctly yields ``a`` -> ``b=c``.
        """
        result = {}
        for line in content.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if "=" in stripped:
                key, _, value = stripped.partition("=")
                result[key.strip()] = value.strip()
        return result

    def _find_env_path(self) -> Path:
        """Find or create .env file path."""
        # Prefer project directory if running from source
        cwd_env = Path.cwd() / ".env"
        if (Path.cwd() / "pyproject.toml").exists():
            return cwd_env
        # Check for existing .mcp-memory-service dir
        home_env_dir = Path.home() / ".mcp-memory-service"
        home_env_dir.mkdir(parents=True, exist_ok=True)
        return home_env_dir / ".env"

    def _generate_env_content(self) -> str:
        """Generate .env file content from config."""
        lines = [
            "# MCP Memory Service configuration (generated by setup wizard)",
            f"MCP_MEMORY_STORAGE_BACKEND={self.config.storage_backend}",
            f"MCP_HTTP_PORT={self.config.http_port}",
            f"MCP_HTTP_HOST={self.config.http_host}",
        ]

        if self.config.cf_api_token:
            lines.append(f"CLOUDFLARE_API_TOKEN={self.config.cf_api_token}")
        if self.config.cf_account_id:
            lines.append(f"CLOUDFLARE_ACCOUNT_ID={self.config.cf_account_id}")
        if self.config.cf_d1_database_id:
            lines.append(f"CLOUDFLARE_D1_DATABASE_ID={self.config.cf_d1_database_id}")
        if self.config.cf_vectorize_index:
            lines.append(f"CLOUDFLARE_VECTORIZE_INDEX={self.config.cf_vectorize_index}")

        # SQLite pragmas for WAL mode
        lines.append("MCP_MEMORY_SQLITE_PRAGMAS=journal_mode=WAL,synchronous=NORMAL")

        # Backup targets
        lines.append(f"MCP_BACKUP_ENABLED={'true' if self.config.backup_local else 'false'}")
        if self.config.backup_r2:
            lines.append("MCP_BACKUP_R2_ENABLED=true")
            lines.append(f"MCP_BACKUP_R2_BUCKET={self.config.backup_r2_bucket}")
        if self.config.backup_github:
            lines.append("MCP_BACKUP_GITHUB_ENABLED=true")
            lines.append(f"MCP_BACKUP_GITHUB_REPO={self.config.backup_github_repo}")
            lines.append(f"MCP_BACKUP_GITHUB_BRANCH={self.config.backup_github_branch}")
            lines.append(f"MCP_BACKUP_GITHUB_TOKEN={self.config.backup_github_token}")
            if self.config.backup_github_local_dir:
                lines.append(
                    f"MCP_BACKUP_GITHUB_LOCAL_DIR={self.config.backup_github_local_dir}"
                )

        # Hybrid settings
        if self.config.storage_backend == "hybrid":
            lines.append("MCP_HYBRID_SYNC_OWNER=http")
            lines.append("MCP_HYBRID_SYNC_ON_STARTUP=true")

        return "\n".join(lines) + "\n"

    def _write_mcp_client_config(self):
        """Write or update MCP client config file."""
        config_path = Path(self.config.mcp_client_config_path)
        if not config_path.parent.exists():
            config_path.parent.mkdir(parents=True, exist_ok=True)

        existing = {}
        if config_path.exists():
            try:
                existing = json.loads(config_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                existing = {}

        # Build server entry — inject env vars for non-cwd .env
        server_entry = {"command": "memory", "args": ["server"], "env": {}}

        env_path = self._find_env_path()
        if env_path != Path.cwd() / ".env":
            # Inject env vars into MCP config (only non-secret vars)
            if self.config.storage_backend != "sqlite_vec":
                if self.config.cf_api_token:
                    server_entry["env"]["CLOUDFLARE_API_TOKEN"] = self.config.cf_api_token
                if self.config.cf_account_id:
                    server_entry["env"]["CLOUDFLARE_ACCOUNT_ID"] = self.config.cf_account_id
                if self.config.cf_d1_database_id:
                    server_entry["env"]["CLOUDFLARE_D1_DATABASE_ID"] = (
                        self.config.cf_d1_database_id
                    )
                if self.config.cf_vectorize_index:
                    server_entry["env"]["CLOUDFLARE_VECTORIZE_INDEX"] = (
                        self.config.cf_vectorize_index
                    )
                server_entry["env"]["MCP_MEMORY_STORAGE_BACKEND"] = (
                    self.config.storage_backend
                )

        if "mcpServers" not in existing:
            existing["mcpServers"] = {}
        existing["mcpServers"]["memory"] = server_entry

        self._atomic_write(config_path, json.dumps(existing, indent=2))
        click.echo(f"  ✓ MCP config written to {config_path}")

    # ── Detection helpers ──────────────────────────────────────

    def _detect_mcp_clients(self) -> list[str]:
        """Detect installed MCP clients."""
        clients = []
        home = Path.home()
        system = platform.system().lower()

        # Claude Desktop
        desktop_paths = {
            "windows": home / "AppData" / "Roaming" / "Claude",
            "darwin": home / "Library" / "Application Support" / "Claude",
            "linux": home / ".config" / "Claude",
        }
        if desktop_paths.get(system, Path("/dev/null")).exists():
            clients.append("claude-desktop")

        # Claude Code (CLI)
        if shutil.which("claude"):
            clients.append("claude-code")

        # Cursor
        cursor_paths = {
            "windows": home / "AppData" / "Roaming" / "Cursor",
            "darwin": home / "Library" / "Application Support" / "Cursor",
            "linux": home / ".config" / "Cursor",
        }
        if cursor_paths.get(system, Path("/dev/null")).exists():
            clients.append("cursor")

        return clients

    def _get_client_config_path(self, client: str) -> str:
        """Get the config file path for an MCP client."""
        home = Path.home()
        system = platform.system().lower()

        if client == "claude-desktop":
            paths = {
                "windows": home
                / "AppData"
                / "Roaming"
                / "Claude"
                / "claude_desktop_config.json",
                "darwin": home
                / "Library"
                / "Application Support"
                / "Claude"
                / "claude_desktop_config.json",
                "linux": home / ".config" / "Claude" / "claude_desktop_config.json",
            }
        elif client == "cursor":
            paths = {
                "windows": home / "AppData" / "Roaming" / "Cursor" / "mcp.json",
                "darwin": home
                / "Library"
                / "Application Support"
                / "Cursor"
                / "mcp.json",
                "linux": home / ".config" / "Cursor" / "mcp.json",
            }
        elif client == "claude-code":
            paths = {
                "windows": home / ".claude" / "settings.json",
                "darwin": home / ".claude" / "settings.json",
                "linux": home / ".claude" / "settings.json",
            }
        else:
            return ""

        return str(paths.get(system, paths.get("linux", "")))

    @staticmethod
    def _atomic_write(path: Path, content: str):
        """Write file atomically (temp + rename)."""
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(str(tmp), str(path))
