# CanMatrix Editor 软件详细设计文档

> 生成日期：2026-06-05
> 对应代码版本：449cd28（调试版本更新）


---

## 第 1 章：概述

### 1.1 项目背景

CAN（Controller Area Network）总线广泛应用于汽车电子和工业控制领域，其矩阵定义（Signal → Message 映射关系）通常以 Vector 公司的 DBC（Database CAN）格式存储。DBC 是 Vector 公司的私有格式，本质是类 INI 的自由文本文件，存在以下痛点：

1. **Git 合并冲突严重**：DBC 以行为单位描述信号（`SG_` 行），增删信号会导致整行位移，Git diff 无法精准定位到具体字段变更，合并时极易产生冲突。
2. **可读性差**：DBC 使用十进制 CAN ID、紧凑的位描述语法（`0|16@1+ (1,0) [0|65535] "rpm" ECU2`），人工阅读和审查困难。
3. **工具链锁定**：主流 DBC 编辑工具（Vector CANdb++、CANoe）为商业软件，且 DBC 格式细节未完全公开，形成工具链锁定。

CanMatrix Editor 的核心目标是：**以 Properties 作为主存储格式，保留与 DBC 工具链的互通能力（导入/导出），解决 Git 版本管理中的合并冲突问题**。

### 1.2 软件目标

| 目标 | 说明 |
|------|------|
| 主存储格式为 Properties | Properties 可读性好、diff 友好、Git 兼容性强 |
| 支持 DBC 导入/导出 | 通过 cantools 库实现与现有 DBC 工具链的互通 |
| 提供 Web GUI | 基于 Vue 3 的现代 Web 编辑器，支持浏览器多标签页 |
| 支持 CLI 无头模式 | 所有操作均可通过 Python API 批量执行 |
| 信号模型贴合 DBC 语义 | 采用 per-message 信号模型，同名信号在不同报文中可独立定义 |

### 1.3 核心特性

- **Properties 主存储**：信号以 dotted keys 形式嵌套在报文下（如 `messages.0x100.signals.RPM`），增删信号只影响该报文块。
- **稀疏输出**：默认值的字段（`factor=1.0`、`offset=0.0` 等）在保存时省略，减少 diff 噪音。
- **十六进制 CAN ID**：Properties 中 `messages.0x100.name=EngineData`，与 CAN 工具链和硬件文档保持一致。
- **Web 前端 + Python 后端**：Vue 3 + Vite 构建前端，WebSocket 全双工通信 + HTTP 辅助（静态文件 / 导出 / 版本检查）。
- **会话隔离与手动持久化**：每个浏览器标签页绑定独立 session，前端显式触发保存，崩溃后可恢复。
- **信号布局验证**：后端实时校验信号位域重叠和越界，支持 Intel（小端）和 Motorola（大端）两种字节序。
- **安全性**：纯本地应用，仅绑定 localhost；所有解析使用标准库或 cantools 官方解析器。

### 1.4 与现有工具的对比

| 特性 | Vector CANdb++ | cantools（Python 库） | **CanMatrix Editor** |
|------|-----------------|----------------------|---------------------|
| 图形界面 | ✅ | ❌ | ✅ |
| Properties 存储 | ❌ | ❌ | ✅ |
| Git diff 友好 | ❌ | N/A | ✅ |
| DBC 导入 | ✅ | ✅ | ✅ |
| DBC 导出 | ✅ | ✅ | ✅ |
| CLI/脚本化 | ❌ | ✅ | ✅ |
| 开源 | ❌ | ✅ | ✅ |
| 信号布局验证 | ❌ | ❌ | ✅ |


---

## 第 2 章：系统架构

### 2.1 整体架构

当前架构采用 **Web 前端（Vue 3 + Vite）+ Python WebSocket/HTTP 后端** 的 B/S 模式：

