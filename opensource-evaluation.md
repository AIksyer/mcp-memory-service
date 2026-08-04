# mcp-memory-service — GitHub Open-Source Readiness Evaluation

> **Evaluator:** Codely Overnight Executor (automated)
> **Date:** 2026-08-04
> **Version evaluated:** v11.5.5
> **Repository:** codeberg.org:doobidoo/mcp-memory-service (upstream) / github.com:AIksyer/mcp-memory-service (fork)
> **Scope:** License compliance, security, documentation, CI/CD, code quality, upstream divergence, GitHub-specific readiness

---

## Executive Summary

The project is a mature, well-architected Python package with 213 source files, ~2,400 tests, 76+ REST API endpoints, MCP protocol support, and comprehensive documentation. The codebase demonstrates strong engineering practices (parameterized SQL, path traversal protection, confused-deputy guards, log injection sanitization).

**However**, one P0 security issue (embedded GitHub PAT in git remote URL) must be resolved before any public release. Several P1 issues (missing derivative-work declaration, stale NOTICE file, no GitHub Actions CI, Codeberg references in GitHub-facing files) need attention for a polished GitHub release.

**Conclusion: Basic readiness — fix P0 + key P1 items to reach "Ready".**

---

## Dimension Scores

| Dimension | Score (1-10) | Summary |
|-----------|:---:|---------|
| License Compliance | 7/10 | Apache 2.0 full text + headers present; NOTICE file has inaccuracies; no derivative-work declaration |
| Security | 6/10 | Strong code-level security; P0: PAT token in git remote; no mypy/pre-commit for type safety |
| Documentation Quality | 8/10 | 151+ docs, comprehensive README; Codeberg URLs need updating for GitHub audience |
| CI/CD Readiness | 5/10 | Forgejo Actions exist but no GitHub Actions workflows; pre-PR gate is excellent |
| Code Quality | 7/10 | ruff configured, ~81% return type annotations; no mypy, no pre-commit hooks |
| Upstream Compliance | 6/10 | Clean orphan history; but no fork attribution, stale NOTICE contributors |
| **Overall** | **6.5/10** | **Basic readiness — needs P0 fix + P1 polish** |

---

## 1. Apache 2.0 License Compliance

### 1.1 LICENSE File

| Check | Status | Detail |
|-------|:------:|--------|
| Full Apache 2.0 text | ✅ | 201 lines, complete TERMS AND CONDITIONS + APPENDIX |
| Copyright notice | ✅ | `Copyright 2024 Heinrich Krupp` |
| No modifications from upstream | ✅ | Standard Apache 2.0 boilerplate, unmodified |
| `license` field in pyproject.toml | ✅ | `license = { text = "Apache-2.0" }` |
| Classifier in pyproject.toml | ✅ | `License :: OSI Approved :: Apache Software License` |

### 1.2 NOTICE File

| Check | Status | Detail |
|-------|:------:|--------|
| File exists | ✅ | Root NOTICE file present |
| Copyright holder identified | ✅ | `Copyright 2024 Heinrich Krupp` |
| Third-party licenses listed | ⚠️ | See issues below |

**NOTICE file issues (P1):**
- Lists **ChromaDB** — this dependency is NOT used anywhere in `pyproject.toml` or source code. It appears to be a leftover from an earlier version. Remove it.
- Lists **sentence-transformers** and **PyTorch** as core dependencies — they are optional (`[ml]` extras), not required. The NOTICE should distinguish core vs optional.
- Missing **authlib** (BSD), **cryptography** (Apache-2.0 OR BSD-3-Clause), **PyJWT** (MIT), **pypdf** (BSD-3-Clause), **zeroconf** (LGPL\*) — all are core dependencies not listed.
  - ⚠️ **LGPL concern:** `zeroconf` is LGPL-licensed. While LGPL is compatible with Apache 2.0 for dynamic linking, Python packages using it should be noted. LGPL does NOT impose copyleft on the consuming project when used as a library (which is the case here), but it should be disclosed.
- Missing **apscheduler** (Apache 2.0), **uvicorn** (BSD-3-Clause), **sse-starlette** (MIT) — core dependencies.

### 1.3 Source File Copyright Headers

| Check | Status | Detail |
|-------|:------:|--------|
| Copyright headers present | ✅ | 121/121 .py files with `Copyright` keyword found |
| Apache boilerplate in headers | ✅ | Standard `Licensed under the Apache License, Version 2.0` header |
| Format consistency | ✅ | All use `# Copyright 2024 Heinrich Krupp` + license boilerplate |

