# Disaster Recovery Guide

This document describes how to recover your memory database from Git and R2
backups in the event of data loss (database corruption, disk failure, accidental
deletion, or migration to a new machine).

## Architecture Overview

Memory OS provides **three layers of data persistence**:

| Layer | Location | Trigger | Purpose |
|-------|----------|---------|---------|
| **Primary** | SQLite database (`sqlite_vec.db`) | Every `store`/`delete` call | Live query + semantic search |
| **Git backup** | `~/AgentMemory/memories/` (Markdown) | `on_store`/`on_delete` hooks (async) | Version-controlled, human-readable backup |
| **R2 backup** | Cloudflare R2 bucket (S3-compatible) | `on_store`/`on_delete` hooks (async) | Off-site cloud redundancy |

The `git_sync` plugin converts each memory to a Markdown file with YAML front
matter and commits it to a local git repository. The `r2_backup` plugin uploads
the same Markdown file to Cloudflare R2. Both operate asynchronously via
`asyncio.create_task` — they never block the primary store path.

## Prerequisites

Before a disaster occurs, ensure the following are set up:

1. **git_sync plugin initialized and enabled:**
   ```bash
   memory-os init --repo ~/AgentMemory
   # Verify:
   memory-os status
   ```

2. **R2 backup configured** (optional but recommended):
   ```bash
   # Edit ~/.memory-os/config.yml:
   r2_backup_enabled: true
   r2_backup_endpoint_url: https://<account_id>.r2.cloudflarestorage.com
   r2_backup_access_key_id: <your-key>
   r2_backup_secret_access_key: <your-secret>
   r2_backup_bucket_name: <your-bucket>
   ```
   See [R2-SETUP.md](R2-SETUP.md) for detailed R2 configuration.

3. **Git remote configured** (for cross-machine sync):
   ```bash
   cd ~/AgentMemory
   git remote add origin <your-git-repo-url>
   git push -u origin main
   ```
   Without a remote, recovery is limited to the local git history.

4. **Verify backups are working:**
   ```bash
   # Store a test memory
   curl -X POST http://127.0.0.1:8000/api/store \
     -H 'Content-Type: application/json' \
     -d '{"content":"backup verification test","tags":["test"]}'

   # Wait 10s for async hooks, then check:
   ls ~/AgentMemory/memories/
   ```

## Recovery Procedures

### Scenario 1: Database Corruption (Local Git Available)

If the SQLite database is corrupted but the local git repo is intact:

```bash
# 1. Stop the service
memory stop

# 2. Back up the corrupted database
cp ~/AppData/Local/mcp-memory/sqlite_vec.db ~/sqlite_vec.db.corrupt

# 3. Delete the corrupted database
rm ~/AppData/Local/mcp-memory/sqlite_vec.db
rm -f ~/AppData/Local/mcp-memory/sqlite_vec.db-wal
rm -f ~/AppData/Local/mcp-memory/sqlite_vec.db-shm

# 4. Restart the service (creates a fresh database)
memory launch

# 5. Pull memories from Git into the new database
memory-os pull

# 6. Verify
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"test","limit":5}'
```

### Scenario 2: Complete Machine Loss (Git Remote Available)

If you need to recover on a new machine:

```bash
# 1. Install mcp-memory-service and memory-os-plugins
pip install mcp-memory-service
pip install memory-os-plugins

# 2. Initialize git sync from the remote
mkdir ~/AgentMemory
cd ~/AgentMemory
git clone <your-git-repo-url> .

# 3. Write config
cat > ~/.memory-os/config.yml << 'EOF'
# Memory OS Git Sync configuration
enabled: true
base_dir: ~/AgentMemory
auto_push: false
batch_size: 5
batch_timeout: 30
EOF

# 4. Start the service
memory launch

# 5. Import all memories from Git
memory-os pull

# 6. Verify recovery
memory-os status
curl -X POST http://127.0.0.1:8000/api/search \
  -H 'Content-Type: application/json' \
  -d '{"query":"important","limit":10}'
```

### Scenario 3: R2-Only Recovery (No Git Remote)

If neither the local database nor the git repo is available, but R2 backups exist:

