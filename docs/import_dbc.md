# CAN FD 支持 — 代码审查问题清单

## 严重问题 (MUST FIX)

### ~~1. UndoEngine 不支持 `database_update` 类型，撤销 bus_type 变更会崩溃~~ ✅ 已修复
- **文件**: `app/services/undo_engine.py` L161-L162, L185-L186, L278-L283
- **问题**: `EditDatabaseHandler` 向 undo 栈推入 `{"type": "database_update", ...}`，但 `_execute_undo` 和 `_execute_redo` 均未处理该类型，会抛出 `ValueError`。
- **修复状态**: 已在 `_execute_undo` / `_execute_redo` 中新增 `database_update` 分支，通过 `_restore_database_update` 方法使用 `setattr` 恢复 `prev`/`next` 值。

### ~~2. `_restore_message` 未恢复 `is_fd` 字段，CAN FD 报文撤销删除后丢失 FD 标记~~ ✅ 已修复
- **文件**: `app/services/undo_engine.py` L212
- **问题**: 删除一条 `is_fd=True` 的报文后执行撤销，`_restore_message` 重建 `Message` 时未传入 `is_fd`。
- **修复状态**: 构造 `Message` 时已加入 `is_fd=msg_data["is_fd"]`。

---

## 警告 (SHOULD FIX)

### ~~3. `setBusType` 乐观更新无失败回滚，前后端状态不一致~~ ✅ 已修复
- **文件**: `frontend/src/components/TopBar.vue` L96-L105
- **问题**: `setBusType` 先乐观更新 `store.busType`，WS 请求失败时仅弹 toast 不回滚。
- **修复状态**: 已改为 BackendValueSync 模式——双向绑定直接写入 store，`.catch` 中用后端返回的权威值 `e.details.bus_type` 覆盖 store，无需手动回滚。

### 4. `full_sync` 缺少 `bus_type` 和消息 `is_fd`，WebSocket 重连后状态丢失
- **文件**: `app/ws/server.py` L146-L170
- **问题**: `_send_full_sync()` 构建的数据中顶层不含 `bus_type`，每条消息不含 `is_fd`。重连后前端状态被覆盖，`is_fd` 回退为 `undefined`/`false`，`busType` 不同步。
- **修复**: `messages_data` 中加 `"is_fd": m.is_fd`，顶层 `data` 中加 `"bus_type": db.bus_type`；前端 `full_sync` case 中同步 `editor.busType`。

### ~~5. 单独更新 `is_fd=False` 可绕过 DLC 校验，产生无效状态~~ ✅ 已修复
- **文件**: `app/models/database.py` L150-L164
- **问题**: 经典 CAN DLC 1-8 的范围检查仅在 `if "dlc" in updates:` 分支内，仅发送 `{"is_fd": false}` 时不触发校验。
- **修复状态**: 已在 `is_fd` 校验分支中增加交叉验证——当 `is_fd` 切换为 False 且当前 DLC 不在 `CLASSIC_CAN_DLC_VALUES` 中时拒绝变更，错误响应中携带当前正确的 `is_fd` 值。

---

## 建议 (CONSIDER)

### ~~6. `resetEditorState()` 未重置 `busType`~~ ✅ 已修复
- **文件**: `frontend/src/stores/editor.js` L98-L115
- **问题**: 会话拆卸后旧的 `busType` 值残留，`resetEditorState()` 中未包含 `this.busType = 'CAN'`。
- **修复状态**: 已在 `resetEditorState()` 中添加 `this.busType = 'CAN'`，紧跟 `this.currentFileName = ''` 之后。

### ~~7. `NewFileHandler` 响应缺少 `bus_type` 字段~~ ✅ 已修复
- **文件**: `app/ws/handlers/file_handlers.py` L55-L58，`frontend/src/stores/fileOperations.js` L172
- **问题**: `LoadFileHandler` 和 `ImportFileHandler` 响应均含 `bus_type`，但 `NewFileHandler` 遗漏，API 不一致。
- **修复状态**: 后端 `NewFileHandler` 响应已加入 `"bus_type": new_db.bus_type`；前端 `fileOperations.js` 已从硬编码 `'CAN'` 改为读取 `data.bus_type || 'CAN'`，与 `loadFile` / `importFile` 保持一致。

### 8. 直接访问 cantools 私有属性 `_dbc`，存在版本依赖风险
- **文件**: `app/io/dbc_io.py` L109-L132，`app/models/database.py` L662-L690
- **问题**: DBC 导出时直接赋值 `can_db._dbc` 并导入 cantools 内部模块路径下的类，版本升级后可能静默失败。建议锁定 cantools 版本并添加 try/except 降级逻辑。
