# 01 — 上游 mcp-memory-service 源码级架构评审

> 评审对象：mcp-memory-service v11.5.5，源码位于 `G:\Project\mcp-memory-service\src\mcp_memory_service\`
> 评审方法：逐模块阅读源码，不凭 README 推测

## 1. 实际分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  Transport Layer（三种入口，共用同一 Service）                 │
│  ┌───────────┐  ┌────────────────┐  ┌────────────────────┐   │
│  │ MCP stdio │  │ REST (FastAPI) │  │ CLI (click)        │   │
│  │ server_   │  │ web/app.py     │  │ cli/main.py        │   │
│  │ impl.py   │  │ 76 endpoints   │  │ memory launch/info │   │
│  └─────┬─────┘  └───────┬────────┘  └─────────┬──────────┘   │
│        │                │                      │             │
│        ▼                ▼                      ▼             │
├─────────────────────────────────────────────────────────────┤
│  Service Layer                                              │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │ MemoryService (services/memory_service.py, 1138 行)    │ │
│  │  • normalize_tags() — 统一标签格式                      │ │
│  │  • store_memory() — 存储 + 去重 + 分片 + 质量评分        │ │
│  │  • retrieve_memories() — 语义检索 + 插件回调             │ │
│  │  • delete_memory() — 删除 + 插件回调                     │ │
│  │  • PluginRegistry — entry_points 自动发现 + hook 执行   │ │
│  └───────────────────────┬─────────────────────────────────┘ │
│                          │                                  │
├──────────────────────────┼──────────────────────────────────┤
│  Storage Layer            │                                  │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │ BaseStorage (storage/base.py, ABC)                     │ │
│  │  abstract: store(), retrieve(), delete(),              │ │
│  │    search_by_tag(), update_memory_metadata(),          │ │
│  │    get_all_memories(), get_by_hash()...                │ │
│  │  default: delete_memories(), search_memories(),        │ │
│  │    retrieve_with_quality_boost(), delete_by_tags()...  │ │
│  │  ┌──────────┐ ┌──────────┐ ┌───────┐ ┌──────────────┐ │ │
│  │  │sqlite_vec│ │cloudflare│ │hybrid │ │milvus        │ │ │
│  │  │.py       │ │.py       │ │.py    │ │.py           │ │ │
│  │  └──────────┘ └──────────┘ └───────┘ └──────────────┘ │ │
│  │  + Graph: graph.py (SQLite) / milvus_graph.py           │ │
│  │  + Factory: factory.py (if-elif 分发)                   │ │
│  └─────────────────────────────────────────────────────────┘ │
│                          │                                  │
├──────────────────────────┼──────────────────────────────────┤
│  Embedding Layer          │                                  │
│  ┌────────────────────────▼────────────────────────────────┐ │
│  │ ONNX all-MiniLM-L6-v2 (384d, 本地)  ← 默认              │ │
│  │ sentence-transformers (可选, ml deps)                   │ │
│  │ External API (vLLM/Ollama/TEI/OpenAI)                   │ │
│  └─────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────┤
│  Cross-cutting（横切关注点）                                  │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────────────────┐ │
│  │Consolidation │ │ SSE 通知  │ │ Sync (JSON 导出/导入     │ │
│  │decay.py     │ │sse.py    │ │ + Litestream 配置)       │ │
│  │forgetting.py│ │          │ │                          │ │
│  │compression  │ │          │ │                          │ │
│  │.py          │ │          │ │                          │ │
│  │scheduler.py │ │          │ │                          │ │
│  └──────────────┘ └──────────┘ └──────────────────────────┘ │
│  ┌──────────────┐ ┌──────────┐ ┌──────────────────────────┐ │
│  │Quality (3-tier│ │ Plugins  │ │ Entity Extraction        │ │
│  │ONNX→Groq→   │ │context.py│ │ extraction/              │ │
│  │Gemini)       │ │registry  │ │                          │ │
│  └──────────────┘ └──────────┘ └──────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
```

