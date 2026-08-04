# 00 — 项目概述与架构总览

> 本文档是 Memory OS 二开项目的顶层设计，基于 mcp-memory-service v11.5.5 源码级评审 + 用户与 ChatGPT 的完整需求对话。

## 1. 用户需求总结

从与 ChatGPT 的多轮对话中，提炼出以下核心需求：

| # | 需求 | 优先级 |
|---|------|--------|
| N1 | **Agent 只管 save/search，同步/备份全自动** — 人不维护记忆基础设施 | P0 |
| N2 | **跨项目记忆复用** — 新项目拉取已有记忆，自动同步 | P1 |
| N3 | **多 Agent 共享** — Claude/Cursor/Codex/Gemini CLI 连同一套记忆 | P0 |
| N4 | **3-2-1 容灾备份** — 本地 SSD + Git + Cloudflare R2/S3 | P1 |
| N5 | **三级记忆分层** — Project / Personal / Global | P2 |
| N6 | **自动遗忘** — importance 衰减，冷门记忆降权 | P2 |
| N7 | **自动标签/摘要** — 存储时自动生成 title/summary/tags | P2 |
| N8 | **Markdown 导出** — 记忆可读、可迁移、不绑定平台 | P1 |
| N9 | **本地优先** — 完全离线可用，Cloudflare 是可选增强 | P0 |
| N10 | **零成本** — 利用免费额度（Cloudflare R2 10GB、GitHub Actions） | P0 |

用户原话：
> "我觉得我主要的痛点是懒，我希望AI能自动帮我同步记忆、拉取、同步、推送等工作，而我只需要在新项目的时候简单配置一下就行"

## 2. 设计哲学

### 2.1 核心原则：Agent 不碰基础设施

```
Agent 只做三件事：
  memory.save(content, tags, metadata)
  memory.search(query, filters)
  memory.delete(hash)

其余全部自动：
  → 生成 Embedding（已有，ONNX 本地）
  → 质量评分（已有，三层 tier）
  → 写 Markdown 文件（待开发，plugin）
  → Git commit + push（待开发，plugin）
  → R2/S3 备份（待开发，GitHub Actions）
  → 知识图谱关联（已有，typed edges）
  → 遗忘/整理（已有，consolidation）
```

**为什么：** 如果让 Claude Code 自己 `git add && git commit && git push`，换了 Cursor 就要重新写 Prompt。统一走 MCP Memory Server，Agent 不关心后端怎么存储和同步。

### 2.2 分层职责

```
┌─────────────────────────────────────────────────────────┐
│  Agent 层（Claude / Cursor / Codex / Gemini CLI）        │
│  只调用 MCP 或 REST API，不感知后端实现                    │
├─────────────────────────────────────────────────────────┤
│  Memory OS 层（我们的二开层）                              │
│  ┌─────────────┐  ┌──────────────┐  ┌────────────────┐ │
│  │ Plugins     │  │ Workers      │  │ CLI Extensions │ │
│  │ (on_store   │  │ (git_sync,   │  │ (memory init,  │ │
│  │  on_delete  │  │  r2_backup,  │  │  memory pull)  │ │
│  │  on_retrieve│  │  auto_tag)   │  │                │ │
│  │  on_consolid│  │              │  │                │ │
│  │  ate)       │  │              │  │                │ │
│  └──────┬──────┘  └──────┬───────┘  └───────┬────────┘ │
│         │                │                   │          │
│         └────────────────┼───────────────────┘          │
│                          │                              │
├──────────────────────────┼──────────────────────────────┤
│  上游 mcp-memory-service (pip 依赖，不改源码)             │
│  ┌───────────────────────▼────────────────────────────┐ │
│  │ MemoryService (业务逻辑 + Plugin Registry)         │ │
│  │   ├─ BaseStorage (ABC)                             │ │
│  │   │   ├─ SqliteVecStorage  ← 当前使用              │ │
│  │   │   ├─ CloudflareStorage ← 未来                  │ │
│  │   │   ├─ HybridStorage     ← 未来                  │ │
│  │   │   └─ MilvusStorage     ← 未来                  │ │
│  │   ├─ ONNX Embeddings (384d, 本地)                  │ │
│  │   ├─ Knowledge Graph (typed edges)                │ │
│  │   ├─ Consolidation (decay + forget + compress)     │ │
│  │   ├─ Quality Scoring (3-tier)                      │ │
│  │   ├─ SSE 实时通知                                   │ │
│  │   └─ Plugin Hooks (entry_points 自动发现)          │ │
│  └────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────┤
│  存储与同步层                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌─────────┐ │
│  │ SQLite   │  │ Markdown │  │ Git Repo │  │ R2 / S3 │ │
│  │ (主数据)  │  │ (可读副本)│  │ (版本管理)│  │ (灾备)  │ │
│  └──────────┘  └──────────┘  └──────────┘  └─────────┘ │
└─────────────────────────────────────────────────────────┘
```

### 2.3 各存储职责明确

| 存储 | 角色 | 数据 | 谁写入 |
|------|------|------|--------|
| **SQLite** | Source of Truth | metadata + embedding + tags + graph | mcp-memory-service |
| **Markdown** | 人类可读副本 | content + tags + summary | git_sync plugin |
| **Git** | 版本管理 | Markdown 变更历史 | git_sync plugin |
| **GitHub** | 云镜像 | Git push | git_sync plugin |
| **R2/S3** | 异地灾备 | SQLite dump + Markdown | GitHub Actions / r2_backup plugin |

