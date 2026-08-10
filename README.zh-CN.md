# mcp-memory-service

[English](README.md) | [中文](README.zh-CN.md)

## AI Agent 持久化共享记忆

开源 AI Agent 记忆后端 — **REST API、MCP、OAuth、CLI、Web 面板**。一个自托管服务，支持所有传输协议。
Agent 存储决策、共享因果知识图谱、5ms 检索上下文 — 无云锁定、零 API 费用。

**兼容 LangGraph · CrewAI · AutoGen · 任何 HTTP 客户端 · Claude Desktop · OpenCode**

---

[![Website](https://img.shields.io/badge/Website-mcpmemory.services-00e5ff?logo=cloudflare&logoColor=white)](https://mcpmemory.services)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![PyPI version](https://img.shields.io/pypi/v/mcp-memory-service?color=blue&logo=pypi&logoColor=white)](https://pypi.org/project/mcp-memory-service/)
[![Python](https://img.shields.io/pypi/pyversions/mcp-memory-service?logo=python&logoColor=white)](https://pypi.org/project/mcp-memory-service/)
[![Codeberg stars](https://img.shields.io/gitea/stars/doobidoo/mcp-memory-service?gitea_url=https%3A%2F%2Fcodeberg.org&logo=codeberg&label=stars)](https://codeberg.org/doobidoo/mcp-memory-service)

---

## 为什么需要这个

你的 AI 助手每次新对话都忘记一切。你又花 10 分钟重新解释项目架构。**又是这样。** MCP Memory Service 自动捕获项目上下文、架构决策和代码模式 — 新会话开始时一切都已知。

| 没有 mcp-memory-service | 有 mcp-memory-service |
|---|---|
| 每次 Agent 运行从零开始 | Agent 在 5ms 内检索之前的决策 |
| 记忆仅限于一次会话 | 记忆在所有 Agent 和会话间共享 |
| 你需要管理 Redis + Pinecone + 胶水代码 | 一个自托管服务，零云费用 |
| 事实之间没有因果关系 | 知识图谱带类型化边（因果、修复、矛盾） |
| 上下文窗口限制导致遗忘 | 自动压缩旧记忆 |

---

## 🚀 60 秒快速开始

> 不确定哪种方式适合你？查看 **[安装指南](docs/setup-guide.md)** — 决策树一分钟内带你找到正确路径。

**1. 安装：**

```bash
pip install mcp-memory-service
```

**2. 运行安装向导：**

```bash
memory setup
```

向导会引导你完成：
1. 存储后端选择（SQLite / Cloudflare / 混合模式）
2. Cloudflare 凭证（如选择云端/混合）
3. 备份目标（本地 / R2 / GitHub 私密仓库）
4. MCP 客户端配置（Claude Desktop / Claude Code / Cursor）
5. 自动生成 `.env` 和 MCP 客户端配置文件

**非交互模式（适合 Agent/脚本）：**

```bash
# 仅本地（最简单，无需云端）
memory setup --non-interactive --backend sqlite_vec --mcp-client claude-code

# 混合模式（本地 + Cloudflare 同步 + R2 备份）
memory setup --non-interactive \
  --backend hybrid \
  --cf-token 你的CF令牌 \
  --cf-account 你的账户ID \
  --cf-d1 D1数据库ID \
  --backup-r2 \
  --mcp-client claude-code
```

**3. 启动服务器：**

```bash
memory launch
```

**4. 验证：**

```bash
memory info
curl http://127.0.0.1:8000/api/health
```

---

<details>
<summary><strong>手动配置 MCP 客户端（不用向导）</strong></summary>

**Claude Desktop：**

在配置文件中添加：
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux**: `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "memory": {
      "command": "memory",
      "args": ["server"]
    }
  }
}
```

**Claude Code：**

```bash
claude mcp add memory -- memory server
```

**Agent 管线（REST API — LangGraph、CrewAI、AutoGen、任何 HTTP 客户端）：**

```bash
MCP_ALLOW_ANONYMOUS_ACCESS=true memory server --http
# REST API 运行在 http://localhost:8000
```

```python
import asyncio
import httpx

BASE_URL = "http://localhost:8000"

async def main():
    async with httpx.AsyncClient() as client:
        await client.post(f"{BASE_URL}/api/memories", json={
            "content": "API 速率限制是每分钟 100 次",
            "tags": ["api", "limits"],
        }, headers={"X-Agent-ID": "researcher"})
        
        results = await client.post(f"{BASE_URL}/api/memories/search", json={
            "query": "API 速率限制",
            "tags": ["agent:researcher"],
        })
        print(results.json()["memories"])

asyncio.run(main())
```

</details>

---

## ✨ 功能特性

🧠 **持久记忆** – 上下文跨会话保留，支持语义搜索
🔍 **智能检索** – 使用 AI 嵌入自动查找相关上下文
⚡ **5ms 速度** – 即时上下文注入，零延迟
🔄 **多客户端** – 兼容 25+ AI 应用
☁️ **云端同步** – 可选 Cloudflare 后端，支持团队协作
🔒 **隐私优先** – 本地优先，你控制自己的数据
📊 **Web 面板** – 在 `http://localhost:8000` 可视化管理记忆
🧬 **知识图谱** – 交互式 D3.js 可视化记忆关系
🏠 **本地质量评分** – 支持任意 OpenAI 兼容端点（Ollama、LiteLLM、vLLM）
🔗 **实体提取** – 自动链接 @提及、#标签、URL 和文件路径
💡 **洞察卡片** – 自动检测记忆库中的模式、趋势和知识盲区
💾 **R2 备份恢复** – 从 Cloudflare R2 经 staging 恢复，含完整性校验
🔄 **同步版本治理** – `sync_version` 递增 + 冲突检测 + 多设备 `device_id`
⏳ **备份隔离** – 新备份 24h 隔离期后才可用于恢复

---

## 存储后端选择

| 后端 | 适用场景 | 性能 | 说明 |
|------|---------|------|------|
| **SQLite-vec** | 本地开发、单用户 | 5ms 读取 | 默认，零配置 |
| **Cloudflare** | 纯云端 | 取决于网络 | 多设备同步 |
| **混合模式** | 生产环境（推荐） | 5ms 本地 + 云同步 | 本地速度 + 云持久性 |
| **Milvus** | 专用向量数据库 | 可变 | Milvus Lite / 自托管 / Zilliz Cloud |

---

## 备份方案

通过 `memory setup` 可自由选择备份目标组合：

| 方案 | 配置 |
|------|------|
| 仅本地备份 | 默认，零配置 |
| 本地 + R2 | `MCP_BACKUP_R2_ENABLED=true` |
| 本地 + GitHub 私密仓库 | `MCP_BACKUP_GITHUB_ENABLED=true` |
| 本地 + R2 + GitHub（三重冗余） | 两者都启用 |

备份通过内置调度器自动运行（默认每日），也可手动触发：
```bash
curl -X POST http://127.0.0.1:8000/api/backup/push-remote
```

### R2 备份恢复（v3）

从 R2 恢复数据库到本地，经过 staging 验证：
```bash
# 从最新的 R2 备份恢复
curl -X POST http://127.0.0.1:8000/api/backup/restore \
  -H "X-API-Key: $KEY"

# 从指定备份恢复
curl -X POST "http://127.0.0.1:8000/api/backup/restore?object_key=backups/sqlite_vec_20260810.db" \
  -H "X-API-Key: $KEY"
```

恢复流程：R2 下载 → staging 完整性检查 → schema 版本兼容性检查 → 备份当前 DB → 替换。
**恢复后不会自动同步 D1**（防止已删除记忆复活）。

### 存储压力清理（v3）

R2 旧备份仅在存储用量超过阈值时才删除（默认 8GB），而非基于时间自动清理：
```bash
# 自定义阈值（GB）
MCP_BACKUP_R2_STORAGE_PRESSURE_THRESHOLD=8
```

### 同步版本治理（v4）

每次写入自动递增 `sync_version`，用于多设备冲突检测：

- `store()` 设置 `sync_version=1`
- `update_memory_metadata()` 递增 `sync_version+1`
- `device_id` 标识写入来源设备（`MCP_DEVICE_ID` 环境变量）

双向对账时，`sync_version` 高的一方胜出（无需容差检查），相等时回退到 `updated_at`。

### 冲突检测与解决（v4）

当本地和云端 `sync_version` 不一致时，自动记录到 `backup_conflicts` 表：
```bash
# 查看未解决冲突
curl -H "X-API-Key: $KEY" http://localhost:8000/api/backup/conflicts

# 标记冲突已解决
curl -X POST "http://localhost:8000/api/backup/conflicts/resolve?conflict_id=1&resolution=manual" \
  -H "X-API-Key: $KEY"
```

### 备份隔离（v4）

新 R2 备份先上传到 `pending/` 前缀，经过隔离期（默认 24 小时）后才提升为 `backups/`：
```bash
# 自定义隔离时间（小时）
MCP_BACKUP_R2_QUARANTINE_HOURS=24
```

> 📖 完整备份系统文档见 [docs/backup-system.md](docs/backup-system.md)

---

## 云端部署（高可用）

混合模式支持云端部署，实现本地 + 云端双 MCP：

```json
{
  "mcpServers": {
    "memory": {
      "command": "memory",
      "args": ["server"]
    },
    "memory-cloud": {
      "url": "https://你的云端地址/mcp"
    }
  }
}
```

- `memory`（本地）— 主用，~5ms 读取
- `memory-cloud` — 本地离线时的兜底

---

## 兼容工具

#### 🤖 Agent 框架（REST API）
**LangGraph** · **CrewAI** · **AutoGen** · **任何 HTTP 客户端**

#### 🖥️ CLI 和终端 AI（MCP）
**Claude Code** · **Gemini CLI** · **OpenCode** · **Codex CLI** · **Goose** · **Aider** · **Continue** · **Zed** · **Cody**

#### 🎨 桌面和 IDE（MCP）
**Claude Desktop** · **VS Code** · **Cursor** · **Windsurf** · **JetBrains** · **Replit**

#### 💬 聊天界面（MCP）
**ChatGPT**（开发者模式）· **claude.ai**（远程 MCP via HTTPS）

---

## 服务器管理（CLI）

```bash
memory launch                  # 后台启动 HTTP 服务器 (127.0.0.1:8000)
memory launch --port 8192      # 自定义端口
memory info                    # 状态和健康检查
memory logs --lines 50         # 查看日志
memory stop                    # 停止服务器
memory setup                   # 交互式配置向导
```

---

## 嵌入模型选择

默认模型（`all-MiniLM-L6-v2`）适用于**纯英文**内容。如果存储中文或其他语言记忆，请切换多语言模型：

```bash
export MCP_EMBEDDING_MODEL=paraphrase-multilingual-MiniLM-L12-v2
```

> ⚠️ **切换模型需要重新嵌入已有记忆**：停止服务，运行 `python scripts/maintenance/regenerate_embeddings.py`，重启。

---

## 📚 文档与资源

- **[安装指南](docs/setup-guide.md)** – 决策树 + 所有场景的分步指南
- **[配置指南](docs/mastery/configuration-guide.md)** – 后端选项和自定义配置
- **[架构概述](docs/architecture.md)** – 底层工作原理
- **[备份系统](docs/backup-system.md)** – R2 备份、恢复、隔离、同步版本、冲突检测（二开）
- **[远程 MCP 设置](docs/remote-mcp-setup.md)** – 浏览器集成 via HTTPS + OAuth
- **[知识图谱面板](docs/features/knowledge-graph-dashboard.md)** – 交互式图谱可视化
- **[故障排除](docs/troubleshooting/)** – 常见问题和解决方案
- **[Wiki](https://codeberg.org/doobidoo/mcp-memory-service/wiki)** – 完整文档
- **[变更日志](CHANGELOG.md)** – 版本历史

---

## 🤝 贡献

欢迎贡献！查看 [CONTRIBUTING.md](CONTRIBUTING.md) 了解指南。

**快速开发设置：**
```bash
git clone https://codeberg.org/doobidoo/mcp-memory-service.git
cd mcp-memory-service
pip install -e .  # 可编辑安装
pytest tests/      # 运行测试
```

---

## License

Apache 2.0 — 见 [LICENSE](LICENSE)