```
┌──────────────────────────────────────────────────────┐
│                    浏览器 (Browser)                    │
│  ┌────────────────────────────────────────────────┐  │
│  │          Vue 3 SPA (dist/ + Vite 构建)          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │  │
│  │  │ 7 Pinia  │ │ Vue      │ │ ws-client.js  │  │  │
│  │  │ Stores   │ │ Components│ │ (WS 客户端)   │  │  │
│  │  └──────────┘ └──────────┘ └───────┬───────┘  │  │
│  │                                     │          │  │
│  │  sessionStorage ← session_id 持久化 │          │  │
│  └─────────────────────────────────────┼──────────┘  │
└────────────────────────────────────────┼─────────────┘
                                         │
                              ┌──────────┴──────────┐
                              │                     │
                    HTTP (localhost:8080)   WS (localhost:8081)
                    静态文件 / 导出 / 版本    CRUD + 广播事件
                              │                     │
┌─────────────────────────────┼─────────────────────┼──┐
│              Python Server (app/server/)              │
│  ┌────────────────────────┐ ┌─────────────────────┐  │
│  │ ApiHandler (HTTP)      │ │ WsServer (WebSocket) │  │
│  │ 静态文件 + 工具端点     │ │ server.py + router.py│  │
│  │ (status/export/version)│ │ + handlers/          │  │
│  └────────────────────────┘ └──────────┬──────────┘  │
│                                        │             │
│  ┌─────────────────────────────────────┤             │
│  │  app/services/session_manager.py   │             │
│  │  ┌────────────┐  ┌────────────────┐ │             │
│  │  │ Session    │  │ SessionManager │ │             │
│  │  │ (id/db/path)│  │ (线程安全字典) │ │             │
│  │  └────────────┘  └────────────────┘ │             │
│  └─────────────────────────────────────┘             │
│           │                                          │
│  ┌────────┴────────────────────────────┐            │
│  │  app/models/ 数据模型层                │            │
│  │  CanDatabase (RLock) → Message → Signal (UUID)   │
│  │  + 信号验证 (重叠/越界) + Properties/DBC 序列化   │
│  └─────────────────────────────────────┘            │
│                                                      │
│  ┌─────────────────────────────────────┐            │
│  │  app/io/  格式 IO 层                  │            │
│  │  properties_io.py  dbc_io.py         │            │
│  │  json_io.py  xml_io.py  c_code_gen.py│            │
│  └─────────────────────────────────────┘            │
│                                                      │
│  ┌─────────────────────────────────────┐            │
│  │  tools/cli.py — CLI 无头会话层        │            │
│  │  CanMatrixSession + OpResult        │            │
│  └─────────────────────────────────────┘            │
└──────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
frontend/src/          (Vue 3 SPA, 7 Pinia Stores)
  └── 通过 WebSocket ──→ app/ws/server.py
        ├── app/ws/router.py  (消息路由 type → handler)
        │     └── app/ws/handlers/  (27 个 Handler，4 个业务域)
        │           └── app/services/session_manager.py  (会话管理)
        │                 └── app/models/  (CanDatabase/Message/Signal + RLock)
        └── app/ws/transport.py  (连接管理 + 广播 + 诊断)

app/server/lifecycle.py  (HTTP + WS 启动入口 + Handler 注册)
app/server/http_handler.py  (静态文件 + 工具端点)

app/io/  (格式 IO 层)
  ├── properties_io.py  (Properties 读写)
  ├── json_io.py        (JSON 读写)
  ├── xml_io.py         (XML 读写)
  ├── dbc_io.py         (DBC 导入导出 via cantools)
  └── c_code_gen.py     (C 代码生成 via Jinja2)

tools/cli.py  (CLI 无头会话层，使用 app/models/ 同一模型)
```

### 2.3 数据流

**导入路径（打开 DBC/Properties 文件）**：
```
本地文件 → 前端 FileReader 读取内容
  → WS request: import_file {format, content, filename}
    → ImportFileHandler.__call__()
      → CanDatabase.from_properties_str() / from_dict()
        → 创建新 Session，返回 session_id
          → WS 重连 + full_sync 同步全量数据
```

**运行时编辑**：
```
Vue 组件用户编辑 → Pinia store 方法 (如 signals.updateSignal())
  → editor._wsRequest(type, data) [WsSyncClient]
    → WS Handler 执行操作 + 广播事件
      → 后端 Session.db 内存更新
        → WS 广播 signal_updated/message_updated 等事件
          → editor._applyWsMessage() 更新前端状态
```

**导出路径**：
```
Vue 组件点击导出 → WS request: download_file {format}
  → DownloadFileHandler → db.to_dbc_str() / to_properties_str()
    → 返回文件内容 → 前端 Blob 下载

或通过 HTTP GET /api/export?sid=xxx&fmt=dbc (辅助路径)
```

**会话恢复**：
```
浏览器重新打开 → sessionStorage 读取 session_id
  → 前端 WS 连接 + hello {session_id} 握手
    → WsServer 验证/恢复 session
      → WS full_sync 推送全量数据（messages + status）
        → editor._applyWsMessage() 恢复前端状态
```


---

## 第 3 章：核心数据模型

### 3.1 设计背景：Per-Message 信号模型

DBC 语义中，**信号是 per-message 的定义**——同一个信号名（如 `RPM`）在报文 A 和报文 B 中可以拥有完全不同的起始位、长度、因子和偏移量。因此本项目**没有全局信号注册表**，每个 `Message` 对象持有自己的 `signals: list[Signal]`。

### 3.2 Signal

**运行时常驻版本**（`app/models/` 目录：`signal.py` + `message.py` + `database.py`）：

