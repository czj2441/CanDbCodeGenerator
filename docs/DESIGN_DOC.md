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
- **Web 前端 + Python 后端**：Vue 3 + Vite 构建前端，Python 标准库 `http.server` 提供 REST API。
- **会话隔离与自动持久化**：每个浏览器标签页绑定独立 session，变更自动落盘，崩溃后可恢复。
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

当前架构采用 **Web 前端（Vue 3 + Vite）+ Python HTTP API 后端** 的 B/S 模式：

```
┌──────────────────────────────────────────────────────┐
│                    浏览器 (Browser)                    │
│  ┌────────────────────────────────────────────────┐  │
│  │          Vue 3 SPA (dist/ + Vite 构建)          │  │
│  │  ┌──────────┐ ┌──────────┐ ┌───────────────┐  │  │
│  │  │ Pinia    │ │ Vue      │ │ api/client.js │  │  │
│  │  │ Store    │ │ Components│ │ (fetch 封装)  │  │  │
│  │  └──────────┘ └──────────┘ └───────┬───────┘  │  │
│  │                                     │          │  │
│  │  localStorage ← session_id 持久化   │          │  │
│  └─────────────────────────────────────┼──────────┘  │
└────────────────────────────────────────┼─────────────┘
                                         │ HTTP (localhost:8080)
                                         │ X-Session-Id header
┌────────────────────────────────────────┼─────────────┐
│              Python HTTP Server (api_server.py)       │
│  ┌─────────────────────────────────────┐            │
│  │   ApiHandler (BaseHTTPRequestHandler)│            │
│  │   ┌──────────┐  ┌────────────────┐  │            │
│  │   │ REST API │  │ 静态文件服务    │  │            │
│  │   │ 路由处理  │  │ (dist/ + 遗留) │  │            │
│  │   └────┬─────┘  └────────────────┘  │            │
│  └────────┼────────────────────────────┘            │
│           │                                          │
│  ┌────────┼────────────────────────────┐            │
│  │  session_manager.py                 │            │
│  │  ┌─────┴──────┐  ┌────────────────┐ │            │
│  │  │ Session    │  │ SessionManager │ │            │
│  │  │ (id/db/path)│  │ (线程安全字典) │ │            │
│  │  └────────────┘  └────────────────┘ │            │
│  └─────────────────────────────────────┘            │
│           │                                          │
│  ┌────────┴────────────────────────────┐            │
│  │  api_server 内联数据模型              │            │
│  │  CanDatabase (RLock) → Message → Signal (UUID)   │
│  │  + 信号验证 (重叠/越界) + Properties/DBC 序列化        │
│  └─────────────────────────────────────┘            │
│                                                      │
│  ┌─────────────────────────────────────┐            │
│  │  core/  独立数据模型 + IO 层          │            │
│  │  can_database.py  properties_io.py        │            │
│  │  dbc_io.py         json_io.py       │            │
│  │  xml_io.py                           │            │
│  └─────────────────────────────────────┘            │
│                                                      │
│  ┌─────────────────────────────────────┐            │
│  │  cli.py — CLI 无头会话层             │            │
│  │  CanMatrixSession + OpResult        │            │
│  └─────────────────────────────────────┘            │
└──────────────────────────────────────────────────────┘
```

### 2.2 模块依赖关系

```
frontend/src/          (Vue 3 SPA)
  └── 通过 REST API (fetch) ──→ api_server.py
        ├── session_manager.py  (会话管理)
        │     └── api_server 内联数据模型 (CanDatabase/Message/Signal + RLock)
        └── cli.py  (CLI 会话)
              └── core/
                    ├── can_database.py  (dataclass 数据模型)
                    ├── properties_io.py  (Properties 读写)
                    ├── json_io.py       (JSON 读写)
                    ├── xml_io.py        (XML 读写)
                    └── dbc_io.py        (DBC 导入导出 via cantools)
```

**两层数据模型说明**：

| 位置 | 用途 | 特点 |
|------|------|------|
| `core/can_database.py` | CLI 脚本、测试、离线操作 | dataclass 装饰器，无 UUID，无锁，纯数据 |
| `api_server.py` 内联类 | Web 运行时服务 | 普通类 + `__init__`，Signal 含 UUID，CanDatabase 含 `threading.RLock` + `modified` 标志 + 信号验证方法 |

两者字段相同但实现独立。`session_manager.py` 通过 `set_model_factory()` 注入 `api_server` 的 `CanDatabase` 类。

### 2.3 数据流

**导入路径（打开 DBC/Properties 文件）**：
```
本地文件 → 前端 FileReader 读取内容
  → POST /api/import {format, content}
    → api_server._post_import()
      → CanDatabase.from_properties_str() / from_dict()
        → 替换当前 Session 的 db
          → 自动保存到 data/{session_id}_{name}.properties
```