Sample verified files: `__init__.py`, `server_impl.py`, `storage/base.py`, `web/app.py`, `embeddings/onnx_embeddings.py` — all have correct headers.

### 1.4 Modification Attribution (Apache 2.0 §4(b))

| Check | Status | Detail |
|-------|:------:|--------|
| Derivative work declaration | ❌ | No "This project is a derivative of..." statement in README or NOTICE |
| CHANGELOG tracks modifications | ✅ | CHANGELOG.md present, extensive version history |
| File-level modification notes | ⚠️ | No per-file "modified from upstream" annotations |

**Note:** This project is the upstream itself (codeberg.org/doobidoo/mcp-memory-service). The GitHub repo (AIksyer/mcp-memory-service) is a mirror/fork. If the GitHub repo is intended as a separate fork with modifications, it should declare the derivative relationship. If it's a pure mirror, the attribution issue is less critical but still recommended for clarity.

### 1.5 Third-Party Dependency License Compatibility

Core dependencies (from `pyproject.toml`):

| Dependency | License | Apache 2.0 Compatible |
|-----------|---------|:---------------------:|
| aiofiles | Apache 2.0 | ✅ |
| aiohttp | Apache 2.0 | ✅ |
| aiosqlite | MIT | ✅ |
| apscheduler | Apache 2.0 | ✅ |
| authlib | BSD-3-Clause | ✅ |
| build | MIT | ✅ |
| chardet | LGPL-2.1 | ⚠️ (see below) |
| click | BSD-3-Clause | ✅ |
| cryptography | Apache-2.0 OR BSD-3-Clause | ✅ |
| fastapi | MIT | ✅ |
| httpx | BSD-3-Clause | ✅ |
| mcp | MIT | ✅ |
| numpy | BSD-3-Clause | ✅ |
| psutil | BSD-3-Clause | ✅ |
| PyJWT | MIT | ✅ |
| pypdf | BSD-3-Clause | ✅ |
| PyYAML | MIT | ✅ |
| python-dotenv | BSD-3-Clause | ✅ |
| python-multipart | Apache 2.0 | ✅ |
| requests | Apache 2.0 | ✅ |
| sqlite-vec | MIT | ✅ |
| sse-starlette | MIT | ✅ |
| uvicorn | BSD-3-Clause | ✅ |
| zeroconf | LGPL | ⚠️ (see below) |

**LGPL dependencies (P2):** `chardet` (LGPL-2.1) and `zeroconf` (LGPL) are included. LGPL is compatible with Apache 2.0 when used as a library (dynamic linking), which is the case for Python packages. However:
- These should be explicitly disclosed in the NOTICE file
- `chardet` could potentially be replaced with `charset-normalizer` (MIT) to avoid LGPL entirely
- `zeroconf` is used for mDNS service discovery and could be made optional

### License Compliance Score: 7/10

**Issues:**
- P1: NOTICE file lists unused dependency (ChromaDB) and omits 8+ actual core dependencies
- P1: No derivative-work / fork attribution statement (if applicable)
- P2: Two LGPL dependencies not disclosed in NOTICE file

---

## 2. Security Audit

### 2.1 Hardcoded Secrets Scan

| Check | Status | Detail |
|-------|:------:|--------|
| Source code scan | ✅ | No hardcoded passwords, secrets, API keys, or tokens in `src/` |
| Only match: `client_secret="[REDACTED]"` | ✅ | In `oauth/registration.py` L245 — placeholder, not a real secret |
| `.env` file tracked in git | ✅ Not tracked | `.env` is in `.gitignore` |
| `.env.example` values | ✅ Safe | All values are placeholders (`your-cloudflare-api-token-here`, etc.) |
| Git history secrets scan | ✅ Clean | `git log --all -p` scan found no leaked credentials |

### 2.2 🔴 P0: GitHub PAT Token in Git Remote URL

```
github  https://AIksyer:REDACTED_GITHUB_TOKEN@github.com/AIksyer/mcp-memory-service.git
```

**Severity: P0 — CRITICAL**

The git remote `github` contains an embedded GitHub Personal Access Token (`gho_...`). This token:
- Is visible to anyone who runs `git remote -v` in this repo
- Grants read/write access to the `AIksyer/mcp-memory-service` GitHub repository
- If committed to `.git/config`, persists across clones

