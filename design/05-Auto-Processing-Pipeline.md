# 05 — 自动处理管道设计

> 本文档定义 on_store 事件触发的全自动处理管道，以及上游已有遗忘机制的分析。

## 1. on_store 全自动管道

### 1.1 管道总览

```
Agent: memory.save(content, tags, metadata)
    │
    ▼
┌─────────────────────────────────────────────────┐
│  MemoryService.store_memory()                    │
│  • normalize_tags()          ← 上游已有          │
│  • content_hash 生成         ← 上游已有          │
│  • 语义去重检查               ← 上游已有          │
│  • content_splitter (分片)   ← 上游已有          │
│  • storage.store(memory)     ← 上游已有          │
│  • async_scorer (质量评分)   ← 上游已有          │
│  • _maybe_link_entities()    ← 上游已有          │
│  • plugin_registry.fire('on_store', memory_dict) │
└───────────────────┬─────────────────────────────┘
                    │
    ┌───────────────┼───────────────┐
    ▼               ▼               ▼
┌────────┐   ┌──────────┐   ┌───────────┐
│git_sync│   │auto_tag  │   │r2_backup  │
│plugin  │   │plugin    │   │plugin     │
│        │   │(P3)     │   │(P2)      │
├────────┤   ├──────────┤   ├───────────┤
│写 .md  │   │关键词提取│   │上传 R2   │
│git add │   │LLM 摘要  │   │          │
│git push│   │更新 tags │   │          │
└────────┘   └──────────┘   └───────────┘
    │               │               │
    ▼               ▼               ▼
 GitHub Actions    metadata         R2/S3
 触发 R2/S3       更新完成          备份完成
 备份
```

### 1.2 管道各阶段延迟估算

| 阶段 | 耗时 | 阻塞主流程？ |
|------|------|-------------|
| normalize_tags + hash + dedup + store | ~5ms | ✅ 是（必须） |
| 质量评分 (ONNX) | 80-150ms | ❌ 后台 async |
| 实体链接 | ~10ms | ❌ 后台 async |
| **on_store hooks:** | | ❌ 全部后台 |
| ├─ git_sync: 写 Markdown | ~2ms | ❌ asyncio task |
| ├─ git_sync: git commit + push | ~2-5s | ❌ asyncio task |
| ├─ auto_tag: 关键词提取 | ~5ms | ❌ asyncio task |
| ├─ auto_tag: LLM 标签 (可选) | ~500ms | ❌ asyncio task |
| └─ r2_backup: 上传 R2 | ~200ms | ❌ asyncio task |

**主流程延迟（Agent 感知到的）：** ~15ms（存储 + 实体链接）
**后台总延迟（全部完成）：** ~3-6s（主要瓶颈是 git push）

### 1.3 为什么 git push 不阻塞

```python
# on_store handler 中
async def on_store_handler(memory_dict: dict):
    asyncio.create_task(_git_sync_store(memory_dict))  # ← 立即返回
    # handler 本身 < 1ms 就返回了
```

Agent 调用 `memory.save()` 后立即得到响应。Git push 在后台 3-5 秒完成。如果 push 失败，自动重试 3 次，不影响存储结果。

## 2. 自动标签提取

### 2.1 方案对比

| 方案 | 延迟 | 准确度 | 依赖 | 推荐 |
|------|------|--------|------|------|
| 关键词提取 (TF-IDF/RAKE) | ~5ms | 中 | 无外部依赖 | P3 首选 |
| 本地 LLM (Ollama) | ~500ms | 高 | Ollama 运行 | P3 可选 |
| 云端 LLM (OpenAI/Groq) | ~300ms | 高 | API key | 不推荐（成本+隐私） |
| 上游实体提取 | ~10ms | 中 | 上游已有 | 立即可用 |

### 2.2 上游已有的实体提取

上游 `extraction/` 模块已实现：
- NER（命名实体识别）
- @mentions 提取（`@Supabase`）
- #tags 提取（`#jwt`）
- URL 提取
- 文件路径提取

这些在 `_maybe_link_entities()` 中自动调用，创建知识图谱边。**但不会自动将提取的实体添加到 tags 中** — 这正是 auto_tag plugin 要做的。