```python
class Signal:
    name: str = ""
    uuid: str          # 运行时唯一标识（8 位 hex），前端-后端通信用
    start_bit: int = 0
    length: int = 8
    byte_order: str = "little_endian"   # "little_endian" | "big_endian"
    is_signed: bool = False
    factor: float = 1.0
    offset: float = 0.0
    min_val: float = 0.0
    max_val: float = 0.0
    unit: str = ""
    comment: str = ""
    receivers: list[str] = []
    multiplexer_mode: str = "none"      # "none" | "multiplexer" | "multiplexed"
    multiplexer_value: int = 0
```

**字段说明**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `""` | 信号名称 |
| `uuid` | `str` | 自动生成 | 运行时标识（仅 app/models/ 版） |
| `start_bit` | `int` | `0` | 起始位（0~63） |
| `length` | `int` | `8` | 信号长度（位） |
| `byte_order` | `str` | `"little_endian"` | Intel（小端）/ Motorola（大端） |
| `is_signed` | `bool` | `False` | 是否有符号整数 |
| `factor` | `float` | `1.0` | 物理值 = 原始值 × factor + offset |
| `offset` | `float` | `0.0` | 偏移量 |
| `min_val` / `max_val` | `float` | `0.0` | 物理值有效范围 |
| `unit` | `str` | `""` | 物理单位（如 `rpm`、`°C`） |
| `receivers` | `list[str]` | `[]` | 接收节点列表 |
| `multiplexer_mode` | `str` | `"none"` | 复用模式 |
| `multiplexer_value` | `int` | `0` | 复用值（仅 `multiplexed` 模式有效） |

### 3.3 Message

```python
class Message:
    id: int = 0
    name: str = ""
    dlc: int = 8
    cycle_time: int = 0        # ms, 0 = event-triggered
    comment: str = ""
    sender: str = ""
    signals: list[Signal] = []  # 该报文包含的信号对象列表
```

### 3.4 CanDatabase（运行时版本）

```python
class CanDatabase:
    name: str
    messages: dict[int, Message]   # key: CAN ID (int)
    modified: bool                  # 是否有未保存的修改
    __lock: threading.RLock         # 线程安全锁
```

**核心方法**：

| 方法 | 说明 |
|------|------|
| `add_message(msg) → bool` | 按 CAN ID 添加报文（重名返回 False） |
| `remove_message(msg_id) → Message | None` | 按 ID 删除报文 |
| `get_message(msg_id) → Message | None` | 按 ID 获取报文 |
| `update_message(msg_id, **kwargs) → bool` | 按关键字更新报文属性 |
| `move_message(old_id, new_id) → bool` | 移动报文到新 CAN ID |
| `add_signal_to_message(msg_id, sig) → bool` | 向报文追加信号（自动确保 UUID 唯一） |
| `remove_signal_from_message(msg_id, sig_uuid) → bool` | 按 UUID 从报文删除信号 |
| `update_signal_in_message(msg_id, sig_uuid, **kwargs) → bool` | 按 UUID 更新信号字段 |
| `validate_signal(msg_id, sig) → (bool, str, dict)` | 验证单个信号的位域合法性 |
| `validate_all_signals(msg_id) → list[dict]` | 返回报文全部信号的布局错误列表 |
| `total_signals() → int` | 统计全部信号总数 |
| `to_dict() → dict` | 序列化为字典（含十六进制 key） |
| `to_properties_str() → str` | 序列化为 Properties 字符串（稀疏输出） |
| `to_dbc_str() → str` | 导出为 DBC 格式字符串 |
| `from_properties_str(content) → CanDatabase` | 从 Properties 字符串反序列化 |
| `from_dict(data) → CanDatabase` | 从字典反序列化 |

### 3.5 信号布局验证

`_get_signal_bits()` 将信号按字节序展开为占用的物理 bit 集合：

- **Intel（小端序）**：从 `start_bit` 开始连续递增 `length` 位
- **Motorola（大端序）**：从 `start_bit`（MSB）开始，字节内从高位向低位填充，到达 bit0 后跳到下一字节的 bit7

`validate_signal()` 执行两项检查：
1. **越界检查**：信号占用的位是否超出 `DLC × 8` 范围
2. **重叠检查**：信号占用的位是否与同报文其他信号冲突

两项检查失败时均返回修复建议（`suggestion` 字段，包含推荐的 `start_bit`）。


---

## 第 4 章：序列化格式设计

### 4.1 格式对比

| 维度 | Properties | DBC（原始） | JSON | XML |
|------|------|-------------|------|-----|
| **可读性** | ★★★★★ | ★★ | ★★★ | ★★ |
| **Git diff 友好** | ★★★★★ | ★★ | ★★★ | ★★ |
| **CAN 语义贴合** | ★★★★ 支持 `0x` 十六进制 | ★★★ | ★★★ | ★★★ |
| **注释支持** | ★★★★★ `#` | ★★★ `CM_` | ❌ | ★★★ |
| **本项目角色** | **主存储格式** | 交换格式 | 辅助格式 | 辅助格式 |

