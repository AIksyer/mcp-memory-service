# mcp-memory-service — Project Structure Analysis Report

> Generated: 2026-08-04  
> Version: v11.5.5  
> Repository: `codeberg.org:doobidoo/mcp-memory-service` (Forgejo, NOT GitHub)

---

## 1. Project Overview

**mcp-memory-service** is an open-source persistent semantic memory backend for AI agents. It provides a single self-hosted service exposing REST API, MCP transport, OAuth, CLI, and a web dashboard. Agents store decisions, share causal knowledge graphs, and retrieve context via vector embeddings — with zero cloud lock-in or API costs.

| Attribute | Value |
|---|---|
| Language | Python 3.10+ |
| Framework | FastAPI (REST), MCP protocol (stdio/HTTP) |
| Build System | Hatchling (`pyproject.toml`) |
| License | Apache 2.0 |
| Version | v11.5.5 |
| Repository Host | Codeberg (`codeberg.org:doobidoo/mcp-memory-service`) |
| CI | Forgejo Actions (`.forgejo/workflows/`) |

### Entry Points (`[project.scripts]`)

| Command | Module | Purpose |
|---|---|---|
| `memory` | `mcp_memory_service.cli.main:main` | CLI entry point (launch, info, stop, restart, logs, server) |
| `memory-server` | `mcp_memory_service.cli.main:memory_server_main` | MCP stdio server via CLI |
| `mcp-memory-server` | `mcp_memory_service.mcp_server:main` | MCP stdio server (legacy entry) |

### Legacy Root-Level Entry Points

| File | Purpose |
|---|---|
| `run_server.py` | HTTP API server (FastAPI/uvicorn) |
| `main.py` | FastAPI Cloud entry point (for FastAPI Cloud hosting) |
| `install.py` | Installation script |
| `memory-ha.ps1` | High-availability PowerShell failover script |

---

## 2. Project Directory Structure

```
mcp-memory-service/
├── .forgejo/workflows/          # CI/CD pipelines (Forgejo Actions)
├── .github/                     # GitHub config (codeql, issue templates, dependabot)
├── .claude/                     # Claude Code directives
├── .claude-plugin/              # Claude plugin config
├── .codely-cli/                 # Codely CLI settings (MCP, hooks)
├── claude_commands/             # Custom Claude slash commands
├── claude-hooks/                # Custom Claude hooks
├── cloudflare/                  # Cloudflare Worker (load balancer)
├── docs/                        # 40+ docs (architecture, guides, troubleshooting)
├── examples/                    # Plugin examples (audit-log, smart-tagger)
├── instincts/                   # Agent instinct definitions
├── memory-os-plugins/           # Memory OS plugin experiments
├── opencode/                    # OpenCode integration
├── scripts/                     # 20+ script subdirectories (ci, pr, backup, etc.)
├── site/                        # mcpmemory.services landing page (Cloudflare Pages)
├── specs/                       # Specifications
├── spike/                       # Spike/prototype code
├── src/mcp_memory_service/      # Main package (213 .py files)
├── test-ha/                     # High-availability test scripts
├── tests/                       # Test suite (227 test_*.py files)
├── tools/                       # Docker images, PyPI placeholders
├── video/                       # Video assets
├── .coveragerc                  # Coverage config
├── .env.example                 # Environment variable reference
├── Dockerfile                   # Container build (standard)
├── pyproject.toml               # Main project config (Hatchling + deps + tools)
├── pyproject-lite.toml          # Lite package variant (ONNX only, no PyTorch)
├── pytest.ini                   # pytest configuration
├── package.json                 # Node.js deps for tooling
├── tsconfig.json                # TypeScript config for tooling
└── validate.ts                  # TypeScript validation script
```

---

## 3. Source Architecture (`src/mcp_memory_service/`)

**213 Python source files** organized into 22 sub-packages:

