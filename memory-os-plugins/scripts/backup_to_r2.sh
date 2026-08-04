#!/usr/bin/env bash
# =============================================================================
# Manual R2 Backup Script
# =============================================================================
# Syncs the memories/ directory to Cloudflare R2 using the S3-compatible API.
# This is a manual backup that does NOT depend on the on_store hook — it
# uploads ALL memory files in one batch.
#
# Prerequisites:
#   - aws CLI installed (aws-cli package)
#   - R2 credentials configured in ~/.memory-os/config.yml
#   - git_sync plugin initialized (memories/ directory exists)
#
# Usage:
#   bash backup_to_r2.sh
#   bash backup_to_r2.sh --dry-run       # Show what would be uploaded
#   bash backup_to_r2.sh --delete        # Delete R2 objects not in local dir
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Parse arguments
# ---------------------------------------------------------------------------
DRY_RUN=false
DELETE_FLAG=""
CONFIG_FILE="$HOME/.memory-os/config.yml"

for arg in "$@"; do
    case "$arg" in
        --dry-run) DRY_RUN=true ;;
        --delete) DELETE_FLAG="--delete" ;;
        --help|-h)
            echo "Usage: $0 [--dry-run] [--delete]"
            echo "  --dry-run  Show what would be uploaded without uploading"
            echo "  --delete   Remove R2 objects that no longer exist locally"
            exit 0
            ;;
    esac
done

# ---------------------------------------------------------------------------
# Read R2 configuration
# ---------------------------------------------------------------------------
if [ ! -f "$CONFIG_FILE" ]; then
    echo "Error: Config file not found at $CONFIG_FILE"
    echo "Run: memory-os init"
    exit 1
fi

# Extract R2 config values (key: value format, r2_backup_ prefix).
get_config_value() {
    local key="$1"
    grep "r2_backup_${key}:" "$CONFIG_FILE" | head -1 | sed "s/.*r2_backup_${key}:\s*//"
}

ENDPOINT_URL=$(get_config_value "endpoint_url")
ACCESS_KEY_ID=$(get_config_value "access_key_id")
SECRET_ACCESS_KEY=$(get_config_value "secret_access_key")
BUCKET_NAME=$(get_config_value "bucket_name")
R2_PREFIX=$(get_config_value "prefix")

# Apply defaults.
R2_PREFIX="${R2_PREFIX:-memories/}"

# Validate required config.
if [ -z "$ENDPOINT_URL" ] || [ -z "$BUCKET_NAME" ]; then
    echo "Error: R2 backup is not configured."
    echo "Set the following in $CONFIG_FILE:"
    echo "  r2_backup_endpoint_url: https://<account_id>.r2.cloudflarestorage.com"
    echo "  r2_backup_access_key_id: <your-access-key>"
    echo "  r2_backup_secret_access_key: <your-secret-key>"
    echo "  r2_backup_bucket_name: <your-bucket-name>"
    exit 1
fi

if [ -z "$ACCESS_KEY_ID" ] || [ -z "$SECRET_ACCESS_KEY" ]; then
    echo "Error: R2 credentials not set in config."
    echo "Configure r2_backup_access_key_id and r2_backup_secret_access_key."
    exit 1
fi

# ---------------------------------------------------------------------------
# Read git_sync repo path
# ---------------------------------------------------------------------------
REPO_PATH=$(grep 'repo_path:' "$CONFIG_FILE" | head -1 | sed 's/.*repo_path:\s*//')
REPO_PATH="${REPO_PATH/#\~/$HOME}"

if [ -z "$REPO_PATH" ]; then
    echo "Error: repo_path not set in config"
    exit 1
fi

MEMORIES_DIR="$REPO_PATH/memories"

if [ ! -d "$MEMORIES_DIR" ]; then
    echo "Error: memories/ directory not found at $MEMORIES_DIR"
    echo "Make sure git_sync is initialized and has synced at least once."
    exit 1
fi

# Count local files.
LOCAL_COUNT=$(find "$MEMORIES_DIR" -name "*.md" -type f | wc -l)
LOCAL_SIZE=$(du -sh "$MEMORIES_DIR" 2>/dev/null | cut -f1 || echo "?")

