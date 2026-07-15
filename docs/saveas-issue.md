# SaveAs 功能问题总结

## 已修复

### 1. 文件名重复时错误提示为英文
- **现象**: SaveAs 输入重复文件名时，Toast 弹出英文错误消息 `"File 'xxx' already exists"`
- **原因**: 后端 `file_handlers.py` 中 `HandlerError` 消息硬编码为英文，前端直接透传 `e.message`
- **修复**:
  - 后端 `file_handlers.py:221`、`session_manager.py` 相关错误消息改为中文
  - 前端 `fileOperations.js` 中 `saveAs()` 按 `e.code === 'FILE_NAME_EXISTS'` 匹配 i18n 键 `toast.saveAsExistsError`，不再依赖后端消息文本
- **涉及文件**: `file_handlers.py`、`session_manager.py`、`fileOperations.js`、`i18n.js`

### 2. 弹出错误后 SaveAs 窗口消失
- **现象**: SaveAs 报错后弹窗立即关闭，用户无法修改文件名重试
- **原因**: `TopBar.vue` 中 `confirmSaveAs()` 在调用 `fileOps.saveAs()` 之前就将 `saveAsConfirmOpen` 设为 `false`
- **修复**:
  - `confirmSaveAs()` 改为 `async`，`await fileOps.saveAs(name)`
  - 仅在成功时关闭弹窗，失败时保持打开
  - `fileOperations.js` 中 `saveAs()` catch 后 `throw e` 让调用方感知失败
  - 新增 `saveAsLoading` ref 防止重复提交
- **涉及文件**: `TopBar.vue`、`fileOperations.js`

### 3. SaveAs 空文件名错误提示为英文
- **现象**: 直接 API 调用传入空 name 时，Toast 弹出英文 `"Name is required"`
- **原因**: 前端 `saveAs()` catch 中未按 `VALUE_INVALID` 错误码匹配 i18n 键
- **修复**:
  - `i18n.js` 新增 `toast.saveAsNameRequired` 键
  - `fileOperations.js` catch 块新增 `e.code === 'VALUE_INVALID'` 分支，使用 i18n 消息
  - 后端 `file_handlers.py:207` 保持英文不变（后端消息仅用于日志）
- **涉及文件**: `i18n.js`、`fileOperations.js`

### 4. SaveAs 时 session 已失效显示英文错误
- **现象**: session 超时被清理后点击“另存为”，Toast 弹出英文 `"Session not found"`
- **原因**: `SaveAsHandler` 缺少 session 前置检查，`ValueError` 未被 `except FileNameExistsError` 捕获，穿透到 Router 兆底
- **修复**:
  - `file_handlers.py` 中 `SaveAsHandler` 增加 `get()` + `HandlerError("SESSION_NOT_FOUND")` 前置检查，与项目内 21 处既有模式一致
  - `fileOperations.js` catch 块新增 `SESSION_NOT_FOUND` 分支，调用 `_resetOnSessionFailure()` 清理状态并复用 i18n `toast.sessionLost`
- **涉及文件**: `file_handlers.py`、`fileOperations.js`

### 5. confirmNew 无防重复提交保护且 Promise 未 catch
- **现象**: 用户快速双击或连按 Enter 可多次触发 `createNewSession`，创建多个 session
- **原因**: `confirmNew()` 是同步函数，调用 async `createNewSession` 后 fire-and-forget，无 loading 守卫、无 await、无 catch
- **修复**:
  - 新增 `newLoading` ref 防重复提交
  - `confirmNew` 改为 async，`await fileOps.createNewSession(name)` + `try/catch/finally`
  - 模板确认按钮添加 `:disabled="newLoading"`
- **涉及文件**: `TopBar.vue`

---

## 待修复

### P1 — 警告级

| # | 位置 | 问题 |
|---|------|------|
| (已全部修复) | — | — |

### P2 — 架构级（既有问题）

| # | 位置 | 问题 |
|---|------|------|
| 4 | `session_manager.py:165-182` | `create()` TOCTOU 竞态：磁盘检查在锁外，并发同名请求可能覆盖文件 |
| 5 | `session_manager.py:278-294` | `save_as()` 的 `resolve_duplicate` 与 `create()` 之间存在竞态窗口 |

### P3 — 建议

| # | 位置 | 问题 |
|---|------|------|
| 6 | `file_handlers.py:54,100,168` | `NewFileHandler`/`ImportFileHandler`/`CreateFileHandler` 的 `already exists` 错误仍为英文 |
| 7 | `TopBar.vue:108,119` | Loading 期间弹窗可被外部点击/取消按钮关闭（既有模式） |
