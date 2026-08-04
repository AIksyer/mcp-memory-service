# Coverage Baseline Report — mcp-memory-service v11.5.5

> Generated: 2026-08-04
> Python: 3.14.2 (system, no venv)
> Platform: win32 (zh-CN locale)
> Test Runner: pytest 9.1.1 + pytest-cov 7.1.0
> Storage Backend: sqlite_vec (forced via env)
> Duration: 385.47s (6m 25s)

---

## 1. Test Results Summary

| Category | Count |
|----------|-------|
| **Passed** | 2,542 |
| **Failed** | 48 |
| **Errors** | 50 |
| **Skipped** | 89 |
| **XFailed** (expected fail) | 23 |
| **XPassed** (unexpected pass) | 6 |
| **Warnings** | 10,385 |
| **Total test items** | 2,758 |

**Pass rate (passed / (passed + failed + errors))**: 2,542 / 2,640 = **96.3%**

---

## 2. Coverage Summary

| Metric | Value |
|--------|-------|
| **Total statements** | 16,826 |
| **Missing statements** | 5,619 |
| **Overall line coverage** | **66.61%** |
| HTML report | `htmlcov/index.html` |

> **Note:** Branch coverage was not separately reported (pytest-cov line mode only, as configured in `.coveragerc`).

---

## 3. Per-Module Coverage Table

### 3.1 Tracked Modules (included in coverage)

