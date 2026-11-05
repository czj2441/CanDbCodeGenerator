# CanMatrix MCP 服务器 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 CanMatrix Editor 增加 PAT（个人MCP访问令牌）认证与一个集中托管的 Streamable HTTP MCP 服务器（`canmatrix_mcp`），让 AI 客户端以任意用户身份完成全部编辑类操作。

**Architecture:** PAT 部分在现有 `AuthService` 上加持久化令牌存储与自助端点，认证解析"会话 token 优先、PAT 兜底"，管理类端点拒绝 PAT。MCP 服务器是薄客户端：ASGI 中间件从 `Authorization: Bearer <PAT>` 取身份，工具层通过 `httpx` 转发 HTTP、经自有 WS 会话池转发约 30 种 WS 消息，业务逻辑全部留在后端。

**Tech Stack:** Python 3.12、官方 `mcp` SDK（FastMCP）、httpx、uvicorn、websockets；前端 Vue 3 + Pinia + vitest；pytest。

**Spec:** `docs/superpowers/specs/2026-11-03-canmatrix-mcp-design.md`

**范围说明：** 本计划含两个子系统——Part A（Task 1-4，PAT 认证，可独立交付）与 Part B（Task 5-14，MCP 服务器，依赖 Part A）。Task 顺序即交付顺序。

## Global Constraints

- Python 3.12；新增依赖仅 `mcp>=1.2.0`、`httpx>=0.27`、`uvicorn>=0.30`（写入 `requirements.txt`）。
- MCP 服务器名 `canmatrix_mcp`；工具名 `canmatrix_` 前缀 + snake_case；工具 description 用中文。
- PAT 明文格式 `pat_` + 64 hex（`secrets.token_hex(32)`）；哈希 = SHA-256 hex；存储 `config/pats.json`。
- PAT 仅有编辑权限：`/api/admin/*`、`/api/file-permission`、`/api/change-password`、`/api/logout`、`/api/tokens*` 拒绝 PAT → 403 `{"success": false, "error": "此操作不支持个人MCP访问令牌"}`。
- **改密码只吊销会话 token，绝不吊销 PAT**；删除用户清空其 PAT。
- MCP 工具面禁止出现：`delete_file`、`steal_lock`、任何管理操作、`get_snapshot_debug`。
- `import_file` 只收内联内容，不接受服务器路径。
- 列表类工具响应统一 `{"total", "count", "offset", "items", "has_more", "next_offset"}`；`limit` 默认 50、上限 200。
- 工具返回 `dict`（FastMCP 结构化输出）；失败抛 `mcp.server.fastmcp.exceptions.ToolError`，消息保留后端中文原文并附可执行建议。
- `export` 走 HTTP `GET /api/export?sid=&fmt=&force=`，`fmt ∈ {properties, dbc, c_header, c_source}`，超时 120s。
- 每个 Task 结束前测试全绿并提交（`git commit`）。

## Review Focus

1. **PAT 双路径认证与会话 token 不回归**：PAT 经 HTTP 与 WS hello 都生效；会话 token 滑动续期行为不变。→ Task 1 `test_validate_token_or_pat_prefers_session_token_and_keeps_sliding_renewal`；Task 3 `test_ws_hello_accepts_pat_and_rejects_bad_token`。
2. **PAT 权限收口**：PAT 调用管理/改密/登出/令牌管理端点必须 403；且**改密码后 PAT 仍有效**。→ Task 2 `test_pat_rejected_on_admin_and_token_endpoints`、`test_change_password_keeps_pat_valid`。
3. **锁与只读语义**：打开被占文件得到含占用者/所有者的报错而非死等；只读会话写操作报错含所有者。→ Task 7 `test_open_locked_file_reports_owner`、`test_write_on_readonly_session_reports_owner`。
4. **多用户隔离**：SessionPool 按 `(username, session_id)` 隔离，A 的连接不能操作 B 的 session。→ Task 6 `test_session_pool_isolates_users`。
5. **上下文与超时**：大列表分页上限生效；大导出（C 代码）用 120s 超时。→ Task 8 `test_list_messages_respects_limit_and_offset`；Task 7 `test_export_returns_content_with_extended_timeout`。

---

## Part A：PAT 认证

### Task 1: PAT 存储与 AuthService

**Files:**
- Create: `tests/test_pat_service.py`
- Modify: `app/auth/service.py`

