# CanDbCodeGenerator

交互式 CAN 报文/信号编辑工具，以 **Properties** 为主存储格式，解决 DBC 文件在 Git 版本管理中合并冲突严重、diff 不可读的痛点。

## 核心功能

- **Properties 主存储**：信号以 dotted keys 形式存储，增删只影响该块，Git diff 精准到字段级别
- **DBC 导入/导出**：通过 `cantools` 与 Vector CANdb++、CANoe 等工具无缝协作
- **Web 可视化编辑**：信号表格 + 布局可视化，支持拖拽调整位置
- **信号验证**：实时检测位域越界和重叠，自动推荐修复位置
- **撤销/重做**：最多 50 步操作历史
- **多会话隔离**：每个浏览器标签页独立 session，自动保存，崩溃可恢复
- **本地运行**：数据不出本机，无需账号、云端或网络连接

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 构建并启动

**Windows**：双击 `build.bat`（或命令行执行 `build.bat`）

**Linux / macOS**：
```bash
chmod +x build.sh && ./build.sh
```

脚本自动完成：前端构建 → 询问是否启动后端服务。启动后访问 `http://localhost:8080/` 即可使用。

### 手动启动服务

如果前端已构建完成，可直接启动：

```bash
python -m app.server.lifecycle
```



## 打包为桌面应用（exe）

项目支持打包成单文件 exe，无需安装 Python 或浏览器，双击即可运行。

### 打包前置条件

```bash
pip install pywebview pyinstaller
```

### 打包

先执行构建脚本确保前端已构建，然后打包：

**Windows**：`build.bat`（构建完成后选 `n` 不启动服务）

```bash
pyinstaller desktop.spec --noconfirm
```

**Linux / macOS**：`./build.sh`（同上）

```bash
pyinstaller desktop.spec --noconfirm
```

生成文件：`dist/CanDbCodeGenerator.exe`（约 30 MB）

### 分发与使用

1. 将 `CanDbCodeGenerator.exe` 复制到目标机器任意位置
2. 双击运行，自动弹出编辑器窗口（基于系统 WebView2，Windows 10/11 已内置）
3. 用户数据保存在 `%APPDATA%\CanDbCodeGenerator\data\`

> **从旧版本升级：** 用户数据目录已从 `%APPDATA%\CanMatrixEditor` 改为 `%APPDATA%\CanDbCodeGenerator`。首次运行新版本前，请备份旧目录并把 `config/`、`data/`、`snapshots/` 复制到新目录；`%LOCALAPPDATA%\CanMatrixEditor\WebView2Cache` 只是缓存，可以丢弃。
>
> **说明：** Windows 10 1803+ 及 Windows 11 均自带 WebView2 Runtime，无需额外安装。
> 若目标系统未安装，可从微软官网下载 [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)。

### 重新打包

每次修改代码后，重新执行构建脚本 + 打包命令即可（构建脚本会自动检测 `node_modules`，按需安装依赖）。

## 使用工作流

```bash
# 1. 启动服务
python -m app.server.lifecycle

# 2. 浏览器访问 http://localhost:8080/
#    导入 DBC → 编辑 → 导出 Properties

# 3. 纳入 Git 管理
git add can_matrix.properties
git commit -m "初始化 CAN 矩阵"

# 4. 日常编辑（Web 编辑器自动保存）
git diff can_matrix.properties   # 精准到信号级别的变更
git commit -m "修改 EngineSpeed 因子"

# 5. 需要交付 DBC 时
# Web 编辑器 → 导出 → DBC
```

### Properties vs DBC diff 对比

**DBC（差）：**
```
 BO_ 291 EngineStatus: 8 ECU1
- SG_ EngineSpeed : 0|16@1+ (1,0) [0|65535] "rpm" ECU2
+ SG_ EngineSpeed : 0|16@1+ (0.5,0) [0|65535] "rpm" ECU2
```
二进制格式行，难以阅读，相邻信号修改会导致整行冲突。

**Properties（优）：**
```diff
 messages.0x123.signals.EngineSpeed.name=EngineSpeed
 messages.0x123.signals.EngineSpeed.start_bit=0
 messages.0x123.signals.EngineSpeed.length=16
 messages.0x123.signals.EngineSpeed.byte_order=little_endian
 messages.0x123.signals.EngineSpeed.is_signed=false
