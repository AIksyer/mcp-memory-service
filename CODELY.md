# CODELY.md

This file provides instructional context for Codely CLI when working in the `mcp-memory-service` repository.

## Project Overview

**mcp-memory-service** is an open-source persistent semantic memory backend for AI agents. It provides a single self-hosted service exposing REST API, MCP transport, OAuth, CLI, and a web dashboard. Agents store decisions, share causal knowledge graphs, and retrieve context via vector embeddings — with zero cloud lock-in or API costs.

- **Language:** Python 3.10+
- **Framework:** FastAPI (web/REST), MCP protocol (stdio/HTTP transport)
- **Build System:** Hatchling (`pyproject.toml`)
- **License:** Apache 2.0
- **Current Version:** v11.5.5
- **Repository Host:** Codeberg (`codeberg.org:doobidoo/mcp-memory-service`) — NOT GitHub. The `github` remote is a suspended mirror.
- **CI:** Forgejo Actions (`.forgejo/workflows/`), not GitHub Actions.

### Key Capabilities
- Semantic search with ONNX embeddings (all-MiniLM-L6-v2, 384d) — runs fully local
- Knowledge graph with typed edges (causes, fixes, contradicts, supports, follows, related)
- Hybrid search (BM25 keyword + vector similarity)
- Memory consolidation (decay scoring, semantic compression, quality-based archival)
- Multiple storage backends: SQLite-Vec, Cloudflare, Hybrid, Milvus
- Web dashboard with 8 tabs (Dashboard, Search, Browse, Documents, Manage, Analytics, Quality, API Docs)
- OAuth 2.1 + DCR for team collaboration
- 25+ AI client integrations (Claude Desktop, Cursor, LangGraph, CrewAI, AutoGen, etc.)

## Building and Running

### Environment Setup
```bash
# Clone from Codeberg (NOT GitHub)
git clone https://codeberg.org/doobidoo/mcp-memory-service.git
cd mcp-memory-service

# Install (editable mode recommended for development)
pip install -e .
# Or with optional dependencies:
pip install -e ".[full]"      # All features (sqlite + ml + dev)
pip install -e ".[sqlite]"    # SQLite with ONNX embeddings only
pip install -e ".[ml]"        # Full ML capabilities (torch + transformers)
pip install -e ".[milvus]"    # Milvus vector DB backend
```

### Server Lifecycle (CLI — preferred)
```bash
memory launch                    # Start HTTP server in background (127.0.0.1:8000)
memory launch --foreground       # Foreground mode
memory launch --storage-backend hybrid
memory info                      # Status and health check
memory logs --lines 50           # Recent logs
memory stop                      # Stop server
memory restart                   # Restart (preserves flags)
```

### Legacy Entry Points
```bash
python -m mcp_memory_service.server          # MCP stdio server (for Claude Desktop)
python run_server.py                          # HTTP API server (FastAPI/uvicorn)
memory server                                  # MCP stdio server via CLI
```

### Testing
```bash
pytest                              # Run all tests (~2,400+ tests, ~216 files)
pytest tests/storage/test_sqlite_vec.py  # Specific test file
pytest -m unit                      # Fast unit tests only
pytest -m integration               # Integration tests (require storage)
pytest -m performance                # Performance benchmarks
pytest --cov=src/mcp_memory_service  # With coverage
bash scripts/pr/pre_pr_check.sh     # MANDATORY pre-PR gate
```

### Health Checks
```bash
curl http://127.0.0.1:8000/api/health
python scripts/validation/validate_configuration_complete.py
python scripts/validation/diagnose_backend_config.py
```

### Building Package
```bash
python -m build
```

## Code Architecture

Package source: `src/mcp_memory_service/`

### Core Components

| Component | Location | Description |
|-----------|----------|-------------|
| **MemoryServer** | `server_impl.py` | Main server class. `list_tools()` builds tool list from declarative registry, `call_tool()` dispatches via routing table. `handle_*` methods live here. |
| **Tool Registry** | `tools/registry.py` | `TOOL_REGISTRY` — declarative `ToolDef` objects, each mapping 1:1 to `types.Tool`. Annotations drive OAuth scope. |
| **Tool Routing** | `tools/routing.py` | `ROUTING_TABLE` (name -> handler) + `resolve_handler(name)` with lazy import. |
| **Handlers** | `server/handlers/*.py` | `async def handle_X(server, arguments) -> List[types.TextContent]` |
| **Compatibility** | `compat.py` | Shims, `_sanitize_log_value()` for log injection guard. |
| **Models** | `models/` | `Memory` dataclass, `MemoryQueryResult`. |
| **CLI** | `cli/` | `memory` command entry point (`cli/main.py`). |

