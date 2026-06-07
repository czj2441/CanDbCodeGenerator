# CanMatrix Editor

交互式 CAN 报文/信号编辑工具，以 **TOML** 为主存储格式，解决 DBC 文件在 Git 版本管理中合并冲突严重、diff 不可读的痛点。

## 核心功能

- **TOML 主存储**：信号以独立块形式存储，增删只影响该块，Git diff 精准到字段级别
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

### 2. 构建前端

```bash
cd frontend
npm install
npm run build
cd ..
```

### 3. 启动服务

```bash
python api_server.py
```

访问 `http://localhost:8080/` 即可使用。

### 重新部署

如果执行了 `git clean`，需要重新构建：

```bash
cd frontend
npm install && npm run build
cd ..
python api_server.py
```



## 使用工作流

```bash
# 1. 启动服务
python api_server.py

# 2. 浏览器访问 http://localhost:8080/
#    导入 DBC → 编辑 → 导出 TOML

# 3. 纳入 Git 管理
git add can_matrix.toml
git commit -m "初始化 CAN 矩阵"

# 4. 日常编辑（Web 编辑器自动保存）
git diff can_matrix.toml   # 精准到信号级别的变更
git commit -m "修改 EngineSpeed 因子"

# 5. 需要交付 DBC 时
# Web 编辑器 → 导出 → DBC
```

### TOML vs DBC diff 对比

**DBC（差）：**
```
 BO_ 291 EngineStatus: 8 ECU1
- SG_ EngineSpeed : 0|16@1+ (1,0) [0|65535] "rpm" ECU2
+ SG_ EngineSpeed : 0|16@1+ (0.5,0) [0|65535] "rpm" ECU2
```
二进制格式行，难以阅读，相邻信号修改会导致整行冲突。

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
│       ├── stores/                Pinia 状态管理
│       ├── api/client.js          HTTP API 客户端
│       └── components/            UI 组件
├── docs/                          架构与设计文档
│   ├── ARCHITECTURE.md            架构特征参考
│   ├── ARCHITECTURE_REFACTOR_PLAN.md  重构方案
│   ├── PRODUCT_POSITIONING.md     产品定位与技术路线
│   └── DESIGN_DOC.md              软件详细设计文档
└── dist/                          前端构建产物（由 Vite 生成）
```

## 依赖

| 包 | 最低版本 | 用途 |
|---|---|---|
| Python | 3.9+ | 运行环境 |
| cantools | 39.0.0 | DBC 文件解析与生成 |
| toml | 0.10.2 | TOML 格式读写 |
| Node.js | 18+ | 前端构建（仅开发/部署时） |

## 文档

- [架构特征](docs/ARCHITECTURE.md) - Store 设计、撤销机制、乐观更新模式
- [产品定位](docs/PRODUCT_POSITIONING.md) - 目标用户、核心价值、技术路线
- [详细设计](docs/DESIGN_DOC.md) - 模块设计、数据流、API 规范
- [重构方案](docs/ARCHITECTURE_REFACTOR_PLAN.md) - 前端架构重构方案