### 4.2 Properties 格式结构

```properties
# CanMatrix Editor - CAN Database Definition

database.name=MyVehicle
messages.0x100.name=EngineData
messages.0x100.dlc=8
messages.0x100.cycle_time=10
messages.0x100.sender=ECU1
messages.0x100.signals.RPM.name=RPM
messages.0x100.signals.RPM.start_bit=0
messages.0x100.signals.RPM.length=16
messages.0x100.signals.RPM.byte_order=little_endian
messages.0x100.signals.RPM.factor=1.0
messages.0x100.signals.RPM.max_val=8000.0
messages.0x100.signals.RPM.unit=rpm
messages.0x100.signals.RPM.receivers=["BCM", "ICU"]
```

**Properties 序列化实现**：

| 实现位置 | 方式 | 用途 |
|----------|------|------|
| `app/io/properties_io.py` → `save_properties()` | `javaproperties.dumps()` | CLI 离线保存，精确控制稀疏输出 |
| `app/models/database.py` → `CanDatabase.to_properties_str()` | `javaproperties.dumps()` | Web 运行时保存，过滤默认值字段 |

两个实现均遵循稀疏输出策略，结果等价。

### 4.3 稀疏输出策略

保存时过滤与默认值相等的字段。默认值定义在 `_SIGNAL_DEFAULTS`：

```python
_SIGNAL_DEFAULTS = {
    "name": "", "start_bit": 0, "length": 8,
    "byte_order": "little_endian", "is_signed": False,
    "factor": 1.0, "offset": 0.0, "min_val": 0.0, "max_val": 0.0,
    "unit": "", "comment": "", "receivers": [],
    "multiplexer_mode": "none", "multiplexer_value": 0,
}
```

**效果**：完整 Signal 有 14 个字段，稀疏输出后平均只输出 4~6 个非默认字段。

### 4.4 十六进制 CAN ID

- Properties 输出时 CAN ID 使用 `"0x100"` 字符串格式作为 dotted key 的一部分
- 反序列化时检测 `0x` 前缀后调用 `int(val, 16)` 解析

### 4.5 DBC 导入/导出

**导入**（`app/io/dbc_io.py` → `import_dbc()`）：
1. `cantools.database.load_file()` 解析 DBC
2. 遍历 `can_db.messages`，转换每个 `cantools Message` → 内部 `Message`
3. 转换每个 `cantools Signal` → 内部 `Signal`（处理字节序、线性/恒等转换、复用模式）
4. 提取周期时间（从 DBC attributes 中匹配 `cycle` 关键字）和发送节点
5. 构建并返回内部 `CanDatabase`

**导出**（`app/io/dbc_io.py` → `export_dbc()`）：
1. 构建 `cantools.database.Database()` 对象
2. 遍历内部 `Message` → `cantools Message`，`Signal` → `cantools Signal`
3. 根据 factor/offset 选择 `LinearConversion` 或 `IdentityConversion`
4. `cantools.database.dump_file()` 写入 DBC

**Web 运行时**的 DBC 导出走 `app/models/database.py` 的 `CanDatabase.to_dbc_str()`，手动构造 DBC 文本（不依赖 `app/io/dbc_io.py`），包含完整的 `NS_`、`BU_`、`BO_`、`SG_`、`CM_` 段。

### 4.6 JSON/XML

`app/io/json_io.py` 和 `app/io/xml_io.py` 提供离线读写。Web 运行时的 JSON 序列化通过 `CanDatabase.to_dict()` / `from_dict()`，XML 仅离线 CLI 支持。


---

## 第 5 章：会话管理

### 5.1 核心概念

每个浏览器标签页对应一个独立的 **Session**，绑定一个磁盘 Properties 文件。前端显式触发保存，浏览器崩溃后可通过 `sessionStorage` 中的 `session_id` 恢复。

### 5.2 Session 数据结构

```python
class Session:
    id: str              # 12 位 hex UUID
    file_path: str       # 绑定的数据文件绝对路径
    db: CanDatabase      # 内存中的数据库实例（app/models/ 版）
    created_at: float    # 创建时间戳
    last_access: float   # 最后访问时间戳
```

### 5.3 SessionManager

全局单例，维护 `dict[session_id → Session]`，线程安全（`threading.Lock`）。

