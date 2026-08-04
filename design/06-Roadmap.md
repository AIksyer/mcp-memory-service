# 06 — 实施路线图

> 每个 Phase 有明确的交付物、验证标准和预计工作量。前一 Phase 的验证通过后再进入下一 Phase。

## 当前状态

| 项目 | 状态 | 日期 |
|------|------|------|
| mcp-memory-service v11.5.5 安装 | ✅ | 2026-07-29 |
| SQLite-Vec 本地存储运行 | ✅ | 2026-07-29 |
| HTTP 服务 + Dashboard | ✅ | 2026-07-29 |
| MCP 接入 Codely CLI | ✅ | 2026-07-29 |
| 第一条记忆存储 + 语义搜索 | ✅ | 2026-07-29 |
| 设计文档完成 | ✅ | 2026-07-29 |

---

## P1: Git 同步 + Markdown 导出

**目标：** Agent 每次存储记忆，自动写 Markdown + git commit + push

### 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | `memory-os-plugins` pip 包 | 包含 git_sync plugin |
| 2 | Git 仓库初始化脚本 | `memory-os init` |
| 3 | Markdown 导出格式 | frontmatter + content |
| 4 | 批量提交队列 | 避免高频存储时过多 git commit |
| 5 | GitHub Private Repo | 存储所有 Markdown 记忆 |

### 工作分解

```
1. 创建 memory-os-plugins 项目骨架           (1h)
2. 实现 markdown.py (Memory → Markdown)      (1h)
3. 实现 git_ops.py (add/commit/push/pull)     (2h)
4. 实现 plugin.py (register + on_store hook) (1h)
5. 实现批量提交队列 GitSyncQueue              (2h)
6. 实现 memory-os init CLI 命令               (1h)
7. 测试 + 文档                                 (2h)
```

**预计工作量：** 1-2 天

### 验证标准

```bash
# 1. 安装 plugin
pip install -e memory-os-plugins

# 2. 初始化 Git 仓库
memory-os init --repo ~/AgentMemory

# 3. 启动服务
memory launch

# 4. 存储记忆
curl -X POST http://127.0.0.1:8000/api/memories \
  -d '{"content":"测试 Git 同步","tags":["test"]}'

# 5. 等待 5 秒
sleep 5

# 6. 验证 Markdown 文件
ls ~/AgentMemory/memories/

# 7. 验证 git log
cd ~/AgentMemory && git log --oneline -1
# 预期输出: <hash> memory: 测试 Git 同步

# 8. 验证 git push (如果配置了远端)
git status  # 应该是 clean (已 push)
```

---

## P2: R2 备份 + GitHub Actions + 跨项目拉取

**目标：** Git push 触发 GitHub Actions → R2/S3 自动备份；新项目可拉取已有记忆

### 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | GitHub Actions workflow | push → R2 同步 |
| 2 | r2_backup plugin | on_store → 直接上传 R2（可选，与 Actions 互补） |
| 3 | memory-os pull 命令 | 拉取远端记忆到本地 |
| 4 | memory-os export/import | JSON 导出/导入 |
| 5 | R2 Bucket 创建 + 配置 | Cloudflare 免费额度 |

### 工作分解

```
1. 创建 Cloudflare R2 Bucket + API Token       (30min)
2. 编写 GitHub Actions workflow (rclone)       (2h)
3. 配置 GitHub Secrets                         (30min)
4. 实现 memory-os pull 命令                     (2h)
5. 实现 memory-os export/import (复用上游)     (1h)
6. 测试灾难恢复流程                             (2h)
```

**预计工作量：** 2-3 天

### 验证标准

```bash
# 1. 存储记忆 → 自动 push → GitHub Actions 触发
# 2. 在 GitHub Actions 页面查看 workflow 执行成功
# 3. 在 R2 Dashboard 查看备份文件

# 4. 灾难恢复测试
memory stop
rm ~/AppData/Local/mcp-memory/sqlite_vec.db  # 模拟数据丢失
memory-os pull  # 从 Git + R2 恢复
memory launch
curl http://127.0.0.1:8000/api/search \
  -d '{"query":"test"}'  # 验证记忆已恢复
```

---

## P3: 三级记忆 + 自动标签

**目标：** 记忆自动分层（Project/Personal/Global），自动提取标签

### 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | project_scope plugin | on_store 注入 scope tags + on_retrieve 重排 |
| 2 | auto_tag plugin | on_store → 关键词提取 → 更新 tags |
| 3 | memory-os switch 命令 | 切换项目 |
| 4 | 配置文件 ~/.memory-os/config.yml | 统一配置 |

### 工作分解

```
1. 实现 project_scope plugin (on_store + on_retrieve)   (3h)
2. 实现 auto_tag extractor (关键词词典)                  (2h)
3. 实现 auto_tag LLM 集成 (可选, Ollama)                 (2h)
4. 实现 memory-os switch CLI                              (1h)
5. 实现配置文件加载                                        (1h)
6. 测试 + 验证                                             (2h)
```