**为什么 Git 不是数据库：** ChatGPT 说得对 — Git 做不到 `WHERE tag='docker' AND importance>80`。SQLite 是真正的 Memory Engine，Git 只管版本和人类可读性。

## 3. 与 ChatGPT 方案的对比

| 维度 | ChatGPT 最终建议 | 我们的方案 | 差异原因 |
|------|-----------------|-----------|---------|
| **底层选择** | 研究接口，自己重写 Kernel（~10000 行） | pip 依赖 mcp-memory-service，不重写 | 源码评审发现已有 Plugin 系统，80% 能力可用，重写是浪费 |
| **集成方式** | Memory Provider / Adapter 模式 | pip 依赖 + entry_points plugin | 上游已有 plugin hook 机制，不需要额外 Adapter 层 |
| **事件总线** | 自建 Event Bus + Worker | 复用 plugin hooks + asyncio Task | hooks 已覆盖 on_store/on_delete/on_retrieve，Worker 用 asyncio.create_task 即可 |
| **项目命名** | memoryd / memd（后台常驻服务） | 不改 — mcp-memory-service 已是后台服务 | `memory launch` 已启动常驻 HTTP 服务，不需要新命名 |
| **Qdrant** | 必须接入 | 可选 — SQLite-Vec 5ms 检索已够用 | 384d 向量在 SQLite-vec 上性能足够，Qdrant 是未来规模扩展时才需要 |
| **Cloudflare D1** | 作为 Memory Provider 选项 | 使用上游已有的 CloudflareStorage | 上游已实现 D1 + Vectorize + R2，不需要自己写 |

### 3.1 为什么不 Fork？

ChatGPT 和我们的结论一致：**不 Fork**。但理由不同：

- ChatGPT：项目更新太快（2 天一个版本），merge 会痛苦
- 我们：**不需要 Fork**。pip 依赖 + entry_points plugin 可以零侵入扩展。只有需要修改上游核心代码时才需要 Fork，而我们的需求全部可以通过 plugin 实现。

### 3.2 为什么不重写 Kernel？

ChatGPT 建议自己重写 Kernel（~10000 行）。我们反对，原因：

1. **上游已有 Plugin 系统** — `plugins/context.py` + `plugins/registry.py` + `entry_points` 自动发现，这正是 ChatGPT 想要的 "Event Bus" 的雏形
2. **上游已有 Storage ABC** — `BaseStorage` 定义了完整的存储接口，已有 4 个实现，加新后端只需继承一个类
3. **上游已有 Consolidation** — 遗忘/衰减/压缩/知识图谱关联全部实现，重写需要重新实现这些
4. **维护成本** — 重写 10000 行后，上游每次更新安全补丁你都要自己移植

## 4. 技术选型

| 层 | 技术 | 选择 | 理由 |
|----|------|------|------|
| Transport | MCP | stdio (Claude/Cursor) + HTTP (REST API) | 上游已实现 |
| Transport | REST | FastAPI | 上游已实现 |
| CLI | click | `memory` 命令 | 上游已实现 |
| Storage | SQLite-Vec | 本地 5ms 检索 | 上游已实现，当前使用 |
| Storage | Cloudflare | D1 + Vectorize + R2 | 上游已实现，未来启用 |
| Embedding | ONNX | all-MiniLM-L6-v2 (384d) | 上游已实现，本地运行 |
| 同步 | Git | GitPython / subprocess | plugin 中实现 |
| 备份 | R2/S3 | boto3 / cloudflare API | plugin + GitHub Actions |
| 调度 | APScheduler | 已集成 | 上游已实现 |
| 通知 | SSE | sse-starlette | 上游已实现 |
| 质量评分 | ONNX + Groq + Gemini | 三层 fallback | 上游已实现 |

## 5. 当前状态

| 项目 | 状态 |
|------|------|
| mcp-memory-service 安装 | ✅ v11.5.5 editable mode |
| 本地 SQLite-Vec 存储 | ✅ 已运行 |
| HTTP 服务 (Dashboard + REST) | ✅ http://127.0.0.1:8000 |
| MCP 接入 Codely CLI | ✅ 已配置 (stdio 模式) |
| 第一条记忆 | ✅ 已存储，语义搜索 16ms |
| git_sync plugin | ⬜ 待开发 (P1) |
| r2_backup plugin | ⬜ 待开发 (P2) |
| 三级记忆分层 | ⬜ 待开发 (P3) |
| 自动标签/摘要 | ⬜ 待开发 (P3) |

## 6. 文档索引

| 文档 | 内容 |
|------|------|
| [01-Source-Architecture-Review.md](01-Source-Architecture-Review.md) | 上游源码级架构评审 |
| [02-Plugin-Pipeline-Design.md](02-Plugin-Pipeline-Design.md) | 插件与事件管道设计 |
| [03-Sync-Backup-Design.md](03-Sync-Backup-Design.md) | 同步与容灾备份设计 |
| [04-Memory-Scoping-Design.md](04-Memory-Scoping-Design.md) | 三级记忆分层设计 |
| [05-Auto-Processing-Pipeline.md](05-Auto-Processing-Pipeline.md) | 自动处理管道设计 |
| [06-Roadmap.md](06-Roadmap.md) | 实施路线图 |
