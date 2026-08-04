# 02 — 插件与事件管道设计

> 本文档定义 Memory OS 的 plugin 开发规范、事件管道架构和具体 plugin 代码骨架。

## 1. 上游现有 Hooks 能力与局限

### 1.1 现有 4 个 Hooks

| Hook | 触发点 | 参数 | 能否修改结果 | 调用频率 |
|------|--------|------|-------------|---------|
| `on_store` | 存储成功后 | `memory_dict: dict` | ❌ 仅副作用 | 每次 store |
| `on_delete` | 删除成功后 | `content_hash: str` | ❌ 仅副作用 | 每次 delete |
| `on_retrieve` | 检索完成后 | `query: str, results: list[dict]` | ✅ 可 rerank | 每次 retrieve |
| `on_consolidate` | 整理完成后 | `report: dict` | ❌ 仅副作用 | 每次整理 |

### 1.2 关键特性

- **自动发现：** 通过 Python `entry_points`（group = `mcp_memory_service.plugins`），不需要改上游代码
- **错误隔离：** 单个 handler 异常不影响主流程和其他 handler
- **串行执行：** 按注册顺序 await 执行，不是并行
- **完整上下文：** `PluginContext` 提供 `storage` 和 `service` 实例引用

### 1.3 局限与应对

| 局限 | 影响 | 应对 |
|------|------|------|
| 串行执行 | 慢 plugin 会阻塞主流程 | handler 内用 `asyncio.create_task()` 做异步 fire-and-forget |
| 没有 `on_update` | 更新元数据不触发 | `on_store` 可捕获新版本；或通过 SSE 监听 |
| 没有 `on_session_start/end` | 无法自动拉取/推送 | 用 Codely CLI hooks 或 Claude Code hooks 实现 |
| 没有优先级 | handler 按注册顺序执行 | 不影响功能，只影响执行顺序 |

## 2. 扩展 Hook 清单（未来 PR）

建议向上游提 PR 增加以下 hooks：

```python
# 建议新增的 HookName
HookName = Literal[
    "on_store",           # 已有
    "on_delete",          # 已有
    "on_retrieve",        # 已有
    "on_consolidate",     # 已有
    "on_update",          # 新增：update_memory_metadata 后触发
    "on_entity_linked",   # 新增：实体关联后触发
    "on_quality_scored",  # 新增：质量评分完成后触发
]
```

**策略：** 不等 PR 合并。当前 4 个 hooks 已足够 P1-P3 阶段所有需求。`on_update` 可以通过 `on_store` 间接覆盖（更新操作本质上是写入新版本）。

## 3. Worker 模式设计

### 3.1 为什么需要 Worker

Plugin hooks 是串行的 — 如果 `on_store` handler 中做 git push（可能需要 2-5 秒），会阻塞存储 API 响应。

**解决方案：** handler 中只创建 asyncio Task，立即返回。实际工作在后台异步执行。

### 3.2 Worker 架构

```
on_store(memory_dict)
    │
    ▼
Plugin Handler（< 1ms，不阻塞）
    │
    ├──→ asyncio.create_task(git_sync_worker(memory_dict))
    ├──→ asyncio.create_task(r2_backup_worker(memory_dict))
    ├──→ asyncio.create_task(auto_tag_worker(memory_dict))
    └──→ asyncio.create_task(markdown_export_worker(memory_dict))
         │
         ▼ (后台异步，互不影响)
    ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────┐
    │ git_sync   │  │ r2_backup  │  │ auto_tag   │  │ md_export  │
    │ worker     │  │ worker     │  │ worker     │  │ worker     │
    │            │  │            │  │            │  │            │
    │ 写 .md     │  │ 上传 R2    │  │ LLM 标签   │  │ 写 .md     │
    │ git add    │  │            │  │ 更新 meta  │  │             │
    │ git commit │  │            │  │            │  │             │
    │ git push   │  │            │  │            │  │             │
    └────────────┘  └────────────┘  └────────────┘  └────────────┘
```

### 3.3 Worker 错误处理

```python
async def safe_worker(coro, name: str, max_retries: int = 3):
    """Worker 包装器：自动重试 + 错误日志，不影响主流程"""
    for attempt in range(max_retries):
        try:
            await coro
            return
        except Exception as e:
            logger.warning(f"Worker '{name}' attempt {attempt+1} failed: {e}")
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避
    logger.error(f"Worker '{name}' failed after {max_retries} attempts")
```

## 4. Plugin 项目结构