```bash
# 1. Install tools
pip install mcp-memory-service memory-os-plugins awscli

# 2. Configure R2 credentials (from your records)
export AWS_ACCESS_KEY_ID="<your-r2-access-key>"
export AWS_SECRET_ACCESS_KEY="<your-r2-secret-key>"
R2_ENDPOINT="https://<account_id>.r2.cloudflarestorage.com"
R2_BUCKET="<your-bucket-name>"

# 3. Download all memories from R2
mkdir -p ~/AgentMemory/memories
aws s3 sync "s3://$R2_BUCKET/memories/" ~/AgentMemory/memories/ \
  --endpoint-url "$R2_ENDPOINT"

# 4. Initialize git sync config
cat > ~/.memory-os/config.yml << 'EOF'
# Memory OS Git Sync configuration
enabled: true
base_dir: ~/AgentMemory
auto_push: false
batch_size: 5
batch_timeout: 30
EOF

# 5. Initialize a new git repo for the recovered memories
cd ~/AgentMemory
git init
git add -A
git commit -m "restore: recovered from R2 backup"

# 6. Start the service and import
memory launch
memory-os pull
```

### Scenario 4: Automated Disaster Recovery Test

Run the test script to verify your recovery pipeline end-to-end:

```bash
cd memory-os-plugins/scripts
bash test_disaster_recovery.sh
```

This script:
1. Stores a test memory (triggers git_sync + r2_backup)
2. Stops the service and deletes the database
3. Recovers from Git using `memory-os pull`
4. Verifies the test memory is searchable
5. Restores the original database

Use `--skip-r2` to skip R2 verification if R2 is not configured.

## Manual R2 Backup

To trigger an R2 backup without waiting for the `on_store` hook (e.g., after
bulk imports or initial setup):

```bash
cd memory-os-plugins/scripts
bash backup_to_r2.sh
```

Options:
- `--dry-run` — show what would be uploaded without uploading
- `--delete` — remove R2 objects that no longer exist locally

This script reads R2 credentials from `~/.memory-os/config.yml` and uses
`aws s3 sync` to upload all files in the `memories/` directory.

## Recovery from JSON Export

If you have a JSON export (created via `memory-os export`), you can import it
directly:

```bash
# Export (do this regularly as an additional backup)
memory-os export -o backup.json

# Import on the new machine
memory-os import -i backup.json
```

JSON exports include content, tags, metadata, and optionally embeddings. The
import is idempotent (content-hash based deduplication).

## Common Issues and Troubleshooting

### `memory-os pull` reports 0 imported

**Cause:** The memories/ directory is empty or the Markdown files are missing
front matter.

**Fix:**
```bash
# Check if MD files exist
find ~/AgentMemory/memories/ -name "*.md" | wc -l

# Verify a file has front matter
head -5 ~/AgentMemory/memories/ab/*.md
```

### git pull fails with "no remote configured"

**Cause:** No git remote was set up before the disaster.

**Fix:** If you have R2 backups, use Scenario 3 above. Otherwise, the local
git history (if the `.git` directory survived) still contains all committed
memories — `memory-os pull` will import from the local working tree without
needing a remote.

### R2 sync fails with "Access Denied"

**Cause:** Incorrect or expired R2 credentials.

**Fix:**
1. Verify credentials in `~/.memory-os/config.yml`
2. Test connectivity:
   ```bash
   AWS_ACCESS_KEY_ID="<key>" AWS_SECRET_ACCESS_KEY="<secret>" \
     aws s3 ls s3://<bucket>/ --endpoint-url https://<account_id>.r2.cloudflarestorage.com
   ```
3. Regenerate R2 API tokens if needed (see [R2-SETUP.md](R2-SETUP.md))

### Embeddings are missing after recovery

**Cause:** The `memory-os pull` command stores memories without pre-computed
embeddings. The mcp-memory-service server generates embeddings on-the-fly
during the next search, but this may be slow for large datasets.

**Fix:** For large datasets, include embeddings in a JSON export:
```bash
memory-os export -o backup.json --include-embeddings
memory-os import -i backup.json
```

### Database is locked

**Cause:** The service is still running when you try to delete the database.

**Fix:**
```bash
memory stop
# Wait for the process to fully exit
sleep 3
# Verify no process is using the database
# Then retry
```

## Best Practices

1. **Test recovery regularly** — run `test_disaster_recovery.sh` monthly.
2. **Configure a git remote** — enables cross-machine recovery.
3. **Enable R2 backup** — provides off-site redundancy.
4. **Export JSON periodically** — `memory-os export -o monthly-backup.json`.
5. **Monitor disk space** — the memories/ directory grows with each stored memory.
6. **Don't rely on a single backup** — use Git + R2 + JSON export for defense in depth.