### Storage Backends (`storage/`)

Strategy Pattern over `BaseStorage` (`base.py`):

| Backend | File | Performance | Use Case |
|---------|------|-------------|----------|
| SQLite-Vec | `sqlite_vec.py` | 5ms reads | Development, single-user (default) |
| Cloudflare | `cloudflare.py` | Network-dependent | Cloud-only, edge |
| Hybrid | `hybrid.py` | 5ms local + cloud sync | **Production (recommended)** |
| Milvus | `milvus.py` | Varies | Dedicated vector DB |

- Factory: `storage/factory.py` — creates the appropriate backend
- Graph storage: `graph.py` (SQLite) / `milvus_graph.py` (Milvus)
- Migrations: `storage/migration_runner.py`, `storage/migrations/`
- Global singleton caching in `server/cache_manager.py` prevents redundant storage initialization

### Web Layer (`web/`)
- FastAPI dashboard + 76-endpoint REST API
- `api/mcp.py` — thin MCP-over-HTTP protocol shim (inherits tool surface from `MemoryServer`, tools not defined twice)
- `local_only_tools()` in `server_impl.py` — filters tools that read caller-supplied filesystem paths from remote transport (confused-deputy guard)
- `web/oauth/` — OAuth 2.1 + DCR implementation
- `web/static/` — dashboard JS (no automated coverage; verify in browser)

### Quality System (`quality/`)
Three-tier scoring, local first:
1. Local ONNX (80-150ms, $0) — default
2. Groq / Llama 3 (500-800ms) — fallback
3. Gemini 1.5 Flash (1-2s) — high-accuracy

### Consolidation (`consolidation/`)
- Dream-inspired memory maintenance via HTTP API (not MCP tools — 90% fewer tokens)
- Scheduled with APScheduler; all schedules default to 'disabled'
- Retention by quality tier: high 365d, medium 180d, low 30-90d (`forgetting.py`)
- Relationship inference: causes, fixes, contradicts, supports, follows, related (confidence threshold 0.6)

### Document Ingestion (`ingestion/`)
- Registry pattern; loaders selected by file extension
- Chunker defaults: 1000 chars, 200 overlap