```
memory-os-plugins/
├── pyproject.toml
├── src/
│   └── memory_os_plugins/
│       ├── __init__.py
│       ├── git_sync/
│       │   ├── __init__.py
│       │   ├── plugin.py        # register() + on_store handler
│       │   ├── markdown.py       # Memory → Markdown 转换
│       │   ├── git_ops.py        # git add/commit/push
│       │   └── config.py         # 配置（repo path、commit msg 模板）
│       ├── r2_backup/
│       │   ├── __init__.py
│       │   ├── plugin.py
│       │   ├── s3_client.py      # S3/R2 兼容上传
│       │   └── config.py
│       ├── auto_tag/
│       │   ├── __init__.py
│       │   ├── plugin.py
│       │   ├── extractor.py      # 关键词/主题提取
│       │   └── llm.py            # 可选 LLM 调用
│       └── project_scope/
│           ├── __init__.py
│           ├── plugin.py         # on_retrieve handler: 注入项目级 tag 过滤
│           └── config.py
└── tests/
```

### 4.1 pyproject.toml 关键配置

```toml
[project]
name = "memory-os-plugins"
version = "0.1.0"
dependencies = [
    "mcp-memory-service>=11.5.0",
    "gitpython>=3.1",
    "boto3>=1.34",  # S3/R2 兼容
]

[project.entry-points."mcp_memory_service.plugins"]
git_sync = "memory_os_plugins.git_sync.plugin:register"
r2_backup = "memory_os_plugins.r2_backup.plugin:register"
auto_tag = "memory_os_plugins.auto_tag.plugin:register"
project_scope = "memory_os_plugins.project_scope.plugin:register"
```

**安装后自动生效** — `pip install memory-os-plugins` 即可，不需要改 mcp-memory-service 任何配置。

## 5. 具体 Plugin 代码骨架

### 5.1 git_sync plugin（P1）

```python
# memory_os_plugins/git_sync/plugin.py
"""Git 同步插件：on_store → 写 Markdown → git commit → git push"""

import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# 全局配置，由 register() 初始化
_config = {}

def register(ctx):
    """插件注册入口 — 由 PluginRegistry 自动调用"""
    from .config import load_config
    _config.update(load_config())

    if not _config.get("enabled"):
        logger.info("git_sync plugin disabled")
        return

    ctx.on("on_store", on_store_handler)
    ctx.on("on_delete", on_delete_handler)
    logger.info(f"git_sync plugin registered (repo: {_config['repo_path']})")


async def on_store_handler(memory_dict: dict):
    """存储后：写 Markdown + git commit/push（异步 fire-and-forget）"""
    asyncio.create_task(_git_sync_store(memory_dict))


async def on_delete_handler(content_hash: str):
    """删除后：删除对应 Markdown + git commit/push"""
    asyncio.create_task(_git_sync_delete(content_hash))


async def _git_sync_store(memory_dict: dict):
    from .markdown import memory_to_markdown
    from .git_ops import git_commit_and_push

    try:
        # 1. 写 Markdown 文件
        md_path = _get_md_path(memory_dict["content_hash"])
        md_content = memory_to_markdown(memory_dict)
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(md_content, encoding="utf-8")

        # 2. Git 操作
        git_commit_and_push(
            repo_path=_config["repo_path"],
            files=[str(md_path)],
            message=f"memory: {memory_dict['content'][:50]}",
        )
        logger.debug(f"git_sync: committed {memory_dict['content_hash'][:12]}")
    except Exception as e:
        logger.warning(f"git_sync store failed: {e}")


async def _git_sync_delete(content_hash: str):
    from .git_ops import git_commit_and_push

    try:
        md_path = _get_md_path(content_hash)
        if md_path.exists():
            md_path.unlink()
            git_commit_and_push(
                repo_path=_config["repo_path"],
                files=[str(md_path)],
                message=f"memory: delete {content_hash[:12]}",
            )
    except Exception as e:
        logger.warning(f"git_sync delete failed: {e}")


def _get_md_path(content_hash: str) -> Path:
    """根据 content_hash 生成 Markdown 文件路径"""
    repo = Path(_config["repo_path"])
    # 分目录存储：前2位 hash 做目录名，避免单目录文件过多
    return repo / "memories" / content_hash[:2] / f"{content_hash}.md"
```

### 5.2 Markdown 导出格式