```
src/mcp_memory_service/
├── __init__.py                  # Package init, version loading
├── _version.py                  # Version string (single source of truth)
├── compat.py                    # Compatibility shims, _sanitize_log_value()
├── dependency_check.py          # Optional dependency detection
├── lm_studio_compat.py          # LM Studio compatibility layer
├── mcp_server.py                # MCP stdio server entry point
├── offline_mode.py              # Offline/embedded mode
├── server_impl.py               # ★ MemoryServer — main server class (3688 lines)
│
├── api/                         # API client layer
│   ├── client.py                # HTTP client
│   ├── operations.py            # API operations
│   ├── sync_wrapper.py          # Sync/async bridge
│   └── types.py                 # API type definitions
│
├── backup/                      # Backup scheduler
│   └── scheduler.py
│
├── bootstrap/                   # Bootstrap profile retrieval
│   ├── formatter.py             # Profile formatter
│   └── formatters/
│
├── cli/                         # CLI (`memory` command)
│   ├── main.py                  # CLI entry point
│   ├── lifecycle.py             # Server lifecycle management
│   ├── ingestion.py             # CLI ingestion commands
│   └── utils.py
│
├── config/                      # Configuration management (15 modules)
│   ├── base.py                  # Base config
│   ├── storage.py               # Storage backend config
│   ├── embedding.py             # Embedding model config
│   ├── graph.py                 # Knowledge graph config
│   ├── oauth.py                 # OAuth config
│   ├── consolidation.py         # Consolidation config
│   ├── quality.py               # Quality scoring config
│   ├── search.py                # Search config
│   ├── transport.py             # Transport config
│   ├── validation.py            # Config validation
│   └── ... (backup, documents, locale, ontology)
│
├── consolidation/               # Memory consolidation (16 modules)
│   ├── base.py                  # Abstract base
│   ├── consolidator.py           # Main consolidator
│   ├── scheduler.py              # APScheduler integration
│   ├── compression.py            # Semantic compression
│   ├── clustering.py             # Memory clustering
│   ├── decay.py                  # Temporal decay scoring
│   ├── forgetting.py             # Retention by quality tier
│   ├── contradictions.py         # Contradiction detection
│   ├── relationship_inference.py # Relationship inference (causes, fixes, etc.)
│   ├── belief.py / belief_service.py  # Belief derivation
│   ├── associations.py           # Memory associations
│   ├── insights.py               # Insight generation
│   ├── quarantine.py             # Quarantine system
│   ├── health.py                 # Consolidation health
│   └── run_tracker.py            # Run tracking
│
├── discovery/                   # Service discovery (mDNS/zeroconf)
│   ├── mdns_service.py
│   └── client.py
│
├── embeddings/                  # ONNX embedding generation
│   ├── onnx_embeddings.py        # all-MiniLM-L6-v2 (384d), local ONNX runtime
│   └── external_api.py           # External embedding API support
│
├── extraction/                  # Entity extraction (NER)
│   ├── multilingual.py           # Multilingual NER
│   └── ner_patterns/             # NER pattern definitions
│
├── harvest/                     # Memory harvesting pipeline
│   ├── harvester.py              # Main harvester
│   ├── parser.py                  # Conversation parser
│   ├── extractor.py               # Memory extractor
│   ├── classifier.py              # Memory classifier
│   ├── rewriter.py                # Memory rewriter
│   ├── auto_capture.py            # Auto-capture
│   ├── bootstrap_utils.py         # Bootstrap utilities
│   ├── models.py                  # Harvest data models
│   └── patterns/                  # Pattern definitions
│
├── health/                      # Health monitoring
│   └── integrity.py              # Integrity monitor
│
├── ingestion/                   # Document ingestion (Registry pattern)
│   ├── base.py                   # Base loader
│   ├── registry.py               # Loader registry
│   ├── chunker.py                # Text chunker (1000 chars, 200 overlap)
│   ├── csv_loader.py
│   ├── json_loader.py
│   ├── pdf_loader.py
│   ├── text_loader.py
│   └── semtools_loader.py
│
├── models/                      # Data models
│   ├── memory.py                 # ★ Memory dataclass
│   ├── association.py            # Association model
│   ├── ontology.py               # Ontology model
│   └── tag_taxonomy.py            # Tag taxonomy
│
├── plugins/                     # Plugin system
│   ├── context.py                # Plugin context (hooks: on_store/on_delete/on_retrieve/on_consolidate)
│   └── registry.py               # Plugin discovery & registration
│
├── quality/                     # Quality scoring (3-tier)
│   ├── scorer.py                 # Local scorer
│   ├── async_scorer.py           # Async scoring
│   ├── onnx_ranker.py            # ONNX ranker (80-150ms, $0)
│   ├── ai_evaluator.py           # AI evaluation (Groq/Gemini fallback)
│   ├── implicit_signals.py       # Implicit quality signals
│   ├── metadata_codec.py         # Quality metadata encoding
│   └── config.py                 # Quality config
│
├── reasoning/                    # Semantic reasoning engine
│   ├── inference.py               # Inference engine
│   ├── entities.py                # Entity management
│   ├── entity_linker.py           # Entity linking
│   ├── multi_strategy.py          # Multi-strategy reasoning
│   ├── mutability.py              # Mutability analysis
│   ├── nli.py                     # NLI contradiction detection
│   ├── ranked_search.py           # Ranked search
│   ├── temporal.py                # Temporal reasoning
│   └── nli_patterns/             # NLI pattern definitions
│
├── scoring/                     # Scoring system
│   └── composite.py              # Composite scoring
│
├── server/                      # Server infrastructure
│   ├── __init__.py                # Server init, caching, client detection
│   ├── __main__.py                # Server main entry
│   ├── cache_manager.py           # Global singleton caching
│   ├── client_detection.py        # MCP client detection
│   ├── environment.py             # Environment setup
│   ├── logging_config.py          # Logging configuration
│   ├── handlers/                  # MCP tool handlers
│   │   ├── memory.py              # Store/retrieve/update/delete handlers
│   │   ├── graph.py               # Knowledge graph handlers
│   │   ├── consolidation.py       # Consolidation handlers
│   │   ├── documents.py           # Document ingestion handlers
│   │   ├── quality.py             # Quality evaluation handlers
│   │   ├── mistake_notes.py       # Mistake note handlers
│   │   └── utility.py             # Utility handlers
│   └── utils/
│       └── response_limiter.py    # Response size limiter
│
├── services/                    # Service layer
│   ├── memory_service.py          # High-level memory service
│   └── graph_service.py           # Knowledge graph service
│
├── storage/                      # Storage backends (Strategy pattern)
│   ├── base.py                    # ★ MemoryStorage ABC (1468 lines)
│   ├── factory.py                 # Backend factory
│   ├── sqlite_vec.py              # SQLite-Vec (default, 5ms reads)
│   ├── cloudflare.py              # Cloudflare D1+Vectorize
│   ├── hybrid.py                  # Hybrid (local + cloud sync, recommended)
│   ├── milvus.py                  # Milvus vector DB
│   ├── milvus_graph.py            # Milvus graph storage
│   ├── graph.py                   # SQLite graph storage
│   ├── http_client.py             # HTTP storage client
│   ├── shared.py                  # Shared storage utilities
│   ├── migration_runner.py        # Schema migration runner
│   ├── migrations/                # SQL migration files
│   │   ├── 008_add_graph_table.sql
│   │   ├── 009_add_relationship_type.sql
│   │   ├── 010_fix_asymmetric_relationships.sql
│   │   ├── 011_memory_evolution_p1.sql
│   │   └── 012_add_belief_store.sql
│   └── mixins/                    # Storage mixins (modular composition)
│       ├── base.py                # Base mixin
│       ├── store.py                # Store operations
│       ├── retrieve.py            # Retrieve operations
│       ├── delete.py               # Delete operations
│       ├── embeddings.py           # Embedding generation/cache
│       ├── metadata.py             # Metadata operations
│       ├── hybrid.py               # Hybrid search (BM25 + vector)
│       └── migrations.py           # Migration support
│
├── sync/                         # Cloud synchronization
│   ├── exporter.py                # Data export
│   ├── importer.py                # Data import
│   └── litestream_config.py      # Litestream config
│
├── tools/                        # Tool system (declarative registry)
│   ├── registry.py                # ★ TOOL_REGISTRY — declarative ToolDef objects
│   └── routing.py                 # ★ ROUTING_TABLE — name → handler mapping
│
├── utils/                       # Utilities (16 modules)
│   ├── cache_manager.py           # Global cache
│   ├── content_splitter.py        # Content splitting
│   ├── db_utils.py                # Database utilities
│   ├── debug.py                   # Debug utilities
│   ├── directory_ingestion.py     # Directory ingestion
│   ├── document_processing.py     # Document processing
│   ├── gpu_detection.py           # GPU detection
│   ├── hashing.py                 # Hashing utilities
│   ├── health_check.py            # Health check factory
│   ├── http_server_manager.py     # HTTP server management
│   ├── port_detection.py          # Port detection
│   ├── quality_analytics.py       # Quality analytics
│   ├── startup_orchestrator.py    # Startup orchestrator
│   ├── system_detection.py        # System detection
│   └── time_parser.py             # Time parsing
│
└── web/                          # Web layer (FastAPI)
    ├── app.py                     # FastAPI app
    ├── body_limit.py              # Request body limit
    ├── dependencies.py            # FastAPI dependencies
    ├── sse.py                      # SSE (Server-Sent Events)
    ├── api/                        # 76-endpoint REST API
    │   ├── mcp.py                  # ★ MCP-over-HTTP protocol shim
    │   ├── memories.py             # Memory CRUD
    │   ├── search.py               # Search endpoints
    │   ├── analytics.py            # Analytics
    │   ├── manage.py               # Management
    │   ├── health.py               # Health check
    │   ├── quality.py              # Quality endpoints
    │   ├── documents.py            # Document ingestion
    │   ├── consolidation.py        # Consolidation endpoints
    │   ├── conflicts.py            # Conflict detection
    │   ├── harvest.py              # Harvest endpoints
    │   ├── backup.py               # Backup endpoints
    │   ├── server.py               # Server management
    │   ├── sync.py                 # Sync endpoints
    │   ├── events.py               # Event streaming
    │   ├── configuration.py        # Config management
    │   └── oauth_status.py         # OAuth status
    ├── oauth/                      # OAuth 2.1 + DCR implementation
    │   ├── authorization.py        # Authorization server
    │   ├── registration.py         # Dynamic Client Registration
    │   ├── middleware.py           # OAuth middleware
    │   ├── models.py               # OAuth models
    │   ├── discovery.py             # OIDC discovery
    │   ├── redirect.py             # Redirect handling
    │   ├── rate_limit.py           # Rate limiting
    │   ├── limits.py               # OAuth limits
    │   └── storage/                # OAuth storage backends
    │       ├── base.py
    │       ├── sqlite.py
    │       ├── memory.py
    │       └── factory.py
    └── static/                     # Dashboard static assets (JS, CSS)
```