**运行时编辑**：
```
Vue 组件用户编辑 → Pinia store 方法
  → api/client.js fetch() + X-Session-Id
    → ApiHandler CRUD 端点
      → Session.db 内存操作
        → _auto_save() 后台线程延迟 500ms 写入磁盘
```

**导出路径**：
```
Vue 组件点击导出 → Pinia store.exportDatabase()
  → POST /api/export {format: "dbc"|"properties"|"json"}
    → db.to_dbc_str() / to_properties_str() / to_dict()
      → 返回字符串内容 → 前端 Blob 下载
```

**会话恢复**：
```
浏览器重新打开 → localStorage 读取 session_id
  → GET /api/session/{id}
    → SessionManager.restore()
      → 从 data/ 目录查找 {id}_*.properties
        → 解析重建 CanDatabase → 返回前端完整数据
```


---

## 第 3 章：核心数据模型

### 3.1 设计背景：Per-Message 信号模型

DBC 语义中，**信号是 per-message 的定义**——同一个信号名（如 `RPM`）在报文 A 和报文 B 中可以拥有完全不同的起始位、长度、因子和偏移量。因此本项目**没有全局信号注册表**，每个 `Message` 对象持有自己的 `signals: list[Signal]`。

### 3.2 Signal

**运行时常驻版本**（`api_server.py` 内联）：

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

**独立 dataclass 版本**（`core/can_database.py`）：字段相同，无 `uuid`，使用 `@dataclass` 装饰器，带 `to_dict()` / `from_dict()` 方法。

**字段说明**：

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `name` | `str` | `""` | 信号名称 |
| `uuid` | `str` | 自动生成 | 运行时标识（仅 api_server 内联版） |
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
| `core/properties_io.py` → `save_properties()` | `javaproperties.dumps()` | CLI 离线保存，精确控制稀疏输出 |
| `models.py` → `CanDatabase.to_properties_str()` | `javaproperties.dumps()` | Web 运行时保存，过滤默认值字段 |

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

**导入**（`core/dbc_io.py` → `import_dbc()`）：
1. `cantools.database.load_file()` 解析 DBC
2. 遍历 `can_db.messages`，转换每个 `cantools Message` → 内部 `Message`
3. 转换每个 `cantools Signal` → 内部 `Signal`（处理字节序、线性/恒等转换、复用模式）
4. 提取周期时间（从 DBC attributes 中匹配 `cycle` 关键字）和发送节点
5. 构建并返回内部 `CanDatabase`

**导出**（`core/dbc_io.py` → `export_dbc()`）：
1. 构建 `cantools.database.Database()` 对象
2. 遍历内部 `Message` → `cantools Message`，`Signal` → `cantools Signal`
3. 根据 factor/offset 选择 `LinearConversion` 或 `IdentityConversion`
4. `cantools.database.dump_file()` 写入 DBC

**Web 运行时**的 DBC 导出走 `api_server.py` 内联的 `CanDatabase.to_dbc_str()`，手动构造 DBC 文本（不依赖 `core/dbc_io.py`），包含完整的 `NS_`、`BU_`、`BO_`、`SG_`、`CM_` 段。

### 4.6 JSON/XML

`core/json_io.py` 和 `core/xml_io.py` 提供离线读写。Web 运行时的 JSON 序列化通过 `CanDatabase.to_dict()` / `from_dict()`，XML 仅离线 CLI 支持。


---

## 第 5 章：会话管理

### 5.1 核心概念

每个浏览器标签页对应一个独立的 **Session**，绑定一个磁盘 Properties 文件。所有变更自动落盘，浏览器崩溃后可通过 `localStorage` 中的 `session_id` 恢复。

### 5.2 Session 数据结构

```python
class Session:
    id: str              # 12 位 hex UUID
    file_path: str       # 绑定的数据文件绝对路径
    db: CanDatabase      # 内存中的数据库实例（api_server 内联版）
    created_at: float    # 创建时间戳
    last_access: float   # 最后访问时间戳
```

### 5.3 SessionManager

全局单例，维护 `dict[session_id → Session]`，线程安全（`threading.Lock`）。

| 方法 | 说明 |
|------|------|
| `set_model_factory(factory)` | 注入 CanDatabase 类（由 api_server 调用） |
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
- 文件名格式：`{session_id}_{name}.properties`
- 原子写入：先写 `.tmp` 临时文件，再 `os.replace()` 覆盖目标文件

### 5.5 自动落盘

每次 CRUD 端点成功处理后，触发 `_auto_save()`：启动 daemon 线程，延迟 500ms 后调用 `SessionManager.save()`，避免阻塞 HTTP 响应。


---

## 第 6 章：REST API 设计