**Interfaces:**
- Produces（后续 Task 2 依赖的精确签名）:
  - `AuthService.create_pat(username: str, name: str, expires_days: int | None = None) -> dict` — 返回 `{"id", "name", "username", "token", "created_at", "expires_at"}`；`token` 明文仅此一次（格式 `pat_` + 64 hex），`expires_at` 为 float 时间戳或 `None`（永不过期）。
  - `AuthService.list_pats(username: str) -> list[dict]` — 每项 `{"id", "name", "created_at", "expires_at", "last_used_at"}`（不含 token/hash）。
  - `AuthService.revoke_pat(username: str, token_id: str) -> bool` — 非本人或不存在返回 `False`。
  - `AuthService.validate_pat(token: str) -> dict | None` — 返回 `{"username", "role"}`；吊销/过期/用户已删/未知 → `None`；更新 `last_used_at`（内存暂存，随 `cleanup_expired` 落盘）。
  - `AuthService.validate_token_or_pat(token: str) -> dict | None` — 先走 `validate_token`（滑动续期），未命中再走 `validate_pat`；返回 `{"username", "role", "auth_type": "session" | "pat"}`。
  - 模块常量 `PATS_FILE = os.path.join(CONFIG_DIR, "pats.json")`；文件 schema：`{"tokens": [{"id", "name", "username", "token_hash", "created_at", "expires_at", "last_used_at", "revoked"}]}`，原子写（tmp + `os.replace`，同 `_save_config` 风格）。
  - 行为约定：`change_password` 现有 `revoke_user_tokens` 调用**保持不变**（只影响会话 token）；`delete_user` 额外清空该用户的 PAT 记录。

- [ ] **Step 1: 写失败测试** `tests/test_pat_service.py`

fixture：monkeypatch `app.auth.service.CONFIG_DIR / USERS_FILE / PATS_FILE / DATA_DIR` 到 `tmp_path` 后构造 `AuthService()`。测试名与关键断言：

```python
def test_create_pat_returns_plaintext_once_and_stores_hash():  # token.startswith("pat_") and len(token) == 68; pats.json 含 sha256(token) 且不含 token 明文
def test_list_pats_hides_secrets():                            # set(item) == {"id","name","created_at","expires_at","last_used_at"}
def test_revoke_pat_only_own_and_effective():                  # 他人 revoke → False; 本人 revoke → True; validate_pat → None
def test_validate_pat_rejects_expired_and_unknown():           # 将 store 中 expires_at 改为过去 → None; "pat_bogus" → None
def test_validate_token_or_pat_prefers_session_token_and_keeps_sliding_renewal():
    # 会话 token → auth_type=="session" 且 expires_at 被延长; PAT → auth_type=="pat" 且无滑动续期
def test_change_password_keeps_pat_valid():                    # 改密码后 validate_pat 仍返回该用户
def test_delete_user_purges_pats():                            # delete_user 后 list_pats == [] 且 validate_pat → None
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/bin/python -m pytest tests/test_pat_service.py -v`
Expected: FAIL（`AttributeError: create_pat` 或收集期错误）

- [ ] **Step 3: 在 `app/auth/service.py` 实现**

按 Interfaces 块实现常量、pats.json 读写与 5 个方法。哈希复用 `_hash_password` 的 SHA-256 思路但无盐（`hashlib.sha256(token.encode()).hexdigest()`）；`id = secrets.token_hex(8)`。

- [ ] **Step 4: 运行测试确认通过**

Run: `venv/bin/python -m pytest tests/ -v`
Expected: 全部 PASS（含既有测试不回归）

- [ ] **Step 5: Commit**

```bash
git add tests/test_pat_service.py app/auth/service.py
git commit -m "feat(auth): add personal access tokens (PAT) to AuthService"
```

### Task 2: HTTP 集成——双认证、/api/tokens 端点、PAT 权限收口

**Files:**
- Modify: `app/server/http_handler.py`
- Create: `tests/test_http_pat_endpoints.py`

**Interfaces:**
- Consumes: Task 1 的 `create_pat / list_pats / revoke_pat / validate_token_or_pat`。
- Produces:
  - `_authenticate()` 返回 `{"username", "role", "auth_type"}`（Bearer 会话 token 或 PAT）。
  - 新增 `_require_session_auth() -> dict | None` — `auth_type != "session"` 时发 403 `{"success": false, "error": "此操作不支持个人MCP访问令牌"}` 返回 `None`。
  - `_require_admin()` 在既有逻辑上增加：`auth_type == "pat"` → 403 同上文案。
  - 路由：`GET /api/tokens` → `{"success": true, "data": [list_pats]}`；`POST /api/tokens` body `{"name": str(1..64), "expires_days": int | null}`（int 时 1..3650）→ `{"success": true, "data": create_pat 结果含明文 token}`；`DELETE /api/tokens/{id}` → `{"success": true}`（未命中 404）。三者均 `_require_session_auth`。
  - `change-password`、`logout` 改用 `_require_session_auth`。

- [ ] **Step 1: 写失败测试** `tests/test_http_pat_endpoints.py`

fixture：tmp 配置的 `AuthService` 注入 `app.server.http_handler.AUTH_SERVICE`，`ThreadingHTTPServer` + `ApiHandler` 起在临时端口；用 `urllib`/`httpx` 发请求。测试：

