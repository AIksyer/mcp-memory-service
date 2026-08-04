# 03 — 同步与容灾备份设计

> 本文档定义 Memory OS 的数据同步管道、备份策略和跨项目记忆拉取机制。

## 1. 3-2-1 备份原则落地

```
┌──────────────────────────────────────────────────────────┐
│                    数据流转                              │
│                                                          │
│  Agent → memory.save()                                  │
│           │                                              │
│           ▼                                              │
│  ┌──────────────┐    on_store hook                     │
│  │ SQLite (主)   │◄────────────────────────────────┐    │
│  │ Source of     │                                 │    │
│  │ Truth         │                                 │    │
│  └──────┬───────┘                                 │    │
│         │                                         │    │
│         ▼                                         │    │
│  ┌──────────────┐         ┌──────────────┐        │    │
│  │ Markdown     │────────►│ Git Commit   │        │    │
│  │ (可读副本)   │         │ + Push       │        │    │
│  └──────────────┘         └──────┬───────┘        │    │
│                                   │                │    │
│                                   ▼                │    │
│                           ┌──────────────┐        │    │
│                           │ GitHub       │        │    │
│                           │ (云镜像)     │        │    │
│                           └──────┬───────┘        │    │
│                                  │ push trigger   │    │
│                                  ▼                │    │
│                           ┌──────────────┐        │    │
│                           │ GitHub Actions│        │    │
│                           │ - SQLite dump │        │    │
│                           │ - R2 upload   │        │    │
│                           │ - S3 upload   │        │    │
│                           └──────┬───────┘        │    │
│                                  │                │    │
│                     ┌────────────┼────────────┐   │    │
│                     ▼            ▼            ▼   │    │
│              ┌──────────┐ ┌──────────┐ ┌──────────┐│    │
│              │ R2       │ │ S3       │ │ VPS      ││    │
│              │ (灾备1)  │ │ (灾备2)  │ │ (灾备3)  ││    │
│              └──────────┘ └──────────┘ └──────────┘│    │
│                                                     │    │
│  跨项目拉取：                                         │    │
│  memory pull ← git clone + JSON import ─────────────┘    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

| 存储层 | 角色 | 数据 | 写入方式 | 频率 |
|--------|------|------|---------|------|
| SQLite | Source of Truth | metadata + embedding + graph | mcp-memory-service | 实时 |
| Markdown | 人类可读副本 | content + tags + summary | git_sync plugin | 每次 store/delete |
| Git | 版本管理 | Markdown 变更历史 | git_sync plugin | 每次 store/delete |
| GitHub | 云镜像 | Git push | git_sync plugin | 每次 store/delete |
| R2 | 异地灾备 | SQLite dump + Markdown | GitHub Actions | 每次 push |
| S3/VPS | 灾备副本 | 同 R2 | GitHub Actions | 每次 push |

## 2. Markdown 导出方案

### 2.1 文件结构

```
AgentMemory/                    # Git 仓库根目录
├── README.md                   # 自动生成的索引
├── memories/
│   ├── ab/
│   │   ├── abc123def456.md     # content_hash 命名
│   │   └── abd789ghi012.md
│   ├── cd/
│   │   └── cde345fgh678.md
│   └── ...
├── indexes/
│   ├── by-tag.md               # 按标签索引
│   ├── by-type.md              # 按类型索引
│   └── by-date.md              # 按日期索引
└── .github/
    └── workflows/
        └── memory-sync.yml     # GitHub Actions
```

### 2.2 Markdown 文件格式

```markdown
---
hash: abc123def456789...
type: decision
tags: [supabase, jwt, auth]
created: 2026-07-29T15:14:12Z
importance: 0.85
---

# Supabase JWT 无限刷新

Agent 一直提示 JWT 无效，原因是 Supabase anon key 配置错误。
解决方案：检查 .env 中的 SUPABASE_ANON_KEY...