| 方法 | 说明 |
|------|------|
| `set_model_factory(factory)` | 注入 CanDatabase 类（由 app/server/lifecycle.py 调用） |
| `create(file_name, db) → session_id` | 创建新 Session 并立即落盘 |
| `get(session_id) → Session | None` | 获取 Session（自动续期，过期则销毁） |
| `restore(session_id) → Session | None` | 从内存或磁盘恢复 Session |
| `save(session_id) → bool` | 手动保存到磁盘（原子写入） |
| `rename(session_id, new_name) → bool` | 重命名数据库并同步更新文件名 |
| `destroy(session_id) → bool` | 销毁 Session（仅清理内存，保留磁盘文件） |
| `list_sessions() → list[dict]` | 列出所有活跃会话 |
| `list_history() → list[dict]` | 扫描 data/ 目录，返回全部历史记录 |
| `load_history(session_id) → Session` | 从历史文件加载，创建新 Session（原数据保留） |
| `delete_history(session_id) → bool` | 删除历史会话（内存 + 磁盘） |
| `cleanup()` | 清理超过 30 分钟未访问的过期 Session |

### 5.4 文件命名与存储

- 存储目录：`data/`（项目根目录下，gitignored）
- 文件名格式：`{name}.properties`（旧格式 `{session_id}_{name}.properties` 自动迁移）
- 原子写入：先写 `.tmp` 临时文件，再 `os.replace()` 覆盖目标文件

### 5.5 手动保存

前端显式发送 WS `save` 请求，后端 `SaveHandler` 调用 `SessionManager.save()` 原子写入磁盘。HTTP 端点已不再处理 CRUD 操作。


---

## 第 6 章：WebSocket 协议设计

### 6.1 概述

- **WS 库**：`websockets` (Python)
- **并发模型**：`asyncio` 事件循环 + `asyncio.to_thread` 执行同步 Handler
- **端口**：HTTP 端口 + 1（默认 8081），路径 `/ws`
- **消息格式**：JSON，请求携带 `requestId`，响应回传同一 `requestId`
- **重连策略**：指数退避（1s → 2s → 4s → ... → max 30s）

### 6.2 WS 消息格式

**请求**（前端 → 后端）：
```json
{ "type": "edit_signal", "requestId": "abc123", "data": { ... }, "session_id": "..." }
```

**响应**（后端 → 前端）：
```json
{ "type": "ok", "requestId": "abc123", "data": { ... }, "new_version": 42 }
```

**错误响应**：
```json
{ "type": "error", "requestId": "abc123", "code": "SIGNAL_OVERLAP", "message": "...", "details": {} }
```

**广播事件**（后端 → 同 session 所有连接）：
```json
{ "type": "signal_updated", "data": { "msg_id": 256, "signal": {...} }, "data_version": 42 }
```

### 6.3 Handler 清单（27 个 type）

| 业务域 | Type | Handler |
|--------|------|----------|
| 信号 | `edit_signal` | `EditSignalHandler` |
| 信号 | `add_signal` | `AddSignalHandler` |
| 信号 | `delete_signal` | `DeleteSignalHandler` |
| 信号 | `batch_add_signals` | `BatchAddSignalsHandler` |
| 信号 | `get_signal_errors` | `GetSignalErrorsHandler` |
| 报文 | `edit_message` | `EditMessageHandler` |
| 报文 | `add_message` | `AddMessageHandler` |
| 报文 | `delete_message` | `DeleteMessageHandler` |
| 报文 | `duplicate_message` | `DuplicateMessageHandler` |
| 报文 | `get_message` | `GetMessageHandler` |
| 报文 | `get_messages` | `GetMessagesHandler` |
| 文件 | `save` | `SaveHandler` |
| 文件 | `new_file` | `NewFileHandler` |
| 文件 | `import_file` | `ImportFileHandler` |
| 文件 | `download_file` | `DownloadFileHandler` |
| 文件 | `create_file` | `CreateFileHandler` |
| 文件 | `load_file` | `LoadFileHandler` |
| 文件 | `save_as` | `SaveAsHandler` |
| 文件 | `delete_file` | `DeleteFileHandler` |
| 文件 | `get_sessions` | `GetSessionsHandler` |
| 系统 | `undo` | `UndoHandler` |
| 系统 | `redo` | `RedoHandler` |
| 系统 | `release_lock` | `ReleaseLockHandler` |
| 系统 | `steal_lock` | `StealLockHandler` |
| 系统 | `get_summary` | `GetSummaryHandler` |
| 系统 | `get_session_info` | `GetSessionInfoHandler` |
| 系统 | `get_status` | `GetStatusHandler` |

### 6.4 连接生命周期

```
hello {session_id} → hello_ack → full_sync → 消息循环 → cleanup
```

- **hello 握手**：5s 超时，验证或创建 session
- **full_sync**：推送全量数据（messages + status + lock_status）
- **消息循环**：请求-响应 + 广播事件
- **心跳**：前端 30s ping，后端 pong
- **关闭码分类**：4xxx 停止重连（`permanent_failure`），其他码正常重连

