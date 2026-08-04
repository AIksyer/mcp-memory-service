# 04 — 三级记忆分层设计

> 本文档定义 Project / Personal / Global 三级记忆分层，基于上游已有 tag 系统实现，无需修改存储层。

## 1. 三级记忆模型

```
┌─────────────────────────────────────────────┐
│  Level 3: Global（全局级）                    │
│  所有项目、所有 Agent 共享                     │
│  例：编码规范、Prompt 模板、架构原则           │
│  Tag: global                                 │
├─────────────────────────────────────────────┤
│  Level 2: Personal（个人级）                  │
│  跨项目共享，但不属于特定项目                  │
│  例：Supabase JWT 经验、Docker 网络坑         │
│  Tag: user:{username}                        │
├─────────────────────────────────────────────┤
│  Level 1: Project（项目级）                   │
│  只属于当前项目                               │
│  例：A 商城支付 SDK 坑、B 游戏 NPC 逻辑       │
│  Tag: proj:{project-name}                    │
└─────────────────────────────────────────────┘
```

## 2. 基于上游 Tag 系统的实现

### 2.1 上游 Tag 系统已有能力

上游 `MemoryService` 已支持：
- `tags` 作为 `List[str]` 存储
- `tag_match: "any" | "all"` 多标签过滤
- `X-Agent-ID` HTTP header 自动添加 `agent:{id}` tag
- `search_by_tags(tags, operation="AND|OR")` 按标签搜索
- Tag taxonomy 命名空间（`TagTaxonomy.parse_tag()`）已有 `sys:`, `q:`, `proj:`, `topic:`, `t:`, `user:`

**关键发现：** 上游 `TagTaxonomy` 已经定义了 `proj:` 和 `user:` 命名空间。我们直接复用。

### 2.2 Tag 命名规范

```python
# 存储记忆时的 tag 示例
tags = [
    "proj:my-app",          # 项目级（Level 1）
    "user:27933",           # 用户级（Level 2）
    "global",               # 全局级（Level 3）
    "supabase",             # 主题标签
    "jwt",                  # 主题标签
    "auth",                 # 主题标签
]
```

### 2.3 自动注入 Scope Tags

通过 `project_scope` plugin（`on_store` hook）自动注入项目级 tag：

```python
# project_scope plugin — on_store handler
async def on_store_handler(memory_dict: dict):
    """存储时自动注入项目/用户/全局 tag"""
    existing_tags = set(memory_dict.get("tags", []))
    scope_tags = set()

    # 注入项目 tag
    project = _config.get("project_name")
    if project:
        scope_tags.add(f"proj:{project}")

    # 注入用户 tag
    user = _config.get("username")
    if user:
        scope_tags.add(f"user:{user}")

    # 如果没有 proj: 和 user: tag，标记为 global
    if not scope_tags:
        scope_tags.add("global")

    merged = list(existing_tags | scope_tags)
    if len(merged) > len(existing_tags):
        # 更新存储中的 tags
        await _update_memory_tags(memory_dict["content_hash"], merged)
```

## 3. 检索优先级与回退策略

### 3.1 检索流程

```
Agent: memory.search("JWT 无限刷新")
    │
    ▼
on_retrieve handler (project_scope plugin)
    │
    ├── 1. 先搜 proj:{current_project} tag 的记忆
    │     → 找到 2 条项目级结果
    │
    ├── 2. 再搜 user:{username} tag 的记忆
    │     → 找到 3 条个人级结果
    │
    ├── 3. 最后搜 global tag 的记忆
    │     → 找到 1 条全局级结果
    │
    └── 合并结果，按 scope 优先级 + relevance_score 排序
         返回: [proj:2条, user:3条, global:1条]
```

### 3.2 on_retrieve 实现策略

**方案 A：Tag 重排（推荐，简单）**

不在搜索时过滤，而是在 `on_retrieve` 中重排结果：

```python
async def on_retrieve_handler(query: str, results: list):
    """按 scope 优先级重排搜索结果"""
    project_tag = f"proj:{_config['project_name']}"
    user_tag = f"user:{_config['username']}"

    project_results = []
    user_results = []
    global_results = []
    other_results = []

    for r in results:
        tags = set(r.get("tags", []))
        if project_tag in tags:
            project_results.append(r)
        elif user_tag in tags:
            user_results.append(r)
        elif "global" in tags:
            global_results.append(r)
        else:
            other_results.append(r)

    # 项目 > 个人 > 全局 > 其他，同级别内按 similarity_score 排序
    return (
        sorted(project_results, key=lambda r: r.get("similarity_score", 0), reverse=True)
        + sorted(user_results, key=lambda r: r.get("similarity_score", 0), reverse=True)
        + sorted(global_results, key=lambda r: r.get("similarity_score", 0), reverse=True)
        + other_results
    )
```

