# CanMatrix Editor

交互式 CAN 报文 / 信号编辑桌面工具。以 **TOML** 为主存储格式，解决 Vector CANdb++ 生成的 `.dbc` 文件不便于 Git 版本管理、合并不稳定的痛点。

## 环境依赖

### 必需依赖

| 包 | 最低版本 | 用途 |
|---|---|---|
| Python | 3.9+ | 运行环境 |
| cantools | 39.0.0 | DBC 文件解析与生成 |
| toml | 0.10.2 | TOML 格式读写 |
| Node.js | 18+ | 前端构建（仅开发/部署时） |

### 依赖安装

**方式一：pip 直接安装（推荐）**

```bash
cd canmatrix_editor
pip install -r requirements.txt
```

**方式二：conda 环境**

```bash
conda create -n canmatrix python=3.11
conda activate canmatrix
pip install -r requirements.txt
```

**方式三：虚拟环境**

```bash
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Linux/macOS
pip install -r requirements.txt
```

### 常见问题

1. **`cantools` 导入报错 `ModuleNotFoundError: bitstruct`**：重新安装 cantools 会自动拉取依赖：
   ```bash
   pip install --force-reinstall cantools
   ```

## 启动方式

### Web 编辑器（推荐）

基于 Vue 3 + Vite 的前端 + Python HTTP API 后端架构。

#### 1. 安装 Python 依赖

```bash
pip install -r requirements.txt
```

#### 2. 安装前端依赖并构建

```bash
cd frontend
npm install
npm run build
cd ..
```

构建产物输出到根目录 `dist/`。

#### 3. 启动后端服务

```bash
python api_server.py
```

访问 `http://localhost:8080/` 即可使用 Web 编辑器。

#### 重新部署（清理后）

如果从仓库克隆或执行了 `git clean`，以下目录会被清除，需要重新构建：

| 被清除的目录 | 原因 | 恢复方式 |
|---|---|---|
| `frontend/node_modules/` | npm 依赖 | `cd frontend && npm install` |
| `dist/` | 前端构建产物 | `cd frontend && npm run build` |
| `data/` | 运行时会话数据 | 自动创建，无需手动恢复 |
| `__pycache__/` | Python 字节码缓存 | 自动重建，无需手动恢复 |

一键重新部署：

```bash
cd frontend
npm install && npm run build
cd ..
python api_server.py
```



## 内部工作逻辑

### 整体架构

```
api_server.py (HTTP 服务入口)
  │
  ├── REST API ── SessionManager ── CanDatabase (数据模型)
  │      │                              │
  │      │         ┌───────────────────┼───────────────────┐
  │      │         ▼                   ▼                   ▼
  │      │   GET /api/messages    GET /api/status    PUT /api/session
  │      │
  │      └── 静态文件服务 (dist/index.html + assets)
  │
  └── core/
       ├── can_database.py   数据模型层
       │    CanDatabase → Message → Signal
       │
       ├── toml_io.py        TOML 读写（主格式）
       ├── json_io.py        JSON 读写（辅助）
       ├── xml_io.py         XML 读写（辅助）
       └── dbc_io.py         DBC 导入导出
            import_dbc() → cantools 解析 → CanDatabase
            export_dbc() → CanDatabase → cantools 生成 DBC 文本
```

### 数据流

```
DBC 文件 ──[cantools.load_file]──→ CanDatabase ──[save_toml]──→ .toml 文件
                                          │
TOML 文件 ──[load_toml]──→ CanDatabase ──┤
JSON 文件 ──[load_json]──→ CanDatabase ──┤── Web 编辑器编辑 ──→ 保存回任意格式
XML 文件  ──[load_xml]──→  CanDatabase ──┤
                                          │
                         CanDatabase ──[export_dbc]──→ .dbc 文件
```

### 关键设计决策

1. **TOML 为首选格式**：每个信号是独立的 `[[messages.signals]]` 数组元素，不嵌套字典。增删信号只影响该块，不会导致相邻行位移——这是传统 DBC 合并冲突的根本原因。

2. **稀疏输出**：默认值字段（`factor=1.0`、`offset=0.0`、`min_val=0.0` 等）在保存时不写入文件，减少 diff 噪音，让修改一目了然。

3. **ID 十六进制**：TOML 中 `id = 0x123`，与 DBC 和 CAN 工具链一致，避免十进制换算的认知负担。

