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

### 2. Run setup wizard (non-interactive)

For SQLite-only (simplest, no cloud):

```bash
memory setup --non-interactive --backend sqlite_vec --mcp-client claude-code
```

For Hybrid (local + Cloudflare sync):

```bash
memory setup --non-interactive \
  --backend hybrid \
  --cf-token CLOUDFLARE_API_TOKEN \
  --cf-account CLOUDFLARE_ACCOUNT_ID \
  --cf-d1 D1_DATABASE_ID \
  --backup-r2 \
  --mcp-client claude-code
```

For Hybrid + R2 + GitHub backup:

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

After setup, the `.env` file is created at `~/.mcp-memory-service/.env` (or in the project directory if running from source). MCP client config is written to the detected client's config file.

## Troubleshooting

- **"memory: command not found"** — ensure pip install succeeded, or use `python -m mcp_memory_service.cli.main setup`
- **"CLOUDFLARE_API_TOKEN not set"** — re-run setup with `--cf-token`
- **"Database is locked"** — ensure WAL mode is enabled (setup wizard adds this automatically)
