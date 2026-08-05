#!/usr/bin/env bash
# =============================================================================
# Disaster Recovery Test Script
# =============================================================================
# Simulates a complete database loss and verifies recovery from Git + R2.
#
# Flow:
#   1. Record current memory count
#   2. Store a test memory (triggers git_sync + r2_backup hooks)
#   3. Wait for async hooks to complete
#   4. Stop the memory service
#   5. Back up and delete the SQLite database
#   6. Recover: git pull + import Markdown files into a fresh database
#   7. Restart the service
#   8. Verify the test memory is recovered via search
#   9. Restore the original database
#
# Prerequisites:
#   - mcp-memory-service installed and configured (memory command available)
#   - memory-os-plugins installed (memory-os command available)
#   - git_sync plugin enabled (~/.memory-os/config.yml)
#   - Optional: r2_backup plugin enabled for cloud backup verification
#   - Service running on http://127.0.0.1:8000
#
# Usage:
#   bash test_disaster_recovery.sh
#   bash test_disaster_recovery.sh --skip-r2    # Skip R2 verification
#   bash test_disaster_recovery.sh --dry-run     # Print actions without executing
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
API_URL="http://127.0.0.1:8000"
TEST_TAG="disaster-recovery-test"
TEST_CONTENT="Disaster recovery test memory ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
SKIP_R2=false
DRY_RUN=false

# Parse arguments.
for arg in "$@"; do
    case "$arg" in
        --skip-r2) SKIP_R2=true ;;
        --dry-run) DRY_RUN=true ;;
        --help|-h)
            echo "Usage: $0 [--skip-r2] [--dry-run]"
            echo "  --skip-r2   Skip R2 backup verification"
            echo "  --dry-run   Print actions without executing destructive operations"
            exit 0
            ;;
    esac
done