```python
def test_token_lifecycle_over_http():            # login → POST /api/tokens → GET 列表含新条目 → PAT 调 /api/me 成功 → DELETE → PAT 调 /api/me 401
def test_tokens_endpoints_reject_pat():          # PAT 调 GET/POST/DELETE /api/tokens → 403 且 error == "此操作不支持个人MCP访问令牌"
def test_pat_rejected_on_admin_and_token_endpoints():
    # PAT 调 GET /api/admin/users、GET /api/file-permission、POST /api/change-password、POST /api/logout → 均 403
def test_me_accepts_pat_and_returns_username():  # PAT 调 /api/me → {"username": ..., "role": ...}
def test_change_password_keeps_pat_valid():      # 创建 PAT → 会话 token 改密码 → PAT 调 /api/me 仍 200（用户要求：改密码不吊销 PAT）
def test_session_token_still_slides():           # 会话 token 连续调 /api/me 不失效（旧行为不回归）
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/bin/python -m pytest tests/test_http_pat_endpoints.py -v` → FAIL（404/无路由）

- [ ] **Step 3: 实现 `app/server/http_handler.py`**

按 Interfaces 改 `_authenticate`、加 `_require_session_auth`、收紧 `_require_admin`、`change-password`/`logout` 换校验、加 `api/tokens` 三条路由（`do_GET`/`do_POST`/`do_DELETE`；DELETE 匹配 `["api","tokens",id]`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `venv/bin/python -m pytest tests/ -v` → 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_http_pat_endpoints.py app/server/http_handler.py
git commit -m "feat(auth): PAT auth on HTTP API + self-service token endpoints"
```

### Task 3: WS hello 接受 PAT

**Files:**
- Modify: `app/ws/server.py`
- Create: `tests/test_ws_pat_auth.py`

**Interfaces:**
- Consumes: `validate_token_or_pat`。
- Produces: `app/ws/server.py` 模块级函数 `_authenticate_ws_token(token: str) -> dict | None`（内部调 `get_auth_service().validate_token_or_pat(token)`），`_handler` 的 hello 认证段改调它。行为不变：未认证 close 4010 `auth_required`；`username = user_info["username"]` 注入后续消息的 `data["_username"]`。

- [ ] **Step 1: 写失败测试** `tests/test_ws_pat_auth.py`

```python
def test_ws_hello_accepts_pat_and_rejects_bad_token():
    # _authenticate_ws_token(PAT) → {"username", "role", "auth_type": "pat"}
    # _authenticate_ws_token("garbage") → None
def test_ws_hello_session_token_unchanged():
    # _authenticate_ws_token(会话 token) → auth_type == "session"（滑动续期语义由 Task 1 保证）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_ws_pat_auth.py -v` → FAIL（函数不存在）