**Remediation:**
1. **Immediately revoke** this token at https://github.com/settings/tokens
2. Update the remote to remove credentials: `git remote set-url github https://github.com/AIksyer/mcp-memory-service.git`
3. Use SSH or a credential helper instead of URL-embedded tokens
4. Audit git history to ensure `.git/config` was never committed

### 2.3 Security Configuration

| Check | Status | Detail |
|-------|:------:|--------|
| `DEBUG=True` default | ✅ Safe | No `DEBUG=True` in defaults; debug mode is opt-in |
| CORS configuration | ✅ Safe | Defaults to `http://localhost:8000,http://127.0.0.1:8000` (not `*`); warns when wildcard is used |
| `allow_credentials` with `*` | ✅ Safe | `allow_credentials="*" not in CORS_ORIGINS` — credentials only enabled when origins are specific |
| OAuth default config | ✅ Safe | `MCP_OAUTH_ENABLED=false` by default; `MCP_ALLOW_ANONYMOUS_ACCESS` commented out (defaults to false) |
| `MCP_MEMORY_ALLOW_HASH_EMBEDDINGS` | ✅ Safe | Defaults to empty (unset); refuses hash embeddings when DB has existing memories; only allows on empty DB |
| API key auth | ✅ Optional | `MCP_API_KEY` defaults to `None` — auth disabled by default for local dev |
| Body size limits | ✅ | `MCP_HTTP_MAX_BODY_BYTES=1048576` (1MB), `MCP_OAUTH_MAX_BODY_BYTES=65536` (64KB) |
| Rate limiting | ✅ | OAuth endpoints rate-limited (`MCP_OAUTH_RATE_LIMIT_PER_MINUTE=60`) |

### 2.4 SQL Injection

| Check | Status | Detail |
|-------|:------:|--------|
| Parameterized queries | ✅ | All SQL uses `?` placeholders with values passed separately |
| f-string SQL patterns | ✅ Safe | f-strings only build placeholder lists (`{placeholders}`) and condition patterns (`{conditions}`), never inject user data |
| Verified files | ✅ | `storage/mixins/delete.py`, `storage/cloudflare.py`, `web/oauth/storage/sqlite.py` — all safe |

### 2.5 Path Traversal

| Check | Status | Detail |
|-------|:------:|--------|
| Tar extraction | ✅ Protected | `_safe_tar_extract()` in `onnx_embeddings.py` validates `realpath` stays within target |
| File path handling | ✅ | No `os.path.join` with user input containing `../` |
| Confused-deputy guard | ✅ | `local_only_tools()` in `server_impl.py` filters filesystem-reading tools from remote transport |
| HTTP MCP shim enforcement | ✅ | `web/api/mcp.py` rejects `tools/call` for local-only tools over HTTP |

### 2.6 SSRF Risk

| Check | Status | Detail |
|-------|:------:|--------|
| External embedding API URL | ⚠️ Low risk | URL is admin-configured via env var (`MCP_EXTERNAL_EMBEDDING_URL`), not user-controlled. No URL validation/scheme checking. An attacker with env access could point to internal services, but this is a standard admin trust model. |
| Cloudflare API calls | ✅ | URLs are constructed from account-scoped config, not user input |

### 2.7 XSS Risk

| Check | Status | Detail |
|-------|:------:|--------|
| API Content-Type headers | ✅ | FastAPI auto-sets `application/json` for API responses |
| Dashboard static files | ✅ | Dashboard JS is served as static assets, not user-generated HTML |
| SECURITY.md mentions XSS | ✅ | "All user input is escaped before rendering" |
| CodeQL XSS queries | ✅ | CodeQL config includes `security-and-quality` suite |

### 2.8 Log Injection

| Check | Status | Detail |
|-------|:------:|--------|
| `_sanitize_log_value()` | ✅ | Implemented in `compat.py`, used throughout codebase |
| AUTHORSHIP.md documents this | ✅ | "user-provided values are sanitized via `_sanitize_log_value()` before logging" |

### Security Score: 6/10

**Issues:**
- P0: GitHub PAT token embedded in git remote URL (CRITICAL)
- P2: No SSRF validation on external embedding API URL (low risk — admin-configured)

---

## 3. Documentation Quality

### 3.1 README.md Assessment