## Metadata
- **quality_score**: 0.92
- **access_count**: 15
- **source_type**: user
```

### 2.3 为什么用 content_hash 命名而不是标题

1. **唯一性** — content_hash 天然唯一，无冲突
2. **幂等性** — 相同内容存储多次不会产生重复文件
3. **删除追踪** — git delete 时精确匹配文件
4. **不需要 LLM 生成标题** — 减少依赖和延迟

前2位 hash 做目录名，避免单目录文件过多（类似 Git 的 object 存储）。

## 3. Git 同步管道

### 3.1 git_sync plugin 工作流

```
on_store(memory_dict)
    │
    ├── (async) 写 Markdown 文件
    ├── (async) git add
    ├── (async) git commit -m "memory: {content[:50]}"
    └── (async) git push (如果配置了 auto_push)
         │
         ▼
    GitHub 仓库更新
         │
         ▼
    GitHub Actions 触发 (见 §4)
```

### 3.2 Git 操作策略

| 操作 | 时机 | 命令 | 冲突处理 |
|------|------|------|---------|
| `git add` | 每次 store/delete | `git add memories/` | N/A |
| `git commit` | 每次 store/delete | `git commit -m "memory: ..."` | N/A |
| `git push` | 每次 commit 后（可配置） | `git push origin main` | `git pull --rebase` 后重试 |
| `git pull` | 新项目初始化 | `git pull origin main` | N/A |

### 3.3 批量提交策略

高频存储时（如 Agent 连续存10条记忆），避免10次 git commit：

```python
# git_ops.py
class GitSyncQueue:
    """批量提交队列：积累 N 条变更后一次提交"""

    def __init__(self, repo_path: str, batch_size: int = 5, timeout: int = 30):
        self.repo_path = repo_path
        self.batch_size = batch_size
        self.timeout = timeout
        self._queue: list[tuple[str, str]] = []  # (action, hash)
        self._timer: asyncio.Task = None
        self._lock = asyncio.Lock()

    async def enqueue(self, action: str, content_hash: str):
        async with self._lock:
            self._queue.append((action, content_hash))
            if len(self._queue) >= self.batch_size:
                await self._flush()
            elif not self._timer:
                self._timer = asyncio.create_task(self._delayed_flush())

    async def _delayed_flush(self):
        await asyncio.sleep(self.timeout)
        await self._flush()

    async def _flush(self):
        if not self._queue:
            return
        # git add → git commit → git push
        batch = self._queue[:]
        self._queue.clear()
        if self._timer:
            self._timer.cancel()
            self._timer = None
        # ... 实际 git 操作
```

### 3.4 分支模型

```
main          ──────────►  生产分支，所有 commit 直接推 main
                │
                │ (如果需要审查)
                ▼
review         ──────────►  审查分支（未来团队场景）
```

单人使用直接推 main。未来如果需要审查，切到 review 分支 + PR。

## 4. Cloudflare R2 备份

### 4.1 R2 免费额度

| 项目 | 免费额度 |
|------|---------|
| 存储 | 10 GB |
| Class A 操作（写） | 1M/月 |
| Class B 操作（读） | 10M/月 |
| 出站流量 | 免费（R2 不收出口费） |

对于个人 Agent Memory（每条 ~1KB metadata + ~384 float embedding ≈ 2KB），10GB 可存约 500 万条记忆。完全够用。

### 4.2 R2 备份内容

| 备份项 | 大小 | 频率 | 方式 |
|--------|------|------|------|
| SQLite DB dump | ~1-50 MB | 每次 push | GitHub Actions |
| Markdown 文件 | ~1-10 MB | 每次 push | Git 仓库本身 |
| Embedding 向量 | 在 SQLite 中 | 随 DB 一起 | N/A |

### 4.3 GitHub Actions Workflow

```yaml
# .github/workflows/memory-sync.yml
name: Memory Sync & Backup

on:
  push:
    paths:
      - 'memories/**'