---

## 4. Core Module Identification

### 4.1 Storage Backends

| Backend | File | Performance | Use Case |
|---------|------|-------------|----------|
| **SQLite-Vec** | `storage/sqlite_vec.py` | 5ms reads | Development, single-user (default) |
| **Cloudflare** | `storage/cloudflare.py` | Network-dependent | Cloud-only, edge |
| **Hybrid** | `storage/hybrid.py` | 5ms local + cloud sync | Production (recommended) |
| **Milvus** | `storage/milvus.py` | Varies | Dedicated vector DB |

- Factory: `storage/factory.py` — creates the appropriate backend
- Graph storage: `storage/graph.py` (SQLite) / `storage/milvus_graph.py` (Milvus)
- Migrations: `storage/migration_runner.py`, `storage/migrations/` (5 SQL files: 008–012)
- Base class: `storage/base.py` — `MemoryStorage` ABC (1468 lines)
- Mixins: `storage/mixins/` — modular composition of store/retrieve/delete/embeddings/metadata/hybrid/migrations

### 4.2 Embeddings (ONNX)

- `embeddings/onnx_embeddings.py` — all-MiniLM-L6-v2 (384d), runs fully local via ONNX Runtime
- `embeddings/external_api.py` — external embedding API support (sqlite_vec backend only)
- Embedding cache in `storage/mixins/embeddings.py` — `_MODEL_CACHE`, `_DIMENSION_CACHE`, `_EMBEDDING_CACHE`
- Hash fallback: when ONNX model unavailable, falls back to hash pseudo-vectors (controlled by `MCP_MEMORY_ALLOW_HASH_EMBEDDINGS`)