```python
# memory_os_plugins/git_sync/markdown.py
"""Memory → Markdown 转换"""

from datetime import datetime, timezone

def memory_to_markdown(memory_dict: dict) -> str:
    """将 memory_dict 转换为可读 Markdown 文件"""
    tags = memory_dict.get("tags", [])
    tags_str = " ".join(f"#{t}" for t in tags) if tags else ""

    created = memory_dict.get("created_at_iso", "")
    memory_type = memory_dict.get("memory_type", "observation")
    content_hash = memory_dict.get("content_hash", "")

    lines = [
        f"---",
        f"hash: {content_hash}",
        f"type: {memory_type}",
        f"tags: [{', '.join(tags)}]",
        f"created: {created}",
        f"---",
        f"",
        f"{memory_dict.get('content', '')}",
        f"",
    ]

    # 附加 metadata
    metadata = memory_dict.get("metadata", {})
    if metadata:
        lines.append("## Metadata")
        for k, v in metadata.items():
            lines.append(f"- **{k}**: {v}")
        lines.append("")

    return "\n".join(lines)
```

### 5.3 auto_tag plugin（P3）

```python
# memory_os_plugins/auto_tag/plugin.py
"""自动标签插件：on_store → 关键词提取 → 更新 tags"""

import asyncio
import logging

logger = logging.getLogger(__name__)

async def on_store_handler(memory_dict: dict):
    asyncio.create_task(_auto_tag(memory_dict))

async def _auto_tag(memory_dict: dict):
    from .extractor import extract_tags
    from ..common.service_access import update_memory_tags

    try:
        content = memory_dict.get("content", "")
        existing_tags = set(memory_dict.get("tags", []))

        # 提取关键词标签
        new_tags = extract_tags(content)
        merged = list(existing_tags | set(new_tags))

        if len(merged) > len(existing_tags):
            # 更新存储中的 tags
            await update_memory_tags(
                memory_dict["content_hash"],
                merged
            )
            logger.debug(f"auto_tag: added {set(new_tags) - existing_tags}")
    except Exception as e:
        logger.warning(f"auto_tag failed: {e}")
```

### 5.4 project_scope plugin（P2）

```python
# memory_os_plugins/project_scope/plugin.py
"""项目级记忆过滤：on_retrieve → 注入项目 tag 过滤"""

import os
import logging

logger = logging.getLogger(__name__)

_config = {}

def register(ctx):
    from .config import load_config
    _config.update(load_config())
    ctx.on("on_retrieve", on_retrieve_handler)

async def on_retrieve_handler(query: str, results: list):
    """对检索结果按项目作用域排序/过滤"""
    project_tag = _config.get("project_tag")
    if not project_tag:
        return results

    # 不过滤掉非项目记忆，但项目级记忆排在前面
    project_results = [r for r in results if project_tag in r.get("tags", [])]
    other_results = [r for r in results if project_tag not in r.get("tags", [])]

    return project_results + other_results
```

## 6. Plugin 配置方案

每个 plugin 通过环境变量或 YAML 配置文件配置：

```yaml
# ~/.memory-os/config.yml
git_sync:
  enabled: true
  repo_path: ~/AgentMemory
  auto_push: true
  commit_message_template: "memory: {preview}"

r2_backup:
  enabled: false  # P2 阶段启用
  endpoint: https://{account_id}.r2.cloudflarestorage.com
  bucket: memory-backup
  access_key: ${R2_ACCESS_KEY}
  secret_key: ${R2_SECRET_KEY}

auto_tag:
  enabled: false  # P3 阶段启用
  method: keyword  # keyword | llm
  llm_base_url: http://localhost:11434/v1

project_scope:
  project_tag: proj:current-project
```

**加载顺序：** 环境变量 > config.yml > 默认值

## 7. 验证方案

### 7.1 单元测试

每个 plugin 独立测试，mock `PluginContext`：

```python
# tests/test_git_sync_plugin.py
import pytest
from unittest.mock import AsyncMock, MagicMock
from memory_os_plugins.git_sync.plugin import register, on_store_handler

@pytest.mark.asyncio
async def test_on_store_creates_markdown(tmp_path):
    ctx = MagicMock()
    ctx.on = MagicMock()
    register(ctx)

    # 模拟 on_store 调用
    memory_dict = {
        "content": "test memory",
        "content_hash": "abc123",
        "tags": ["test"],
    }
    await on_store_handler(memory_dict)

    # 等待 asyncio task 完成
    await asyncio.sleep(1)

    # 验证 Markdown 文件已创建
    assert (tmp_path / "memories" / "ab" / "abc123.md").exists()
```

### 7.2 集成测试

启动真实 mcp-memory-service + plugin，验证端到端流程：

```bash
# 1. 安装 plugin
pip install -e .

# 2. 启动服务
memory launch

# 3. 存储记忆
curl -X POST http://127.0.0.1:8000/api/memories \
  -H "Content-Type: application/json" \
  -d '{"content": "test integration", "tags": ["test"]}'

# 4. 验证 Markdown 已生成
ls ~/AgentMemory/memories/

# 5. 验证 git commit
cd ~/AgentMemory && git log --oneline -1
```
