# CanMatrix MCP 服务器（canmatrix_mcp）设计文档

日期：2026-11-03
状态：已评审、已批准（含两处用户修正：改密码不吊销 PAT；撤销栈 v1 不隔离、为未来文件版本管理预留）

## 意图与背景

CanMatrix Editor 是 CAN 报文/信号编辑工具：Python 后端（HTTP + WebSocket，session 中心）+ Vue 前端，Properties 为主存储，支持 DBC 导入/导出、C 代码生成、位域校验、撤销/重做、多用户（token 认证、文件锁、文件所有权）。

本设计新增一个 MCP 服务器，让 AI 客户端（Claude Code / OpenCode 等）完成界面上的全部**编辑类**操作：导入 DBC、查询/增删改报文与信号、值表管理、数据错误校验、撤销/重做、保存/另存为、导出 properties / DBC / C 头文件 / C 源文件。

**工作模式**：AI 独立于人——自己开 session 后台改数据，人不一定开着界面。

## 目标

- 集中托管的 **Streamable HTTP** MCP 服务器（无状态 JSON），与后端同机部署，作为后端客户端转发现有 HTTP/WS 接口，不复制业务逻辑。
- **PAT（Personal Access Token，个人访问令牌）** 认证：用户在 Web 端自助创建/吊销，MCP 客户端每个请求带 `Authorization: Bearer <PAT>`，服务端解析出用户名（`whoami`），操作以该用户身份执行。
- 工具面覆盖全部编辑类操作（含文件级：新建/导入/保存/另存为/导出），查询支持分页/过滤。
- 错误信息可执行（如 DBC 导出被数据错误拒绝时引导先修复）。

## 非目标

- 不暴露管理类操作：用户管理、文件权限分配、`steal_lock` 抢锁；`delete_file` 不暴露。
- 不做 OAuth、不做第二套认证、不复制业务逻辑到 MCP 层。
- 不做调试类接口（如 `get_snapshot_debug`）。
- 不做 AI/人会话共享：AI session 与人的 session 独立。

## 反目标

- 不做"一步到位"的魔法复合工具（工具面按业务域接近 1:1 映射，带批量变体）。
- `import_file` 不接受服务器侧文件路径（只收内联内容），防止越权读盘。

## 约束（现有实现事实）

- WS 消息约 30 种（`app/ws/handlers/`），编辑全部走 WS + `session_id`；HTTP 提供 `/api/login`、`/api/me`、`/api/export`、`/api/admin/*`。
- 会话 token 为内存发放、TTL 8 小时滑动续期、重启作废——因此新增 PAT。
- 权限模型：文件侧车（`data/{file}.perm.json`）严格所有权，仅 owner 可写；无侧车全员只读（含 admin）。**本设计不动权限模型**：AI 的权限=其 PAT 所属用户的权限，自己的文件可写，他人的只读（打开即只读会话）。
- 撤销栈/崩溃快照按文件名跨会话传递（`undo_engine.save_orphan`、快照被下一个打开者消费）。**v1 接受此现状**，文档写明"人和 AI 先后用同一文件时 undo 历史会传递"（文件锁保证不会同时编辑）。

## 方案对比（Approaches）

| 方案 | 说明 | 取舍 |
|------|------|------|
| A. 本地 stdio MCP | 每人本机起进程连后端 | 调试简单；与集中部署形态不符，各人需自装自更新 |
| **B. 集中托管 Streamable HTTP（选定）** | 与后端同机部署，AI 客户端远程接入，Bearer PAT 传身份 | 多一个服务要运维；零安装、升级即全员生效 |
| C. 双传输 | A 的代码支持 stdio + HTTP | 多一层抽象 |

选 B：与现有 systemd 多用户部署一致；传输层与业务层分离，将来加 stdio 不必重写。语言选 Python（官方 `mcp` SDK / FastMCP）而非 TypeScript：与仓库同语言同仓库交付，团队只维护一套。

## 关键设计

### PAT（后端新增）

- 持久化 `config/pats.json`（与 `users.json` 同侧车模式）：`id`、备注 `name`、`username`、`token_hash`（SHA-256）、`created_at`、`expires_at`（可空=永不过期）、`last_used_at`、`revoked`。明文 `pat_<hex>` 仅创建时展示一次。
- 自助端点（仅**会话 token** 可用）：`GET /api/tokens`、`POST /api/tokens`（`{name, expires_days}`）、`DELETE /api/tokens/{id}`。管理员不介入。
- 认证解析：Bearer 先试会话 token（滑动续期），再试 PAT（不续期）。PAT 贯穿 HTTP 与 WS hello。
- **权限收口（两层）**：管理端点（`/api/admin/*`、文件权限、`change-password`、`logout`、`/api/tokens*`）拒绝 PAT（403）；MCP 工具面也不含管理操作。
- **改密码不吊销 PAT**（只吊销会话 token）；删除用户清空其 PAT。

### MCP 服务器

- 身份：MCP 客户端经 `Authorization: Bearer <PAT>` 传身份，ASGI 中间件注入 contextvar；工具层通过 `require_user()` 解析 `{"username", "role"}`（带 60s 缓存）。
- 会话：SessionPool 按 `(username, session_id)` 持有 WS 连接；每连接 hello 握手、请求-响应（requestId）、30s 心跳；闲置 30 分钟回收；`close_session` 显式关闭并释放锁。崩溃靠后端心跳超时兜底。
- 工具命名 `canmatrix_` 前缀 snake_case；列表统一 `{total, count, offset, items, has_more, next_offset}`，limit 默认 50 / 上限 200；每个工具标 readOnly/destructive 等注解。
- 工具面（约 30 个）：`whoami`、`list_files`、`open_file`、`import_file`、`create_file`、`save`、`save_as`、`close_session`、`get_summary`、`export`；报文/信号/值表的查（分页过滤）+ 增改删 + 批量；`get_data_errors`、`undo`、`redo`、`get_save_diff`。精确参数映射见实施计划。

### 为未来"轻量级文件版本管理"的预留（用户要求）

- v1 不改 undo/快照语义；设计标注改造点：`undo_engine.save_orphan` 的 re-key（按文件名 → 按会话/命名空间）、快照的"消费式读取"。
- MCP 工具描述不把"undo 归属文件"写死；未来可平滑增加 `canmatrix_list_versions` / `canmatrix_restore_version` 一类工具；`close_session` 语义预留"存为版本"扩展位。
- 词汇区分："文件版本管理"（未来）与现有 API 的编辑版本号（`new_version`）严格分开。

## 测试与验收

- PAT：pytest 单测（创建/校验/过期/吊销/管理端点拒绝 PAT/改密不吊销 PAT）。
- MCP：工具层测试（真实后端 fixture）+ 端到端集成测试 + MCP Inspector 冒烟。
- 评估：10 个只读评估问题（XML），验证 AI 真实可用。

## 留给实现者的决定

包布局（`app/mcp/`）、session TTL 与心跳数值、工具 docstring 文案、export 返回策略（文本直返）、PAT `last_used_at` 落盘节流方式。