4. **前后端分离**：前端 Vue 3 负责 UI 渲染，所有数据操作通过 REST API 与 Python 后端交互。后端 `CanDatabase` 对象图通过 `SessionManager` 自动持久化到磁盘，会话可在浏览器意外关闭后恢复。

## 安全性考量

### 数据安全

- **本地服务**：CanMatrix Editor 在本地 `localhost:8080` 运行，不连接外部网络，CAN 矩阵数据不会外泄。
- **文件操作安全**：所有写入操作通过标准 Python `open()` 完成，依赖操作系统文件系统权限控制。无提权行为。
- **自动持久化**：每次修改后后端自动保存到磁盘，浏览器意外关闭后可通过 `localStorage` 中的 session_id 恢复会话。

### 输入安全

- **DBC 导入**：`import_dbc()` 通过 `cantools` 官方解析器处理，不执行外部代码，不受 DBC 文件注入攻击。
- **TOML/JSON/XML 加载**：使用标准库解析器（`toml.load` / `json.load` / `xml.etree.ElementTree.parse`），均有限制解析深度和大小。
- **表单输入**：前端数值输入框限制有效范围（如 CAN ID 限制 0~0x1FFFFFFF），非法输入在提交前被校验拦截。

### 权限需求

- 仅需用户对项目目录和 `.toml` / `.dbc` 文件的读写权限。
- 不需要管理员权限。
- 不修改注册表、系统配置、环境变量。
- 不创建后台服务或自启动项。

## Git 版本管理工作流

### 推荐流程

```bash
# 1. 启动服务
python api_server.py

# 2. 在浏览器中访问 http://localhost:8080/
#    导入 DBC → 编辑 → 导出 TOML → 保存为 can_matrix.toml

# 3. 将 TOML 纳入 Git
git add can_matrix.toml
git commit -m "初始化 CAN 矩阵，从 DBC 导入"

# 4. 日常编辑
# 在 Web 编辑器中编辑后自动保存到 can_matrix.toml
git diff can_matrix.toml   # 查看变更，精准到信号级别
git commit -m "新增 BatteryStatus 报文，修改 EngineSpeed 因子"

# 5. 需要交付 DBC 时
# Web 编辑器 → 导出 → DBC → can_matrix.dbc
# 将 .dbc 发给使用 CANdb++ 的同事

# 6. 合入上游 DBC 变更
# 同事改了 .dbc → Web 编辑器导入 → 覆盖当前 .toml → git diff 审查
```

### TOML vs DBC diff 对比

**DBC（差）：**
```
 BO_ 291 EngineStatus: 8 ECU1
- SG_ EngineSpeed : 0|16@1+ (1,0) [0|65535] "rpm" ECU2
+ SG_ EngineSpeed : 0|16@1+ (0.5,0) [0|65535] "rpm" ECU2
```
二进制格式行，难以阅读，且相邻信号修改会导致整行冲突。

**TOML（优）：**
```diff
 [[messages.signals]]
 name = "EngineSpeed"
 start_bit = 0
 length = 16
 byte_order = "little_endian"
 is_signed = false
-factor = 1
+factor = 0.5
 max_val = 65535
 unit = "rpm"
 comment = "Speed in RPM"
```
独立的信号块，只显示实际变更的字段，人类和 Git 都能精准理解。

## 项目结构

```
canmatrix_editor/
├── api_server.py                  Web 后端服务（HTTP API + 静态文件）
├── session_manager.py             会话管理器（自动持久化、历史恢复）
├── cli.py                         命令行入口
├── requirements.txt               依赖清单
├── README.md                      本文档
├── .gitignore                     版本控制忽略规则
├── core/                          数据模型与 IO
│   ├── can_database.py            CanDatabase / Message / Signal 数据模型
│   ├── toml_io.py                 TOML 读写（主存储格式）
│   ├── json_io.py                 JSON 读写（辅助格式）
│   ├── xml_io.py                  XML 读写（辅助格式）
│   └── dbc_io.py                  DBC 导入导出（cantools）
├── frontend/                      Vue 3 + Vite 前端（Web 编辑器）
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.vue
│       ├── main.js
│       ├── i18n.js                国际化（中/英）
│       ├── stores/editor.js       Pinia 状态管理
│       ├── api/client.js          HTTP API 客户端
│       └── components/            TopBar、SignalTable、MessagePanel 等
└── dist/                          前端构建产物（由 Vite 生成）
```