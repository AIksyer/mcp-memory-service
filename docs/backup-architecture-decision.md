# 树状备份架构决策文档

## 目标

请 ChatGPT 审阅以下架构提案，指出缺陷和改进建议，最终给出是否采纳的建议。

---

## 背景

mcp-memory-service 的数据分布在多个节点：

```
节点类型              | 角色              | 数据风险    | 位置
─────────────────────┼─────────────────┼───────────┼──────────
本地 SQLite           | 主节点（活跃读写）  | 高风险     | 用户机器
Cloudflare D1        | HA 主节点（云端同步）| 高风险     | Cloudflare
─────────────────────┼─────────────────┼───────────┼──────────
R2 备份               | 低风险（快照备份）  | 低风险     | Cloudflare
GitHub 私密仓库        | 低风险（快照备份）  | 低风险     | GitHub
Render 部署           | HA 子节点（后端）   | 中风险     | Render
Railway 部署          | HA 子节点（后端）   | 中风险     | Railway
FastAPI Cloud 部署    | HA 子节点（后端）   | 中风险     | FastAPI Cloud
```

## 当前问题

1. **备份方向不明确**：哪些节点推送到哪些备份目标？谁负责推送？
2. **冲突无策略**：如果 R2 和 GitHub 的数据不一致，用哪个恢复？
3. **节点角色不清**：Render/Railway/FastAPI Cloud 是独立备份源还是只转发 D1 的数据？
4. **回流风险**：低风险区域（R2/GitHub）的数据不应该回流到主节点

## 提案：树状单向传导备份

### 节点层级

```
        ┌─────────┐          ┌─────────┐
        │ 本地SQLite│◄──双向──►│  D1 HA  │    ← 主节点层（高风险，双向同步）
        └────┬────┘          └────┬────┘
             │                    │
     ┌───────┼───────┐     ┌──────┼──────┐
     ▼       ▼       ▼     ▼      ▼      ▼
   R2    GitHub   (future)  Render Railway FastAPI   ← 低风险层（只接收，不回流）
  (快照)  (快照)   (S3等)   (HA子节点)              ← 由 D1/本地推送，不反向传导
```

### 数据流规则

| 方向 | 规则 | 说明 |
|------|------|------|
| 本地 ↔ D1 | **双向同步** | `_bidirectional_reconcile` 已实现 |
| 本地 → R2 | **单向推送** | 定时快照，不回流 |
| 本地 → GitHub | **单向推送** | 定时快照，不回流 |
| D1 → Render/Railway/FastAPI | **HA 转发** | HA Worker LB 负载均衡，子节点不独立备份 |
| R2 ↔ GitHub | **互相验证** | GitHub Actions `cross-verify.yml` 校验 SHA-256 |
| R2 → 本地 | **仅恢复** | 用户手动触发 `restore_backup` |
| GitHub → 本地 | **仅恢复** | 用户手动 `git clone` + 恢复 |

### 关键原则

1. **低风险节点只接收不传导**：R2/GitHub 只从本地或 D1 接收推送，不会反向推回主节点
2. **主节点双向**：本地 ↔ D1 通过 hybrid sync + reconcile 双向对账
3. **HA 子节点透明**：Render/Railway/FastAPI Cloud 是 HA Worker LB 后面的后端，不独立备份数据，它们的数据来自 D1（实时同步）
4. **交叉验证**：R2 和 GitHub 互相校验 SHA-256，发现不一致时告警
5. **恢复路径**：本地丢失 → 从 R2 或 GitHub 恢复（手动选择最新版本）

### 备份触发条件

| 触发方式 | 频率 | 推送到 | 条件 |
|---------|------|--------|------|
| 服务器启动 | 一次性 | R2 + GitHub | `MCP_BACKUP_REMOTE_ON_STARTUP=true` |
| 定时调度 | daily（可配） | R2 + GitHub | `BACKUP_ENABLED=true` + 服务器运行中 |
| 手动 API | 按需 | R2 + GitHub | `POST /api/backup/push-remote` |
| GitHub Actions | daily | 只校验 | 比较 GitHub vs R2 SHA-256 |