| Module | Stmts | Miss | Cover | Status |
|--------|-------|------|-------|--------|
| `__init__.py` | 21 | 14 | 33.33% | 🔴 <50% |
| `_version.py` | 1 | 0 | 100.00% | ✅ |
| `api/__init__.py` | 7 | 0 | 100.00% | ✅ |
| `api/types.py` | 6 | 0 | 100.00% | ✅ |
| `backup/__init__.py` | 2 | 2 | 0.00% | 🔴 <50% |
| `bootstrap/__init__.py` | 0 | 0 | 100.00% | ✅ |
| `bootstrap/formatter.py` | 85 | 12 | 85.88% | ✅ |
| `bootstrap/formatters/__init__.py` | 0 | 0 | 100.00% | ✅ |
| `compat.py` | 2 | 0 | 100.00% | ✅ |
| `config/__init__.py` | 14 | 0 | 100.00% | ✅ |
| `config/backup.py` | 15 | 2 | 86.67% | ✅ |
| `config/base.py` | 157 | 60 | 61.78% | ✅ |
| `config/consolidation.py` | 39 | 12 | 69.23% | ✅ |
| `config/documents.py` | 11 | 1 | 90.91% | ✅ |
| `config/embedding.py` | 10 | 3 | 70.00% | ✅ |
| `config/graph.py` | 13 | 2 | 84.62% | ✅ |
| `config/locale.py` | 6 | 0 | 100.00% | ✅ |
| `config/oauth.py` | 138 | 79 | 42.75% | 🔴 <50% |
| `config/ontology.py` | 16 | 9 | 43.75% | 🔴 <50% |
| `config/quality.py` | 40 | 9 | 77.50% | ✅ |
| `config/search.py` | 27 | 10 | 62.96% | ✅ |
| `config/storage.py` | 142 | 76 | 46.48% | 🔴 <50% |
| `config/transport.py` | 26 | 0 | 100.00% | ✅ |
| `config/validation.py` | 24 | 6 | 75.00% | ✅ |
| `consolidation/__init__.py` | 12 | 0 | 100.00% | ✅ |
| `consolidation/associations.py` | 157 | 24 | 84.71% | ✅ |
| `consolidation/base.py` | 93 | 9 | 90.32% | ✅ |
| `consolidation/belief.py` | 45 | 0 | 100.00% | ✅ |
| `consolidation/belief_service.py` | 208 | 42 | 79.81% | ✅ |
| `consolidation/clustering.py` | 181 | 28 | 84.53% | ✅ |
| `consolidation/compression.py` | 212 | 10 | 95.28% | ✅ |
| `consolidation/consolidator.py` | 484 | 146 | 69.83% | ✅ |
| `consolidation/contradictions.py` | 88 | 18 | 79.55% | ✅ |
| `consolidation/decay.py` | 93 | 3 | 96.77% | ✅ |
| `consolidation/forgetting.py` | 259 | 37 | 85.71% | ✅ |
| `consolidation/health.py` | 187 | 33 | 82.35% | ✅ |
| `consolidation/insights.py` | 143 | 10 | 93.01% | ✅ |
| `consolidation/quarantine.py` | 63 | 8 | 87.30% | ✅ |
| `consolidation/relationship_inference.py` | 148 | 23 | 84.46% | ✅ |
| `consolidation/run_tracker.py` | 44 | 0 | 100.00% | ✅ |
| `dependency_check.py` | 146 | 40 | 72.60% | ✅ |
| `embeddings/__init__.py` | 3 | 0 | 100.00% | ✅ |
| `embeddings/external_api.py` | 84 | 20 | 76.19% | ✅ |
| `embeddings/onnx_embeddings.py` | 140 | 57 | 59.29% | ✅ |
| `extraction/__init__.py` | 0 | 0 | 100.00% | ✅ |
| `extraction/multilingual.py` | 74 | 10 | 86.49% | ✅ |
| `extraction/ner_patterns/__init__.py` | 47 | 0 | 100.00% | ✅ |
| `harvest/__init__.py` | 6 | 0 | 100.00% | ✅ |
| `harvest/auto_capture.py` | 116 | 37 | 68.10% | ✅ |
| `harvest/bootstrap_utils.py` | 63 | 12 | 80.95% | ✅ |
| `harvest/classifier.py` | 128 | 30 | 76.56% | ✅ |
| `harvest/extractor.py` | 101 | 4 | 96.04% | ✅ |
| `harvest/harvester.py` | 174 | 66 | 62.07% | ✅ |
| `harvest/models.py` | 35 | 2 | 94.29% | ✅ |
| `harvest/parser.py` | 126 | 4 | 96.83% | ✅ |
| `harvest/patterns/__init__.py` | 113 | 44 | 61.06% | ✅ |
| `harvest/rewriter.py` | 172 | 86 | 50.00% | ⚠️ borderline |
| `health/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `health/integrity.py` | 139 | 63 | 54.68% | ✅ |
| `lm_studio_compat.py` | 129 | 81 | 37.21% | 🔴 <50% |
| `models/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `models/association.py` | 18 | 2 | 88.89% | ✅ |
| `models/memory.py` | 232 | 67 | 71.12% | ✅ |
| `models/ontology.py` | 132 | 12 | 90.91% | ✅ |
| `models/tag_taxonomy.py` | 45 | 0 | 100.00% | ✅ |
| `offline_mode.py` | 22 | 5 | 77.27% | ✅ |
| `plugins/__init__.py` | 3 | 0 | 100.00% | ✅ |
| `plugins/context.py` | 13 | 0 | 100.00% | ✅ |
| `plugins/registry.py` | 60 | 5 | 91.67% | ✅ |
| `quality/__init__.py` | 6 | 0 | 100.00% | ✅ |
| `quality/ai_evaluator.py` | 265 | 159 | 40.00% | 🔴 <50% |
| `quality/async_scorer.py` | 110 | 32 | 70.91% | ✅ |
| `quality/config.py` | 67 | 5 | 92.54% | ✅ |
| `quality/implicit_signals.py` | 43 | 0 | 100.00% | ✅ |
| `quality/metadata_codec.py` | 140 | 62 | 55.71% | ✅ |
| `quality/onnx_ranker.py` | 330 | 268 | 18.79% | 🔴 <50% |
| `quality/scorer.py` | 41 | 1 | 97.56% | ✅ |
| `reasoning/__init__.py` | 8 | 0 | 100.00% | ✅ |
| `reasoning/entities.py` | 103 | 5 | 95.15% | ✅ |
| `reasoning/entity_linker.py` | 42 | 9 | 78.57% | ✅ |
| `reasoning/inference.py` | 98 | 23 | 76.53% | ✅ |
| `reasoning/multi_strategy.py` | 62 | 4 | 93.55% | ✅ |
| `reasoning/mutability.py` | 22 | 1 | 95.45% | ✅ |
| `reasoning/nli.py` | 106 | 16 | 84.91% | ✅ |
| `reasoning/nli_patterns/__init__.py` | 33 | 4 | 87.88% | ✅ |
| `reasoning/ranked_search.py` | 59 | 6 | 89.83% | ✅ |
| `reasoning/temporal.py` | 35 | 0 | 100.00% | ✅ |
| `scoring/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `scoring/composite.py` | 26 | 0 | 100.00% | ✅ |
| `server/__init__.py` | 6 | 0 | 100.00% | ✅ |
| `server/cache_manager.py` | 54 | 21 | 61.11% | ✅ |
| `server/client_detection.py` | 32 | 10 | 68.75% | ✅ |
| `server/environment.py` | 94 | 70 | 25.53% | 🔴 <50% |
| `server/handlers/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `server/handlers/consolidation.py` | 241 | 151 | 37.34% | 🔴 <50% |
| `server/handlers/documents.py` | 115 | 108 | 6.09% | 🔴 <50% |
| `server/handlers/graph.py` | 345 | 130 | 62.32% | ✅ |
| `server/handlers/memory.py` | 796 | 296 | 62.81% | ✅ |
| `server/handlers/mistake_notes.py` | 20 | 6 | 70.00% | ✅ |
| `server/handlers/quality.py` | 335 | 160 | 52.24% | ✅ |
| `server/handlers/utility.py` | 60 | 24 | 60.00% | ✅ |
| `server/logging_config.py` | 31 | 3 | 90.32% | ✅ |
| `server/utils/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `server/utils/response_limiter.py` | 65 | 7 | 89.23% | ✅ |
| `server_impl.py` | 1,473 | 702 | 52.34% | ✅ |
| `services/__init__.py` | 2 | 0 | 100.00% | ✅ |
| `services/graph_service.py` | 44 | 0 | 100.00% | ✅ |
| `services/memory_service.py` | 406 | 54 | 86.70% | ✅ |
| `storage/__init__.py` | 22 | 8 | 63.64% | ✅ |
| `storage/base.py` | 346 | 141 | 59.25% | ✅ |
| `storage/cloudflare.py` | 1,084 | 525 | 51.57% | ✅ |
| `storage/factory.py` | 68 | 49 | 27.94% | 🔴 <50% |
| `storage/graph.py` | 357 | 75 | 78.99% | ✅ |
| `storage/hybrid.py` | 871 | 400 | 54.08% | ✅ |
| `storage/migration_runner.py` | 133 | 7 | 94.74% | ✅ |
| `storage/mixins/__init__.py` | 9 | 0 | 100.00% | ✅ |
| `storage/mixins/base.py` | 241 | 86 | 64.32% | ✅ |
| `storage/mixins/delete.py` | 217 | 60 | 72.35% | ✅ |
| `storage/mixins/embeddings.py` | 280 | 73 | 73.93% | ✅ |
| `storage/mixins/hybrid.py` | 130 | 28 | 78.46% | ✅ |
| `storage/mixins/metadata.py` | 346 | 73 | 78.90% | ✅ |
| `storage/mixins/migrations.py` | 265 | 60 | 77.36% | ✅ |
| `storage/mixins/retrieve.py` | 627 | 158 | 74.80% | ✅ |
| `storage/mixins/store.py` | 151 | 36 | 76.16% | ✅ |
| `storage/shared.py` | 55 | 5 | 90.91% | ✅ |
| `storage/sqlite_vec.py` | 11 | 0 | 100.00% | ✅ |
| `tools/__init__.py` | 0 | 0 | 100.00% | ✅ |
| `tools/registry.py` | 10 | 0 | 100.00% | ✅ |
| `tools/routing.py` | 24 | 0 | 100.00% | ✅ |
| `utils/__init__.py` | 3 | 0 | 100.00% | ✅ |
| `utils/document_processing.py` | 28 | 21 | 25.00% | 🔴 <50% |
| `utils/hashing.py` | 4 | 0 | 100.00% | ✅ |
| `utils/system_detection.py` | 210 | 130 | 38.10% | 🔴 <50% |
| `web/__init__.py` | 4 | 2 | 50.00% | ⚠️ borderline |
| `web/body_limit.py` | 65 | 10 | 84.62% | ✅ |
| **TOTAL** | **16,826** | **5,619** | **66.61%** | |

### 3.2 Modules Omitted from Coverage (`.coveragerc`)

These modules are explicitly excluded from coverage tracking. They have **no coverage data**:

| Module / Path | Omit Reason |
|---------------|-------------|
| `web/oauth/*` | OAuth system — no tests yet (Issue #316) |
| `web/app.py` | Web infrastructure — minimal test coverage |
| `web/sse.py` | Web infrastructure — minimal test coverage |
| `web/api/*` (17 modules) | Web API endpoints — minimal test coverage |
| `web/dependencies.py` | Web infrastructure |
| `sync/*` (3 modules) | Sync infrastructure — no tests |
| `backup/scheduler.py` | Infrastructure code |
| `consolidation/scheduler.py` | Infrastructure code |
| `cli/*` (5 modules) | CLI commands — minimal coverage |
| `api/client.py`, `api/operations.py`, `api/sync_wrapper.py` | API client layer — infrastructure code |
| `ingestion/*` (8 modules) | Ingestion system — minimal coverage |
| `discovery/*` (2 modules) | Discovery system — infrastructure code |
| `utils/cache_manager.py` | Infrastructure code |
| `utils/directory_ingestion.py` | Infrastructure code |
| `utils/health_check.py` | Infrastructure code |
| `utils/http_server_manager.py` | Infrastructure code |
| `utils/port_detection.py` | Infrastructure code |
| `utils/quality_analytics.py` | Infrastructure code |
| `utils/startup_orchestrator.py` | Infrastructure code |
| `utils/time_parser.py` | Infrastructure code |
| `utils/gpu_detection.py` | Infrastructure code |
| `utils/db_utils.py` | Infrastructure code |
| `utils/content_splitter.py` | Infrastructure code |
| `utils/debug.py` | Infrastructure code |
| `storage/http_client.py` | HTTP client — minimal usage |
| `storage/milvus.py` | Tested in dedicated CI job (Docker) |
| `storage/milvus_graph.py` | Tested in dedicated CI job (Docker) |
| `server/__main__.py` | CLI entry point |
| `mcp_server.py` | CLI entry point |

**Total omitted modules: ~50 files across 10+ subsystems**

---

## 4. Modules with Coverage Below 50%

| Module | Stmts | Miss | Cover | Root Cause |
|--------|-------|------|-------|------------|
| `backup/__init__.py` | 2 | 2 | 0.00% | No test file; backup module untested |
| `server/handlers/documents.py` | 115 | 108 | 6.09% | Document ingestion handlers untested |
| `quality/onnx_ranker.py` | 330 | 268 | 18.79% | ONNX ranker model loading/test infra missing |
| `server/environment.py` | 94 | 70 | 25.53% | Environment setup code untested |
| `utils/document_processing.py` | 28 | 21 | 25.00% | Document processing utils untested |
| `storage/factory.py` | 68 | 49 | 27.94% | Factory branches (cloudflare/milvus) untested |
| `lm_studio_compat.py` | 129 | 81 | 37.21% | LM Studio compatibility layer untested |
| `server/handlers/consolidation.py` | 241 | 151 | 37.34% | Consolidation handlers untested |
| `quality/ai_evaluator.py` | 265 | 159 | 40.00% | AI evaluator (Groq/Gemini) untested |
| `config/oauth.py` | 138 | 79 | 42.75% | OAuth config untested |
| `config/ontology.py` | 16 | 9 | 43.75% | Ontology config untested |
| `config/storage.py` | 142 | 76 | 46.48% | Storage config branches untested |
| `__init__.py` | 21 | 14 | 33.33% | Package init version loading untested |

**Borderline (exactly 50%)**:
| Module | Stmts | Miss | Cover |
|--------|-------|------|-------|
| `harvest/rewriter.py` | 172 | 86 | 50.00% |
| `web/__init__.py` | 4 | 2 | 50.00% |

---

## 5. Modules with No Test Coverage (0% or omitted)

### 5.1 Tracked but 0% coverage
- `backup/__init__.py` — 0.00% (2 statements, both missing)

### 5.2 Omitted from coverage tracking entirely (~50 files)
These modules are excluded from coverage via `.coveragerc` and have no coverage data at all:

**Web API layer** (17 modules): `web/api/analytics.py`, `web/api/backup.py`, `web/api/configuration.py`, `web/api/conflicts.py`, `web/api/consolidation.py`, `web/api/documents.py`, `web/api/events.py`, `web/api/harvest.py`, `web/api/health.py`, `web/api/manage.py`, `web/api/mcp.py`, `web/api/memories.py`, `web/api/oauth_status.py`, `web/api/quality.py`, `web/api/search.py`, `web/api/server.py`, `web/api/sync.py`

**OAuth system** (12 modules): `web/oauth/authorization.py`, `web/oauth/discovery.py`, `web/oauth/limits.py`, `web/oauth/middleware.py`, `web/oauth/models.py`, `web/oauth/rate_limit.py`, `web/oauth/redirect.py`, `web/oauth/registration.py`, `web/oauth/storage/base.py`, `web/oauth/storage/factory.py`, `web/oauth/storage/memory.py`, `web/oauth/storage/sqlite.py`

**CLI** (5 modules): `cli/__init__.py`, `cli/ingestion.py`, `cli/lifecycle.py`, `cli/main.py`, `cli/utils.py`

**Ingestion** (8 modules): `ingestion/__init__.py`, `ingestion/base.py`, `ingestion/chunker.py`, `ingestion/csv_loader.py`, `ingestion/json_loader.py`, `ingestion/pdf_loader.py`, `ingestion/registry.py`, `ingestion/semtools_loader.py`, `ingestion/text_loader.py`

**Sync** (3 modules): `sync/exporter.py`, `sync/importer.py`, `sync/litestream_config.py`

**Discovery** (2 modules): `discovery/client.py`, `discovery/mdns_service.py`

**Utils** (12 modules): `utils/cache_manager.py`, `utils/content_splitter.py`, `utils/db_utils.py`, `utils/debug.py`, `utils/directory_ingestion.py`, `utils/gpu_detection.py`, `utils/health_check.py`, `utils/http_server_manager.py`, `utils/port_detection.py`, `utils/quality_analytics.py`, `utils/startup_orchestrator.py`, `utils/time_parser.py`

**Other**: `web/app.py`, `web/sse.py`, `web/dependencies.py`, `backup/scheduler.py`, `consolidation/scheduler.py`, `api/client.py`, `api/operations.py`, `api/sync_wrapper.py`, `storage/http_client.py`, `storage/milvus.py`, `storage/milvus_graph.py`, `server/__main__.py`, `mcp_server.py`

---

## 6. Failed Tests — Detailed Analysis

### 6.1 Failure Category Summary

| Category | Failures | Errors | Root Cause | Fix Difficulty |
|----------|----------|--------|------------|-----------------|
| Windows PermissionError (WinError 32) | 13 | 50 | SQLite temp DB files locked during teardown | Medium — need async close before cleanup |
| Windows GBK Encoding Error | 16 | 0 | `pathlib.read_text()` / subprocess uses GBK on zh-CN Windows | Easy — add `encoding="utf-8"` |
| OAuth sqlite3.Row.get() | 7 | 0 | `sqlite3.Row` has no `.get()` method | Easy — use `row["key"]` or convert to dict |
| CLI `uv run` not available | 11 | 0 | Tests call `uv run memory` but `uv` not installed | Easy — mock subprocess or use `memory` directly |
| CLI status embedding empty output | 3 | 0 | CLI command produces no stdout | Medium — investigate CLI status handler |
| FastAPI router API change | 1 | 0 | `'_IncludedRouter' has no attribute 'path'` | Easy — adapt to new FastAPI API |
| Unix-only signal.SIGKILL | 1 | 0 | `signal.SIGKILL` doesn't exist on Windows | Easy — skip on Windows |
| Harvest API 404 | 2 | 0 | API routes not registered in test app | Medium — check route registration |
| Source code assertion mismatch | 1 | 0 | Expected string refactored out of source | Easy — update assertion |
| TLS verification source read | 1 | 0 | GBK encoding error reading config source | Easy — add `encoding="utf-8"` |

### 6.2 Detailed Failure List

#### Category 1: Windows PermissionError [WinError 32] — 13 failures + 50 errors

**Root cause**: SQLite database files in temp directories cannot be deleted during `TemporaryDirectory.__exit__()` because unclosed `sqlite3.Connection` objects hold file locks on Windows. This is a Windows-specific issue — on Linux, file deletion succeeds even with open file handles.

**Failed tests (13)**:
- `tests/integration/test_api_memories_chronological.py` (7 tests) — PermissionError during tempdir cleanup
- `tests/test_quality_system.py::TestQualityAPILayer` (6 tests) — PermissionError during tempdir cleanup

**Errored tests (50)** — all at teardown:
- `tests/integration/test_api_with_memory_service.py` (5 errors)
- `tests/storage/test_graph_distribution.py` (18 errors)
- `tests/storage/test_hybrid_graph_methods.py` (11 errors)
- `tests/test_hybrid_storage.py` (1 error)
- `tests/test_issue_396.py` (2 errors)
- `tests/test_quality_system.py` (1 error)
- `tests/web/api/test_analytics_graph.py` (12 errors)

**Fix**: Ensure `storage.close()` is awaited before temp directory cleanup. Tests calling `storage.close()` synchronously on async storage mixins leave connections open.

---

#### Category 2: Windows GBK Encoding Error — 16 failures

**Root cause**: On zh-CN Windows, Python's default encoding is GBK. `pathlib.Path.read_text()` and `subprocess.run().stdout` use the system default encoding. Source files contain UTF-8 characters (em-dashes —, smart quotes, etc.) that fail to decode as GBK.

**Affected tests**:
- `tests/integration/test_cli_interfaces.py` (11 failures) — subprocess stdout decoded as GBK
- `tests/web/api/test_health_info_disclosure.py` (4 failures) — `pathlib.Path.read_text()` on source files
- `tests/unit/test_imports.py::test_server_impl_imports` (1 failure) — `open().read()` without encoding

**Fix**: Add `encoding="utf-8"` to all `read_text()` and `open()` calls in tests. For subprocess, use `text=True, encoding="utf-8"` or `capture_output=True` with manual UTF-8 decoding.

---

#### Category 3: OAuth sqlite3.Row.get() AttributeError — 7 failures

**Root cause**: `web/oauth/storage/sqlite.py:482` calls `row.get("code_challenge", None)` on a `sqlite3.Row` object. `sqlite3.Row` does not have a `.get()` method — that's a `dict` method. The code should use `row["code_challenge"]` with a try/except or key check.

**Affected tests** (all in `tests/unit/test_oauth_storage_backends.py`):
- `test_store_and_get_authorization_code[sqlite]`
- `test_authorization_code_one_time_use[sqlite]`
- `test_cleanup_expired[sqlite]`
- `test_concurrent_code_consumption[sqlite]`
- `test_persistence_across_connections`
- `test_store_and_get_authorization_code_with_pkce[sqlite]`
- `test_authorization_code_without_pkce[sqlite]`

**Fix**: Replace `row.get("key", default)` with `row["key"] if "key" in row.keys() else default` or convert Row to dict first.

---

#### Category 4: CLI `uv run` Not Available — 11 failures

**Root cause**: `tests/integration/test_cli_interfaces.py` runs commands via `subprocess.run(["uv", "run", "memory", ...])`. The `uv` tool is not installed or not on PATH. Return code is 1 instead of expected 0.

**Affected tests** (all in `tests/integration/test_cli_interfaces.py`):
- `TestCLIInterfaces::test_memory_command_exists`
- `TestCLIInterfaces::test_memory_server_command_exists`
- `TestCLIInterfaces::test_memory_server_version_flag`
- `TestCLIInterfaces::test_memory_server_vs_memory_server_subcommand`
- `TestCLIInterfaces::test_argument_compatibility`
- `TestCLIFunctionality::test_memory_status_command`
- `TestCLIRobustness::test_environment_variable_passing`
- `TestCLIRobustness::test_cli_error_handling`
- `TestCLIRobustness::test_memory_server_argument_parity`
- `TestCLIPerformance::test_cli_startup_time`
- `TestCLIPerformance::test_memory_version_performance`

**Fix**: Install `uv` or mock the subprocess calls. Alternatively, use `memory` directly instead of `uv run memory`.

---

#### Category 5: CLI Status Embedding Empty Output — 3 failures

**Root cause**: `tests/unit/test_cli_status_embedding.py` expects "EXIT 1" or "Deep round-trip smoke test" in stdout, but the CLI produces empty output. The `memory status` command likely fails silently.

**Affected tests**:
- `test_status_reports_degraded_hash_backend_and_exits_1`
- `test_status_detects_dimension_mismatch_and_exits_1`
- `test_status_deep_round_trip_reports_each_step`

---

#### Category 6: FastAPI Router API Change — 1 failure

**Root cause**: `tests/integration/test_http_server_startup.py:65` does `route.path for route in app.routes` but FastAPI now returns `_IncludedRouter` objects that don't have a `.path` attribute.

**Fix**: Filter routes by type or use `getattr(route, 'path', None)`.

---

#### Category 7: Unix-Only signal.SIGKILL — 1 failure

**Root cause**: `scripts/run/memory_wrapper_cleanup.py:145` uses `signal.SIGKILL` which doesn't exist on Windows.

**Fix**: Use `signal.SIGTERM` on Windows or skip the test with `@pytest.mark.skipif(sys.platform == 'win32')`.

---

#### Category 8: Harvest API 404 — 2 failures

**Root cause**: `tests/web/api/test_harvest_api.py` expects HTTP 200/500 but gets 404, indicating harvest routes are not registered in the test FastAPI app.

**Affected tests**:
- `test_harvest_dry_run_happy_path` — assert 404 == 200
- `test_harvest_propagates_harvester_failure_as_500` — assert 404 == 500

---

#### Category 9: Source Code Assertion Mismatch — 1 failure

**Root cause**: `tests/test_issues_603_to_608.py:204` asserts `"hasattr(self.embedding_model, 'embedding_dimension')"` is in source code, but the code has been refactored and this pattern no longer exists.

---

#### Category 10: TLS Verification Source Read — 1 failure

**Root cause**: `tests/discovery/test_tls_verification.py:87` calls `config_path.read_text()` without `encoding="utf-8"`, fails with GBK UnicodeDecodeError.

---

## 7. Git-Tracked __pycache__/*.pyc Files

**Result: ✅ None found.**

```
$ git ls-files "*.pyc" "__pycache__/*"
(empty)
```

No `.pyc` or `__pycache__` files are tracked by git. The `.gitignore` properly excludes these. No `git rm --cached` cleanup needed.

---

## 8. Test Configuration Notes

| Config File | Key Settings |
|-------------|-------------|
| `pytest.ini` | `asyncio_mode = auto`, `testpaths = tests`, `--import-mode=prepend` |
| `.coveragerc` | `source = src/mcp_memory_service`, ~50 files omitted, `show_missing = true` |
| `pyproject.toml` | `[project.scripts]`: `memory`, `memory-server`, `mcp-memory-server` |

### Environment Variables Used
- `MCP_MEMORY_STORAGE_BACKEND=sqlite_vec` (forced for tests)
- `MCP_TEST_ALLOW_CLOUD_BACKEND=false` (no cloud tests)

### Python Version Note
Tests were run with **Python 3.14.2** (system Python, no project venv available in worktree). The project targets Python 3.10+. Python 3.14 introduces deprecation warnings for `asyncio.iscoroutinefunction` (slated for removal in 3.16) and `datetime.utcfromtimestamp()`.

---

## 9. Recommendations

### P0 — Fix Immediately
1. **OAuth sqlite3.Row.get()** — 7 failures, production bug. Replace `.get()` with proper Row access.
2. **GBK encoding in tests** — 16 failures. Add `encoding="utf-8"` to all `read_text()` and subprocess calls.
3. **Windows temp DB cleanup** — 63 failures+errors. Await `storage.close()` before `TemporaryDirectory.__exit__()`.

### P1 — Fix Soon
4. **CLI `uv run` dependency** — 11 failures. Either install `uv` in CI or switch to `python -m mcp_memory_service.cli.main`.
5. **FastAPI router API** — 1 failure. Adapt to new FastAPI version's router structure.
6. **Harvest API 404** — 2 failures. Ensure routes are registered in test app.
7. **signal.SIGKILL on Windows** — 1 failure. Add platform skip.

### P2 — Improve Coverage
8. **`server/handlers/documents.py`** (6.09%) — Add document ingestion handler tests.
9. **`quality/onnx_ranker.py`** (18.79%) — Add ONNX ranker model tests.
10. **`storage/factory.py`** (27.94%) — Test factory branches for all backends.
11. **`server/environment.py`** (25.53%) — Add environment setup tests.
12. **`quality/ai_evaluator.py`** (40.00%) — Mock Groq/Gemini API calls.
13. **`lm_studio_compat.py`** (37.21%) — Add LM Studio compatibility tests.
14. **`server/handlers/consolidation.py`** (37.34%) — Add consolidation handler tests.
15. **Omitted modules** (~50 files) — Prioritize `web/api/*`, `cli/*`, `ingestion/*` for test coverage.