## 2. 六个关键问题的源码级回答

### Q1: Memory 是否真正独立？

**✅ 是。** `Memory` 是纯 dataclass（`models/memory.py`），不依赖任何 transport、storage 或 MCP 类型。

```python
@dataclass
class Memory:
    content: str
    content_hash: str
    tags: List[str] = field(default_factory=list)
    memory_type: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    embedding: Optional[List[float]] = None
    created_at: Optional[float] = None
    created_at_iso: Optional[str] = None
    updated_at: Optional[float] = None
    updated_at_iso: Optional[str] = None
```

附加属性通过 `@property` 从 `metadata` 中读取（`quality_score`, `access_count`, `source_type`, `credibility`, `emotion` 等），不污染数据结构。

### Q2: Storage 是否可插拔？

**✅ 是，设计良好。** `BaseStorage`（`storage/base.py`）是 ABC，定义了：
- 抽象方法：`store()`, `retrieve()`, `delete()`, `search_by_tag()`, `search_by_tags()`, `update_memory_metadata()`, `get_all_memories()`, `get_by_hash()`, `cleanup_duplicates()`
- 默认实现：`delete_memories()` (灵活删除), `search_memories()` (统一搜索), `retrieve_with_quality_boost()` (质量重排), `delete_by_tags()`, `store_batch()`, `update_memory()`, `update_memories_batch()` 等

`factory.py` 通过环境变量 `MCP_MEMORY_STORAGE_BACKEND` 选择后端。已有 4 个实现：SQLite-Vec、Cloudflare、Hybrid、Milvus。

**局限：** factory 是硬编码 if-elif 链，不是注册表模式。新增后端需要修改 `factory.py`（加一个 elif 分支，改动极小）。

### Q3: 是否存在 Event 系统？

**⚠️ 部分存在 — 但已足够。** 有两套机制：

#### 3a. Plugin Hooks（关键发现）

`plugins/context.py` + `plugins/registry.py`：

```python
HookName = Literal["on_store", "on_delete", "on_retrieve", "on_consolidate"]

@dataclass
class PluginContext:
    storage: Any  # 存储后端实例
    service: Any  # MemoryService 实例

    def on(self, hook: HookName, fn: HookFn) -> None:
        self._hooks.setdefault(hook, []).append(fn)
```

插件通过 Python `entry_points`（group = `mcp_memory_service.plugins`）自动发现。`MemoryService.__init__` 中调用 `discover_and_register()`。

Hook 触发点（在 `memory_service.py` 中）：
- `on_store` — L473/L505：存储成功后触发，传入 `memory_dict`
- `on_retrieve` — L600：检索后触发，可修改返回结果（rerank）
- `on_delete` — L710：删除后触发，传入 `content_hash`
- `on_consolidate` — 整理后触发，传入 report dict

**这就是你插入 Git/R2/S3 同步的入口。不需要改任何上游代码。**

#### 3b. SSE（`web/sse.py`）

`SSEManager` 向 Web 客户端广播实时事件，有 replay buffer（`deque(maxlen=N)`）。支持 Last-Event-ID 断线重连。但这只是对外推送，不是内部事件总线。

### Q4: Sync 是否耦合？

**⚠️ 轻度耦合。** `sync/` 模块只有：
- `MemoryExporter` — 导出全部记忆为 JSON
- `MemoryImporter` — 从 JSON 导入
- `LitestreamManager` — Litestream 复制配置

Hybrid 后端内部做了 Cloudflare 同步（后台 asyncio task），但**没有 Git 集成，没有 R2/S3 备份管道**。这正是我们需要通过 plugin 添加的。

### Q5: CLI 是否独立？

**✅ 是。** `cli/main.py` 是独立模块，`memory` 命令通过 `pyproject.toml` 的 `[project.scripts]` 注册。CLI 通过 HTTP API 调用服务（`memory launch/info/stop/logs`），不直接操作存储。

