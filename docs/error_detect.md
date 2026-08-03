# 后端错误检测逻辑清单

> 自动生成，基于 `app/` 目录下所有后端源码。

---

## 1. 通用错误框架

### 1.1 HandlerError（业务错误基类）
- **文件**: `app/ws/router.py` L27-34
- **结构**: `HandlerError(code, message, details)`
- Router 捕获后转为 WS `type: "error"` 响应，携带 `code` + `message` + `details`

### 1.2 Router 兜底异常捕获
- **文件**: `app/ws/router.py` L119-130
- **错误码**: `INTERNAL_ERROR`
- 捕获所有非 `HandlerError` 的未预期异常，防止 WS 断连

### 1.3 未知消息类型
- **文件**: `app/ws/router.py` L72-80
- **错误码**: `UNKNOWN_TYPE`
- 收到未注册的 `msg.type` 时返回

---

## 2. 文件名安全校验

### 2.1 validate_file_name()
- **文件**: `app/ws/handlers/_common.py` L10-34
- 防御路径穿越、头注入、非法字符

| 检测项 | 错误 |
|--------|------|
| 空/非字符串 | `Invalid file name` |
| Null 字节 (`\x00`) | `Null byte in file name` |
| Windows 保留字符 `:*?"<>\|` | `Invalid characters in file name` |
| 路径分隔符 `/` `\` | `Path separator in file name` |
| CR/LF 头注入 `\r` `\n` | `Invalid characters in file name` |
| 绝对路径 | `Absolute path not allowed` |
| normpath 后不一致 | `Invalid file name` |

**使用此校验的 Handler**（统一抛出 `INVALID_FILE_NAME`）：
- NewFileHandler, ImportFileHandler, CreateFileHandler, LoadFileHandler, SaveAsHandler, DeleteFileHandler

### 2.2 _safe_path()（路径穿越防御）
- **文件**: `app/services/session_manager.py` L87-93
- `realpath` 后检查是否仍在 `data_dir` 内
- 错误: `ValueError("Path traversal detected: {file_name}")`

---

## 3. HTTP 静态文件安全

### 3.1 路径穿越检查
- **文件**: `app/server/http_handler.py` L82-84, L99-104
- normpath 后检查 `..` / 绝对路径 → HTTP 403 `Forbidden`
- realpath 后检查是否仍在 base_dir 内 → HTTP 403 `Forbidden`

### 3.2 文件不存在
- **文件**: `app/server/http_handler.py` L106-108
- HTTP 404 `Not found`

---

## 4. 会话级错误

### 4.1 SESSION_NOT_FOUND
- 几乎所有 Handler 在 `self._sm.get(sid)` 返回 `None` 时抛出
- 含义: 会话不存在/已过期

### 4.2 FILE_LOCKED
- **文件**: `file_handlers.py` L193-194, `system_handlers.py` L157-158
- 文件已被其他标签页/会话打开时拒绝操作

### 4.3 FILE_NAME_EXISTS
- **文件**: `file_handlers.py` L53-54, L100-101, L172-173, L229-230
- 新建/导入/另存为时文件名与已有文件冲突

### 4.4 SAVE_FAILED
- **文件**: `file_handlers.py` L27-30
- 保存会话到磁盘失败（含会话不存在）

---

## 5. 报文级错误

### 5.1 MESSAGE_NOT_FOUND
- 编辑/删除/复制/获取报文时，`msg_id` 在 `db.messages` 中不存在

### 5.2 VALUE_INVALID — 报文 ID
| Handler | 检测 | 错误消息 |
|---------|------|----------|
| EditMessageHandler | `_parse_id()` 返回 None | `Invalid new ID` |
| AddMessageHandler | `_parse_id()` 返回 None | `Invalid or missing message ID` |
| ~~GetMessageHandler~~ | ~~`_parse_id()` 返回 None~~ | ~~`Invalid message ID`~~ [→ deferrable B1] |

### 5.3 VALUE_INVALID — 报文名称
- **文件**: `app/models/database.py` L143-148, `message_handlers.py` L111-113
- 名称为空/非字符串 → `Message name cannot be empty`
- details: `error_code: "message_name_empty", field: "name"`

### 5.4 VALUE_INVALID — DLC
- **文件**: `app/models/database.py` L166-195, `message_handlers.py` L114-123
- DLC 非数字 → `Invalid DLC value`
- DLC 不在合法集合 `{1-8, 12, 16, 20, 24, 32, 48, 64}` → `Invalid DLC`
- 经典 CAN 下 DLC > 8 → `Classic CAN only supports DLC 1-8`
- ~~DLC 缩小导致信号越界~~ → ~~`DLC reduction would make signal '{name}' out of bounds`~~ [→ deferrable A1]

### 5.5 VALUE_INVALID — is_fd 切换
- **文件**: `app/models/database.py` L151-164
- is_fd 非 bool → `is_fd must be a boolean`
- CAN FD → CAN 但当前 DLC > 8 → `Classic CAN only supports DLC 1-8, current DLC is {dlc}`

### 5.6 CONFLICT — 报文 ID 冲突
- 添加/编辑/复制报文时 ID 已存在 → `报文 0x{id:X} 已存在`

### 5.7 DLC_TOO_LARGE — bus_type 切换
- **文件**: `system_handlers.py` L208-216
- CAN FD → CAN 时存在 DLC > 8 的报文 → `经典 CAN 仅支持 DLC 1-8，请先减小以下报文的 DLC`

### 5.8 VALUE_INVALID — bus_type
- **文件**: `system_handlers.py` L205-206
- bus_type 不是 `"CAN"` 或 `"CAN FD"` → `bus_type must be 'CAN' or 'CAN FD'`

---

## 6. 信号级错误

### 6.1 SIGNAL_NOT_FOUND
- 编辑/删除信号时 `sig_uuid` 在报文中不存在

### 6.2 FIELD_NOT_EDITABLE
- **文件**: `signal_handlers.py` L71-72
- 编辑的字段不在 `EDITABLE_SIGNAL_FIELDS` 白名单中
- 白名单: `name, start_bit, length, byte_order, factor, offset, min_val, max_val, unit, comment`

### 6.3 _validate_signal_fields()（统一字段校验）
- **文件**: `signal_handlers.py` L14-41
- 供 add/edit/batch 复用

| 检测项 | error_code | 错误消息 |
|--------|-----------|----------|
| name 为空/非字符串 | `signal_name_empty` | Signal name cannot be empty |
| name 与同报文已有信号重名 | `signal_name_duplicate` | Signal name '{name}' already exists |
| length < 1 / 非数字 | `signal_length_invalid` | Signal length must be at least 1 |
| factor/offset/min_val/max_val 非数字 | `invalid_number` | Invalid {field} value |
| factor/offset/min_val/max_val 为 NaN/Infinity | `invalid_number` | {field} cannot be NaN or Infinity |
| ~~factor == 0~~ | ~~`factor_zero`~~ | ~~Factor cannot be zero~~ [→ deferrable A2] |

### 6.4 validate_signal()（信号位布局校验）
- **文件**: `app/models/database.py` L332-390

| 检测项 | type | 错误消息 |
|--------|------|----------|
| ~~报文不存在~~ | ~~`invalid_param`~~ | ~~Message not found~~ [→ deferrable B4] |
| ~~DLC < 1~~ | ~~`invalid_param`~~ | ~~Invalid message DLC~~ [→ deferrable B5] |
| start_bit < 0 | `invalid_param` | Start bit must be non-negative |
| length < 1 | `invalid_param` | Signal length must be at least 1 |
| ~~信号位越界 (超出 DLC 范围)~~ | ~~`out_of_bounds`~~ | ~~Signal out of bounds~~ [→ deferrable A3] |
| ~~信号与已有信号位重叠~~ | ~~`overlap`~~ | ~~Signal overlaps with '{other_name}'~~ [→ deferrable A4] |

- 越界和重叠错误都包含 `suggestion` 字段（推荐的空闲起始位）

### 6.5 validate_all_signals()（全文信号校验）
- **文件**: `app/models/database.py` L392-434
- 在 DLC 变更、信号增删后触发，返回所有信号的越界+重叠错误列表
- 通过 `signal_errors_changed` 事件推送给前端

### 6.6 BatchAddSignals 批量错误
- **文件**: `signal_handlers.py` L209-230
- 信号数组为空 → `Expected non-empty signals array`
- 单个信号校验失败不阻断整批，收集到 `errors` 数组
- 全部失败 → `No signals created`

---

## 7. 撤销/重做错误

### 7.1 UNDO_FAILED
- **文件**: `system_handlers.py` L27-28
- `undo()` 返回 `success: False` 时抛出

### 7.2 REDO_FAILED
- **文件**: `system_handlers.py` L68-69
- `redo()` 返回 `success: False` 时抛出

### ~~7.3 Session not found (undo/redo 内部)~~ [→ deferrable B6]
- **文件**: `session_manager.py` L644-653
- ~~undo/redo 时 session 不存在 → 返回 `{success: False, message: "Session not found"}`~~

### 7.4 撤销栈为空
- **文件**: `app/services/undo_engine.py` L54-55
- undo 栈空 → `{success: False, message: "No operation to undo"}`

### 7.5 重做栈为空
- **文件**: `app/services/undo_engine.py` L82-83
- redo 栈空 → `{success: False, message: "No operation to redo"}`

### 7.6 撤销/重做执行异常
- **文件**: `app/services/undo_engine.py` L63-65, L91-93
- 执行撤销/重做操作时数据异常（报文/信号不存在）→ 回滚栈并返回 `{success: False, message: "Undo/Redo failed: {error}"}`

### ~~7.7 未知撤销类型~~ [→ deferrable B7]
- **文件**: `app/services/undo_engine.py` L163-164, L187-188
- ~~snap.type 不是已知类型 → `ValueError("Unknown undo/redo type: {type}")`~~

### ~~7.8 深拷贝失败回退~~ [→ deferrable E1]
- **文件**: `app/services/undo_engine.py` L33-37
- ~~`json.dumps/loads` 深拷贝撤销快照失败 → warning 日志 + 浅拷贝回退~~

---

## 8. 文件导入/导出错误

### 8.1 VALUE_INVALID — 不支持的格式
- **文件**: `file_handlers.py` L86, L136
- import/export 的 format 不是 `properties`/`json`/`dbc`/`c_header`/`c_source`

### 8.2 IMPORT_FAILED
- **文件**: `file_handlers.py` L89-90
- 导入解析异常（JSON 解析失败、Properties 格式错误等）

### 8.3 EXPORT_FAILED
- **文件**: `file_handlers.py` L137-138
- 导出序列化异常

### 8.4 SaveAs 名称校验
- **文件**: `file_handlers.py` L215-226
- name 为空 → `Name is required`
- 去掉 `.properties` 后为空/纯下划线 → `File name cannot be empty`

---

## 9. WebSocket 连接级错误

### 9.1 Hello 超时
- **文件**: `app/ws/server.py` L44-50
- 5 秒内未收到 hello → WS close 4001 `"hello timeout"`

### 9.2 非 hello 首消息
- **文件**: `app/ws/server.py` L53-55
- 首条消息不是 `type: "hello"` → WS close 4002 `"expected hello"`

### 9.3 Session 不存在（连接拒绝）
- **文件**: `app/ws/server.py` L62-69
- hello 中的 session_id 在后端找不到 → WS close 4003 `"session_not_found"`

### ~~9.4 JSON 解析失败~~ [→ deferrable F3]
- **文件**: `app/ws/server.py` L90-92
- ~~收到非 JSON 消息 → 丢弃并记录 warning，不断连~~

---

## 10. 文件锁系统错误

### 10.1 FileLockedError
- **文件**: `app/services/session_manager.py` L37-39
- 文件被其他会话占用时抛出（restore 路径）

### 10.2 FileNameExistsError
- **文件**: `app/services/session_manager.py` L42-44
- 创建会话时同名文件已存在

### 10.3 心跳超时清理
- **文件**: `app/services/session_manager.py` L665-678
- 30 秒无心跳 → session 自动销毁 + 文件锁释放 + 写快照

### ~~10.4 resolve_duplicate 上限~~ [→ deferrable E4]
- **文件**: `app/services/file_persistence.py` L83-98
- ~~重名文件递增序号超过 9999 次 → `FileExistsError`~~

---

## 11. HTTP API 错误

### 11.1 Session not found
- **文件**: `http_handler.py` L229-231
- export 时 sid 无效 → HTTP 404

### ~~11.2 Server initializing~~ [→ deferrable F4]
- **文件**: `http_handler.py` L204-205, L217-218
- ~~SESSION_MGR 尚未初始化 → HTTP 503~~

### 11.3 不支持的导出格式
- **文件**: `http_handler.py` L248-249
- fmt 不是 dbc/properties/c_header/c_source → HTTP 400

### 11.4 缺少 sid 参数
- **文件**: `http_handler.py` L224-226
- export 时未传 sid → HTTP 400

---

## 12. 快照系统错误

### 12.1 快照写入失败
- **文件**: `app/services/snapshot.py` L52-55
- 写快照时任何异常 → error 日志 + 返回 `False`

### ~~12.2 快照恢复失败~~ [→ deferrable E2]
- **文件**: `app/services/session_manager.py` L259-263
- ~~从快照 `from_dict` 失败 → error 日志 + 回退到磁盘文件加载~~

### ~~12.3 快照解析失败~~ [→ deferrable E3]
- **文件**: `app/services/snapshot.py` L86-87, L127-128
- ~~`find_snapshot_for_file` / `_scan_snapshot_filenames` 解析 JSON 失败 → 跳过该快照~~

---

## 13. 启动期错误

### 13.1 依赖检查
- **文件**: `lifecycle.py` L26-53
- 缺少 cantools/javaproperties/websockets/Jinja2 → 打印错误并 `sys.exit(1)`

### 13.2 端口冲突
- **文件**: `lifecycle.py` L159-166
- 端口被占用且无法清理 → `sys.exit(1)`

### 13.3 save_all_dirty 紧急备份
- **文件**: `session_manager.py` L395-405
- 保存失败时写紧急备份文件 `{sid}_EMERGENCY.properties`
- 紧急备份也失败 → critical 日志

### 13.4 WS 广播失败
- **文件**: `app/ws/transport.py` L199-210
- 发送消息时 `ConnectionClosed` → 静默吞掉
- 其他发送异常 → warning 日志 + 诊断计数 +1

---

## 错误码速查表

| 错误码 | 来源 | 含义 |
|--------|------|------|
| `SESSION_NOT_FOUND` | WS Handler | 会话不存在/已过期 |
| `INVALID_FILE_NAME` | WS Handler | 文件名非法（路径穿越/特殊字符） |
| `FILE_NAME_EXISTS` | WS Handler | 文件名已存在 |
| `FILE_LOCKED` | WS Handler | 文件被其他标签页锁定 |
| `SAVE_FAILED` | WS Handler | 保存失败 |
| `VALUE_INVALID` | WS Handler | 字段值非法（含 details 说明具体字段） |
| `CONFLICT` | WS Handler | 报文 ID 冲突 |
| `MESSAGE_NOT_FOUND` | WS Handler | 报文不存在 |
| `SIGNAL_NOT_FOUND` | WS Handler | 信号不存在 |
| `FIELD_NOT_EDITABLE` | WS Handler | 信号字段不可编辑 |
| `IMPORT_FAILED` | WS Handler | 文件导入失败 |
| `EXPORT_FAILED` | WS Handler | 文件导出失败 |
| `DLC_TOO_LARGE` | WS Handler | CAN FD→CAN 时 DLC 超出经典 CAN 范围 |
| `UNDO_FAILED` | WS Handler | 撤销失败 |
| `REDO_FAILED` | WS Handler | 重做失败 |
| `UNKNOWN_TYPE` | WS Router | 未注册的消息类型 |
| `INTERNAL_ERROR` | WS Router | 未预期的服务端异常 |
| `FileLockedError` | 内部异常 | 文件锁冲突（被 Handler 转为 FILE_LOCKED） |
| `FileNameExistsError` | 内部异常 | 文件名重复（被 Handler 转为 FILE_NAME_EXISTS） |