- [ ] **Step 3: 实现** — 抽出 `_authenticate_ws_token` 并替换 `_handler` 中 `auth.validate_token(token)` 调用（`app/ws/server.py` hello 段）。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_ws_pat_auth.py app/ws/server.py
git commit -m "feat(auth): accept PAT in WS hello handshake"
```

### Task 4: 前端个人MCP访问令牌管理

**Files:**
- Create: `frontend/src/components/TokenManagementModal.vue`, `frontend/src/stores/__tests__/authStoreTokens.test.js`
- Modify: `frontend/src/stores/authStore.js`, `frontend/src/components/FileBrowser.vue`, `frontend/src/i18n.js`

**Interfaces:**
- Consumes: Task 2 的 `/api/tokens` 端点。
- Produces:
  - `authStore` actions：`listTokens() -> Promise<Array>`、`createToken(name: string, expiresDays: number | null) -> Promise<Object>`（含一次性明文 `token`）、`revokeToken(id: string) -> Promise<void>`；内部复用 `authStore` 现有 `_fetch`（带 Bearer）。
  - `TokenManagementModal.vue`：`v-model:visible` 双向（与 `ChangePasswordModal` 同约定，参照 `FileBrowser.vue:410` 用法）；内容=令牌表格（名称/创建时间/过期时间/最后使用）、创建表单（备注名 + 过期：永不/30 天/90 天/自定义天数）、创建后一次性展示明文（含复制按钮）、逐条吊销按钮。
  - `FileBrowser.vue`：用户菜单加"个人MCP访问令牌"入口（`tokensOpen` ref），与"修改密码"入口相邻。
  - `i18n.js`：新增 `tokens.*` 键（中英文两份）。

- [ ] **Step 1: 写失败测试** `frontend/src/stores/__tests__/authStoreTokens.test.js`

```js
// mock fetch：断言三个 action 调用 /api/tokens 的 method/headers/body，
// createToken 返回解析后的 data（含 token），revokeToken 调 DELETE /api/tokens/{id}
```

- [ ] **Step 2: 运行确认失败** — Run: `cd frontend && npx vitest run src/stores/__tests__/authStoreTokens.test.js` → FAIL

- [ ] **Step 3: 实现** — 按 Interfaces 实现 store actions、Modal、入口、i18n。

- [ ] **Step 4: 运行确认通过** — Run: `cd frontend && npx vitest run` → PASS；`cd frontend && npx vite build` 成功。

- [ ] **Step 5: Commit**

```bash
git add frontend/src
git commit -m "feat(ui): personal access token management modal"
```

---

## Part B：MCP 服务器

### Task 5: MCP 骨架 + 身份中间件 + whoami

**Files:**
- Create: `app/mcp/__init__.py`, `app/mcp/errors.py`, `app/mcp/auth_context.py`, `app/mcp/backend.py`, `app/mcp/server.py`, `app/mcp/__main__.py`, `tests/test_mcp_identity.py`
- Modify: `requirements.txt`

**Interfaces:**
- Produces（Task 6-11 依赖的精确签名）:
  - `app/mcp/errors.py`: `class BackendError(Exception)`，属性 `code: str`、`message: str`、`details: dict`。
  - `app/mcp/auth_context.py`: `set_current_pat(pat: str | None) -> None`；`require_user() -> dict` — 返回 `{"username", "role"}`，无 PAT 或后端校验失败时抛 `ToolError("未认证：请在 Authorization: Bearer <PAT> 中提供个人MCP访问令牌")`；对同一 PAT 的 `/api/me` 结果缓存 60 秒。
  - `app/mcp/backend.py`（HTTP 部分）: `get_backend() -> BackendClient`（用当前 PAT + 环境变量 `CANMATRIX_BACKEND_URL` 构造）；`BackendClient.request(method: str, path: str, body: dict | None = None, timeout: float = 30.0) -> dict`（httpx.AsyncClient，`Authorization: Bearer <PAT>`；HTTP 非 2xx 或 `{"success": false}` → 抛 `BackendError(code=f"HTTP_{status}", message=error 文案, details=details)`）。
  - `app/mcp/server.py`: `mcp = FastMCP("canmatrix_mcp")`；`build_app() -> ASGIApp`（`mcp.streamable_http_app()` 外包一层中间件：读 `Authorization: Bearer` → `set_current_pat`，缺失 → 401 `{"error": "unauthorized"}`）。
  - `app/mcp/__main__.py`: `python -m app.mcp` 以 uvicorn 起 `build_app()`；env：`CANMATRIX_BACKEND_URL`（默认 `http://127.0.0.1:8080`）、`CANMATRIX_MCP_HOST`（默认 `127.0.0.1`）、`CANMATRIX_MCP_PORT`（默认 `8081`）。
  - 工具 `canmatrix_whoami() -> dict` — `require_user()` 后返回 `{"username", "role"}`；description：「返回当前令牌对应的用户名与角色」；注解 `readOnlyHint: true`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_identity.py`

```python
def test_middleware_rejects_missing_header():    # ASGI 请求无 Authorization → 401
def test_middleware_sets_pat():                  # 带 Bearer 时 contextvar 取到 PAT
def test_whoami_returns_username():              # httpx.MockTransport 桩 /api/me → {"username": "alice", "role": "user"}
def test_require_user_caches_me_calls():         # 60s 内两次 require_user 仅 1 次 /api/me 请求
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_identity.py -v` → FAIL

- [ ] **Step 3: 实现** — `requirements.txt` 加 `mcp>=1.2.0`、`httpx>=0.27`、`uvicorn>=0.30`，`venv/bin/pip install -r requirements.txt`；按 Interfaces 实现六个文件与工具。

- [ ] **Step 4: 运行确认通过 + 冒烟**

Run: `venv/bin/python -m pytest tests/ -v` → PASS；`venv/bin/python -c "from app.mcp.server import mcp; assert mcp.name == 'canmatrix_mcp'"` 无输出。

- [ ] **Step 5: Commit**

```bash
git add app/mcp requirements.txt tests/test_mcp_identity.py
git commit -m "feat(mcp): server skeleton, PAT identity middleware, whoami tool"
```

### Task 6: WS 会话层 + live_backend 测试夹具

**Files:**
- Modify: `app/mcp/backend.py`
- Create: `tests/conftest.py`, `tests/test_mcp_ws_session.py`

**Interfaces:**
- Consumes: Task 5 的 `BackendClient`、`BackendError`。
- Produces（Task 7-12 依赖）:
  - `CallResult`（dataclass）：`data: dict`、`new_version: int | None`、`new_session_id: str | None`。
  - `WsConnection`：`connect(ws_url: str, pat: str) -> WsConnection`（hello 握手 `{"type": "hello", "session_id": "", "token": pat}`，未认证抛 `BackendError("AUTH_REQUIRED", ...)`）；`async call(msg_type: str, data: dict) -> CallResult`（发送 `{"type", "requestId": uuid4, "data"}`，等待同 `requestId` 的响应：`{"type": "ok", ...}` → `CallResult`；`{"type": "error", "code", "message", "details"}` → 抛 `BackendError`）；`async close() -> None`；后台任务每 30s 发 `{"type": "ping"}`。
  - `BackendClient.control() -> WsConnection` — 每用户共享一条无 session 连接（供 `get_sessions` 等）。
  - `BackendClient.open_session(msg_type: str, data: dict) -> tuple[WsConnection, CallResult]` — 新建连接执行创建类消息（`load_file`/`import_file`/`create_file`），按 `CallResult.new_session_id` 登记入池。
  - `BackendClient.get_session(session_id: str) -> WsConnection` — 查池，未命中抛 `BackendError("SESSION_NOT_FOUND", "会话不存在或已过期，请重新 canmatrix_open_file")`。
  - `BackendClient.close_session(session_id: str) -> None` — 发 WS `release_lock`（`{"session_id", "abort": False}`，以 `app/ws/handlers/system_handlers.py` 的 ReleaseLockHandler 为准）后关连接、出池。
  - SessionPool：key `(username, session_id)`；空闲 30 分钟自动关连接出池。
  - `tests/conftest.py` 夹具 `live_backend`：在进程内按 `app/server/lifecycle.py` 的启动序列组装真实后端（`init_auth_service`、`init_session_manager`、WS 服务 + `ThreadingHTTPServer`，端口取临时端口，monkeypatch `CONFIG_DIR/USERS_FILE/PATS_FILE/DATA_DIR` 到 `tmp_path`），预置测试用户 `alice`（owner）与 `bob`，各发一个 PAT；yield `{"base_url", "ws_url", "pat_alice", "pat_bob", "auth"}`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_ws_session.py`

