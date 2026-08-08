---
name: mcp-memory-setup
description: Deploy and configure mcp-memory-service for AI agents. Handles installation, storage backend selection, backup target configuration, and MCP client integration. Use when a user asks to install, set up, or deploy mcp-memory-service, or when configuring memory storage for an AI application.
---

# MCP Memory Service Setup

## Overview

This skill deploys mcp-memory-service — a persistent semantic memory backend for AI agents. It handles pip installation, storage backend selection, backup configuration, and MCP client integration via the `memory setup` CLI command.

## Prerequisites

- Python 3.10+ (3.11 or 3.12 recommended)
- pip or uv
- For Cloudflare backends: Cloudflare account with D1 + Vectorize

## Deployment Steps

### 1. Install the package

```bash
pip install mcp-memory-service
```

Or from source:

```bash
git clone https://github.com/AIksyer/mcp-memory-service.git
cd mcp-memory-service
pip install -e .
```

### 2. Run setup wizard

**Interactive (recommended for first-time users):**

```bash
memory setup
```

The wizard will guide you through:
1. Storage backend (SQLite / Cloudflare / Hybrid)
2. Cloudflare credentials (if cloud/hybrid)
3. Backup targets (local / R2 / GitHub)
4. MCP client detection and configuration
5. Review and confirm

**Non-interactive (for agents/scripts):**

SQLite-only (simplest, no cloud):

```bash
memory setup --non-interactive --backend sqlite_vec --mcp-client claude-code
```

Hybrid (local + Cloudflare sync):

```bash
memory setup --non-interactive \
  --backend hybrid \
  --cf-token CLOUDFLARE_API_TOKEN \
  --cf-account CLOUDFLARE_ACCOUNT_ID \
  --cf-d1 D1_DATABASE_ID \
  --backup-r2 \
  --mcp-client claude-code
```

Hybrid + R2 + GitHub backup (triple redundancy):

```bash
memory setup --non-interactive \
  --backend hybrid \
  --cf-token $CF_TOKEN \
  --cf-account $CF_ACCOUNT \
  --cf-d1 $D1_ID \
  --backup-r2 \
  --backup-github \
  --github-repo user/mcp-memory-data \
  --github-token $GH_TOKEN \
  --mcp-client claude-code
```

### 3. Start the server

```bash
memory launch
```

### 4. Verify

```bash
memory info
curl http://127.0.0.1:8000/api/health
```

## What Setup Does Automatically

- **Generates `.env`** — all configuration in one file (merged with existing, never overwrites)
- **Backs up existing `.env`** to `.env.bak` before any changes
- **Configures MCP client** — writes to the detected client's config file:
  - Claude Desktop: `claude_desktop_config.json`
  - Claude Code: `~/.claude/settings.json`
  - Cursor: `mcp.json`
- **Prints a usage guide** — shows available MCP tools, backup status, and cloud deployment instructions

## MCP Client Configuration

After setup, your AI client will have a `memory` MCP server entry. This gives the agent access to these tools:

| Tool | Description |
|------|-------------|
| `memory_store` | Save a memory with content, tags, and type |
| `memory_search` | Semantic search across all memories |
| `memory_retrieve` | Retrieve memories by query |
| `memory_delete` | Delete a memory by content hash |
| `memory_list` | List all memories with pagination |
| `memory_update` | Update memory metadata (tags, type) |
| `memory_graph` | Knowledge graph operations |
| `memory_consolidate` | Run memory consolidation |

## Cloud Deployment (Optional)

For high availability, deploy to a cloud platform (Render, Railway, etc.) and configure **dual MCP**:

```json
{
  "mcpServers": {
    "memory": {
      "command": "memory",
      "args": ["server"]
    },
    "memory-cloud": {
      "url": "https://your-cloud-url/mcp"
    }
  }
}
```

- `memory` (local) — primary, fast (~5ms reads)
- `memory-cloud` — fallback when local is offline
- Both share the same Cloudflare D1 + Vectorize backend via hybrid sync

## Configuration Options

| Flag | Description | Default |
|------|-------------|---------|
| `--backend` | sqlite_vec / cloudflare / hybrid | sqlite_vec |
| `--cf-token` | Cloudflare API token | (none) |
| `--cf-account` | Cloudflare account ID | (none) |
| `--cf-d1` | D1 database ID | (none) |
| `--backup-r2` | Enable R2 backup | false |
| `--backup-github` | Enable GitHub backup | false |
| `--github-repo` | GitHub repo (user/repo) | (none) |
| `--github-token` | GitHub PAT | (none) |
| `--mcp-client` | claude-desktop / claude-code / cursor / none | none |
| `--http-port` | HTTP server port | 8000 |

## Post-Setup

After setup completes, the wizard prints a guide showing:
1. How to start the server (`memory launch`)
2. How to verify it's running (`memory info`, health check)
3. Which MCP client was configured and where
4. Available MCP tools
5. Cloud deployment instructions (if hybrid)
6. Backup configuration status

## Troubleshooting

- **"memory: command not found"** — ensure pip install succeeded, or use `python -m mcp_memory_service.cli.main setup`
- **"CLOUDFLARE_API_TOKEN not set"** — re-run setup with `--cf-token`
- **"Database is locked"** — ensure WAL mode is enabled (setup wizard adds this automatically)
- **".env.bak leaked to GitHub"** — `.env` and `.env.bak` are in `.gitignore`; verify with `git status` before pushing
- **GBK encoding error on Windows** — the CLI forces UTF-8 output; if still failing, run `chcp 65001` before `memory setup`
