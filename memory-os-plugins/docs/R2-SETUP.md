# R2 Backup Setup Guide

This guide walks you through configuring Cloudflare R2 as an off-site
backup target for your memory repository. Once configured, every `git push`
to `main` that touches `memories/**` triggers a GitHub Actions workflow
that syncs your memories to R2 via the S3-compatible API.

## Prerequisites

- A GitHub repository with your memories (created via `memory-os init`)
- A Cloudflare account (free tier includes 10 GB R2 storage)
- `aws-cli` is NOT required locally — the GitHub Actions runner has it pre-installed

## Step 1: Create an R2 Bucket

1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com/).
2. Navigate to **R2 Object Storage** in the left sidebar.
3. Click **Create bucket**.
4. Enter a bucket name (e.g. `agent-memory-backup`).
   - Bucket names must be globally unique and DNS-compatible.
5. Choose a location hint (optional — `Auto` is fine for most use cases).
6. Click **Create bucket**.

Note the bucket name — you will use it as the `R2_BUCKET_NAME` secret.

## Step 2: Create R2 API Credentials

R2 uses S3-compatible API credentials (Access Key ID + Secret Access Key),
distinct from Cloudflare's general API tokens.

1. In the Cloudflare Dashboard, go to **R2 Object Storage**.
2. Click **Manage R2 API Tokens** (or **API Tokens** under R2 settings).
3. Click **Create API Token**.
4. Configure the token:
   - **Token name**: `memory-os-sync` (or any descriptive name)
   - **Permissions**: **Object Read & Write**
   - **Specify bucket**: Select the bucket you created in Step 1
     (or choose *Apply to all buckets* if you prefer)
   - **TTL**: Leave as default (no expiry) or set as needed
5. Click **Create API Token**.
6. **Important**: Copy the credentials immediately — the Secret Access Key
   is only shown once:
   - **Access Key ID** — starts with a short alphanumeric string
   - **Secret Access Key** — a longer string
   - **Endpoint URL** — `https://<account_id>.r2.cloudflarestorage.com`
7. Also note your **Cloudflare Account ID** (visible in the right sidebar
   of the Cloudflare Dashboard).

## Step 3: Configure GitHub Secrets

In your GitHub repository:

1. Go to **Settings → Secrets and variables → Actions**.
2. Click **New repository secret** for each of the following:

| Secret name | Value | Description |
|---|---|---|
| `R2_ACCESS_KEY_ID` | Access Key ID from Step 2 | R2 S3-compatible access key |
| `R2_SECRET_ACCESS_KEY` | Secret Access Key from Step 2 | R2 S3-compatible secret key |
| `R2_ACCOUNT_ID` | Cloudflare Account ID | Used to build the R2 endpoint URL |
| `R2_BUCKET_NAME` | Bucket name from Step 1 | Target R2 bucket |

## Step 4: Add the Workflow

### Option A: Via `memory-os init --enable-r2-sync`

When initializing a new memory repository:

```bash
memory-os init --repo ~/AgentMemory --enable-r2-sync
```

This copies the workflow template to `.github/workflows/r2-sync.yml`
automatically.

### Option B: Via the setup script

If you already have a repository:

```bash
# From the memory-os-plugins source directory
./templates/setup-github-actions.sh /path/to/your/repo
```

### Option C: Manual copy

Copy `templates/github-actions/r2-sync.yml` to your repository's
`.github/workflows/r2-sync.yml` and commit it.

## Step 5: Verify

1. Make a change to a file under `memories/` in your repository.
2. Commit and push to `main`:
   ```bash
   git add memories/
   git commit -m "test: trigger R2 sync"
   git push origin main
   ```
3. Go to the **Actions** tab in your GitHub repository.
4. You should see a **Sync Memories to R2** workflow running.
5. Once it completes (green checkmark), verify the R2 bucket contents:
   - Via Cloudflare Dashboard → R2 → your bucket → `memories/` prefix
   - Or via aws-cli locally:
     ```bash
     export AWS_ACCESS_KEY_ID="your-access-key-id"
     export AWS_SECRET_ACCESS_KEY="your-secret-access-key"
     aws s3 ls s3://your-bucket-name/memories/ \
       --endpoint-url https://your-account-id.r2.cloudflarestorage.com
     ```

## Troubleshooting

### Workflow doesn't trigger

- Ensure the push is to the `main` branch.
- Ensure at least one changed file is under `memories/**`.
- Check that `.github/workflows/r2-sync.yml` exists and is committed.

### Access denied / 403 errors

- Verify the R2 API token has **Object Read & Write** permission.
- Verify the token is scoped to the correct bucket.
- Double-check the `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` secrets
  are set correctly (no trailing whitespace).

### Wrong endpoint URL

- The endpoint must be:
  `https://<account_id>.r2.cloudflarestorage.com`
- Ensure `R2_ACCOUNT_ID` contains only the account ID (not the full URL).

### `--delete` flag concerns

The `--delete` flag removes R2 objects that no longer exist in the local
`memories/` directory. This keeps R2 in sync with your git repository.
If you want to keep all historical objects (append-only), remove the
`--delete` flag from the workflow.