```python
async def test_call_roundtrip_and_error_mapping():   # 用 alice PAT 调 get_sessions 成功; edit 不存在 session → BackendError.code == "SESSION_NOT_FOUND"
async def test_session_pool_isolates_users():        # bob 用 alice 的 session_id 调用 → 报错; 两用户连接对象互不相同
async def test_ping_keeps_connection_alive():        # 短 TTL 环境下 45s 内连接因 ping 保持（空闲 TTL 不误杀）
async def test_idle_ttl_closes_connection():         # 无调用超过 TTL → 连接关闭且池中消失
async def test_close_session_releases_lock():        # close_session 后 bob 可 open 同一文件（无 FILE_LOCKED）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_ws_session.py -v` → FAIL

- [ ] **Step 3: 实现** — 按 Interfaces 实现 `WsConnection`/`CallResult`/SessionPool 与 `live_backend` 夹具（超时数值：ping 30s、空闲 TTL 30min，测试中可注入覆盖）。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp/backend.py tests/conftest.py tests/test_mcp_ws_session.py
git commit -m "feat(mcp): WS session pool with heartbeat and per-user isolation"
```

### Task 7: 文件/会话工具

**Files:**
- Create: `app/mcp/tools_session.py`, `tests/test_mcp_tools_session.py`
- Modify: `app/mcp/server.py`（注册工具）

**Interfaces:**
- Consumes: Task 5/6 的 `require_user`、`get_backend`、`BackendError`、`open_session/get_session/control/close_session`。
- Produces（工具签名即对外接口）:
  - `canmatrix_list_files() -> dict` — WS `get_sessions`（经 `control()`），结果按分页约定返回；items 含后端 `list_history` 原字段（含 `is_locked`、owner）。
  - `canmatrix_open_file(file_name: str) -> dict` — WS `load_file`（`{"file_name", "current_session_id": ""}`），返回 `{"session_id", "file_name", "bus_type", "message_count", "signal_count", "can_write"}`。`can_write` 由 HTTP `GET /api/file-permission?file={file_name}` 的 `owner` 与 `require_user()` 的 `username` 相等决定（无侧车时 owner 为空串 → `False`，与后端严格所有权一致）。
  - `canmatrix_create_file(name: str, content: dict | None = None) -> dict` — WS `create_file`，返回 `{"session_id", "file_name", "message_count", "signal_count"}`。
  - `canmatrix_import_file(file_name: str, format: str = "dbc", content: str = "") -> dict` — WS `import_file`（`{"format", "content", "filename": file_name}`）；`format ∈ {"dbc", "properties"}`，否则 `ToolError`。
  - `canmatrix_save(session_id: str) -> dict` — WS `save`。
  - `canmatrix_save_as(session_id: str, name: str) -> dict` — WS `save_as`（`{"name"}`）。
  - `canmatrix_close_session(session_id: str) -> dict` — `close_session()`，返回 `{"closed": true}`。
  - `canmatrix_get_summary(session_id: str) -> dict` — WS `get_summary`。
  - `canmatrix_export(session_id: str, format: str = "properties", force: bool = False) -> dict` — HTTP `GET /api/export?sid={session_id}&fmt={format}&force={0|1}`（超时 120s），返回 `{"format", "file_name", "content"}`；`format ∈ {properties, dbc, c_header, c_source}`。后端 422（数据错误）时 `ToolError` 消息含「先运行 canmatrix_get_data_errors 修复，或设置 force=true 强制导出」。
  - 全部工具错误统一映射：`BackendError` → `ToolError(f"{message}（{code}）")`；`FILE_LOCKED` 时附「占用者信息见消息」；只读会话写入的后端错误附「文件所有者可写，联系其授权或由其编辑」。
  - 注解：查询类 `readOnlyHint: true`；写类 `destructiveHint: true`（save/export 标 `idempotentHint` 视语义）。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_tools_session.py`（用 `live_backend`）

