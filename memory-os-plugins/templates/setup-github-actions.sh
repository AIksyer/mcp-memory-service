#!/usr/bin/env bash
# setup-github-actions.sh — copy r2-sync.yml to a target repository.
#
# Usage:
#   ./setup-github-actions.sh [repo_path]
#
# If repo_path is omitted, the current directory is used.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEMPLATE="${SCRIPT_DIR}/github-actions/r2-sync.yml"

REPO_PATH="${1:-.}"
WORKFLOWS_DIR="${REPO_PATH}/.github/workflows"

# --- Validate template exists ----------------------------------------------- #

if [[ ! -f "${TEMPLATE}" ]]; then
  echo "Error: r2-sync.yml not found at ${TEMPLATE}" >&2
  exit 1
fi

# --- Copy workflow ---------------------------------------------------------- #

mkdir -p "${WORKFLOWS_DIR}"
cp "${TEMPLATE}" "${WORKFLOWS_DIR}/r2-sync.yml"
echo "Copied r2-sync.yml to ${WORKFLOWS_DIR}/r2-sync.yml"

# --- Print instructions ----------------------------------------------------- #

cat <<'INSTRUCTIONS'

=== GitHub Secrets Configuration ===

The following secrets must be configured in your repository
(Settings → Secrets and variables → Actions → New repository secret):

  1. R2_ACCESS_KEY_ID
     Your Cloudflare R2 Access Key ID.
     Created via: Cloudflare Dashboard → R2 → Manage R2 API Tokens
     → Create API Token → Object Read & Write

  2. R2_SECRET_ACCESS_KEY
     Your Cloudflare R2 Secret Access Key.
     Generated together with the Access Key ID.

  3. R2_ACCOUNT_ID
     Your Cloudflare Account ID.
     Found in: Cloudflare Dashboard → right sidebar

  4. R2_BUCKET_NAME
     The name of your R2 bucket (e.g. "agent-memory-backup").

=== Verification ===

After pushing to main with changes under memories/, check:
  - GitHub Actions tab → "Sync Memories to R2" workflow runs
  - R2 bucket contents via Cloudflare Dashboard or:
    aws s3 ls s3://YOUR_BUCKET/memories/ \
      --endpoint-url https://ACCOUNT_ID.r2.cloudflarestorage.com

For detailed setup instructions, see docs/R2-SETUP.md.

INSTRUCTIONS