| Section | Status | Detail |
|---------|:------:|--------|
| Project description | ✅ | Clear, compelling intro with comparison table |
| Installation steps | ✅ | `pip install` + client config (Claude Desktop, Claude Code, etc.) |
| Usage examples | ✅ | Multiple client integrations shown |
| Configuration | ✅ | Comprehensive `.env.example` with 200+ documented variables |
| API documentation | ✅ | FastAPI auto-docs at `/api/docs`, wiki reference |
| Architecture docs | ✅ | `docs/architecture.md` + `docs/mastery/architecture-overview.md` |
| Badges | ✅ | License, PyPI, Python, Codeberg stars, framework compatibility |
| GitHub-friendly badges | ⚠️ | Codeberg star badge instead of GitHub stars; no GitHub Actions CI badge |
| Clone URL | ⚠️ | Points to `codeberg.org/doobidoo/mcp-memory-service.git` |
| Release notes | ✅ | Detailed v11.x release notes in README + CHANGELOG.md |
| Contributing link | ✅ | Links to CONTRIBUTING.md |

**README issues (P1 for GitHub):**
- Clone URL is `https://codeberg.org/doobidoo/mcp-memory-service.git` — should be updated to GitHub URL for the fork
- Star badge is Codeberg, not GitHub
- No GitHub Actions CI badge (because no GitHub Actions workflows exist)
- Links to Codeberg wiki (`https://codeberg.org/doobidoo/mcp-memory-service/wiki`) — GitHub users expect GitHub wiki or Discussions
- "All Releases" links to Codeberg releases page

### 3.2 Documentation Depth

| Metric | Count |
|--------|-------|
| `docs/*.md` files | 151+ |
| Tutorials | 3 (demo walkthrough, data analysis, advanced techniques) |
| Troubleshooting guides | 11 |
| Setup guides | 5+ (setup-guide, quick-setup, first-time-setup, etc.) |
| Architecture docs | 2 (architecture.md, mastery/architecture-overview.md) |
| Integration guides | 15+ (LangGraph, CrewAI, AutoGen, Claude, Cursor, OpenCode, etc.) |
| API reference | FastAPI auto-gen `/api/docs` + wiki |
| Configuration guide | `docs/mastery/configuration-guide.md` (comprehensive) |

### 3.3 Code Comments Quality

Spot-checked 5 core modules:

| File | Quality | Detail |
|------|:-------:|--------|
| `server_impl.py` | Good | Module docstring, method docstrings with Google style, inline comments for complex logic |
| `storage/base.py` | Good | Abstract methods documented with Args/Returns/Raises sections |
| `web/app.py` | Good | Startup sequence commented, middleware rationale explained |
| `embeddings/onnx_embeddings.py` | Good | `_safe_tar_extract` has security rationale comment |
| `storage/mixins/embeddings.py` | Good | Hash embedding fallback policy thoroughly documented |

### 3.4 GitHub-Specific Documentation

| File | Status | Detail |
|------|:------:|--------|
| `CONTRIBUTING.md` | ✅ | 473 lines, comprehensive; references "Fork on GitHub" (good for GitHub) |
| `CODE_OF_CONDUCT.md` | ✅ | Present |
| `SECURITY.md` | ✅ | Detailed policy with severity classification, response timeline |
| `AUTHORSHIP.md` | ✅ | Clear authorship and governance statement |
| GitHub Discussions config | ⚠️ | ISSUE_TEMPLATE/config.yml references `github.com/doobidoo/mcp-memory-service/discussions` — should be `AIksyer` |
| GitHub Wiki | ❌ | No GitHub wiki content (docs are in `docs/` directory) |

### Documentation Score: 8/10

**Issues:**
- P1: README clone URL, badges, and links point to Codeberg, not GitHub
- P1: ISSUE_TEMPLATE config.yml references wrong GitHub user (`doobidoo` instead of `AIksyer`)
- P2: No GitHub Discussions template or categories configuration
- P2: Consider adding a GitHub Pages site (site/ directory has landing page content)

---

## 4. CI/CD Readiness

### 4.1 Existing CI (Forgejo Actions)

| Workflow | File | Purpose |
|----------|------|---------|
| CI | `.forgejo/workflows/ci.yml` | Tests + coverage, version drift check |
| Release | `.forgejo/workflows/release.yml` | PyPI publish (main + lite), Docker Hub push |
| Deploy Site | `.forgejo/workflows/deploy-site.yml` | Cloudflare Pages deploy |
| Cleanup | `.forgejo/workflows/cleanup-images.yml` | Docker image cleanup |

**CI workflow analysis:**
- Test job: `pytest tests/ --ignore=tests/consolidation --ignore=tests/benchmarks --ignore=tests/integration -m "not benchmark" --cov=mcp_memory_service`
- Runs on `docker` runner (self-hosted)
- Uses Forgejo action mirror (`data.forgejo.org/actions/checkout@v4.4.0`)
- 20-minute timeout
- No coverage gate (commented out — "re-introduce once baseline is stable")