### 2.3 auto_tag plugin 实现

```python
# memory_os_plugins/auto_tag/extractor.py
"""关键词/主题标签提取"""

import re
from collections import Counter

# 技术栈关键词词典（可扩展）
TECH_KEYWORDS = {
    # 前端
    "react", "vue", "angular", "nextjs", "next.js", "vite", "webpack",
    "typescript", "javascript", "css", "tailwind", "sass",
    # 后端
    "python", "django", "flask", "fastapi", "node", "express", "go",
    "rust", "java", "spring", "csharp",
    # 数据库
    "postgres", "postgresql", "mysql", "redis", "mongodb", "sqlite",
    "supabase", "firebase", "d1", "turso",
    # 基础设施
    "docker", "kubernetes", "k8s", "nginx", "cloudflare", "vercel",
    "aws", "gcp", "azure",
    # AI/ML
    "openai", "claude", "llm", "embedding", "rag", "mcp",
    "langchain", "langgraph", "crewai",
}

def extract_tags(content: str, max_tags: int = 5) -> list[str]:
    """从内容中提取关键词标签"""
    content_lower = content.lower()

    # 1. 匹配技术栈关键词
    found = set()
    for keyword in TECH_KEYWORDS:
        # 使用词边界匹配，避免 "react" 匹配 "reactive"
        pattern = r'\b' + re.escape(keyword) + r'\b'
        if re.search(pattern, content_lower):
            found.add(keyword)

    # 2. 提取 #hashtags
    hashtags = re.findall(r'#(\w+)', content)
    found.update(t.lower() for t in hashtags)

    # 3. 提取错误代码模式 (如 ERR_001, ECONNREFUSED)
    error_codes = re.findall(r'\b([A-Z]{2,}_\d+|[A-Z]{4,})\b', content)
    found.update(code.lower() for code in error_codes[:2])

    return list(found)[:max_tags]
```

### 2.4 可选：LLM 摘要生成

```python
# memory_os_plugins/auto_tag/llm.py
"""使用本地 LLM 生成标题和摘要"""

async def generate_title_and_summary(content: str) -> dict:
    """调用 Ollama 或其他 OpenAI 兼容 API 生成标题和摘要"""
    import httpx

    prompt = f"""分析以下技术记忆，生成：
1. 一个简短标题（< 50 字符）
2. 一句话摘要（< 100 字符）

内容：{content[:500]}

返回 JSON: {{"title": "...", "summary": "..."}}
"""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "http://localhost:11434/v1/chat/completions",
            json={
                "model": "qwen2.5:7b-instruct",
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
                "temperature": 0.1,
            },
            timeout=5.0,
        )
        return resp.json()["choices"][0]["message"]["content"]
```

## 3. 遗忘机制（上游已有实现分析）

### 3.1 上游遗忘系统架构

```
consolidation/
├── scheduler.py          ← APScheduler 定时触发
├── consolidator.py       ← 主整理器（编排各阶段）
├── decay.py              ← 衰减评分（时间 + 访问频率）
├── forgetting.py         ← 遗忘引擎（归档/压缩/删除）
├── compression.py        ← 语义压缩（合并相似记忆）
├── clustering.py        ← 语义聚类
├── relationship_inference.py  ← 关系推断
├── contradictions.py    ← 矛盾检测
├── belief.py            ← 信念推导
└── insights.py          ← 模式发现（Insight Cards）
```

### 3.2 衰减评分（decay.py）

`RelevanceScore` dataclass 计算每条记忆的相关性：

```python
# 衰减因子（基于源码分析）：
# 1. 时间衰减：越老的记忆相关性越低
# 2. 访问频率：越常被访问的记忆相关性越高
# 3. 质量分数：高质量记忆衰减更慢
# 4. 重要性：高重要性记忆衰减更慢
```

**保留策略（retention）按质量分层：**
- 高质量 (score > 0.7)：保留 365 天
- 中质量 (0.3 < score < 0.7)：保留 180 天
- 低质量 (score < 0.3)：保留 30-90 天

### 3.3 遗忘操作（forgetting.py）