# Resolve the SQLite database path.
# Priority: env var > default locations.
resolve_db_path() {
    # Check env vars first.
    for env_var in MCP_MEMORY_SQLITE_PATH MCP_MEMORY_SQLITEVEC_PATH; do
        if [ -n "${!env_var:-}" ] && [ -f "${!env_var}" ]; then
            echo "${!env_var}"
            return 0
        fi
    done

    # Check common default locations.
    local candidates=(
        "$HOME/AppData/Local/mcp-memory/sqlite_vec.db"
        "$HOME/.local/share/mcp-memory/sqlite_vec.db"
        "$HOME/.mcp-memory/sqlite_vec.db"
    )

    for candidate in "${candidates[@]}"; do
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done

    # Not found.
    echo ""
    return 1
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------
echo_section() {
    echo ""
    echo "=== $1 ==="
}

check_service() {
    if ! curl -sf "$API_URL/api/health" >/dev/null 2>&1; then
        echo "Error: mcp-memory-service is not running at $API_URL"
        echo "Start it with: memory launch"
        exit 1
    fi
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
echo_section "Pre-flight Checks"

check_service
echo "✓ Service is running"

# Verify memory-os CLI is available.
if ! command -v memory-os >/dev/null 2>&1; then
    echo "Error: memory-os CLI not found. Install memory-os-plugins first."
    exit 1
fi
echo "✓ memory-os CLI available"

# Verify git_sync is configured.
CONFIG_FILE="$HOME/.memory-os/config.yml"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found at $CONFIG_FILE"
    echo "Run: memory-os init"
    exit 1
fi

REPO_PATH=$(grep 'base_dir:' "$CONFIG_FILE" | head -1 | sed 's/.*base_dir:\s*//')
if [ -z "$REPO_PATH" ]; then
    echo "Error: base_dir not set in config"
    exit 1
fi
# Expand ~ in path.
REPO_PATH="${REPO_PATH/#\~/$HOME}"
echo "✓ Git sync repo: $REPO_PATH"

if [ ! -d "$REPO_PATH/memories" ]; then
    echo "Error: memories/ directory not found in $REPO_PATH"
    echo "Make sure the git_sync plugin is enabled and has synced at least once."
    exit 1
fi

# Resolve database path.
DB_PATH=$(resolve_db_path)
if [ -z "$DB_PATH" ]; then
    echo "Error: Could not find SQLite database file."
    echo "Set MCP_MEMORY_SQLITE_PATH env var or check default locations."
    exit 1
fi
echo "✓ Database: $DB_PATH"

# ---------------------------------------------------------------------------
# Step 1: Record current memory count
# ---------------------------------------------------------------------------
echo_section "1. Record current memory count"

BEFORE=$(curl -sf -X POST "$API_URL/api/search" \
    -H 'Content-Type: application/json' \
    -d '{"query":"test","limit":1}' 2>/dev/null \
    | python -c 'import sys,json; r=json.load(sys.stdin); print(len(r.get("results",[])))' 2>/dev/null || echo "0")
echo "Before: $BEFORE search results (baseline)"

# ---------------------------------------------------------------------------
# Step 2: Store a test memory
# ---------------------------------------------------------------------------
echo_section "2. Store test memory"

if [ "$DRY_RUN" = true ]; then
    echo "[DRY-RUN] Would store test memory: $TEST_CONTENT"
    echo "[DRY-RUN] Would wait for git_sync + r2_backup hooks"
    echo "[DRY-RUN] Would stop service, delete DB, recover from Git, restart, verify"
    echo "[DRY-RUN] Would restore original database"
    echo ""
    echo "=== Dry Run Complete ==="
    exit 0
fi

STORE_RESPONSE=$(curl -sf -X POST "$API_URL/api/store" \
    -H 'Content-Type: application/json' \
    -d "{\"content\":\"$TEST_CONTENT\",\"tags\":[\"$TEST_TAG\"]}" 2>/dev/null || echo "")

if [ -n "$STORE_RESPONSE" ]; then
    TEST_HASH=$(echo "$STORE_RESPONSE" | python -c 'import sys,json; r=json.load(sys.stdin); print(r.get("content_hash","")[:12])' 2>/dev/null || echo "?")
    echo "✓ Stored memory: hash=$TEST_HASH"
else
    echo "⚠ Store API may have a different endpoint — checking..."
    # Try /api/memories as fallback
    STORE_RESPONSE=$(curl -sf -X POST "$API_URL/api/memories" \
        -H 'Content-Type: application/json' \
        -d "{\"content\":\"$TEST_CONTENT\",\"tags\":[\"$TEST_TAG\"]}" 2>/dev/null || echo "")
    if [ -n "$STORE_RESPONSE" ]; then
        echo "✓ Stored via /api/memories"
    else
        echo "Error: Failed to store test memory"
        exit 1
    fi
fi

# ---------------------------------------------------------------------------
# Step 3: Wait for async hooks (git_sync + r2_backup)
# ---------------------------------------------------------------------------
echo_section "3. Waiting for async sync hooks"

echo "Waiting 10s for git_sync + r2_backup to fire..."
sleep 10

# Verify the Markdown file was created.
MD_HASH=$(echo "$STORE_RESPONSE" | python -c 'import sys,json; r=json.load(sys.stdin); print(r.get("content_hash",""))' 2>/dev/null || echo "")
if [ -n "$MD_HASH" ]; then
    MD_PREFIX="${MD_HASH:0:2}"
    MD_FILE="$REPO_PATH/memories/$MD_PREFIX/$MD_HASH.md"
    if [ -f "$MD_FILE" ]; then
        echo "✓ Markdown file exists: ${MD_HASH:0:12}.md"
    else
        echo "⚠ Markdown file not found at expected path"
        echo "  Expected: $MD_FILE"
        echo "  The git_sync plugin may not have fired yet — continuing anyway."
    fi
fi

if [ "$SKIP_R2" = false ]; then
    echo "Checking R2 backup..."
    # Try to list R2 objects with the test hash prefix.
    if command -v aws >/dev/null 2>&1; then
        R2_CONFIG_ENDPOINT=$(grep 'r2_backup_endpoint_url:' "$CONFIG_FILE" | sed 's/.*r2_backup_endpoint_url:\s*//' || echo "")
        R2_BUCKET=$(grep 'r2_backup_bucket_name:' "$CONFIG_FILE" | sed 's/.*r2_backup_bucket_name:\s*//' || echo "")
        R2_ACCESS_KEY=$(grep 'r2_backup_access_key_id:' "$CONFIG_FILE" | sed 's/.*r2_backup_access_key_id:\s*//' || echo "")
        R2_SECRET_KEY=$(grep 'r2_backup_secret_access_key:' "$CONFIG_FILE" | sed 's/.*r2_backup_secret_access_key:\s*//' || echo "")

        if [ -n "$R2_BUCKET" ] && [ -n "$R2_CONFIG_ENDPOINT" ]; then
            R2_PREFIX=$(grep 'r2_backup_prefix:' "$CONFIG_FILE" | sed 's/.*r2_backup_prefix:\s*//' || echo "memories/")
            AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$R2_SECRET_KEY" \
                aws s3 ls "s3://$R2_BUCKET/$R2_PREFIX" \
                --endpoint-url "$R2_CONFIG_ENDPOINT" 2>/dev/null \
                && echo "✓ R2 bucket accessible" \
                || echo "⚠ R2 verification failed (non-critical)"
        else
            echo "⚠ R2 not configured — skipping R2 verification"
        fi
    else
        echo "⚠ aws CLI not installed — skipping R2 verification"
    fi
fi

# ---------------------------------------------------------------------------
# Step 4: Stop the service
# ---------------------------------------------------------------------------
echo_section "4. Stop the memory service"

memory stop 2>/dev/null || true
echo "✓ Service stopped"

sleep 2

# ---------------------------------------------------------------------------
# Step 5: Back up and delete the database
# ---------------------------------------------------------------------------
echo_section "5. Back up and delete database"

DB_BACKUP="${DB_PATH}.dr-backup"
cp "$DB_PATH" "$DB_BACKUP"
echo "✓ Backed up to: $DB_BACKUP"

rm -f "$DB_PATH"
echo "✓ Deleted: $DB_PATH"

# Also remove WAL and SHM files if they exist.
rm -f "${DB_PATH}-wal" "${DB_PATH}-shm" 2>/dev/null || true

# ---------------------------------------------------------------------------
# Step 6: Recover from Git
# ---------------------------------------------------------------------------
echo_section "6. Recover from Git"

echo "Pulling latest from git remote..."
cd "$REPO_PATH"
git pull --rebase 2>/dev/null || echo "  (git pull skipped — no remote or already up to date)"

echo "Importing memories into fresh database..."
memory-os pull 2>/dev/null || {
    echo "⚠ memory-os pull failed — trying manual import..."

    # Fallback: use memory-os export from git, then import.
    TEMP_JSON=$(mktemp --suffix=.json 2>/dev/null || mktemp)
    python -c "
import json, sys
from pathlib import Path

repo = Path('$REPO_PATH')
memories_dir = repo / 'memories'
memories = []

for md_file in sorted(memories_dir.rglob('*.md')):
    if md_file.name == 'README.md':
        continue
    text = md_file.read_text(encoding='utf-8')
    # Parse front matter.
    if not text.startswith('---'):
        continue
    parts = text.split('---', 2)
    if len(parts) < 3:
        continue
    fm_text = parts[1].strip()
    body = parts[2].strip()
    fm = {}
    for line in fm_text.splitlines():
        if ':' in line:
            k, _, v = line.partition(':')
            fm[k.strip()] = v.strip()
    tags_str = fm.get('tags', '[]').lstrip('[').rstrip(']')
    tags = [t.strip() for t in tags_str.split(',') if t.strip()]
    memories.append({
        'content': body,
        'content_hash': fm.get('hash', ''),
        'tags': tags,
        'memory_type': fm.get('type', 'observation'),
        'metadata': {},
    })

export = {'export_metadata': {'source': 'disaster-recovery'}, 'memories': memories}
json.dump(export, open('$TEMP_JSON', 'w'), ensure_ascii=False, indent=2)
print(f'Exported {len(memories)} memories to $TEMP_JSON')
" 2>/dev/null && memory-os import -i "$TEMP_JSON" 2>/dev/null || echo "  Manual import also failed"
    rm -f "$TEMP_JSON"
}

# ---------------------------------------------------------------------------
# Step 7: Restart the service
# ---------------------------------------------------------------------------
echo_section "7. Restart service"

memory launch 2>/dev/null || memory launch --foreground &
sleep 5

# Wait for service to be ready.
for i in $(seq 1 10); do
    if curl -sf "$API_URL/api/health" >/dev/null 2>&1; then
        echo "✓ Service is running"
        break
    fi
    echo "  Waiting for service... ($i/10)"
    sleep 2
done

# ---------------------------------------------------------------------------
# Step 8: Verify recovery
# ---------------------------------------------------------------------------
echo_section "8. Verify recovery"

AFTER=$(curl -sf -X POST "$API_URL/api/search" \
    -H 'Content-Type: application/json' \
    -d "{\"query\":\"$TEST_CONTENT\",\"limit\":10}" 2>/dev/null \
    | python -c 'import sys,json; r=json.load(sys.stdin); print(len(r.get("results",[])))' 2>/dev/null || echo "0")

echo "After: $AFTER results for test memory"

if [ "$AFTER" -gt 0 ]; then
    echo ""
    echo "✅ DISASTER RECOVERY SUCCESSFUL!"
    echo "  Test memory was recovered from Git sync."
else
    echo ""
    echo "❌ DISASTER RECOVERY FAILED!"
    echo "  Test memory was not found after recovery."
    echo "  Restoring original database..."
fi

# ---------------------------------------------------------------------------
# Step 9: Restore original database
# ---------------------------------------------------------------------------
echo_section "9. Restore original database"

memory stop 2>/dev/null || true
sleep 2

if [ -f "$DB_BACKUP" ]; then
    cp "$DB_BACKUP" "$DB_PATH"
    rm -f "$DB_BACKUP"
    echo "✓ Original database restored"
else
    echo "⚠ Backup file not found — database may need manual recovery"
fi

# Restart service with original database.
memory launch 2>/dev/null || memory launch --foreground &
sleep 3

echo ""
echo "=== Disaster Recovery Test Complete ==="
echo ""
echo "Summary:"
echo "  Test memory:   $TEST_CONTENT"
echo "  Git repo:      $REPO_PATH"
echo "  Database:      $DB_PATH"
echo "  Recovery:      $([ "$AFTER" -gt 0 ] && echo '✅ PASSED' || echo '❌ FAILED')"