### 4.2 GitHub Actions Migration

| Check | Status | Detail |
|-------|:------:|--------|
| `.github/workflows/` directory | ❌ | Does not exist — no GitHub Actions workflows |
| Migration feasibility | ✅ High | Forgejo Actions uses GitHub Actions-compatible syntax; migration is straightforward |
| Action references | ⚠️ | Forgejo workflows use `https://data.forgejo.org/actions/checkout@...` — need to change to `actions/checkout@v4` for GitHub |
| Runner labels | ⚠️ | `runs-on: docker` → `runs-on: ubuntu-latest` |

**Migration steps needed:**
1. Create `.github/workflows/ci.yml` — adapt from `.forgejo/workflows/ci.yml`
2. Create `.github/workflows/release.yml` — adapt for GitHub Releases (use `softprops/action-gh-release`)
3. Replace Forgejo action references with standard GitHub Actions
4. Change runner labels from `docker` to `ubuntu-latest`
5. Set up GitHub secrets (`PYPI_TOKEN`, `DOCKER_USERNAME`, `DOCKER_PASSWORD`)

### 4.3 Pre-PR Quality Gate

| Check | Status | Detail |
|-------|:------:|--------|
| `scripts/pr/pre_pr_check.sh` exists | ✅ | 283-line comprehensive script |
| Staged files check | ✅ | Ensures files are staged before PR |
| Quality gate (complexity, security) | ✅ | Runs `quality_gate.sh --staged --with-pyscn` |
| Test suite with coverage | ✅ | Runs pytest with `--cov`, 80% threshold |
| Handler coverage check | ✅ | Verifies all 17 MCP handlers are tested |
| Import validation | ✅ | Regression check for import issues |
| Reusable on GitHub Actions | ✅ | Bash script, platform-independent |

### 4.4 Coverage Reporting

| Check | Status | Detail |
|-------|:------:|--------|
| `.coveragerc` exists | ✅ | Comprehensive omit list, precision=2, show_missing=true |
| Coverage in CI | ✅ | `--cov-report=term-missing:skip-covered` |
| Codecov/Coveralls integration | ❌ | Not configured |
| Coverage badge | ❌ | Not in README |

### 4.5 Pre-commit Hooks

| Check | Status | Detail |
|-------|:------:|--------|
| `.pre-commit-config.yaml` | ❌ | Does not exist |

**Recommendation:** Add `.pre-commit-config.yaml` with ruff, black, and basic checks. The `pre_pr_check.sh` is a good fallback but doesn't catch issues at commit time.

### CI/CD Score: 5/10

**Issues:**
- P1: No GitHub Actions workflows — must create `.github/workflows/ci.yml` for GitHub
- P1: No `.github/workflows/release.yml` for GitHub Releases
- P1: Action references use Forgejo mirrors, need standard GitHub Actions
- P2: No Codecov/Coveralls integration
- P2: No pre-commit hooks configuration

---

## 5. Code Quality

### 5.1 Linting & Formatting

| Tool | Configured | Detail |
|------|:----------:|--------|
| ruff | ✅ | `pyproject.toml [tool.ruff]` — line-length=88, target=py310 |
| ruff rules | ✅ | E, W, F, I, UP, RUF, B, C4, SIM selected; sensible ignores (E501, E203, E402, B008) |
| ruff format | ✅ | quote-style=double, indent-style=space |
| black | ✅ | Listed in dev dependencies; line length 88 (implicit from ruff) |
| mypy | ❌ | Not configured anywhere; not in dependencies |

**ruff configuration quality:** Good. Ruleset is comprehensive, per-file ignores for `__init__.py` and tests are appropriate. The ignore list is well-reasoned (FastAPI Depends pattern, async shutdown patterns).

### 5.2 Type Annotation Coverage

| Metric | Value |
|--------|-------|
| Total function definitions | 1,848 |
| Functions without return type annotation | 345 (18.6%) |
| Functions with return type annotation | 1,503 (81.4%) |

**Assessment:** 81% return type coverage is moderate. Key untyped areas:
- `cli/lifecycle.py` — CLI commands (acceptable, Click handles types)
- `cli/main.py` — CLI entry points (acceptable)
- `server_impl.py` — 21/122 functions untyped (should improve)
- `storage/hybrid.py` — 15/68 functions untyped (should improve)