-messages.0x123.signals.EngineSpeed.factor=1
+messages.0x123.signals.EngineSpeed.factor=0.5
 messages.0x123.signals.EngineSpeed.max_val=65535
 messages.0x123.signals.EngineSpeed.unit=rpm
```
独立的信号块，只显示实际变更的字段，人类和 Git 都能精准理解。

## MCP 服务器

CanDbCodeGenerator 附带一个集中托管的 **Streamable HTTP MCP 服务器**（服务名 `candb_codegenerator_mcp`），
让 AI 客户端（OpenCode、Claude Code 等）以任意用户身份完成全部编辑操作——新建/导入文件、
增删改报文与信号、管理值表、校验、导出与保存。业务逻辑全部留在后端，MCP 服务器只是薄客户端。

### 获取 PAT（个人MCP访问令牌）

MCP 服务器以 `Authorization: Bearer <PAT>` 头认证身份。PAT 的创建路径：

**文件列表页 → 用户菜单 → 个人MCP访问令牌**

在弹窗中填写备注名与有效期（永不 / 30 天 / 90 天 / 自定义），创建后一次性展示明文令牌
（`pat_` + 64 位十六进制），请立即复制保存；列表支持随时吊销。

### 启动

MCP 服务器已**内嵌进后端**：启动后端时，MCP 随之一同启动，无需单独跑进程。

```bash
# 只启动后端，HTTP / WS / MCP 三元组一起拉起
venv/bin/python -m app.server.lifecycle
```

端口同源派生，构成绑定三元组：**HTTP = P、WS = P + 1、MCP = P + 2**。默认
`P = 8080`，故 MCP 默认监听 `http://127.0.0.1:8082/mcp`；MCP 永远指向本进程后端，不会失配。

> 端口用 `P + 2` 而非 `P + 1`：`P + 1` 已被后端 WS 占用，MCP 需错开一位。

**防多实例保护**：默认检测到端口被占用（很可能已有另一实例在运行）时**拒绝启动**，
不会自动换端口。需终止旧进程后再启动：

```bash
# 显式加 --auto-clean：自动终止旧进程后启动
venv/bin/python -m app.server.lifecycle --auto-clean
```

生产部署见 [systemd 部署指南](docs/systemd-deploy.md)。
（`venv/bin/python -m app.mcp` 仅保留作独立调试入口，生产不再使用。）

### 客户端接入

**OpenCode**（`opencode.json`，项目根目录或 `~/.config/opencode/opencode.json`）：

```json
{
  "mcp": {
    "candb-codegenerator": {
      "type": "remote",
      "url": "http://127.0.0.1:8082/mcp",
      "enabled": true,
      "headers": {
        "Authorization": "Bearer pat_你的令牌"
      }
    }
  }
}
```

**Claude Code**（项目根 `.mcp.json` 或 `claude mcp add`）：

```json
{
  "mcpServers": {
    "candb-codegenerator": {
      "type": "http",
      "url": "http://127.0.0.1:8082/mcp",
      "headers": {
        "Authorization": "Bearer pat_你的令牌"
      }
    }
  }
}
```

> 通过 HTTPS 反向代理对外暴露时，把 `url` 换成代理地址即可；令牌切勿提交进仓库。

### 工具面一览