### 6.1 概述

- **HTTP 框架**：Python 标准库 `http.server` + `BaseHTTPRequestHandler`
- **并发模型**：单线程 `HTTPServer`（非 `ThreadingHTTPServer`，桌面应用场景足够）
- **数据格式**：请求/响应均为 JSON（`Content-Type: application/json`）
- **会话标识**：通过 `X-Session-Id` 请求头传递
- **CORS**：允许所有来源（本地开发需求）
- **统一响应格式**：`{"success": bool, "data": any, "error": str, "details": dict | null}`

### 6.2 端点清单

#### 状态与摘要

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/status` | 服务健康检查 + 概要（message_count, signal_count, modified, session_id, file_name） |
| GET | `/api/summary` | 完整摘要（含所有报文列表） |

#### 报文 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/messages` | 列出所有报文（thin：id, id_hex, name, dlc, cycle_time, signal_count） |
| GET | `/api/messages/{id}` | 获取单个报文完整信息（含所有信号） |
| POST | `/api/messages` | 创建报文（Body: id, name, dlc, ...） |
| PUT | `/api/messages/{id}` | 更新报文（支持修改 ID 即 move） |
| DELETE | `/api/messages/{id}` | 删除报文 |
| GET | `/api/messages/{id}/signal-errors` | 获取报文全部信号布局错误 |

#### 信号 CRUD

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/messages/{id}/signals` | 向报文添加信号 |
| PUT | `/api/messages/{id}/signals/{uuid}` | 按 UUID 更新信号 |
| DELETE | `/api/messages/{id}/signals/{uuid}` | 按 UUID 删除信号 |

#### 会话管理

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/session` | 创建新会话（Body: name, content?） |
| GET | `/api/session/{id}` | 获取会话元数据 |
| GET | `/api/sessions` | 列出全部历史会话 |
| POST | `/api/session/{id}/load` | 恢复历史会话 |
| PUT | `/api/session` | 重命名数据库 |
| DELETE | `/api/session/{id}` | 删除历史会话 |