**Recommendation:** Add mypy to dev dependencies with a gradual typing configuration:
```toml
[tool.mypy]
python_version = "3.10"
ignore_missing_imports = true
check_untyped_defs = true
```

### 5.3 Code Style Consistency

| Check | Status | Detail |
|-------|:------:|--------|
| PEP 8 compliance | ✅ | ruff enforces E/W rules |
| Import ordering | ✅ | ruff `I` rule (isort equivalent) |
| Double quotes | ✅ | ruff format `quote-style = "double"` |
| Line length | ✅ | 88 (Black default) |
| Google-style docstrings | ✅ | Consistent across public APIs |

### 5.4 Test Architecture

| Metric | Value |
|--------|-------|
| Test files | 227 `test_*.py` files |
| Total tests | ~2,400 |
| Test markers | `unit`, `integration`, `performance`, `asyncio`, `benchmark` |
| pytest config | `pytest.ini` with `asyncio_mode = auto` |
| Test safety | 3 guards: temp dir prefix, session start abort, session finish validation |
| `TEST_MEMORY_TAG` | `"__test__"` reserved for cleanup |

### Code Quality Score: 7/10

**Issues:**
- P1: No mypy configuration — type errors are not caught in CI
- P2: 18.6% of functions lack return type annotations
- P2: No pre-commit hooks for automated formatting/linting at commit time

---

## 6. Upstream Divergence Analysis

### 6.1 Repository Relationship

| Attribute | Value |
|-----------|-------|
| Upstream | `codeberg.org:doobidoo/mcp-memory-service` |
| GitHub fork | `github.com:AIksyer/mcp-memory-service` |
| Fork relationship on GitHub | Not declared (not marked as a fork in GitHub settings) |
| Git history | Clean orphan — 4 commits on `main`, starting from "initial: clean public release" |
| Total commits (all branches) | 76 (including overnight task branches) |
| Main branch commits | 4 |

### 6.2 Divergence from Upstream

The main branch was created as a **clean orphan commit** — no shared git history with the upstream Codeberg repository. This means:
- No `git merge-base` with upstream
- No ability to `git pull upstream main` for updates
- Changes cannot be easily rebased on upstream

**Modifications visible in the repo (from main branch commits + file analysis):**
1. **HA deployment infrastructure:** `memory-ha.ps1`, `main.py` (FastAPI Cloud entry), Cloudflare Worker LB (`cloudflare/worker/mcp-lb/`)
2. **Environment-variable configured deployment** — no hardcoded URLs (per commit message: "env-var configured HA")
3. **Additional `.gitignore` entries** — `design/`, `task-output.md`, `memory-os-plugins/`, `CODELY.md`, `.env`, `.wrangler/`, `wrangler.toml`, `.pyscn/`
4. **Coverage baseline report** — `coverage-baseline.md`, `analysis-report.md`

### 6.3 Apache 2.0 Compliance for Derivatives

| Requirement | Status | Detail |
|-------------|:------:|--------|
| Retain LICENSE file | ✅ | Unmodified Apache 2.0 full text |
| Retain copyright notices | ✅ | All source files retain `Copyright 2024 Heinrich Krupp` |
| Retain NOTICE file | ⚠️ | Present but has inaccuracies (see §1.2) |
| State changes made | ❌ | No "prominent notices" of modifications |
| Fork attribution | ❌ | No "derivative of codeberg.org/doobidoo/mcp-memory-service" statement |

**Apache 2.0 §4(b) states:** "You must cause any modified files to carry prominent notices stating that You changed the files; and the date of any change."

The clean orphan history makes it impossible to track which files were modified from upstream. **Recommendation:** Add a `NOTICE` or `README` section stating the derivative relationship and linking to the upstream.

### 6.4 Fork-Specific Files (Not in Upstream)

| File/Directory | Purpose | License Concern |
|---------------|---------|-----------------|
| `memory-ha.ps1` | HA failover PowerShell script | None (original work) |
| `main.py` | FastAPI Cloud entry point | None (original work) |
| `cloudflare/worker/mcp-lb/` | Cloudflare Worker load balancer | None (original work, JS) |
| `coverage-baseline.md` | Test coverage report | None (documentation) |
| `analysis-report.md` | Project structure analysis | None (documentation) |
| `.codely-cli/` | Codely CLI settings (gitignored) | N/A (not committed) |

No third-party code that would require additional license attribution was found.

### Upstream Compliance Score: 6/10

**Issues:**
- P1: No derivative-work declaration (Apache 2.0 §4(b))
- P1: Clean orphan history prevents tracking upstream modifications
- P1: GitHub repo not marked as fork of upstream
- P2: NOTICE file doesn't acknowledge upstream contributors