# ---------------------------------------------------------------------------
# Pre-flight: verify aws CLI
# ---------------------------------------------------------------------------
if ! command -v aws >/dev/null 2>&1; then
    echo "Error: aws CLI is not installed."
    echo "Install with: pip install awscli"
    echo ""
    echo "Alternatively, use the Python backup script:"
    echo "  python -c \"from memory_os_plugins.r2_backup.r2_ops import sync_directory_to_r2; ...\""
    exit 1
fi

# ---------------------------------------------------------------------------
# Display backup summary
# ---------------------------------------------------------------------------
echo "╔══════════════════════════════════════════════════════╗"
echo "║           R2 Manual Backup Summary                   ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Source:      $MEMORIES_DIR"
echo "║  Files:       $LOCAL_COUNT"
echo "║  Size:        $LOCAL_SIZE"
echo "║  Destination: s3://$BUCKET_NAME/$R2_PREFIX"
echo "║  Endpoint:   $ENDPOINT_URL"
echo "║  Mode:        $([ "$DRY_RUN" = true ] && echo 'DRY-RUN' || echo 'UPLOAD') $DELETE_FLAG"
echo "╚══════════════════════════════════════════════════════╝"

# ---------------------------------------------------------------------------
# Sync to R2
# ---------------------------------------------------------------------------
if [ "$DRY_RUN" = true ]; then
    echo ""
    echo "[Dry-run] The following files would be uploaded:"
    AWS_ACCESS_KEY_ID="$ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$SECRET_ACCESS_KEY" \
    aws s3 sync "$MEMORIES_DIR/" "s3://$BUCKET_NAME/$R2_PREFIX" \
        --endpoint-url "$ENDPOINT_URL" \
        $DELETE_FLAG --dryrun 2>/dev/null || {
        echo "Error: aws s3 sync failed (dry-run)"
        exit 1
    }
    echo ""
    echo "✓ Dry-run complete — no files were uploaded."
    exit 0
fi

echo ""
echo "Starting sync..."

START_TIME=$(date +%s)

AWS_ACCESS_KEY_ID="$ACCESS_KEY_ID" \
AWS_SECRET_ACCESS_KEY="$SECRET_ACCESS_KEY" \
    aws s3 sync "$MEMORIES_DIR/" "s3://$BUCKET_NAME/$R2_PREFIX" \
        --endpoint-url "$ENDPOINT_URL" \
        $DELETE_FLAG 2>/dev/null || {
    echo "Error: aws s3 sync failed."
    echo ""
    echo "Common issues:"
    echo "  - Incorrect credentials (verify r2_backup_access_key_id/secret_access_key)"
    echo "  - Wrong endpoint URL (should be https://<account_id>.r2.cloudflarestorage.com)"
    echo "  - Bucket doesn't exist or wrong name"
    echo "  - Network connectivity issues"
    exit 1
}

END_TIME=$(date +%s)
DURATION=$((END_TIME - START_TIME))

# ---------------------------------------------------------------------------
# Verify: list objects in R2
# ---------------------------------------------------------------------------
echo ""
echo "Verifying backup..."

R2_COUNT=$(AWS_ACCESS_KEY_ID="$ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$SECRET_ACCESS_KEY" \
    aws s3 ls "s3://$BUCKET_NAME/$R2_PREFIX" \
        --endpoint-url "$ENDPOINT_URL" \
        --recursive 2>/dev/null | wc -l || echo "0")

echo ""
echo "╔══════════════════════════════════════════════════════╗"
echo "║           Backup Complete                            ║"
echo "╠══════════════════════════════════════════════════════╣"
echo "║  Local files:   $LOCAL_COUNT"
echo "║  R2 objects:    $R2_COUNT"
echo "║  Duration:      ${DURATION}s"
echo "║  Delete mode:   $([ -n "$DELETE_FLAG" ] && echo 'enabled' || echo 'disabled')"
echo "╚══════════════════════════════════════════════════════╝"

if [ "$R2_COUNT" -ge "$LOCAL_COUNT" ]; then
    echo ""
    echo "✅ Backup successful — all files synced to R2."
else
    echo ""
    echo "⚠ Warning: R2 object count ($R2_COUNT) < local file count ($LOCAL_COUNT)"
    echo "  Some files may not have been uploaded. Check aws CLI output for errors."
fi