### Q6: MCP 是否只是一个 Adapter？

**✅ 是。** `server_impl.py` 的 `MemoryServer` 类和 `web/api/mcp.py` 都是 transport adapter，都调用同一个 `MemoryService`。工具定义在 `tools/registry.py`（声明式 `ToolDef`），路由在 `tools/routing.py`。HTTP 层的 `api/mcp.py` 直接复用 MCP 的工具表面，不重复定义。

## 3. 已有能力清单（80%）

| 能力 | 模块 | 状态 | 备注 |
|------|------|------|------|
| MCP stdio transport | `server_impl.py` | ✅ | Claude/Cursor/Codex 等 |
| MCP HTTP transport | `web/api/mcp.py` | ✅ | Streamable HTTP + SSE |
| REST API (76 endpoints) | `web/api/*.py` | ✅ | FastAPI |
| CLI | `cli/main.py` | ✅ | `memory launch/stop/info/logs` |
| SQLite-Vec 存储 | `storage/sqlite_vec.py` | ✅ | 5ms 检索 |
| Cloudflare 存储 | `storage/cloudflare.py` | ✅ | D1 + Vectorize + R2 |
| Hybrid 存储 | `storage/hybrid.py` | ✅ | 本地 + 云同步 |
| Milvus 存储 | `storage/milvus.py` | ✅ | 向量 DB |
| ONNX 嵌入 | `embeddings/` | ✅ | 本地 384d |
| 知识图谱 | `storage/graph.py` | ✅ | typed edges |
| 混合搜索 | `storage/sqlite_vec.py` | ✅ | BM25 + Vector |
| 遗忘机制 | `consolidation/forgetting.py` | ✅ | 衰减 + 归档 |
| 衰减评分 | `consolidation/decay.py` | ✅ | 时间 + 访问频率 |
| 压缩整理 | `consolidation/compression.py` | ✅ | 语义合并 |
| 整理调度 | `consolidation/scheduler.py` | ✅ | APScheduler |
| 质量评分 | `quality/` | ✅ | 三层 (ONNX→Groq→Gemini) |
| 实体提取 | `extraction/` | ✅ | NER + @mentions + #tags |
| 关系推断 | `consolidation/relationship_inference.py` | ✅ | causes/fixes/contradicts |
| Plugin 系统 | `plugins/` | ✅ | 4 hooks + entry_points |
| SSE 通知 | `web/sse.py` | ✅ | 实时推送 + replay |
| OAuth 2.1 | `web/oauth/` | ✅ | 团队协作 |
| 文档导入 | `ingestion/` | ✅ | PDF/MD/JSON 分片 |
| Dashboard | `web/static/` | ✅ | 8 tab 可视化 |

## 4. 缺失能力清单（20%）

| 能力 | 当前状态 | 解决方案 | 优先级 |
|------|---------|---------|--------|
| **Git 自动同步** | ❌ 完全没有 | on_store plugin → Markdown + git commit/push | P1 |
| **R2/S3 备份** | ❌ 完全没有 | r2_backup plugin + GitHub Actions | P2 |
| **Markdown 导出** | ❌ 完全没有 | on_store plugin → 写 .md 文件 | P1 |
| **项目级记忆分层** | ❌ 无 Project/Personal/Global | tag namespace (proj:/user:/global) | P2 |
| **自动标签提取** | ❌ store 时不自动生成 | on_store plugin → LLM/关键词提取 | P3 |
| **自动摘要生成** | ❌ 无 | on_store plugin → LLM 调用 | P3 |
| **onSessionStart/End hooks** | ❌ 无 | 需提 PR 到上游 or 自己 patch | P4 |
| **Qdrant 后端** | ❌ 不支持 | 继承 BaseStorage | P4 |
| **跨项目记忆拉取** | ❌ 无 | CLI: memory init + git clone + JSON import | P2 |

## 5. 插件系统深度分析

### 5.1 工作原理

