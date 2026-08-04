# TODO Tracker

**Last Updated:** 2026-08-04
**Scan Directory:** src
**Total TODOs:** 5

## Summary

| Priority | Count | Description |
|----------|-------|-------------|
| CRITICAL (P0) | 0 | Security, data corruption, blocking bugs |
| HIGH (P1) | 2 | Performance, user-facing, incomplete features |
| MEDIUM (P2) | 2 | Code quality, optimizations, technical debt |
| LOW (P3) | 1 | Documentation, cosmetic, nice-to-haves |

---

## CRITICAL (P0)
*(None in this list)*

**Resolved:**
- ~~`src/mcp_memory_service/web/api/analytics.py` - Period filtering is not implemented~~ — Period filtering IS implemented (see `days` parameter in top-tags endpoint, L935-937). This TODO no longer exists in the codebase.

---

## HIGH (P1)
- `src/mcp_memory_service/storage/cloudflare.py:278` - Lack of a fallback for embedding generation makes the service vulnerable to external API failures.
- `src/mcp_memory_service/web/api/manage.py:398` - Inefficient queries can cause significant performance bottlenecks, especially with large datasets. (cont-3 intended to fix via `get_tag_statistics()` but changes were not merged)

---

## MEDIUM (P2)
- `src/mcp_memory_service/web/api/documents.py:640` - Using a deprecated FastAPI event handler (`@router.on_event("startup")`); should be migrated to the modern `lifespan` context manager to reduce technical debt. (cont-1 intended to migrate but changes were not merged)
- `src/mcp_memory_service/web/api/analytics.py:435` - The `storage.get_stats()` method is missing a `memories_this_month` data point, leading to API inconsistency. Current code uses inefficient `get_recent_memories(n=5000)` loop as workaround. (cont-2 intended to fix but changes were not merged)

---

## LOW (P3)
- `src/mcp_memory_service/quality/ai_evaluator.py:485` - TODO: use `_create_scoring_prompt(query, memory.content)` to handle empty queries.

---

## How to Address

1. **CRITICAL**: Address immediately, block releases if necessary
2. **HIGH**: Schedule for current/next sprint
3. **MEDIUM**: Add to backlog, address in refactoring sprints
4. **LOW**: Address opportunistically or when touching related code

## Updating This Tracker

Run: `bash scripts/maintenance/scan_todos.sh`