**预计工作量：** 2 天

### 验证标准

```bash
# 1. 切换到项目
memory-os switch --project mall

# 2. 存储项目级记忆
curl -X POST http://127.0.0.1:8000/api/memories \
  -d '{"content":"商城支付坑","tags":["payment"]}'

# 3. 验证 tag 自动注入
curl -X POST http://127.0.0.1:8000/api/search \
  -d '{"query":"payment"}' | jq '.results[0].tags'
# 预期: ["payment", "proj:mall", "user:27933", ...]

# 4. 切换到另一个项目
memory-os switch --project game

# 5. 搜索 — 项目级记忆应该排在个人级后面
curl -X POST http://127.0.0.1:8000/api/search \
  -d '{"query":"payment"}' | jq '.results[0].tags'
# 预期: proj:mall 的结果排在 proj:game 的后面
```

---

## P4: Qdrant 后端 + 生命周期 Hooks

**目标：** 接入 Qdrant 向量库；实现 onSessionStart/End 自动记忆

### 交付物

| # | 交付物 | 说明 |
|---|--------|------|
| 1 | Qdrant storage backend | 继承 BaseStorage |
| 2 | storage factory 注册 | 添加到 factory.py elif 分支 |
| 3 | onSessionStart hook | 自动拉取相关记忆 |
| 4 | onSessionEnd hook | 自动总结 → 存储 → 同步 |
| 5 | Codely CLI hooks 配置 | session 生命周期集成 |

### 工作分解

```
1. 实现 QdrantStorage(BaseStorage)              (8h)
2. 注册到 factory.py                             (1h)
3. 测试 Qdrant 后端                              (4h)
4. 设计 session hook 协议                        (2h)
5. 实现 onSessionEnd 自动总结                    (4h)
6. Codely CLI hooks 集成                         (2h)
7. 测试 + 文档                                    (3h)
```

**预计工作量：** 3-4 天

### 验证标准

```bash
# 1. 切换到 Qdrant 后端
export MCP_MEMORY_STORAGE_BACKEND=qdrant
memory launch

# 2. 验证存储 + 检索
curl -X POST http://127.0.0.1:8000/api/memories \
  -d '{"content":"qdrant test","tags":["test"]}'
curl -X POST http://127.0.0.1:8000/api/search \
  -d '{"query":"qdrant"}'

# 3. 验证 session hooks
# 启动 Codely CLI → 自动拉取记忆
# 结束 session → 自动总结存储
```

---

## 长期演进方向（P5+）

| 方向 | 说明 | 优先级 |
|------|------|--------|
| **Cloudflare Hybrid 后端** | 启用上游已有的 CloudflareStorage + HybridStorage | 可随时启用 |
| **团队协作** | OAuth 2.1 + 多用户 + 权限控制（上游已实现） | 按需 |
| **Dashboard 增强** | 知识图谱 3D 可视化（上游已实现） | 按需 |
| **Remote MCP** | claude.ai 浏览器直接连接（上游已实现） | 按需 |
| **Insight Cards** | 模式发现 + 趋势分析（上游已实现） | 启用 consolidation |
| **Multi-store** | 物理分区存储（上游 store 参数已支持） | P4 后 |
| **Memory OS daemon** | 常驻后台服务（已有 memory launch） | 已满足 |

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| 上游大版本更新破坏 plugin API | 低 | 中 | 锁定版本 + plugin 只依赖 4 个核心 hooks |
| 上游作者停更 | 低 | 高 | Apache 2.0 允许 Fork 自救 |
| Git push 频率过高被 GitHub 限制 | 低 | 低 | 批量提交队列（P1 已解决） |
| R2 免费额度用尽 | 极低 | 低 | 10GB 足够 500 万条记忆 |
| Python 3.14 兼容性 | 低 | 中 | 已验证 SQLite+ONNX 可运行 |
| 插件 handler 异常影响主流程 | 极低 | 低 | 上游已有 try/except 隔离 |

## 总结

```
P0 ✅ 已完成    — 本地部署 + MCP 接入
P1 ⬜ 1-2 天    — Git 同步 + Markdown 导出
P2 ⬜ 2-3 天    — R2 备份 + GitHub Actions + 跨项目拉取
P3 ⬜ 2 天      — 三级记忆 + 自动标签
P4 ⬜ 3-4 天    — Qdrant + 生命周期 Hooks

总计：约 8-11 个工作日完成全部 P1-P4
```

**核心原则：** 每个 Phase 交付可独立使用的功能，不依赖后续 Phase。P1 完成后就有可用的 Git 同步，P2 完成后就有容灾备份，P3 完成后就有项目分层。不需要全部完成才能用。