jobs:
  backup-r2:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install rclone
        run: sudo apt-get install -y rclone

      - name: Configure R2
        env:
          R2_ACCESS_KEY: ${{ secrets.R2_ACCESS_KEY }}
          R2_SECRET_KEY: ${{ secrets.R2_SECRET_KEY }}
          R2_ENDPOINT: ${{ secrets.R2_ENDPOINT }}
        run: |
          mkdir -p ~/.config/rclone
          cat > ~/.config/rclone/rclone.conf << EOF
          [r2]
          type = s3
          provider = Cloudflare
          access_key_id = $R2_ACCESS_KEY
          secret_access_key = $R2_SECRET_KEY
          endpoint = $R2_ENDPOINT
          EOF

      - name: Sync Markdown to R2
        run: rclone sync ./memories r2:memory-backup/memories --progress

      - name: Download and upload SQLite dump
        env:
          MCP_API_URL: ${{ secrets.MCP_API_URL }}
        run: |
          # 从本地服务导出 SQLite（如果服务可访问）
          # 或者从 R2 下载最近的 dump，增量更新
          curl -X POST $MCP_API_URL/api/sync/export \
            -o /tmp/memories.json
          rclone copy /tmp/memories.json r2:memory-backup/dumps/
```

### 4.4 GitHub Actions 限制

| 限制 | 免费额度 | 应对 |
|------|---------|------|
| 执行时间 | 2000 分钟/月 | 每次 < 1 分钟，足够 |
| 并发 | 20 jobs | 足够 |
| Secrets | 100 个 | 足够 |

## 5. 跨项目记忆拉取

### 5.1 新项目初始化流程

```bash
# 在新项目中初始化 Memory OS
memory-os init --project my-new-app

# 等同于：
# 1. git clone https://github.com/user/AgentMemory ~/AgentMemory (如果不存在)
# 2. git pull (拉取最新记忆)
# 3. 导入 Markdown → SQLite (如果本地 SQLite 为空)
# 4. 设置 project_tag = "proj:my-new-app"
# 5. 配置 MCP server 指向本地 SQLite
```

### 5.2 CLI 命令设计

```bash
# 初始化新项目
memory-os init [--project NAME] [--repo URL]

# 手动拉取最新记忆
memory-os pull

# 手动推送本地记忆到远端
memory-os push

# 导出全部记忆到 JSON
memory-os export [--output FILE]

# 从 JSON 导入记忆
memory-os import [--input FILE]

# 查看同步状态
memory-os status
```

### 5.3 导入/导出格式

复用上游已有的 `MemoryExporter` / `MemoryImporter`（`sync/exporter.py` / `sync/importer.py`）：

```python
# 导出
from mcp_memory_service.sync import MemoryExporter
exporter = MemoryExporter(storage)
await exporter.export_to_json(Path("memories.json"))

# 导入
from mcp_memory_service.sync import MemoryImporter
importer = MemoryImporter(storage)
await importer.import_from_json(Path("memories.json"))
```

## 6. 数据一致性

### 6.1 一致性模型

| 场景 | 策略 |
|------|------|
| 本地 SQLite vs Markdown | 最终一致 — on_store hook 异步写 Markdown |
| 本地 Git vs GitHub | 最终一致 — async push，失败自动重试 |
| GitHub vs R2/S3 | 最终一致 — GitHub Actions 触发 |
| 多设备同步 | 基于 Git — pull → import → 使用 |

### 6.2 冲突处理

```
设备A: memory.save("X") → git push
设备B: memory.save("Y") → git push (冲突)
```

**处理：** Git 层面的冲突用 `git pull --rebase` 解决。由于 Markdown 文件以 content_hash 命名（唯一），不会产生文件冲突 — 两个不同记忆的文件路径不同。

**SQLite 层面：** 每台设备有独立的 SQLite，通过 JSON import/export 同步。content_hash 保证幂等 — 相同内容不会重复导入。

### 6.3 灾难恢复流程

```
场景：本地 SSD 损坏，SQLite 丢失

恢复步骤：
1. git clone https://github.com/user/AgentMemory ~/AgentMemory
2. memory-os import --input ~/AgentMemory/dumps/latest.json
   (从 R2 下载最近的 SQLite dump)
3. memory launch — 恢复运行

数据丢失范围：
- 从最后一次 push 到损坏之间的记忆（通常 < 1 小时）
- Markdown 文件不受影响（已在 Git 中）
```