### Other Subsystems
- `embeddings/` — ONNX embedding generation
- `extraction/` — entity extraction (NER, @mentions, #tags, URLs, file paths)
- `reasoning/` — semantic reasoning, belief derivation
- `bootstrap/` — bootstrap profile retrieval
- `sync/` — cloud synchronization infrastructure
- `backup/` — backup scheduler
- `discovery/` — service discovery (mDNS/zeroconf)
- `config/` — configuration management
- `plugins/` — plugin system

## Development Conventions

### Non-Negotiable Rules
1. **Repo lives on Codeberg**, not GitHub. Use `origin` = `codeberg.org:doobidoo/mcp-memory-service`. Do NOT use `gh` or `github.com` URLs for CI, releases, or issues.
2. **Never manually bump versions.** Follow the documented release workflow (`.claude/directives/version-management.md`).
3. **Run `bash scripts/pr/pre_pr_check.sh` before every PR.** Mandatory gate — blocks on security findings and health score <50.
4. **Use the project venv** at `.venv` (Python 3.11). System `python`/`pytest` are NOT the project interpreter.
5. **Access `Memory` fields by attribute** (`memory.tags`), never via `memory.metadata.get('tags')`. This has caused 3 production bugs.
6. **Sanitize user-provided values in logs** with `_sanitize_log_value()` from `mcp_memory_service.compat`.
7. **MCP server configs go in `.mcp.json`**, not `settings.json`.
8. **Update `site/index.html` version strings on every MINOR/MAJOR release** (CI gate enforces this).
9. **Report outcomes faithfully.** "Tests pass" means you ran them and saw them pass.

### Coding Style
- PEP 8, line length 88 (Black formatter default)
- Use double quotes for strings
- Type hints for all function signatures
- Google-style docstrings for public functions/classes
- Import order: standard library -> third party -> local (`mcp_memory_service`)
- Semantic commit messages: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `perf:`, `chore:`

### Key Design Patterns
1. **Strategy Pattern** — Storage backends, health checks, quality analytics
2. **Registry Pattern** — Document loaders, storage factory, declarative tool registry
3. **Orchestrator Pattern** — Startup orchestrator, consolidation scheduler
4. **Singleton Pattern** — Global caching (storage, service instances)
5. **Processor Pattern** — Document ingestion, file processing

### Test Architecture
- ~2,400 tests across ~216 files; `tests/` mirrors `src/`
- pytest with `asyncio_mode = auto` (pytest.ini)
- Markers: `unit`, `integration` (needs storage), `performance`, `asyncio`
- **Test safety (critical):** Three guards in `conftest.py` prevent tests from touching production databases:
  1. Isolated temp directory with prefix `mcp-test-` at module import
  2. `pytest_sessionstart` aborts if production path detected
  3. `pytest_sessionfinish` validates temp location before cleanup
- Tests force `MCP_MEMORY_STORAGE_BACKEND=sqlite_vec` unless `MCP_TEST_ALLOW_CLOUD_BACKEND=true`
- `TEST_MEMORY_TAG = "__test__"` is reserved for automatic cleanup — never use for real data

### Adding a New MCP Tool (v11+ declarative pattern)
1. Add `ToolDef(name, description, input_schema, annotations)` to `TOOL_REGISTRY` in `tools/registry.py`
2. Implement `async def handle_X(server, arguments)` in `server/handlers/*.py`
3. Add `"<tool_name>": <handler>` to `ROUTING_TABLE` in `tools/routing.py`
4. If tool reads caller-supplied paths, add to `local_only_tools()` in `server_impl.py`
5. Add tests in `tests/server/test_handlers.py`
6. Set `annotations={"readOnlyHint": True, ...}` for non-mutating tools (drives OAuth scope)

### Critical Configuration Gotchas
- `MCP_MEMORY_SQLITE_PRAGMAS` must include `journal_mode=WAL` (prevents "database is locked")
- `MCP_HYBRID_SYNC_OWNER=http` for hybrid mode (only HTTP server syncs to Cloudflare)
- `MCP_INIT_TIMEOUT` defaults to 30s on Windows, 15s elsewhere; raise for slow machines
- External embedding APIs only work with `sqlite_vec` backend, not `hybrid` or `cloudflare`
- Embedding dimensions must match database schema; changing models requires re-embedding all memories

### Security-Sensitive Paths (extra PR scrutiny)
- `src/mcp_memory_service/web/api/mcp.py` — HTTP MCP transport, OAuth scope enforcement
- `src/mcp_memory_service/server_impl.py` — MCP tool registration, write-scope gate
- `src/mcp_memory_service/web/oauth/` — OAuth 2.1 implementation
- `src/mcp_memory_service/storage/` — Data integrity, production database

## Configuration

Full variable reference: `.env.example`. Precedence: environment variables -> `.env` -> defaults.

Key environment variables:
- `MCP_MEMORY_STORAGE_BACKEND` — `sqlite_vec` | `cloudflare` | `hybrid` | `milvus`
- `MCP_HTTP_PORT` — HTTP server port (default: 8000)
- `MCP_EMBEDDING_MODEL` — Embedding model selection
- `MCP_GRAPH_STORAGE_MODE` — `memories_only` | `dual_write` (default) | `graph_only`
- `MCP_HYBRID_SEARCH_ENABLED` — BM25 + vector fusion (default: true)
- `MCP_CONSOLIDATION_ENABLED` — Master switch for consolidation
- `MCP_OAUTH_ENABLED` — OAuth 2.1 authentication
- `MCP_ALLOW_ANONYMOUS_ACCESS` — Unauthenticated access (dev only)

## Documentation Map

| Location | Content |
|----------|---------|
| `README.md` | User-facing docs, installation, features |
| `CLAUDE.md` | Comprehensive dev guide (Claude Code specific, very detailed) |
| `CHANGELOG.md` | Version history |
| `CONTRIBUTING.md` | Contribution guidelines |
| `docs/` | Guides, troubleshooting, architecture specs |
| `docs/architecture.md` | Architecture overview |
| `docs/mastery/configuration-guide.md` | Full configuration reference |
| `docs/setup-guide.md` | Setup decision tree |
| `scripts/README.md` | Complete script reference |
| `site/` | mcpmemory.services landing page (auto-deployed to Cloudflare Pages) |
| `.claude/directives/` | Topic-specific directives for Claude Code |
| `.env.example` | All environment variables with comments |

## Codely Structured Memories

### User

### Feedback

### Project
- [2026-07-30 00:43:33] Memory OS 二开设计文档已完成 (2026-07-29): 7 个文档位于 G:\Project\mcp-memory-service\design\ (00-Overview ~ 06-Roadmap), 共 ~83KB。核心方案: pip 依赖 mcp-memory-service + entry_points plugin 模式 (不 Fork/不重写)。上游已有 plugin 系统 (plugins/context.py, 4 hooks: on_store/on_delete/on_retrieve/on_consolidate) 是 Git/R2/S3 同步的入口。P0 已完成 (本地部署+MCP接入), P1-P4 预计 8-11 工作日。
### Reference