`ControlledForgettingEngine` 不是直接删除，而是：

1. **归档（Archive）** — 低相关性记忆移到归档目录
2. **压缩（Compress）** — 相似记忆合并为一条摘要
3. **删除（Delete）** — 归档超过 N 天且从未被访问的记忆

```python
# forgetting.py 归档目录结构
~/.mcp_memory_archive/
├── daily/         ← 日常归档
├── compressed/    ← 压缩后的记忆
└── metadata/      ← 归档元数据
```

### 3.4 调度配置

上游使用 APScheduler，所有调度默认为 'disabled'（安全第一）：

```bash
# .env 中启用
MCP_CONSOLIDATION_ENABLED=true
MCP_SCHEDULE_DAILY=02:00          # 每天凌晨 2 点整理
MCP_SCHEDULE_WEEKLY=SUN 03:00     # 每周日凌晨 3 点深度整理
MCP_SCHEDULE_MONTHLY=01 04:00     # 每月 1 号凌晨 4 点月度整理
```

### 3.5 我们的增强方向

上游遗忘机制已经很完善，我们只需要：

1. **on_consolidate hook** — 整理完成后触发 Git 同步（删除/压缩的记忆需要在 Markdown 仓库中同步）
2. **重要性配置** — 通过 `metadata.importance` 字段手动标记重要记忆（不衰减）
3. **自定义保留策略** — 通过 plugin 配置覆盖默认的保留天数

## 4. 完整存储流程示例

```
Agent: "记住这个：Supabase JWT 无限刷新是因为 middleware 没检查 token 过期"

memory.save(
    content="Supabase JWT 无限刷新是因为 middleware 没检查 token 过期",
    tags=["supabase", "jwt", "bug"],
    metadata={"type": "bug"}
)
    │
    ▼ (~5ms)
MemoryService:
    • normalize_tags → ["supabase", "jwt", "bug"]
    • hash → "a3f8b2..."
    • dedup → 新记忆，不重复
    • storage.store() → SQLite + embedding 写入
    • quality_scorer → 0.85 (后台)
    • entity_link → supabase ↔ jwt (知识图谱边)
    • fire('on_store', memory_dict)
        │
        ├── git_sync (async, <1ms to return)
        │   • 写 memories/a3/a3f8b2....md
        │   • git add + commit + push (后台 3s)
        │
        ├── auto_tag (async, <1ms to return)
        │   • extract_tags → ["supabase", "jwt", "middleware", "token"]
        │   • update_memory_metadata(tags=merged_tags) (后台)
        │
        └── project_scope (async, <1ms to return)
            • 注入 proj:current-project tag (后台)

Agent 得到响应 (~15ms 总延迟)
    │
    │ (后台 3-5 秒)
    ▼
Git 仓库已更新 → GitHub Actions 触发 → R2 备份完成
```

## 5. 验证方案

### 5.1 管道完整性测试

```bash
# 1. 存储一条记忆
curl -X POST http://127.0.0.1:8000/api/memories \
  -d '{"content":"test pipeline","tags":["test"]}'

# 2. 等待后台任务完成
sleep 5

# 3. 验证 Markdown 已生成
ls ~/AgentMemory/memories/*/

# 4. 验证 Git 已推送
cd ~/AgentMemory && git log --oneline -1

# 5. 验证 tags 已增强（如果 auto_tag 启用）
curl -X POST http://127.0.0.1:8000/api/search \
  -d '{"query":"test pipeline"}' | jq '.results[0].tags'

# 6. 验证 R2 备份（如果 GitHub Actions 已配置）
# 在 GitHub Actions 页面查看 workflow 执行状态
```

### 5.2 性能基准

```python
# tests/benchmark_pipeline.py
import pytest
import time

@pytest.mark.asyncio
async def test_store_latency(test_store):
    """验证主流程延迟 < 50ms"""
    start = time.time()
    result = await test_store.store(Memory(
        content="benchmark test",
        content_hash="bench_001",
        tags=["bench"],
    ))
    elapsed = (time.time() - start) * 1000
    assert elapsed < 50  # 50ms 阈值
    assert result[0] is True  # success
```