### 6.5 HTTP 保留端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 简单健康检查 `{"status": "ok"}` |
| GET | `/api/version` | 返回版本号 + 版本 hash |
| GET | `/api/export` | 文件导出下载（dbc/properties/c_header/c_source） |
| GET | `/api/diag` | WS 诊断快照（需 --ws-debug） |
| POST | `/api/release` | 释放 session 锁 |
| PUT/DELETE | `*` | 返回 404："All CRUD operations moved to WebSocket." |

### 6.6 静态文件服务

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Vue 构建产物 `dist/index.html` |
| GET | `/assets/*` | Vite 构建的 JS/CSS 资源 |


---

## 第 7 章：CLI 层设计

### 7.1 CanMatrixSession

`tools/cli.py` 提供 `CanMatrixSession` 类作为**无头（headless）会话**，镜像 Web GUI 的所有操作：

```python
class CanMatrixSession:
    database: CanDatabase       # app/models/database.py 版本
    current_filepath: str | None
    _modified: bool
```

### 7.2 OpResult 模式

所有操作返回 `OpResult` 对象：

```python
class OpResult:
    success: bool
    message: str
    data: object | None

    @staticmethod
    def ok(msg, data) → OpResult
    @staticmethod
    def fail(msg) → OpResult
```

### 7.3 公开 API

**文件操作**：`new_database(name)`, `open_file(path)`, `save(path?)`, `save_as(path, fmt)`, `export_dbc(path)`

**报文操作**：`add_message(msg)`, `force_add_message(msg)`, `remove_message(msg_id)`, `update_message(msg_id, **kw)`, `get_message(msg_id)`, `list_messages()`

**信号操作**：`add_signal(msg_id, sig)`, `remove_signal(msg_id, sig_name)`, `update_signal(msg_id, sig_name, **kw)`

**查询**：`is_modified`, `message_count`, `total_signal_count()`, `summary()`

### 7.4 CLI 与 Web 运行时的关系

- `tools/cli.py` 使用 `app/models/database.py` 同一模型（有 UUID，有 RLock）
- `app/server/lifecycle.py` 使用同一模型，通过 WS Handler 操作
- `app/server/` 不依赖 `tools/cli.py`；`app/services/session_manager.py` 直接操作 CanDatabase
- `cli.py` 仅供命令行脚本和测试使用


---

## 第 8 章：前端架构

### 8.1 技术栈

| 技术 | 版本 | 用途 |
|------|------|------|
| Vue 3 | ^3.5.13 | UI 框架（Composition API + `<script setup>`） |
| Pinia | ^3.0.2 | 状态管理 |
| Vite | ^6.3.5 | 构建工具与开发服务器 |
| 纯 CSS (OKLCH) | — | 样式（CSS 自定义属性实现暗/亮主题） |

### 8.2 项目结构

```
frontend/
├── index.html
├── package.json
├── vite.config.js          # 构建输出 → ../dist
└── src/
    ├── main.js             # createApp + Pinia 挂载
    ├── App.vue             # 根组件：三栏布局 + 主题 + 右键菜单 + 快捷键
    ├── i18n.js             # 中/英文国际化
    ├── api/
    │   └── client.js       # Session ID 管理（sessionStorage 持久化）
    ├── stores/
    │   ├── editor.js       # 核心数据 + WS 连接 + 消息分发 + 健康检查 (422 行)
    │   ├── uiStore.js      # UI 状态（Toast、模态框、主题） (76 行)
    │   ├── messages.js     # 报文 CRUD (112 行)
    │   ├── signals.js      # 信号 CRUD + 批量创建 (180 行)
    │   ├── clipboard.js    # 信号/报文剪贴板 (98 行)
    │   ├── fileOperations.js # 文件操作 (205 行)
    │   └── undoRedo.js     # 撤销/重做计数器 (67 行)
    ├── utils/
    │   ├── ws-client.js    # WS 客户端（连接 + 重连 + 心跳） (293 行)
    │   ├── storeHelpers.js # Store 工具函数 (150 行)
    │   ├── signalLayout.js # 信号 bit 布局计算
    │   ├── format.js       # 格式化工具
    │   └── version-check.js # 版本检查
    ├── directives/
    │   └── lazyValue.js    # Vue 自定义指令
    └── components/
        ├── TopBar.vue          # 顶部导航栏
        ├── MessageList.vue     # 左侧报文列表
        ├── SignalTable.vue     # 中央可编辑信号表格
        ├── MessagePanel.vue    # 右侧报文属性编辑面板
        ├── StatusBar.vue       # 底部状态栏
        ├── Toast.vue           # Toast 通知
        ├── LoadingOverlay.vue  # 加载遮罩
        ├── ContextMenu.vue     # 右键上下文菜单
        ├── BatchModal.vue      # 批量创建信号弹窗
        ├── FileBrowser.vue     # 文件浏览器（创建/加载/删除/导入文件）
        ├── SignalLayoutVisualizer.vue # 信号布局可视化
        └── LogPanel.vue        # 操作日志面板
```