```python
async def test_create_open_save_close_roundtrip():           # create_file → save → close → open_file 得到同名文件
async def test_import_dbc_then_export_properties():          # 内联最小 DBC → export properties 含信号名
async def test_open_locked_file_reports_owner():             # alice 开着文件时 bob open → ToolError 文案含 "alice"
async def test_write_on_readonly_session_reports_owner():    # bob 只读会话调 save/编辑类 → ToolError 文案含所有者提示
async def test_list_files_shows_owner_and_lock():            # items 含 file_name/owner/is_locked
async def test_export_returns_content_with_extended_timeout():  # export c_source 返回非空 content 且 format == "c_source"
async def test_export_blocked_by_data_errors_mentions_fix():   # 构造数据错误后 export dbc（force=False）→ ToolError 提及 get_data_errors
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_tools_session.py -v` → FAIL

- [ ] **Step 3: 实现** — `app/mcp/tools_session.py` 九个工具 + 共享错误映射函数（后续 Task 复用，放 `app/mcp/errors.py`：`def tool_error(e: BackendError) -> ToolError`）；`server.py` 注册。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp tests/test_mcp_tools_session.py
git commit -m "feat(mcp): file and session tools"
```

### Task 8: 报文工具

**Files:**
- Create: `app/mcp/tools_messages.py`, `tests/test_mcp_tools_messages.py`
- Modify: `app/mcp/server.py`

**Interfaces:**
- Consumes: Task 7 的错误映射 `tool_error` 与工具约定。
- Produces:
  - `canmatrix_list_messages(session_id: str, filter: str | None = None, limit: int = 50, offset: int = 0) -> dict` — WS `get_messages` 后在工具层按 `filter`（大小写不敏感子串，匹配 name 与 id_hex）过滤并按分页约定返回；items 为后端报文摘要（`{id, id_hex, name, dlc, cycle_time, is_fd, sender, comment, signal_count, total_signal_bits}`）。
  - `canmatrix_get_message(session_id: str, msg_id: int) -> dict` — WS `get_message`（含信号明细）。
  - `canmatrix_add_message(session_id: str, message: dict) -> dict` — WS `add_message`（`{"message": message}`；`message` 必填键 `id: int`、`name: str`、`dlc: int`，其余透传，与 `app/ws/handlers/message_handlers.py` AddMessageHandler 一致）。
  - `canmatrix_edit_message(session_id: str, msg_id: int, fields: dict) -> dict` — WS `edit_message`。
  - `canmatrix_batch_edit_messages(session_id: str, msg_ids: list[int], fields: dict) -> dict` — WS `batch_edit_messages`。
  - `canmatrix_delete_message(session_id: str, msg_id: int) -> dict` — WS `delete_message`。
  - `canmatrix_batch_delete_messages(session_id: str, msg_ids: list[int]) -> dict` — WS `batch_delete_messages`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_tools_messages.py`

```python
async def test_add_get_edit_delete_message_roundtrip():
async def test_list_messages_respects_limit_and_offset():   # 造 5 条 → limit=2 得 count==2, has_more==True, total==5
async def test_list_messages_filter_matches_name_and_id_hex():
async def test_batch_edit_and_batch_delete():
async def test_add_message_missing_required_fields():       # 缺 dlc → ToolError（后端 VALUE_INVALID 文案）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_tools_messages.py -v` → FAIL