```
1. 你写一个 pip 包，pyproject.toml 中声明：
   [project.entry-points."mcp_memory_service.plugins"]
   my_plugin = "my_package.plugin:register"

2. MemoryService.__init__() 调用 PluginRegistry.discover_and_register()

3. discover_and_register() 用 importlib.metadata.entry_points() 发现所有
   注册在 "mcp_memory_service.plugins" group 下的 entry points

4. 对每个 entry point，调用 ep.load() 获取 register 函数，传入 PluginContext

5. register(ctx) 函数中调用 ctx.on("on_store", my_handler) 订阅 hook

6. 后续每次 store/retrieve/delete 操作，PluginRegistry.fire() 按顺序调用
   所有注册的 handler
```

### 5.2 PluginContext 能力

```python
@dataclass
class PluginContext:
    storage: Any  # 完整的存储后端实例 — 可直接读写存储
    service: Any  # MemoryService 实例 — 可调用所有业务方法
    _hooks: dict[HookName, list[HookFn]]
```

**关键：plugin 拿到的 `storage` 和 `service` 是完整的实例引用**，意味着 plugin 可以：
- 直接调用 `storage.get_all_memories()` 获取所有记忆
- 调用 `storage.get_by_hash(hash)` 获取特定记忆
- 调用 `service.update_memory_metadata(hash, updates)` 修改记忆元数据
- 调用 `service.list_memories()` 分页查询

### 5.3 Hook 执行特性

```python
async def fire(self, hook: HookName, *args, **kwargs) -> Any:
    # on_retrieve: handlers 可以修改返回结果（链式 rerank）
    # 其他 hooks: handlers 只做副作用，不影响主流程
    # 异常隔离: 单个 handler 失败不影响其他 handler 和主流程
```

**局限：**
- hooks 是同步串行执行的（await 一个接一个），不是并行
- 没有 hook 优先级机制（按注册顺序执行）
- 没有 on_update hook（更新元数据时不触发）
- 没有 on_session_start / on_session_end hook

### 5.4 插件错误隔离

```python
# registry.py L80-83
try:
    await fn(*args, **kwargs)
except Exception:
    logger.exception("Error in plugin hook '%s' handler %s", hook, fn.__qualname__)
```

**任何 plugin handler 抛异常都不会影响主流程** — 存储操作照常成功。这意味着即使 git push 失败，记忆仍然被正确存储。

## 6. 风险评估

### 6.1 Bus Factor = 1

项目几乎完全由 Heinrich Krupp 一人维护。

**缓解：** Apache 2.0 许可证允许随时 Fork 自救。我们采用 pip 依赖模式，如果上游停更，可以：
1. 锁定版本 `pip install mcp-memory-service==11.5.5`
2. 逐步 Fork 并自己维护

### 6.2 API 稳定性

v11 移除了废弃的工具别名（`compat.DEPRECATED_TOOLS`），说明 API 正在收窄稳定。但 plugin hook 接口（`PluginContext`）自添加以来未变。

**缓解：** 我们的 plugin 只依赖 4 个 hook（`on_store`/`on_delete`/`on_retrieve`/`on_consolidate`），这些是核心生命周期，不太可能被移除。

### 6.3 Plugin Hooks 局限

当前只有 4 个 hooks，缺少 `on_update`、`on_session_start`、`on_session_end`。

**缓解：**
- `on_update` — 可以通过 `on_store` 捕获（update 本质是 store 新版本）
- `on_session_start/end` — 不依赖 plugin，而是通过 Codely CLI 的 hooks 或 Claude Code hooks 实现

### 6.4 Python 3.14 兼容性

用户环境是 Python 3.14.2。项目 `pyproject.toml` 声明 `requires-python >= "3.10"`，但某些依赖（如 `milvus-lite`）可能不支持 3.14。

**缓解：** 当前只使用 `[sqlite]` extras（onnxruntime + tokenizers），已验证可在 3.14 上运行。