### 8.3 Pinia Store（7 Store 架构）

应用状态拆分为 7 个专职 Store：

| Store | 职责 | 行数 |
|-------|------|------|
| **editor** | 核心数据 + WS 连接管理 + 广播消息分发 + 健康检查 + 日志 | 422 |
| **ui** | Toast、上下文菜单、模态框、主题、布局视图、日志面板 | 76 |
| **messages** | 报文 CRUD（加载、选中、添加、删除、属性编辑） | 112 |
| **signals** | 信号 CRUD（添加、编辑、删除、批量创建、自动修复） | 180 |
| **clipboard** | 信号/报文剪贴板（复制、剪切、粘贴、复制报文） | 98 |
| **fileOperations** | 文件操作（保存、加载、另存为、新建、导入、释放锁） | 205 |
| **undoRedo** | 撤销/重做计数器 + WS 请求 | 67 |

- **数据更新模式**：服务端权威 + WS 广播同步（发 WS 请求 → 等待服务端确认 → 广播事件更新 UI）
- **撤销栈**：后端 `undo_engine.py` 管理，50 步，前端仅维护计数器
- **剪贴板**：支持信号和报文的复制/剪切/粘贴（Ctrl+C/V/X）
- **批量信号创建**：模板展开生成多条信号
- **WS 健康检查**：检查 WS 连接状态，2s 定时器
- **信号错误获取**：选中报文时通过 WS 请求获取布局验证结果
- **主题切换**：dark/light 主题持久化到 localStorage
- **国际化**：zh/en 切换

### 8.4 SignalTable 组件

核心工作区的可编辑信号表格：
- 列：Name, Start Bit, Length, Byte Order, Factor, Offset, Min, Max, Unit, Comment
- 行内编辑，blur 触发 API 保存
- 红色边框高亮有重叠/越界错误的信号
- 自动修复建议按钮
- 行选择支持剪贴板操作

### 8.5 构建与部署

- 开发模式：`cd frontend && npm run dev`（Vite 开发服务器 :5173，代理 API 到 :8080）
- 生产构建：`npm run build` → 输出到 `dist/`
- 后端服务：`python -m app.server.lifecycle` → 访问 `http://localhost:8080/`


---

## 第 9 章：关键设计决策

### 9.1 Properties 作为主存储格式

**决策**：以 Java Properties 为主存储格式，DBC 仅作为导入/导出格式。

- ✅ dotted keys 嵌套贴合 per-message 信号模型（如 `messages.0x100.signals.RPM`）
- ✅ 增删信号只影响所在报文块，不会导致全文行位移
- ✅ 注释以 `#` 书写，工程师可自由添加备注
- ✅ O(n) 线性序列化性能（javaproperties 库）

### 9.2 稀疏输出

**决策**：保存时只输出非默认值字段。

- ✅ 文件简洁，平均减少 60% 行数
- ✅ diff 精准，修改一个字段只显示一行变更
- ⚠️ 反序列化时需回填默认值

### 9.3 轻量级 B/S 架构

**决策**：浏览器前端 + Python HTTP/WebSocket 后端，不使用 Electron/PyQt/重量级 Web 框架。

- ✅ 前端技术栈（Vue 3 + Vite）生态成熟，UI 开发效率高
- ✅ Python 源码直接运行，跨平台成本低
- ✅ 依赖轻量：`cantools` + `javaproperties` + `websockets` + `Jinja2`
- ⚠️ 后端仅绑定 localhost，不支持远程访问（这是设计意图）

### 9.4 统一数据模型

**决策**：`app/models/` 下使用统一的 CanDatabase 模型（含 UUID、RLock、信号验证）。

- CLI 和 Web 运行时共享同一模型，避免维护两套实现的同步负担
- Signal 含 UUID 用于前端-后端通信，Message 含完整信号列表
- CanDatabase 含 `threading.RLock` 线程安全 + `modified` 标志 + 信号验证方法

### 9.5 Per-Message 信号模型

**决策**：信号是 per-message 定义，不维护全局信号注册表。

- ✅ 贴合 DBC 语义，模型直观
- ✅ 复制报文时通过深拷贝可完全独立复制信号定义
- ⚠️ 同名信号跨报文的一致性需工程师手动保证（DBC 本身也无此保证）

### 9.6 会话即文件

**决策**：每个编辑会话绑定一个磁盘文件，变更即时原子写入。

- ✅ 数据文件是唯一持久化真相源
- ✅ 原子写入防止崩溃损坏
- ✅ `localStorage` 仅存 `session_id`，不缓存业务数据

### 9.7 服务端权威 + WS 广播同步

**决策**：前端发 WS 请求等待服务端确认，通过广播事件同步更新 UI。