### 4.3 Memory Operations

| Operation | Handler | Mixin |
|-----------|---------|-------|
| Store | `server/handlers/memory.py` | `storage/mixins/store.py` |
| Retrieve | `server/handlers/memory.py` | `storage/mixins/retrieve.py` |
| Update | `server/handlers/memory.py` | `storage/mixins/store.py` |
| Delete | `server/handlers/memory.py` | `storage/mixins/delete.py` |
| Consolidate | `server/handlers/consolidation.py` | `consolidation/consolidator.py` |

High-level service: `services/memory_service.py`  
Tool dispatch: `server_impl.py` → `tools/routing.py` → `server/handlers/*.py`

### 4.4 Knowledge Graph

- `storage/graph.py` — SQLite graph storage
- `storage/milvus_graph.py` — Milvus graph storage
- `services/graph_service.py` — Graph service layer
- `server/handlers/graph.py` — Graph MCP tool handlers
- Edge types: causes, fixes, contradicts, supports, follows, related
- Relationship inference: `consolidation/relationship_inference.py` (confidence threshold 0.6)
- Config: `MCP_GRAPH_STORAGE_MODE` — `memories_only` | `dual_write` (default) | `graph_only`

### 4.5 REST API

- `web/app.py` — FastAPI application
- 76 endpoints across `web/api/` (17 modules):
  - `memories.py` — Memory CRUD
  - `search.py` — Semantic/hybrid search
  - `mcp.py` — MCP-over-HTTP protocol shim (inherits tool surface from MemoryServer)
  - `analytics.py` — Analytics + graph analytics
  - `manage.py` — Memory management
  - `health.py` — Health check
  - `quality.py` — Quality evaluation
  - `documents.py` — Document ingestion
  - `consolidation.py` — Consolidation triggers
  - `conflicts.py` — Conflict detection
  - `harvest.py` — Harvest pipeline
  - `backup.py` — Backup management
  - `server.py` — Server management
  - `sync.py` — Sync management
  - `events.py` — Event streaming
  - `configuration.py` — Config management
  - `oauth_status.py` — OAuth status
- `local_only_tools()` in `server_impl.py` — filters tools that read caller-supplied filesystem paths from remote transport (confused-deputy guard)

### 4.6 MCP Protocol Transport

- `mcp_server.py` — MCP stdio server entry point
- `server_impl.py` — `MemoryServer` class: `list_tools()` builds from `TOOL_REGISTRY`, `call_tool()` dispatches via `ROUTING_TABLE`
- `web/api/mcp.py` — MCP-over-HTTP thin shim (inherits tool surface, tools not defined twice)
- `tools/registry.py` — `TOOL_REGISTRY` declarative `ToolDef` objects, each mapping 1:1 to `types.Tool`
- `tools/routing.py` — `ROUTING_TABLE` (name → handler) + `resolve_handler(name)` with lazy import

### 4.7 OAuth 2.1 + DCR

- `web/oauth/` — Full OAuth 2.1 + Dynamic Client Registration implementation
- `authorization.py` — Authorization server
- `registration.py` — DCR endpoint
- `middleware.py` — OAuth middleware (scope enforcement)
- `rate_limit.py` / `limits.py` — Rate limiting
- `storage/` — Pluggable OAuth storage (SQLite, in-memory, factory)
- `discovery.py` — OIDC discovery endpoint
- Write-scope gate in `server_impl.py` — drives OAuth scope from `ToolDef.annotations`

---

## 5. Module Dependency Graph