### 冲突解决

| 场景 | 策略 |
|------|------|
| 本地比 R2 新 | 推送本地 → R2 + GitHub（覆盖旧快照） |
| R2 比本地新 | 告警，不自动覆盖本地（用户决定是否恢复） |
| R2 和 GitHub SHA 不同 | 告警，以本地为准重新推送 |
| D1 和本地不一致 | `_bidirectional_reconcile` 双向对账 |
| HA 子节点数据过期 | 由 D1 实时同步补齐，无需独立备份 |

### 未解决的问题（请 ChatGPT 评估）

1. **多设备冲突**：设备 A 和设备 B 都连同一个 D1，各自往 R2 推送——R2 上会有两个不同的快照。如何确定哪个是"正确"的？
   - 建议：R2 备份键加 `device_id` 前缀（如 `backups/device-A/sqlite_vec_20260810.db`）
   
2. **HA 子节点离线**：Render/Railway/FastAPI Cloud 中的某个宕机了，D1 的数据仍然完整。但如果 D1 也出问题怎么办？
   - 建议：D1 的备份由本地 SQLite 负责（本地 → D1 是双向同步，本地 → R2 是快照备份）

3. **GitHub 仓库无限增长**：每次备份是一个 commit，二进制 .db 文件不可 delta 压缩。半年后仓库会很大。
   - 建议：定期 `git gc` 或限制历史保留数

4. **本地和 D1 同时崩溃**：只能从 R2/GitHub 恢复。但 R2/GitHub 的快照可能是几小时前的。
   - 建议：增加备份频率到 hourly（如果数据变化频繁）

5. **HA Worker LB 不在备份链中**：Worker LB 只做路由转发，不存数据。如果 Worker 配置丢失（KV 数据），需要重新部署。
   - 建议：Worker 配置用 `wrangler.toml.example` + secrets 管理，已在 `.gitignore` 中保护

---

## 请 ChatGPT 评估以下维度

1. **这个树状架构是否合理？** 主节点双向、低风险单向、交叉验证的模式是否最佳实践？
2. **多设备冲突的 device_id 方案是否足够？** 还是需要分布式锁？
3. **HA 子节点不独立备份是否正确？** 还是应该每个部署节点都独立推送到自己的备份目标？
4. **R2 和 GitHub 的角色区分是否清晰？** 两者都是快照备份，是否有必要区分主/备？
5. **恢复路径是否完善？** 从 R2 恢复和从 GitHub 恢复的流程是否需要自动化？
6. **是否有遗漏的灾难场景？**

请给出具体的改进建议和风险评估。

---

## ChatGPT Architecture Review (2026-08-10)

**Score: 8.5/10 architecture, 7/10 data safety, 7/10 disaster recovery**

### Key Corrections (adopted in v2)

1. **GitHub = Audit Copy, not DB storage** — Git is unsuitable for binary files. GitHub stores only manifest + checksum.txt.
2. **R2 = Primary Backup Authority** — Full DB snapshots with history retention (7 daily + 4 weekly + 3 monthly).
3. **Enhanced manifest** — Includes `schema_version`, `device_id`, `backup_type` for version governance.
4. **R2 history retention** — Not just latest-overwrite; preserves historical snapshots for point-in-time recovery.
5. **HA nodes stay stateless** — Confirmed correct. Render/Railway/FastAPI don't backup independently.

### Deferred to v3

- `sync_version` field + conflict table (requires DB schema migration)
- Automated restore via staging (R2 → staging → validate → primary → reconcile → D1)
- Backup quarantine (pending → verified after 24h)
- Credential rotation procedure

### Final Decision

v2 implements: R2/GitHub role split, history retention, enhanced manifest.
v3 will address: sync_version, automated restore, quarantine.
