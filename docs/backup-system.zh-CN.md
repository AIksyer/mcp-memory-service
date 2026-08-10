# 备份系统文档

本 fork 在上游备份系统基础上扩展了 R2 远程备份、staging 恢复、存储压力清理、同步版本治理、冲突检测和备份隔离功能。

## 配置

所有配置在 `.env` 中设置。完整参考见 `.env.example`。

### 远程备份目标

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MCP_BACKUP_R2_ENABLED` | `false` | 启用 R2 备份上传 |
| `MCP_BACKUP_R2_BUCKET` | `mcp-memory-backup` | R2 存储桶名称 |
| `MCP_BACKUP_R2_STORAGE_PRESSURE_THRESHOLD` | `8` (GB) | 存储用量超过此值时才删除旧备份 |
| `MCP_BACKUP_R2_QUARANTINE_HOURS` | `24` | 隔离备份提升为可用备份的小时数 |
| `MCP_BACKUP_GITHUB_ENABLED` | `false` | 启用 GitHub 审计备份（仅清单+校验和） |
| `MCP_BACKUP_GITHUB_REPO` | (空) | GitHub 审计仓库 |
| `MCP_BACKUP_GITHUB_TOKEN` | (空) | GitHub 个人访问令牌 |
| `MCP_BACKUP_REMOTE_ON_STARTUP` | `true` | 服务器启动时推送远程备份 |
| `MCP_DEVICE_ID` | (随机 UUID) | 同步跟踪用设备标识 |

R2 备份复用 Cloudflare 存储配置中的 `CLOUDFLARE_API_TOKEN` 和 `CLOUDFLARE_ACCOUNT_ID`。

## 工作原理

### 备份流程

```
store() / update_memory_metadata()
    │ sync_version = 1 (新建) 或 sync_version + 1 (更新)
    │ device_id = MCP_DEVICE_ID
    ▼
create_backup()
    │ SQLite 备份 API → 本地 .db 文件
    │ 完整性检查门控
    ▼
_push_to_remote()
    ├── _push_to_r2() → pending/sqlite_vec_{时间戳}.db
    │   └── _r2_cleanup_under_pressure() (仅当用量 > 阈值)
    │   └── _r2_promote_pending() (提升旧 pending → backups/)
    └── _push_to_github() → manifest.json + checksum.txt (仅审计)
```

### 恢复（v3）

`POST /api/backup/restore` — 从 R2 经 staging 恢复：

1. 下载 R2 备份到 staging 路径
2. 对 staging 执行 PRAGMA integrity_check
3. Schema 版本兼容性检查（拒绝旧 schema）
4. 备份当前 DB 到 `.db.pre_r2_restore`
5. 替换主 DB
6. 返回结果包含警告：**不要自动对账**

恢复只扫描 `backups/` 前缀（不扫描 `pending/`）。

### 同步版本与冲突检测（v4）

每次写入递增 `sync_version`：
- `store()`：设置 `sync_version = 1`
- `update_memory_metadata()`：`sync_version = sync_version + 1`

双向对账时（`_reconcile_drift_in_both`）：
1. 比较 `sync_version` — 高版本胜出（无容差检查）
2. 如果双方 `sync_version > 0` 且不同 → 记录冲突
3. 如果相等或一方为 0（v4 之前数据）→ 回退到 `updated_at` 比较

冲突按 `content_hash` 去重 — 每个 hash 只保留一条未解决冲突。

### 冲突解决

```bash
# 查看未解决冲突
curl -H "X-API-Key: $KEY" https://你的地址/api/backup/conflicts

# 解决冲突
curl -X POST -H "X-API-Key: $KEY" \
  "https://你的地址/api/backup/conflicts/resolve?conflict_id=1&resolution=manual"
```

### 备份隔离

新 R2 上传先进入 `pending/` 前缀。经过 `MCP_BACKUP_R2_QUARANTINE_HOURS`（默认 24 小时）后，提升为 `backups/`：
1. 从 `pending/` 下载
2. 重新上传到 `backups/`
3. 验证 HTTP 成功（R2 无服务端复制）
4. 从 `pending/` 删除

这确保备份在可用于恢复前经过隔离观察期。

## API 端点

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| `POST` | `/api/backup/now` | 写 | 触发立即本地备份 |
| `POST` | `/api/backup/push-remote` | 写 | 备份 + 推送到 R2/GitHub |
| `POST` | `/api/backup/restore` | 写 | 从 R2 恢复（staging） |
| `GET` | `/api/backup/status` | 读 | 备份服务状态 |
| `GET` | `/api/backup/list` | 读 | 列出本地备份 |
| `GET` | `/api/backup/r2/list` | 读 | 列出 R2 备份对象 |
| `GET` | `/api/backup/conflicts` | 读 | 列出未解决的同步冲突 |
| `POST` | `/api/backup/conflicts/resolve` | 写 | 标记冲突已解决 |

## 数据库迁移

| 迁移 | 说明 |
|------|------|
| 013 | `backup_conflicts` 表（冲突审计跟踪） |
| 014 | `memories` 表新增 `sync_version` + `device_id` 列 |

两个迁移在启动时自动应用（SQLite 通过 MigrationRunner，D1 通过 `_add_column_with_retry`）。