---

## 7. GitHub-Specific Checks

### 7.1 Issue Templates

| File | Status | Quality |
|------|:------:|:------:|
| `bug_report.yml` | ✅ | Structured YAML form |
| `feature_request.yml` | ✅ | Structured YAML form |
| `performance_issue.yml` | ✅ | Specialized performance report form |
| `config.yml` | ✅ | Disables blank issues, adds contact links |
| Contact links | ⚠️ | Point to `github.com/doobidoo/mcp-memory-service/wiki` and `/discussions` — should be `AIksyer` |

**P1 Issue:** All URLs in `config.yml` reference `doobidoo` instead of `AIksyer`. These links will be broken on the GitHub fork.

### 7.2 CODEOWNERS

| Check | Status | Detail |
|-------|:------:|--------|
| File exists | ✅ | `.github/CODEOWNERS` |
| Coverage | ✅ | Security-sensitive paths, storage backends, quality system, reasoning engine |
| Maintainer GitHub handles | ⚠️ | References `@doobidoo`, `@zc277584121`, `@henry201605`, `@filhocf` — these are upstream maintainers, may not have access to the fork |

**P2 Issue:** CODEOWNERS references upstream maintainers who may not be collaborators on the GitHub fork. This will cause GitHub to show warnings about unreachable reviewers.

### 7.3 Dependabot

| Check | Status | Detail |
|-------|:------:|--------|
| File exists | ✅ | `.github/dependabot.yml` |
| Python ecosystem | ⚠️ | Configured for `uv` ecosystem, not `pip` — `uv` is Dependabot's newer ecosystem; `pip` may be more appropriate for this project |
| GitHub Actions | ✅ | `github-actions` ecosystem configured, weekly |
| Update limit | ✅ | 5 PRs for uv, 3 for actions |
| Grouping | ✅ | All deps grouped |
| Ignores | ✅ | `transformers` major updates deferred |

### 7.4 FUNDING.yml

| Check | Status | Detail |
|-------|:------:|--------|
| File exists | ✅ | `.github/FUNDING.yml` |
| Platforms | ✅ | GitHub Sponsors (`doobidoo`), Ko-fi, Buy Me a Coffee, PayPal |
| Appropriate? | ⚠️ | Funding goes to upstream maintainer `doobidoo`, not fork owner `AIksyer`. This may be intentional (support upstream) but should be clarified. |

### 7.5 CodeQL

| Check | Status | Detail |
|-------|:------:|--------|
| Config exists | ✅ | `.github/codeql/codeql-config.yml` |
| Scope | ✅ | `src/mcp_memory_service/**` included; tests/docs/scripts excluded |
| Query suite | ✅ | `security-and-quality` |
| False positive suppression | ✅ | `py/clear-text-storage-of-sensitive-data` (env files by design), `py/ssrf` (account_id validated) |
| CodeQL workflow | ❌ | No `.github/workflows/codeql.yml` — the config exists but no workflow runs it |

**P1 Issue:** CodeQL config exists but there's no GitHub Actions workflow to actually run CodeQL analysis. Create `.github/workflows/codeql.yml`.

### 7.6 GitHub Pages

| Check | Status | Detail |
|-------|:------:|--------|
| `site/` directory | ✅ | Landing page (mcpmemory.services) with HTML/CSS/JS |
| GitHub Pages config | ❌ | Not configured |
| Potential | ✅ | `site/` could be served via GitHub Pages for a project homepage |

### 7.7 Summary of GitHub-Specific Issues

| Issue | Severity | Fix |
|-------|:--------:|-----|
| ISSUE_TEMPLATE config.yml URLs point to `doobidoo` | P1 | Replace `doobidoo` with `AIksyer` |
| No `.github/workflows/` CI workflow | P1 | Create `ci.yml`, `codeql.yml` |
| CODEOWNERS references upstream maintainers | P2 | Update for fork collaborators |
| No GitHub Pages for `site/` | P2 | Enable GitHub Pages from `site/` directory |
| FUNDING.yml points to upstream maintainer | P2 | Update or add note about supporting upstream |
| Dependabot uses `uv` ecosystem | P2 | Consider `pip` ecosystem if not using `uv` lockfile |

---

## Issue Summary (Prioritized)

### P0 — Must Fix Before Release

| # | Issue | Section |
|---|-------|---------|
| 1 | GitHub PAT token (`gho_...`) embedded in git remote URL | §2.2 |