| 类别 | 工具 |
|------|------|
| 身份 | `candb_whoami` |
| 文件/会话 | `candb_list_files`、`candb_open_file`、`candb_create_file`、`candb_import_file`、`candb_save`、`candb_save_as`、`candb_close_session`、`candb_get_summary`、`candb_export` |
| 报文 | `candb_list_messages`、`candb_get_message`、`candb_add_message`、`candb_edit_message`、`candb_batch_edit_messages`、`candb_delete_message`、`candb_batch_delete_messages` |
| 信号 | `candb_list_signals`、`candb_get_signal`、`candb_add_signal`、`candb_batch_add_signals`、`candb_edit_signal`、`candb_batch_edit_signals`、`candb_delete_signal`、`candb_batch_delete_signals` |
| 值表 | `candb_list_value_tables`、`candb_add_value_table`、`candb_update_value_table`、`candb_rename_value_table`、`candb_delete_value_table` |
| 校验/历史 | `candb_get_data_errors`、`candb_undo`、`candb_redo`、`candb_get_save_diff` |

### 权限与边界

- PAT 仅有**编辑权限**：打开他人文件得到**只读会话**（`can_write=false`），写操作会被后端
  拒绝并提示文件所有者；管理、改密、登出、令牌管理等端点对 PAT 一律返回 403。
- **不提供** `delete_file`、`steal_lock` 及任何管理类工具，也不能查看调试快照。
- `candb_import_file` 只收内联内容，不接受服务器路径。

## 项目结构

```
CanDbCodeGenerator/
├── app/                             Python 主包
│   ├── server/                      HTTP 服务层
│   │   ├── lifecycle.py             服务启动入口（python -m app.server.lifecycle）
│   │   ├── http_handler.py          静态文件服务 + 诊断端点
│   │   └── port_utils.py            端口检测工具
│   ├── models/                      数据模型
│   │   ├── database.py              CanDatabase（RLock + 信号验证 + 序列化）
│   │   ├── message.py               Message 数据类
│   │   └── signal.py                Signal 数据类
│   ├── services/                    业务服务层
│   │   ├── session.py               Session 数据类
│   │   ├── session_manager.py       会话生命周期管理（自动保存、超时清理）
│   │   ├── file_lock.py             文件锁（多标签页互斥）
│   │   ├── file_persistence.py      磁盘持久化（原子写入）
│   │   └── undo_engine.py           撤销/重做引擎
│   ├── io/                          格式 IO
│   │   ├── properties_io.py         Properties 读写（主存储格式）
│   │   ├── dbc_io.py                DBC 导入导出（cantools）
│   │   └── c_code_gen.py            C 代码生成
│   └── ws/                          WebSocket 全双工通信
│       ├── server.py                WS 服务端（asyncio）
│       ├── transport.py             WS I/O 封装（连接管理 + 广播）
│       ├── router.py                消息路由（type → handler）
│       └── handlers/                业务 Handler（信号/报文/文件/系统）
├── tools/                           工具脚本
│   ├── desktop.py                   桌面应用入口（pywebview）
│   └── compute_version.py           版本号计算
├── frontend/                        Vue 3 + Vite 前端（Web 编辑器）
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.vue                  根组件（三栏布局 + 主题 + 快捷键）
│       ├── stores/                  Pinia 状态管理
│       ├── api/client.js            HTTP API 客户端
│       └── components/              UI 组件
├── docs/                            架构与设计文档
├── desktop.spec                     PyInstaller 打包配置
├── build.bat / build.sh             构建脚本
├── requirements.txt                 Python 依赖
├── README.md                        本文档
└── dist/                            前端构建产物 / exe 输出目录
```

## 依赖

| 包 | 最低版本 | 用途 |
|---|---|---|
| Python | 3.9+ | 运行环境 |
| cantools | 39.0.0 | DBC 文件解析与生成 |
| javaproperties | 0.8.0 | Properties 格式读写 |
| Node.js | 18+ | 前端构建（仅开发/部署时） |
| pywebview | 5.0+ | 桌面窗口（仅打包时需要） |
| pyinstaller | 6.0+ | 打包为 exe（仅打包时需要） |

## 文档

- [架构特征](docs/ARCHITECTURE.md) - Store 设计、撤销机制、乐观更新模式
- [产品定位](docs/PRODUCT_POSITIONING.md) - 目标用户、核心价值、技术路线
- [详细设计](docs/DESIGN_DOC.md) - 模块设计、数据流、API 规范