**方案 B：多轮搜索（精确但慢）**

```python
async def scoped_search(query, n_results=10):
    # 1. 项目级搜索
    proj_results = await storage.retrieve(query, n_results=5, tags=[f"proj:{project}"])
    # 2. 用户级搜索
    user_results = await storage.retrieve(query, n_results=5, tags=[f"user:{user}"])
    # 3. 全局级搜索
    global_results = await storage.retrieve(query, n_results=3, tags=["global"])
    # 合并去重
    return merge_dedup(proj_results, user_results, global_results)
```

方案 B 精确但需要 3 次向量搜索（~15ms vs 5ms）。方案 A 只需 1 次搜索，在 `on_retrieve` 中重排。推荐先用方案 A。

### 3.3 上游已有的 tag 过滤能力

上游 `retrieve()` 方法已支持 `tags` 参数，在 SQL 层面过滤：

```python
# 上游 storage/base.py retrieve() 签名
async def retrieve(
    self, query: str, n_results: int = 5,
    tags: Optional[List[str]] = None,  # ← 按 tag 过滤
    min_confidence: float = 0.0,
    include_superseded: bool = False,
    start_time: Optional[float] = None,
    end_time: Optional[float] = None
) -> List[MemoryQueryResult]:
```

这意味着如果需要精确的 scope 过滤，可以直接在搜索时传 `tags=["proj:my-app"]`，不需要 post-hoc 重排。

## 4. 多项目共享与隔离

### 4.1 共享场景

```
项目 A（商城）          项目 B（游戏）
    │                       │
    ├── proj:mall           ├── proj:game
    │                       │
    └───────────┬───────────┘
                │
         user:27933  ← 共享
                │
            global    ← 共享
```

- 项目 A 的记忆默认只对项目 A 可见
- 但 Agent 可以通过搜索 `tags=["user:27933"]` 跨项目检索
- `global` tag 的记忆所有项目都能搜到

### 4.2 配置方式

```yaml
# ~/.memory-os/config.yml
project_scope:
  project_name: mall          # 当前项目名
  username: 27933             # 用户名
  search_strategy: rerank     # rerank (方案A) | scoped (方案B)

  # 可选：项目间共享配置
  shared_projects:
    - mall
    - payment-sdk             # mall 可以看到 payment-sdk 的记忆
```

### 4.3 项目切换

```bash
# 切换到新项目
memory-os switch --project game

# 这会更新 config.yml 中的 project_name
# 后续存储的记忆自动带 proj:game tag
# 检索时自动优先返回 proj:game 的记忆
```

## 5. Memory Store 分区（未来）

上游 v11 已支持 `store` 参数（多分区存储）：

```python
# 上游 storage/base.py get_all_memories() 签名
async def get_all_memories(
    self, limit=None, offset=0,
    memory_type=None, tags=None, tag_match="any",
    stale_days=None, include_embeddings=False,
    store: Optional[str] = "default",  # ← 存储分区
) -> List[Memory]:
```

未来可以利用 `store` 参数实现物理隔离：
- `store="proj:mall"` — 项目级物理分区
- `store="personal"` — 个人级物理分区
- `store="global"` — 全局级物理分区

但当前阶段，tag 过滤已足够，不需要物理分区。

## 6. 验证方案

```python
# 测试三级记忆分层
@pytest.mark.asyncio
async def test_memory_scoping(test_store):
    # 存储三级记忆
    await test_store.store(Memory(
        content="商城支付 SDK 配置坑",
        content_hash=hash("1"),
        tags=["proj:mall", "payment", "sdk"],
    ))
    await test_store.store(Memory(
        content="Supabase JWT 无限刷新解决方案",
        content_hash=hash("2"),
        tags=["user:27933", "supabase", "jwt"],
    ))
    await test_store.store(Memory(
        content="统一的错误处理架构原则",
        content_hash=hash("3"),
        tags=["global", "architecture", "error-handling"],
    ))

    # 验证按 scope 检索
    proj_results = await test_store.retrieve(
        "SDK 配置", tags=["proj:mall"]
    )
    assert len(proj_results) >= 1
    assert "proj:mall" in proj_results[0].memory.tags

    user_results = await test_store.retrieve(
        "JWT", tags=["user:27933"]
    )
    assert len(user_results) >= 1

    global_results = await test_store.retrieve(
        "架构", tags=["global"]
    )
    assert len(global_results) >= 1
```