#### 文件操作

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/new` | 创建全新空数据库（替换当前会话） |
| POST | `/api/import` | 导入文件内容（Body: format, content, filename） |
| POST | `/api/export` | 导出为指定格式（Body: format → 返回 content 字符串） |

#### 静态文件

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | Vue 构建产物 `dist/index.html` |
| GET | `/assets/*` | Vite 构建的 JS/CSS 资源 |
| GET | `/canmatrix_web_editor.html` | 遗留单文件 HTML 编辑器（兼容保留） |


---

## 第 7 章：CLI 层设计

### 7.1 CanMatrixSession

`cli.py` 提供 `CanMatrixSession` 类作为**无头（headless）会话**，镜像 Web GUI 的所有操作：

```python
class CanMatrixSession:
    database: CanDatabase       # core/can_database.py 的 dataclass 版本
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

**信号操作**：`add_signal(msg_id, sig)`, `remove_signal(msg_id, sig_name)`, `update_signal(msg_id, sig_name, **kw)`, `list_signals(msg_id)`, `list_all_signals()`

**查询**：`is_modified`, `message_count`, `total_signal_count()`, `summary()`

### 7.4 CLI 与 Web 运行时的关系

- `cli.py` 使用 `core/can_database.py` 的 dataclass 版本（无 UUID，无锁）
- `api_server.py` 使用内联类版本（有 UUID，有 RLock）
- `api_server.py` 不依赖 `cli.py`；`session_manager.py` 直接操作 api_server 内联的 CanDatabase
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
├── vite.config.js          # 代理 /api → localhost:8080，构建输出 → ../dist
└── src/
    ├── main.js             # createApp + Pinia 挂载
    ├── App.vue             # 根组件：三栏布局 + 主题 + 右键菜单 + 快捷键
    ├── i18n.js             # 中/英文国际化
    ├── api/
    │   └── client.js       # fetch 封装：X-Session-Id 注入，ApiError 统一处理
    ├── stores/
    │   └── editor.js       # Pinia 中央状态（CRUD、撤销栈、剪贴板、会话管理）
    ├── utils/
    │   └── format.js       # 格式化工具（十六进制显示、模板展开）
    └── components/
        ├── TopBar.vue          # 顶部导航栏
        ├── MessageList.vue     # 左侧报文列表
        ├── SignalTable.vue     # 中央可编辑信号表格（含验证错误高亮）
        ├── MessagePanel.vue    # 右侧报文属性编辑面板
        ├── StatusBar.vue       # 底部状态栏
        ├── Toast.vue           # Toast 通知
        ├── LoadingOverlay.vue  # 加载遮罩
        ├── ContextMenu.vue     # 右键上下文菜单
        ├── BatchModal.vue      # 批量创建信号弹窗
        └── HistoryModal.vue    # 历史会话浏览弹窗
```

### 8.3 Pinia Store（editor.js）

中央状态管理，包含所有应用状态和业务逻辑：

- **报文/信号 CRUD**：乐观 UI 更新（先更新本地状态，异步发 API，失败回滚）
- **撤销栈**：50 条历史记录，Ctrl+Z 撤销
- **剪贴板**：支持信号和报文的复制/剪切/粘贴（Ctrl+C/V/X）
- **批量信号创建**：模板展开生成多条信号
- **会话管理**：创建、恢复、历史列表、删除、重命名
- **API 健康检查**：定时 ping `/api/status`
- **信号错误获取**：选中报文时自动拉取布局验证结果
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
- 后端服务：`python api_server.py` → 访问 `http://localhost:8080/`


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

**决策**：浏览器前端 + Python 标准库 HTTP 后端，不使用 Electron/PyQt/重量级 Web 框架。

- ✅ 前端技术栈（Vue 3 + Vite）生态成熟，UI 开发效率高
- ✅ Python 源码直接运行，跨平台成本低
- ✅ 无框架依赖，部署只需 Python 3.9+
- ⚠️ 后端仅绑定 localhost，不支持远程访问（这是设计意图）

### 9.4 两层数据模型

**决策**：`core/can_database.py` 使用 dataclass（供 CLI），`api_server.py` 内联普通类（供 Web 运行时）。

- Web 运行时版本需要 UUID 标识信号、RLock 线程安全、modified 追踪
- CLI 版本只需纯数据类，保持简单，易于测试
- 两个版本字段一致，通过 `to_dict()` / `from_dict()` 可互转

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

### 9.7 乐观 UI 更新

**决策**：前端先更新 UI，异步发 API，失败回滚。

- ✅ 即时响应，无等待感
- ✅ 回滚机制保证数据一致性
- ⚠️ 需要完善的错误处理和回滚逻辑


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
```

仅两个运行时依赖，均为成熟 PyPI 包。


---

## 第 11 章：文件清单

| 文件路径 | 行数（估算） | 职责 |
|---------|-------------|------|
| `api_server.py` | ~1247 | HTTP API 服务器：内联数据模型 + REST 路由 + 静态文件 + 自动保存 |
| `session_manager.py` | ~387 | Session/SessionManager：会话生命周期、原子持久化、历史恢复 |
| `cli.py` | ~266 | CanMatrixSession + OpResult：CLI 无头会话层 |
| `core/__init__.py` | ~1 | 包标记 |
| `core/can_database.py` | ~223 | Signal/Message/CanDatabase dataclass 版本（CLI 用） |
| `core/dbc_io.py` | ~176 | DBC 导入/导出（via cantools） |
| `core/properties_io.py` | ~35 | Properties 读写（javaproperties 库，稀疏输出） |
| `core/json_io.py` | ~27 | JSON 读写 |
| `core/xml_io.py` | ~110 | XML 读写（ElementTree + minidom 格式化） |
| `requirements.txt` | 2 | Python 依赖声明 |
| `frontend/package.json` | — | Vue 3 + Pinia + Vite 依赖 |
| `frontend/vite.config.js` | — | Vite 构建配置（API 代理 + 输出路径） |
| `frontend/src/main.js` | — | Vue 应用入口 |
| `frontend/src/App.vue` | — | 根组件：布局、主题、快捷键 |
| `frontend/src/i18n.js` | — | 中/英文国际化 |
| `frontend/src/api/client.js` | — | fetch 封装（X-Session-Id 注入） |
| `frontend/src/stores/editor.js` | ~658 | Pinia 中央状态管理 |
| `frontend/src/utils/format.js` | — | 格式化工具 |
| `frontend/src/components/TopBar.vue` | — | 顶部导航栏 |
| `frontend/src/components/MessageList.vue` | — | 报文列表 |
| `frontend/src/components/SignalTable.vue` | — | 信号编辑表格 |
| `frontend/src/components/MessagePanel.vue` | — | 报文属性面板 |
| `frontend/src/components/StatusBar.vue` | — | 状态栏 |
| `frontend/src/components/Toast.vue` | — | Toast 通知 |
| `frontend/src/components/LoadingOverlay.vue` | — | 加载遮罩 |
| `frontend/src/components/ContextMenu.vue` | — | 右键菜单 |
| `frontend/src/components/BatchModal.vue` | — | 批量创建信号 |
| `frontend/src/components/HistoryModal.vue` | — | 历史会话浏览 |
| `canmatrix_web_editor.html` | — | 遗留单文件 HTML 编辑器（兼容保留） |
| `data/` | — | 运行时会话数据目录（gitignored） |
| `dist/` | — | Vite 前端构建产物（gitignored） |