- [ ] **Step 3: 实现** — `app/mcp/tools_messages.py` 七个工具（分页/过滤辅助函数放模块内私有）；注册。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp tests/test_mcp_tools_messages.py
git commit -m "feat(mcp): message tools"
```

### Task 9: 信号工具

**Files:**
- Create: `app/mcp/tools_signals.py`, `tests/test_mcp_tools_signals.py`
- Modify: `app/mcp/server.py`

**Interfaces:**
- Produces:
  - `canmatrix_list_signals(session_id: str, msg_id: int | None = None, filter: str | None = None, limit: int = 50, offset: int = 0) -> dict` — 数据源：`msg_id` 给定时 WS `get_message` 的信号明细，否则遍历 `get_messages` 各报文的 `to_dict()` 信号；items 含 `msg_id` 与信号字段；分页/过滤同 Task 8 约定。
  - `canmatrix_get_signal(session_id: str, msg_id: int, sig_name: str) -> dict`。
  - `canmatrix_add_signal(session_id: str, msg_id: int, signal: dict) -> dict` — WS `add_signal`（`{"msg_id", "signal"}`；`signal` 字段集同 `signal_handlers.AddSignalHandler`）。
  - `canmatrix_batch_add_signals(session_id: str, msg_id: int, signals: list[dict]) -> dict` — WS `batch_add_signals`。
  - `canmatrix_edit_signal(session_id: str, msg_id: int, sig_name: str, field: str, value) -> dict` — WS `edit_signal`（`{"msg_id", "sig_name", "field", "value"}`）。
  - `canmatrix_batch_edit_signals(session_id: str, msg_id: int, sig_names: list[str], fields: dict) -> dict` — WS `batch_edit_signals`。
  - `canmatrix_delete_signal(session_id: str, msg_id: int, sig_name: str) -> dict` — WS `delete_signal`。
  - `canmatrix_batch_delete_signals(session_id: str, msg_id: int, sig_names: list[str]) -> dict` — WS `batch_delete_signals`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_tools_signals.py`

```python
async def test_add_get_edit_delete_signal_roundtrip():
async def test_batch_add_signals_creates_all():              # 3 个信号一次性创建，list_signals count==3
async def test_edit_signal_field_value():                    # edit factor → get_signal.factor 更新
async def test_list_signals_filter_and_pagination():
async def test_edit_signal_overlap_reports_data_error():     # 改位域造成重叠 → 返回含 data_errors 提示（后端事件里的 errors 字段透传）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_tools_signals.py -v` → FAIL

- [ ] **Step 3: 实现** — `app/mcp/tools_signals.py` 八个工具；注册。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp tests/test_mcp_tools_signals.py
git commit -m "feat(mcp): signal tools"
```

### Task 10: 值表工具

**Files:**
- Create: `app/mcp/tools_value_tables.py`, `tests/test_mcp_tools_value_tables.py`
- Modify: `app/mcp/server.py`

**Interfaces:**
- Produces:
  - `canmatrix_list_value_tables(session_id: str) -> dict` — WS `get_value_tables`。
  - `canmatrix_add_value_table(session_id: str, name: str, entries: dict) -> dict` — WS `add_value_table`（`{"name", "entries"}`，entries 为 `{value: label}` 映射）。
  - `canmatrix_update_value_table(session_id: str, name: str, entries: dict) -> dict` — WS `update_value_table`。
  - `canmatrix_rename_value_table(session_id: str, old_name: str, new_name: str) -> dict` — WS `rename_value_table`（`{"old_name", "new_name"}`）。
  - `canmatrix_delete_value_table(session_id: str, name: str) -> dict` — WS `delete_value_table`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_tools_value_tables.py`

```python
async def test_add_list_update_rename_delete_roundtrip():
async def test_add_value_table_invalid_entries():            # 非法 entries → ToolError（后端 VALUE_INVALID）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_tools_value_tables.py -v` → FAIL

- [ ] **Step 3: 实现** — 五个工具；注册。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp tests/test_mcp_tools_value_tables.py
git commit -m "feat(mcp): value table tools"
```

### Task 11: 校验与历史工具

**Files:**
- Create: `app/mcp/tools_history.py`, `tests/test_mcp_tools_history.py`
- Modify: `app/mcp/server.py`

**Interfaces:**
- Produces:
  - `canmatrix_get_data_errors(session_id: str, limit: int = 50, offset: int = 0) -> dict` — WS `get_data_errors`，分页约定同 Task 8。
  - `canmatrix_undo(session_id: str) -> dict` — WS `undo`。
  - `canmatrix_redo(session_id: str) -> dict` — WS `redo`。
  - `canmatrix_get_save_diff(session_id: str) -> dict` — WS `get_save_diff`。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_tools_history.py`

```python
async def test_data_errors_pagination():
async def test_undo_redo_roundtrip():                        # add_message → undo → get_message 报不存在 → redo → get_message 存在
async def test_save_diff_reflects_pending_changes():         # 编辑后 get_save_diff 非空；save 后再查为空（或无变更标记）
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_tools_history.py -v` → FAIL