- ✅ 数据一致性由服务端保证，前端无需回滚逻辑
- ✅ 广播事件确保多标签页数据同步
- ✅ `data_version` 防止乱序更新
- ⚠️ 操作延迟比乐观 UI 略高（等待服务端响应）


---

## 第 10 章：安全性设计

### 10.1 数据安全

- **纯本地应用**：仅绑定 `localhost:8080`，不发起任何外部网络请求
- **无遥测/无账号/无云服务**
- **文件原子写入**：`.tmp` → `os.replace()` 防止崩溃损坏
- **权限需求**：仅需对项目目录和 `.properties`/`.dbc` 文件的读写权限，无需管理员权限

### 10.2 输入安全

| 格式 | 解析器 | 安全性 |
|------|--------|--------|
| Properties | `javaproperties`（PyPI 纯 Python） | 无 C 扩展，无已知安全漏洞 |
| JSON | `json`（stdlib） | 标准库，安全性极高 |
| XML | `xml.etree.ElementTree`（stdlib） | 默认禁用外部实体（XXE 防护） |
| DBC | `cantools.database.load_file()` | 成熟开源库，DBC 非可执行格式 |

### 10.3 输入验证

| 字段 | 后端验证 |
|------|---------|
| 报文 CAN ID | 支持十进制和 `0x` 十六进制解析，重复检查 |
| 报文 DLC | 隐式通过信号越界检查约束（`dlc × 8` 位范围） |
| 信号起始位/长度 | `validate_signal()` 检查越界和重叠 |
| 信号 UUID | `_ensure_sig_uuid_unique()` 自动去重 |

### 10.4 依赖

`requirements.txt`：
```
cantools>=39.0.0
javaproperties>=0.8.0
websockets>=12.0
Jinja2>=3.1.0
```

四个运行时依赖，均为成熟 PyPI 包。


---

## 第 11 章：文件清单

| 文件路径 | 职责 |
|---------|------|
| `app/server/lifecycle.py` | HTTP + WS 服务启动入口 + 生命周期管理 + Handler 注册 |
| `app/server/http_handler.py` | 静态文件服务 + HTTP 工具端点（status/version/export/diag/release） |
| `app/server/port_utils.py` | 端口检测工具 |
| `app/models/database.py` | CanDatabase 运行时模型（RLock + 信号验证 + 序列化） |
| `app/models/signal.py` | Signal 数据类 |
| `app/models/message.py` | Message 数据类 |
| `app/services/session_manager.py` | 会话生命周期管理（超时清理） |
| `app/services/session.py` | Session 数据类 |
| `app/services/file_lock.py` | 文件锁（多标签页互斥） |
| `app/services/file_persistence.py` | 磁盘持久化（原子写入） |
| `app/services/undo_engine.py` | 撤销/重做引擎（含孤儿栈） |
| `app/io/properties_io.py` | Properties 读写（javaproperties 库，稀疏输出） |
| `app/io/dbc_io.py` | DBC 导入/导出（via cantools） |
| `app/io/json_io.py` | JSON 读写 |
| `app/io/xml_io.py` | XML 读写（ElementTree + minidom 格式化） |
| `app/io/c_code_gen.py` | C 代码生成（Jinja2 模板） |
| `app/ws/server.py` | WebSocket 服务端（连接生命周期 + full_sync） |
| `app/ws/transport.py` | WS I/O 封装（连接管理 + 广播 + 诊断） |
| `app/ws/router.py` | 消息路由（type → handler 分发 + HandlerResult/HandlerError） |
| `app/ws/handlers/*.py` | 业务 Handler（27 个，4 个业务域：信号/报文/文件/系统） |
| `tools/cli.py` | CanMatrixSession + OpResult：CLI 无头会话层 |
| `tools/desktop.py` | 桌面应用入口（pywebview） |
| `tools/compute_version.py` | 版本号计算脚本 |
| `requirements.txt` | Python 依赖声明 |
| `frontend/package.json` | Vue 3 + Pinia + Vite 依赖 |
| `frontend/vite.config.js` | Vite 构建配置（输出路径） |
| `frontend/src/App.vue` | 根组件：布局、主题、快捷键 |
| `frontend/src/stores/` | Pinia 状态管理（7 个 Store：editor + ui + messages + signals + clipboard + fileOperations + undoRedo） |
| `frontend/src/utils/` | 工具函数（ws-client.js + storeHelpers.js + signalLayout.js + format.js + version-check.js） |
| `frontend/src/components/` | UI 组件（12 个） |
| `desktop.spec` | PyInstaller 打包配置 |
| `build.bat` / `build.sh` | 构建脚本 |
| `data/` | 运行时会话数据目录（gitignored） |
| `dist/` | Vite 前端构建产物（gitignored） |
