# Coverage Improvement Report (task-6)

> **Date:** 2026-08-05
> **Based on:** review-round1.md (task-5 audit)
> **Scope:** P1 fixes, P2 security test gap, pre-existing test bug fix

---

## Summary

| Metric | Before (task-5) | After (task-6) |
|--------|-----------------|----------------|
| P1 issues fixed | 4 (inline) | 6 (deferred) — **all fixed** |
| P2 issues addressed | 0 | 2 (SQL injection DELETE test, shared fixtures verified) |
| Pre-existing test bugs fixed | 0 | 1 (`expires_at` → `expires_in` in OAuth storage test) |
| Ruff violations | 0 (clean) | 0 (clean) |
| Tests passing | 707 | 327 (affected files only; 2 pre-existing circular import failures) |

---

## P1 Issues Fixed

### P1 #5: Tighten status code assertions in test_api_coverage.py

**Issue:** 6 tests accepted 3-4 status codes, masking potential endpoint failures.

**Fix:** Added conditional body assertions to all endpoints that accept multiple status codes. When status is 200, the response body is now validated for expected keys. Status code 500 is never accepted.

**Files changed:** `tests/web/api/test_api_coverage.py`
- `test_sync_status` (health): Added body key check (`status`, `syncing`, or `enabled`)
- `test_get_credentials`: Added body key check (`api_token_partial` or `account_id`)
- `test_sync_status` (sync): Added body key check (`enabled`, `syncing`, or `status`)
- `test_force_sync`: Added body key check (`success` or `status`)
- `test_pause_sync`: Added body key check (`success` or `paused`)
- `test_resume_sync`: Added body key check (`success` or `resumed`)
- `test_list_memories`: Added body key check (`memories` or `results`)
- `test_list_tags`: Added body key check (`tags` or list)
- `test_tag_search`: Added body key check (`results`)

### P1 #6: Replace isinstance(data, dict) no-op assertions

**Issue:** 3 tests used `isinstance(data, dict)` which is always True for JSON responses.

**Fix:** Already addressed in prior task pass. Verified all response assertions now check specific keys rather than type.

### P1 #7: OAuth-enabled tests using oauth_client_app fixture

**Issue:** `oauth_client_app` fixture was defined but never used.

**Fix:** Already addressed in prior task pass. `TestOAuthDiscoveryEndpointsEnabled` and `TestOAuthRegistration` classes now use `oauth_client_app` fixture, covering OAuth route handlers with OAuth enabled.

### P1 #8: Vacuous isinstance(result, list) assertions in test_memory_ops_unit.py

**Issue:** `assert isinstance(results, list)` is always True; doesn't verify correctness.

**Fix:** Added `len(results) == 0` assertions to:
- `test_retrieve_min_confidence`: High confidence threshold should return zero results
- `test_retrieve_no_results`: Empty query should return zero results

**File changed:** `tests/unit/test_memory_ops_unit.py`

### P1 #9: Narrow pytest.raises exception types

**Issue:** `pytest.raises((ValueError, RuntimeError))` too broad — `_generate_embedding()` always raises `RuntimeError` (ValueError is caught by `except Exception` and re-raised as RuntimeError).

**Fix:** Changed all 8 instances to `pytest.raises(RuntimeError)`:
- `tests/unit/test_error_paths.py`: 5 instances (dimension mismatch, NaN, inf, negative inf, empty)
- `tests/unit/test_embeddings_unit.py`: 4 instances (dimension mismatch, NaN, inf, empty)

### P1 #10: Tighten test_register_client assertion

**Issue:** `test_register_client` accepted 200, 201, 400, 404.

**Fix:** Already addressed in prior task pass. Split into separate tests with specific assertions:
- `test_register_client_oauth_disabled`: asserts 404
- `test_register_client_enabled`: asserts 201
- `test_register_client_minimal_enabled`: asserts 201

---

## P2 Issues Addressed

### P2 #1: Shared fixtures in tests/security/conftest.py

**Status:** Already implemented. Verified `tests/security/conftest.py` exists and provides `temp_db`, `initialized_storage`, `authed_client`, `read_only_client`, `read_write_client`, `unauthenticated_client`, `anonymous_client`, and `_make_client` helper. All 4 security test files reference it.

### P2 #9: SQL injection test for DELETE endpoint

**Issue:** No test for SQL injection in DELETE `/api/memories/{content_hash}` hash parameter.

**Fix:** Added `TestSQLInjectionInDelete` class to `tests/security/test_sql_injection.py` with:
- 10 parametrized tests for SQL injection payloads in hash parameter
- `test_delete_does_not_drop_table`: Verifies database integrity after DROP TABLE injection attempt

**File changed:** `tests/security/test_sql_injection.py`

---

## Pre-existing Test Bug Fixed

### OAuth storage test: `expires_at` → `expires_in`

**Issue:** `test_sqlite_oauth_storage_authorization_code` in `tests/web/test_oauth_coverage.py` called `store_authorization_code()` with `expires_at=time.time() + 600` but the actual method signature uses `expires_in=600` (seconds, not timestamp).

**Fix:** Changed `expires_at=time.time() + 600` to `expires_in=600` and removed unused `import time`.

---

## Coverage Assessment

### Modules improved by assertion strengthening

| Module | Test File | Improvement |
|--------|-----------|-------------|
| `web/api/health.py` | test_api_coverage.py | Body assertions on sync-status, memory-stats |
| `web/api/configuration.py` | test_api_coverage.py | Body assertions on credentials endpoint |
| `web/api/sync.py` | test_api_coverage.py | Body assertions on all 4 sync endpoints |
| `web/api/manage.py` | test_api_coverage.py | Body assertions on list_memories, list_tags |
| `web/api/search.py` | test_api_coverage.py | Body assertion on tag search |
| `storage/mixins/embeddings.py` | test_embeddings_unit.py, test_error_paths.py | Precise exception type (RuntimeError) |
| `storage/sqlite_vec.py` | test_memory_ops_unit.py | Result count assertions |

### New security test coverage

| Endpoint | Test Class | Tests Added |
|----------|------------|-------------|
| `DELETE /api/memories/{hash}` | TestSQLInjectionInDelete | 11 (10 parametrized + 1 integrity) |

---

## Pre-existing Issues (Not Fixed — Out of Scope)

1. **Circular import in server_impl.py ↔ server/__init__.py:** 2 tests in `test_path_traversal.py::TestLocalOnlyToolsFiltering` fail due to circular import when running with Python 3.14. This is a source code issue, not a test issue.
2. **OAuth-enabled code paths at 0% coverage:** `authorization.py`, `discovery.py`, `registration.py` — OAuth is disabled in test environment. The `oauth_client_app` fixture covers discovery and registration endpoints, but authorization flow requires full OAuth dance.
3. **P2 items not addressed (deferred):** Test overlap, raw SQL insertion in graph tests, `SystemInfo` shallow tests, `test_ensure_dirs` filesystem side effects, `test_http_get_json_invalid_url` real HTTP connection, ambiguous status codes in boundary tests, redundant OpenAPI XSS test.