- [ ] **Step 3: 实现** — 四个工具；注册。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add app/mcp tests/test_mcp_tools_history.py
git commit -m "feat(mcp): data errors, undo/redo and save diff tools"
```

### Task 12: 端到端集成测试 + MCP Inspector 冒烟

**Files:**
- Create: `tests/test_mcp_e2e.py`

**Interfaces:**
- Consumes: Task 5 `build_app()`、Task 6 `live_backend`。
- Produces: 全链路验收测试；Inspector 冒烟命令写入本任务 Step 3 注释与 Task 14 文档。

- [ ] **Step 1: 写失败测试** `tests/test_mcp_e2e.py`

uvicorn 起 `build_app()`（临时端口），用官方 SDK 的 streamable-http `ClientSession`（请求头 `Authorization: Bearer <pat_alice>`）跑一个完整工作流：

```python
async def test_full_workflow_over_mcp():
    # whoami → create_file → add_message → add_signal → get_data_errors
    # → export properties（含信号名）→ save → close_session → list_files 显示文件
async def test_mcp_rejects_request_without_pat():            # 无 Authorization → 连接/调用失败
async def test_mcp_rejects_revoked_pat():                    # 吊销后工具调用返回未认证错误
```

- [ ] **Step 2: 运行确认失败** — Run: `venv/bin/python -m pytest tests/test_mcp_e2e.py -v` → FAIL

- [ ] **Step 3: 实现** — 起服务、连会话、断言；修通全链路。冒烟（手动验收）：`venv/bin/python -m app.mcp` 后 `npx @modelcontextprotocol/inspector` 连接，确认工具清单完整、`canmatrix_whoami` 可调。

- [ ] **Step 4: 运行确认通过** — Run: `venv/bin/python -m pytest tests/ -v` → PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_mcp_e2e.py
git commit -m "test(mcp): end-to-end workflow over streamable HTTP"
```

### Task 13: 评估问题（10 题）

**Files:**
- Create: `docs/evals/canmatrix_mcp_evals.xml`

**Interfaces:**
- Consumes: Task 12 的样例数据工作流（评估针对固定种子数据：一个含 2-3 报文、5+ 信号、1 个值表、1 个已知数据错误的 properties 文件）。

- [ ] **Step 1: 固定评估数据** — 写 `docs/evals/README.md` 一段：如何用 MCP 工具造出种子数据（create_file/import_file 序列），数据从此不变。
- [ ] **Step 2: 写 10 个评估问答** — `docs/evals/canmatrix_mcp_evals.xml`（格式同 mcp-builder 评估指南 `<evaluation><qa_pair><question/><answer/></qa_pair></evaluation>`）。要求：全部只读、单答案可字符串验证、需 ≥3 次工具调用。例：「种子数据里信号数最多的报文叫什么？」「哪个报文存在数据错误，错误码是什么？」「EngineSpeed 信号的因子和偏移是多少？」
- [ ] **Step 3: 自验** — 每题亲自用工具链跑一遍确认答案稳定、可复现，把最终答案写进 XML；答案与数据不一致则修正数据或题目。
- [ ] **Step 4: Commit**

```bash
git add docs/evals
git commit -m "docs(mcp): evaluation question set for canmatrix_mcp"
```

### Task 14: 部署与文档

**Files:**
- Create: `deploy/canmatrix-mcp.service`
- Modify: `docs/systemd-deploy.md`, `README.md`

**Interfaces:**
- Consumes: Task 5 的 env 约定（`CANMATRIX_BACKEND_URL`、`CANMATRIX_MCP_HOST`、`CANMATRIX_MCP_PORT`）。

- [ ] **Step 1: 写 systemd unit** `deploy/canmatrix-mcp.service` — `ExecStart=<venv>/python -m app.mcp`，`Environment=CANMATRIX_BACKEND_URL=http://127.0.0.1:8080`，`CANMATRIX_MCP_HOST=127.0.0.1`，`CANMATRIX_MCP_PORT=8081`，Restart=always，与现有后端 unit 同风格。
- [ ] **Step 2: 更新 `docs/systemd-deploy.md`** — MCP 服务安装/启动小节；安全建议：绑定 `127.0.0.1` 走 HTTPS 反代（nginx 示例一段），不要直接暴露 8081。
- [ ] **Step 3: 更新 `README.md`** — 「MCP 服务器」章节：PAT 创建路径（文件列表页 → 个人MCP访问令牌）、AI 客户端接入示例（OpenCode/Claude Code 的 streamable HTTP 配置 + `Authorization: Bearer <PAT>` 头）、工具面一览表、只读他人文件/删除文件与管理操作不可用的说明。
- [ ] **Step 4: 全量回归** — Run: `venv/bin/python -m pytest tests/ -v` → PASS；`cd frontend && npx vitest run` → PASS。
- [ ] **Step 5: Commit**

```bash
git add deploy docs README.md
git commit -m "docs: deploy and usage docs for canmatrix_mcp"
```