### P1 — Should Fix Before Release

| # | Issue | Section |
|---|-------|---------|
| 2 | NOTICE file lists unused dependency (ChromaDB), omits 8+ actual core dependencies | §1.2 |
| 3 | No derivative-work / fork attribution statement (Apache 2.0 §4(b)) | §1.4, §6.3 |
| 4 | No `.github/workflows/ci.yml` — no CI on GitHub | §4.2 |
| 5 | No `.github/workflows/codeql.yml` — CodeQL config exists but never runs | §7.5 |
| 6 | README clone URL, badges, and links point to Codeberg, not GitHub | §3.1 |
| 7 | ISSUE_TEMPLATE config.yml references wrong GitHub user (`doobidoo` → `AIksyer`) | §7.1 |
| 8 | No mypy configuration — type errors not caught | §5.2 |
| 9 | Release workflow not adapted for GitHub Releases | §4.2 |

### P2 — Nice to Have

| # | Issue | Section |
|---|-------|---------|
| 10 | No Codecov/Coveralls integration | §4.4 |
| 11 | No pre-commit hooks configuration | §4.5, §5.1 |
| 12 | 18.6% of functions lack return type annotations | §5.2 |
| 13 | LGPL dependencies (chardet, zeroconf) not disclosed in NOTICE | §1.5 |
| 14 | CODEOWNERS references upstream maintainers | §7.2 |
| 15 | No GitHub Pages for `site/` directory | §7.6 |
| 16 | FUNDING.yml points to upstream maintainer | §7.4 |
| 17 | Dependabot uses `uv` ecosystem (may need `pip`) | §7.3 |
| 18 | No GitHub Discussions categories configured | §3.4 |
| 19 | No SSRF validation on external embedding API URL | §2.6 |

---

## Improvement Recommendations (Priority Order)

### Immediate (P0)

1. **Revoke the exposed GitHub PAT** and remove it from the git remote URL
   ```bash
   git remote set-url github https://github.com/AIksyer/mcp-memory-service.git
   ```

### Before Release (P1)

2. **Fix NOTICE file:**
   - Remove ChromaDB (not a dependency)
   - Add all core dependencies with their licenses
   - Add "This project is a derivative of [mcp-memory-service](https://codeberg.org/doobidoo/mcp-memory-service)" statement

3. **Create `.github/workflows/ci.yml`:**
   ```yaml
   name: CI
   on: [push, pull_request]
   jobs:
     test:
       runs-on: ubuntu-latest
       steps:
         - uses: actions/checkout@v4
         - uses: actions/setup-python@v5
           with: { python-version: "3.12" }
         - run: pip install -e ".[dev,sqlite]"
         - run: pytest tests/ --ignore=tests/consolidation --ignore=tests/benchmarks --ignore=tests/integration -m "not benchmark" --cov=mcp_memory_service --timeout=120
   ```

4. **Create `.github/workflows/codeql.yml`** to run the existing CodeQL config

5. **Update README for GitHub:**
   - Change clone URL to GitHub
   - Replace Codeberg star badge with GitHub stars badge
   - Add GitHub Actions CI badge (once CI is set up)

6. **Fix ISSUE_TEMPLATE config.yml URLs** — replace `doobidoo` with `AIksyer`

7. **Add mypy to dev dependencies** with gradual typing config

8. **Create `.github/workflows/release.yml`** for GitHub Releases

### Polish (P2)

9. Add `.pre-commit-config.yaml` with ruff + black
10. Set up Codecov integration
11. Update CODEOWNERS for fork collaborators
12. Enable GitHub Pages from `site/` directory
13. Consider replacing `chardet` (LGPL) with `charset-normalizer` (MIT)

---

## Final Conclusion

**GitHub Open-Source Readiness: Basic Readiness**

The project has excellent engineering foundations — comprehensive test suite, security-conscious code, thorough documentation, and established quality gates. The codebase itself is production-ready.

However, for a public GitHub release, the following must be addressed:
1. **P0 (blocking):** Exposed GitHub PAT token in git remote — must revoke and remove before any push
2. **P1 (should fix):** Missing GitHub Actions CI, stale NOTICE file, Codeberg-oriented README, wrong URLs in issue templates

Once the P0 issue is resolved and the P1 items are addressed, the project will be **fully ready** for public GitHub release. The strong code quality, test coverage, and documentation depth provide a solid foundation for community adoption.

---

*Evaluation performed automatically by Codely Overnight Executor on 2026-08-04.*