```
                    ┌─────────────────┐
                    │   CLI (cli/)     │
                    │  memory command  │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │  server_impl.py  │◄──── MCP stdio (mcp_server.py)
                    │  MemoryServer    │◄──── HTTP (web/app.py → web/api/mcp.py)
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼──────┐  ┌───▼──────────┐
     │ tools/      │  │ services/   │  │ server/       │
     │ registry.py │  │ memory_svc  │  │ handlers/     │
     │ routing.py  │  │ graph_svc   │  │ (7 handlers)  │
     └────────┬───┘  └──────┬──────┘  └───┬──────────┘
              │              │              │
              └──────────────┼──────────────┘
                             │
                    ┌────────▼────────┐
                    │  storage/         │◄──── embeddings/onnx_embeddings.py
                    │  base.py (ABC)    │◄──── embeddings/external_api.py
                    │  ├ sqlite_vec.py  │
                    │  ├ cloudflare.py  │
                    │  ├ hybrid.py      │
                    │  ├ milvus.py      │
                    │  └ graph.py       │
                    └────────┬────────┘
                             │
              ┌──────────────┼──────────────┐
              │              │              │
     ┌────────▼───┐  ┌──────▼──────┐  ┌───▼──────────┐
     │ models/     │  │ config/      │  │ utils/        │
     │ memory.py   │  │ (15 modules) │  │ (16 modules)  │
     │ ontology.py │  │              │  │               │
     └────────────┘  └──────────────┘  └───────────────┘

     Cross-cutting:
     ┌─────────────────────────────────────────────────────┐
     │ consolidation/  ←── quality/ ←── reasoning/          │
     │ (16 modules)      (7 modules)   (8 modules)         │
     │                                                     │
     │ extraction/ ←── ingestion/ ←── harvest/              │
     │ (NER)           (8 loaders)   (10 modules)          │
     │                                                     │
     │ plugins/ ←── discovery/ ←── sync/ ←── backup/        │
     │ (hooks)      (mDNS)        (export/  (scheduler)    │
     │                             import)                  │
     └─────────────────────────────────────────────────────┘
```

### Key Dependency Flows

1. **Request flow**: CLI/HTTP/MCP → `server_impl.py` → `tools/routing.py` → `server/handlers/*` → `services/*` → `storage/*`
2. **Embedding flow**: `storage/mixins/embeddings.py` → `embeddings/onnx_embeddings.py` (or `external_api.py`) → cached vectors
3. **Consolidation flow**: `consolidation/scheduler.py` (APScheduler) → `consolidation/consolidator.py` → `quality/scorer.py` → `storage/*` mutations
4. **Graph flow**: `server/handlers/graph.py` → `services/graph_service.py` → `storage/graph.py` (or `milvus_graph.py`)
5. **Web flow**: `web/app.py` → `web/api/*` → `services/*` or `server_impl.py` → `storage/*`

---

## 6. Test Suite

### 6.1 Test Framework Configuration (`pytest.ini`)

```ini
[pytest]
asyncio_mode = auto              # All async tests run automatically
testpaths = tests                # Test discovery root
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = --import-mode=prepend   # Ensure package is properly imported
markers =
    unit: unit tests
    integration: integration tests (require storage)
    performance: performance tests
    asyncio: mark test as async
    enable_plugins: allow plugin discovery in test
```

### 6.2 Test File Inventory

**227 test files** across 20 subdirectories:

| Directory | Files | Description |
|-----------|-------|-------------|
| `tests/` (root) | 84 | Core feature tests (storage, graph, embeddings, quality, etc.) |
| `tests/unit/` | 29 | Fast unit tests (imports, CLI, OAuth, loaders, config) |
| `tests/storage/` | 24 | Storage backend tests (SQLite-Vec, Milvus, hybrid, graph, migrations) |
| `tests/integration/` | 17 | End-to-end integration tests (API, server handlers, OAuth flows) |
| `tests/consolidation/` | 16 | Consolidation pipeline tests (decay, compression, contradictions) |
| `tests/web/api/` | 12 | REST API endpoint tests (write scope, transport parity, analytics) |
| `tests/harvest/` | 10 | Harvest pipeline tests (parser, classifier, extractor, integration) |
| `tests/benchmarks/` | 8 | Performance benchmarks (LoCoMo, LongMemEval, DevBench, NDCG) |
| `tests/web/` | 4 | Web infrastructure tests (SSE, sessions, OAuth hardening, middleware) |
| `tests/reasoning/` | 5 | Reasoning engine tests (NLI, temporal, mutability, ranked search) |
| `tests/timestamp/` | 5 | Timestamp preservation tests (issue #99 validation) |
| `tests/services/` | 3 | Service layer tests (memory service, mistake notes, log injection) |
| `tests/server/` | 2 | Server handler tests (store session/memory handlers) |
| `tests/plugins/` | 2 | Plugin system tests (hooks, wiring) |
| `tests/performance/` | 2 | Performance tests (hybrid live, background sync) |
| `tests/api/` | 2 | API client tests (operations, compact types) |
| `tests/discovery/` | 1 | Discovery test (TLS verification) |
| `tests/maintenance/` | 1 | Maintenance test (changelog housekeeping) |
| `tests/quality/` | 1 | Quality test (maintain) |
| `tests/smithery/` | 1 | Smithery integration test |
| **Total** | **227** | |

### 6.3 Test Safety System (`conftest.py`)

Three-layer safety system prevents tests from touching production databases:

1. **Isolated temp directory**: `tempfile.mkdtemp(prefix='mcp-test-db-')` at module import, path set as `MCP_MEMORY_SQLITE_PATH`
2. **`pytest_sessionstart`**: Aborts test run if production path detected
3. **`pytest_sessionfinish`**: Triple verification before cleanup (temp dir check, production indicator check, positive allowlist)

Additional test configuration:
- `MCP_MEMORY_STORAGE_BACKEND` forced to `sqlite_vec` (unless `MCP_TEST_ALLOW_CLOUD_BACKEND=true`)
- `MCP_SEMANTIC_DEDUP_ENABLED=false` — prevents test interference
- `MCP_MEMORY_ALLOW_HASH_EMBEDDINGS=1` — allows hash fallback in ML-free environments
- `MCP_MEMORY_ONNX_ALLOW_DOWNLOAD=0` — prevents 80MB model download in CI
- `TEST_MEMORY_TAG = "__test__"` — reserved tag for automatic cleanup
- `_disable_plugins` fixture — prevents external plugin interference
- `_clear_embedding_caches` fixture — resets embedding caches between tests

### 6.4 Test Markers

| Marker | Purpose |
|--------|---------|
| `@pytest.mark.unit` | Fast unit tests (no storage required) |
| `@pytest.mark.integration` | Integration tests (require storage backend) |
| `@pytest.mark.performance` | Performance benchmark tests |
| `@pytest.mark.asyncio` | Async test (auto-applied via `asyncio_mode = auto`) |
| `@pytest.mark.enable_plugins` | Override `_disable_plugins` fixture for specific tests |

---

## 7. Coverage Configuration

### 7.1 `.coveragerc`

```ini
[run]
source = src/mcp_memory_service
omit = (extensive list, see below)

[report]
precision = 2
show_missing = true
skip_covered = false
exclude_lines =
    pragma: no cover
    def __repr__
    if TYPE_CHECKING:
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
    @(abc\.)?abstractmethod
```

### 7.2 `pyproject.toml [tool.coverage.*]`

Duplicate configuration in `pyproject.toml` with identical omit list.

### 7.3 Omitted Modules (no coverage tracking)

| Module | Reason |
|--------|--------|
| `web/oauth/*` | No tests yet (Issue #316) |
| `web/app.py`, `web/sse.py` | Minimal test coverage |
| `web/api/*`, `web/dependencies.py` | Minimal test coverage |
| `sync/*` | No tests |
| `backup/scheduler.py`, `consolidation/scheduler.py` | Infrastructure code |
| `cli/*`, `cli/utils.py` | Minimal coverage |
| `api/client.py`, `api/operations.py`, `api/sync_wrapper.py` | Infrastructure code |
| `ingestion/*` | Minimal coverage |
| `discovery/*` | Infrastructure code |
| 13 `utils/*` modules | Infrastructure code |
| `storage/milvus.py`, `storage/milvus_graph.py` | Requires pymilvus (not in CI) |
| `storage/http_client.py` | Minimal usage |
| `__main__.py`, `mcp_server.py` | CLI entry points |

### 7.4 CI Coverage Usage

CI runs `--cov=mcp_memory_service --cov-report=term-missing:skip-covered` — **report-only, no `--cov-fail-under` gate**. The comment states: "re-introduce a gate once the deterministic-subset baseline is known and stable."

---

## 8. Dependency Management

### 8.1 Build System

```toml
[build-system]
requires = ["hatchling", "python-semantic-release", "build"]
build-backend = "hatchling.build"
```

### 8.2 Core Dependencies (26 packages)

| Package | Purpose |
|---------|---------|
| `mcp>=1.8.0,<2.0.0` | Model Context Protocol SDK |
| `fastapi[standard]>=0.115.5` | Web framework |
| `uvicorn>=0.30.0` | ASGI server |
| `sqlite-vec>=0.1.6` | SQLite vector extension |
| `aiosqlite>=0.20.0` | Async SQLite |
| `aiohttp>=3.13.3` | Async HTTP client |
| `httpx>=0.24.0` | HTTP client |
| `numpy>=2.3.0` | Numerical operations |
| `apscheduler>=3.11.0` | Consolidation scheduler |
| `authlib>=1.6.9` | OAuth 2.1 |
| `PyJWT[crypto]>=2.12.0` | JWT tokens |
| `cryptography>=46.0.6` | Cryptographic primitives |
| `python-multipart>=0.0.22` | File upload support |
| `python-dotenv>=1.0.0` | .env file loading |
| `sse-starlette>=2.1.0` | Server-Sent Events |
| `zeroconf>=0.130.0` | mDNS service discovery |
| `pypdf>=6.9.1` | PDF ingestion |
| `chardet>=5.0.0` | Encoding detection |
| `click>=8.0.0` | CLI framework |
| `PyYAML>=6.0` | YAML parsing |
| `psutil>=5.9.0` | Process/system info |
| `aiofiles>=23.2.1` | Async file I/O |
| `requests>=2.32.4` | HTTP client (sync) |

### 8.3 Optional Dependency Groups

| Group | Packages | Use Case |
|-------|----------|----------|
| `dev` | pytest, pytest-asyncio, pytest-cov, pytest-benchmark, pytest-timeout, pytest-subtests, black, ruff | Development & testing |
| `sqlite` | onnxruntime, tokenizers | SQLite-Vec with lightweight ONNX (recommended) |
| `ml` | sentence-transformers, tokenizers, torch, transformers, wandb | Full ML capabilities |
| `nli` | transformers, onnxruntime | NLI contradiction detection |
| `sqlite-ml` | mcp-memory-service[sqlite,ml] | SQLite with full ML |
| `milvus` | pymilvus, milvus-lite, setuptools<83, mcp-memory-service[ml] | Milvus backend |
| `full` | mcp-memory-service[sqlite,ml,dev] | All dependencies |

### 8.4 Version Management

- `python-semantic-release` for automated version bumping
- Version source: `src/mcp_memory_service/_version.py` (`__version__`)
- Synced to `pyproject.toml:version` and `pyproject-lite.toml:version`
- Semantic commit messages drive version bumps: `feat:` → minor, `fix:`/`perf:` → patch

### 8.5 Lite Package

`pyproject-lite.toml` — a variant package without PyTorch, using only ONNX embeddings. Published alongside the main package to PyPI in the release pipeline.

---

## 9. CI/CD Configuration

### 9.1 Forgejo Actions (`.forgejo/workflows/`)

| Workflow | File | Trigger | Purpose |
|----------|------|---------|---------|
| **CI** | `ci.yml` | push/PR to main | Version drift check + tests with coverage |
| **Release** | `release.yml` | tag `v*.*.*` / manual | PyPI publish (main + lite) + Docker Hub push |
| **Deploy Site** | `deploy-site.yml` | push to main (site/**) | Cloudflare Pages deploy via wrangler |
| **Cleanup Images** | `cleanup-images.yml` | Weekly cron (Sun 02:00 UTC) / manual | Docker Hub image retention policy |

### 9.2 CI Pipeline Details (`ci.yml`)

**Runner**: self-hosted Docker runner on Hetzner (tinyclaw)

**Jobs**:
1. `version-drift-check` — Verifies `site/index.html` version matches `_version.py` (MAJOR.MINOR)
2. `test` — Installs `.[dev,sqlite]`, runs pytest with coverage:
   - Excludes: `tests/consolidation`, `tests/benchmarks`, `tests/integration`
   - Excludes: `-m "not benchmark"`
   - Coverage: `--cov=mcp_memory_service --cov-report=term-missing:skip-covered`
   - Timeout: `--timeout=120` per test
   - No `-x` flag (reports all failures)
   - No `--cov-fail-under` gate

### 9.3 Release Pipeline Details (`release.yml`)

1. **Test** — `pytest -m unit -q` (unit tests only)
2. **Publish PyPI** — Builds main package + lite package, uploads both via twine
3. **Publish Docker** — Builds standard (amd64) + slim (amd64+arm64) images to Docker Hub

### 9.4 GitHub Configuration (`.github/`)

- `.github/codeql/` — CodeQL analysis config
- `.github/ISSUE_TEMPLATE/` — Issue templates
- `.github/CODEOWNERS` — Code ownership rules
- `.github/dependabot.yml` — Dependabot config
- `.github/FUNDING.yml` — Sponsorship info

Note: GitHub is a **suspended mirror**. The `.github/` directory exists for issue templates and codeql config, but CI runs on Forgejo Actions.

### 9.5 Scripts Directory (`scripts/`)

20 subdirectories with utility scripts:

| Directory | Purpose |
|-----------|---------|
| `scripts/ci/` | CI helpers (version check) |
| `scripts/pr/` | PR pre-check gate (`pre_pr_check.sh`) |
| `scripts/backup/` | Backup scripts |
| `scripts/benchmarks/` | Performance benchmarking |
| `scripts/database/` | Database utilities |
| `scripts/demo/` | Demo scripts |
| `scripts/development/` | Development helpers |
| `scripts/installation/` | Installation scripts |
| `scripts/migration/` | Migration scripts |
| `scripts/quality/` | Quality analysis scripts |
| `scripts/test/` | Test helpers |
| `scripts/testing/` | Testing utilities |
| `scripts/validation/` | Validation scripts |
| `scripts/verification/` | Verification scripts |
| ... and more |

---

## 10. Documentation

### 10.1 Root-Level Documentation

| File | Content |
|------|---------|
| `README.md` | User-facing docs, installation, features |
| `CLAUDE.md` | Comprehensive dev guide (Claude Code specific, very detailed) |
| `CHANGELOG.md` | Version history (auto-generated by semantic-release) |
| `CONTRIBUTING.md` | Contribution guidelines |
| `CODE_OF_CONDUCT.md` | Code of conduct |
| `SECURITY.md` | Security policy |
| `AUTHORSHIP.md` | Authorship info |
| `SPONSORS.md` | Sponsorship info |
| `AGENTS.md` | Agent guidelines |
| `NOTICE.md` | Third-party notices |
| `LICENSE` | Apache 2.0 license |

### 10.2 Docs Directory (`docs/`)

40+ documents across 30+ subdirectories:

| Document | Content |
|----------|---------|
| `docs/architecture.md` | Architecture overview |
| `docs/ROADMAP.md` | Project roadmap |
| `docs/README.md` | Docs index |
| `docs/setup-guide.md` | Setup decision tree |
| `docs/mastery/configuration-guide.md` | Full configuration reference |
| `docs/BENCHMARKS.md` | Performance benchmarks |
| `docs/MIGRATION.md` | Migration guide |
| `docs/oauth-quickstart.md` | OAuth quick start |
| `docs/oauth-setup.md` | OAuth setup guide |
| `docs/sqlite-vec-backend.md` | SQLite-Vec backend docs |
| `docs/milvus-backend.md` | Milvus backend docs |
| `docs/cloudflare-setup.md` | Cloudflare setup |
| `docs/docker-optimized-build.md` | Docker build guide |
| `docs/document-ingestion.md` | Document ingestion guide |
| `docs/integrations.md` | Client integrations |
| `docs/LIGHTWEIGHT_ONNX_SETUP.md` | ONNX setup |
| `docs/LM_STUDIO_COMPATIBILITY.md` | LM Studio compat |
| `docs/remote-mcp-setup.md` | Remote MCP setup |
| `docs/memory-ontology.md` | Memory ontology |
| `docs/DOMAIN_EXTRACTORS.md` | Domain extractors |

Plus subdirectories: `architecture/`, `deployment/`, `development/`, `examples/`, `features/`, `guides/`, `implementation/`, `integration/`, `integrations/`, `maintenance/`, `migration/`, `migrations/`, `research/`, `reviews/`, `testing/`, `troubleshooting/`, `tutorials/`, `verification/`, etc.

### 10.3 API Documentation

- REST API: 76 endpoints, documented via FastAPI auto-generated OpenAPI/Swagger at `/docs`
- MCP tools: Declarative registry in `tools/registry.py`, each with description and input schema
- OAuth: `docs/oauth-quickstart.md`, `docs/oauth-setup.md`, `docs/oauth-storage-backends.md`

### 10.4 Landing Page (`site/`)

- `site/index.html` — mcpmemory.services landing page
- Auto-deployed to Cloudflare Pages via `deploy-site.yml` workflow
- Version strings in `site/index.html` must match `_version.py` (CI gate)

---

## 11. Coding Style & Tooling

| Tool | Configuration | Purpose |
|------|---------------|---------|
| **Black** | `line-length = 88` (implicit via ruff) | Code formatting |
| **Ruff** | `line-length = 88`, `target-version = "py310"` | Linting + formatting |
| **pytest** | `asyncio_mode = auto` | Test framework |
| **pytest-cov** | `--cov-report=term-missing:skip-covered` | Coverage reporting |
| **pytest-timeout** | `--timeout=120` (CI) | Test timeout |
| **pytest-benchmark** | `@pytest.mark.benchmark` | Performance benchmarks |
| **python-semantic-release** | Auto version bump + changelog | Release management |

### Ruff Configuration

- **Selected rules**: E (pycodestyle errors), W (warnings), F (pyflakes), I (isort), UP (pyupgrade), RUF, B (bugbear), C4 (comprehensions), SIM (simplify)
- **Ignored rules**: E501 (line too long), E203 (whitespace before colon), E402 (import order), B008 (FastAPI Depends), and several SIM rules for readability
- **Per-file ignores**: `__init__.py` (F401, E402), `tests/*` (B011, SIM)

---

## 12. Key Design Patterns

| Pattern | Usage |
|---------|-------|
| **Strategy Pattern** | Storage backends, health checks, quality analytics |
| **Registry Pattern** | Document loaders, storage factory, declarative tool registry |
| **Orchestrator Pattern** | Startup orchestrator, consolidation scheduler |
| **Singleton Pattern** | Global caching (storage, service instances) via `server/cache_manager.py` |
| **Processor Pattern** | Document ingestion, file processing |
| **Mixin Pattern** | Storage mixins (store/retrieve/delete/embeddings/metadata/hybrid/migrations) |
| **Handler Pattern** | MCP tool handlers (7 handler modules in `server/handlers/`) |

---

## Summary

mcp-memory-service is a mature, production-grade Python project with:
- **213 source files** across 22 sub-packages, 3688-line main server implementation
- **227 test files** across 20 test directories with triple-safety test isolation
- **4 Forgejo Actions CI workflows** (CI, release, site deploy, image cleanup)
- **Strategy-pattern storage** with 4 backends (SQLite-Vec, Cloudflare, Hybrid, Milvus)
- **Declarative tool registry** for MCP protocol (1:1 ToolDef → Tool → Handler → Router)
- **OAuth 2.1 + DCR** with pluggable storage backends
- **76-endpoint REST API** + MCP-over-HTTP shim
- **Coverage tracking** with extensive omits for untested infrastructure code
- **No `--cov-fail-under` gate** — coverage is report-only for now
