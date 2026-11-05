# systemd 服务部署指南

> 本文档介绍如何将 CanDbCodeGenerator 以 systemd 服务方式部署到 Linux 生产环境。
>
> 最后更新：2026-11-05

---

## 一、前置条件

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Linux 系统 | Ubuntu 20.04+ / CentOS 8+ | 需支持 systemd |
| Python | 3.9+ | 后端运行环境 |
| Node.js | 18+ | 仅构建前端时需要 |

---

## 二、部署步骤

### 2.1 构建项目

```bash
# 克隆项目到部署目录
git clone <repo-url> /opt/candb-codegenerator
cd /opt/candb-codegenerator

# 执行构建（自动创建 venv、安装依赖、构建前端）
chmod +x build.sh
./build.sh
```

> **注意**：`build.sh` 会启动服务进行验证，按 `Ctrl+C` 停止后继续部署。

### 2.2 调整服务配置

编辑 `deploy/candb-codegenerator.service`，按实际环境修改路径：

```ini
[Service]
# 修改为你的实际项目路径
WorkingDirectory=/opt/candb-codegenerator
ExecStart=/opt/candb-codegenerator/venv/bin/python -m app.server.lifecycle --host 0.0.0.0 --no-browser --auto-clean
```

**可调整的参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 绑定地址。`0.0.0.0` 允许外部访问，`127.0.0.1` 仅本机 |
| `--port` | `8080` | HTTP 端口（WebSocket 自动用 `port+1`、MCP 自动用 `port+2`） |
| `--auto-clean` | 已启用 | 启动时自动终止旧进程（默认端口被占用时会拒绝启动） |
| `WorkingDirectory` | `/opt/candb-codegenerator` | 项目安装目录 |

示例：绑定到 9090 端口：

```ini
ExecStart=/opt/candb-codegenerator/venv/bin/python -m app.server.lifecycle --host 0.0.0.0 --port 9090 --no-browser --auto-clean
```

### 2.3 安装服务

```bash
# 复制 service 文件到 systemd 目录
sudo cp deploy/candb-codegenerator.service /etc/systemd/system/

# 重载 systemd 配置
sudo systemctl daemon-reload

# 设置开机自启
sudo systemctl enable candb-codegenerator

# 启动服务
sudo systemctl start candb-codegenerator
```

### 2.4 验证服务状态

```bash
# 查看服务状态
sudo systemctl status candb-codegenerator

# 预期输出示例：
# ● candb-codegenerator.service - CanDbCodeGenerator
#    Loaded: loaded (/etc/systemd/system/candb-codegenerator.service; enabled)
#    Active: active (running) since ...
```

浏览器访问 `http://<服务器IP>:8080` 确认页面可正常加载。

---

## 三、日常运维命令

### 服务管理

```bash
# 启动
sudo systemctl start candb-codegenerator

# 停止
sudo systemctl stop candb-codegenerator

# 重启
sudo systemctl restart candb-codegenerator

# 查看状态
sudo systemctl status candb-codegenerator

# 禁用开机自启
sudo systemctl disable candb-codegenerator
```

### 日志查看

服务日志有两个来源：

**1. journald 日志**（systemd 管理的控制台输出）

```bash
# 实时跟踪日志
sudo journalctl -u candb-codegenerator -f

# 查看最近 100 行
sudo journalctl -u candb-codegenerator -n 100

# 查看今天的日志
sudo journalctl -u candb-codegenerator --since today

# 按时间范围查询
sudo journalctl -u candb-codegenerator --since "2026-08-14 10:00" --until "2026-08-14 12:00"
```

**2. 文件日志**（项目内置，自动轮转）

日志文件位于项目目录下的 `logs/`，按启动会话和日期组织：

```
logs/
  20260814_103022/           ← 启动时间戳目录
    2026-08-14_001.log       ← 当日第 1 个文件
    2026-08-14_002.log       ← 超 10MB 后自动拆分
```

```bash
# 查看最新一次启动的日志
ls -lt /opt/candb-codegenerator/logs/ | head -1
tail -f /opt/candb-codegenerator/logs/<最新目录>/*.log

# 搜索错误
grep -r "ERROR" /opt/candb-codegenerator/logs/
```

> 文件日志自动保留 30 天，超期目录由服务内部定时清理（每 24 小时一次）。

### 健康检查

```bash
# HTTP 接口（无需认证）
curl -s http://localhost:8080/api/status
# 预期：{"success":true,"data":{"status":"ok"}}

# 版本查询
curl -s http://localhost:8080/api/version
```

---

## 四、自恢复机制

服务配置了以下自恢复策略：

| 配置项 | 值 | 说明 |
|--------|------|------|
| `Restart` | `on-failure` | 进程异常退出（非零退出码、被信号杀死）时自动重启 |
| `RestartSec` | `5` | 重启前等待 5 秒 |

**触发重启的场景**：
- 进程崩溃（Segmentation fault、未捕获异常等）
- OOM Killer 终止进程
- 手动 `kill -9`（但 `systemctl stop` 不会触发重启）

**不触发重启的场景**：
- 正常退出（`systemctl stop`、`Ctrl+C`）
- 进程以退出码 0 结束

---

## 五、更新部署

### 5.1 常规更新

```bash
# 1. 拉取最新代码
cd /opt/candb-codegenerator
git pull

# 2. 重新构建前端（如有前端变更）
cd frontend && npm install && npm run build && cd ..

# 3. 重启服务加载新代码
sudo systemctl restart candb-codegenerator

# 4. 确认状态正常
sudo systemctl status candb-codegenerator
```

### 5.2 从旧名称 canmatrix-editor 升级

仅当服务器上仍存在旧服务名 `canmatrix-editor` 或旧部署目录 `/opt/canmatrix` 时需要执行。

**1. 停止并移除旧 unit**

```bash
sudo systemctl disable --now canmatrix-editor
sudo rm /etc/systemd/system/canmatrix-editor.service
sudo systemctl daemon-reload
```

**2. 迁移项目目录（二选一）**

```bash
# 方案 A：把旧目录移动到新路径（推荐）
sudo mv /opt/canmatrix /opt/candb-codegenerator

# 方案 B：保留旧目录，但必须修改新 unit 中的 WorkingDirectory / ExecStart
# 将 /opt/candb-codegenerator 改成 /opt/canmatrix
```

如果新目录已经存在，不要执行 `mv`，改为逐项核对代码、`config/`、`data/`、`snapshots/` 和 `logs/` 是否已迁移。

**3. 安装并启动新 unit**

```bash
cd /opt/candb-codegenerator
sudo cp deploy/candb-codegenerator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now candb-codegenerator
sudo systemctl status candb-codegenerator
```

**4. 更新反向代理与环境变量**

- nginx 站点文件如仍使用旧名，重命名并重新加载：

```bash
sudo mv /etc/nginx/sites-available/canmatrix-mcp \
        /etc/nginx/sites-available/candb-codegenerator-mcp
sudo ln -sfn /etc/nginx/sites-available/candb-codegenerator-mcp \
             /etc/nginx/sites-enabled/candb-codegenerator-mcp
sudo rm -f /etc/nginx/sites-enabled/canmatrix-mcp
sudo nginx -t && sudo systemctl reload nginx
```

- systemd unit、`/etc/default/*`、shell profile 或容器环境中的变量需要改为新名称：

| 旧变量 | 新变量 |
|--------|--------|
| `CANMATRIX_BACKEND_URL` | `CANDB_CODEGENERATOR_BACKEND_URL` |
| `CANMATRIX_MCP_HOST` | `CANDB_CODEGENERATOR_MCP_HOST` |
| `CANMATRIX_MCP_PORT` | `CANDB_CODEGENERATOR_MCP_PORT` |
| `CANMATRIX_MCP_SCHEME` | `CANDB_CODEGENERATOR_MCP_SCHEME` |

> HTTPS 反向代理部署必须保留 `CANDB_CODEGENERATOR_MCP_SCHEME=https`，否则前端展示的 MCP 地址会回退为 `http://`。

**5. 更新 MCP 客户端配置**

客户端配置中的服务器名可自定义，但工具名已经统一改为 `candb_*` 前缀：

- `canmatrix_open_file` → `candb_open_file`
- `canmatrix_list_messages` → `candb_list_messages`
- 其余工具同理，完整列表见项目 README 的「工具面一览」

**6. 浏览器存储会自动迁移**

前端首次加载时会一次性把 `canmatrix_*` 存储键迁移为 `candb_*`，包括登录令牌、主题、列宽和排序偏好，无需手动清除浏览器数据。每个浏览器配置文件会在各自首次访问时完成迁移。

> 桌面版（打包 exe）的数据目录升级步骤见项目 README 的「打包为桌面应用」章节。

---

## 六、故障排查

### 服务启动失败

```bash
# 查看详细错误日志
sudo journalctl -u candb-codegenerator --no-pager -n 50

# 常见原因：
# 1. 端口被占用 → 修改 service 中的 --port 参数
# 2. venv 路径错误 → 确认 WorkingDirectory 和 ExecStart 路径一致
# 3. Python 依赖缺失 → 重新执行 build.sh 或 pip install -r requirements.txt
```

### 端口冲突

```bash
# 查看端口占用
ss -tlnp | grep 8080

# 如果旧的 CanDbCodeGenerator 进程残留：
sudo pkill -f "app.server.lifecycle"

# 然后重启服务
sudo systemctl restart candb-codegenerator
```

### 日志目录权限问题

```bash
# 确保服务用户有权限写入 logs/ 目录
sudo chown -R $(whoami):$(whoami) /opt/candb-codegenerator/logs/

# 或检查 service 中是否配置了 User=（默认以 root 运行）
grep "User=" /etc/systemd/system/candb-codegenerator.service
```

---

## 七、卸载

```bash
sudo systemctl stop candb-codegenerator
sudo systemctl disable candb-codegenerator
sudo rm /etc/systemd/system/candb-codegenerator.service
sudo systemctl daemon-reload
```

---

## 八、MCP 服务器（candb_codegenerator_mcp）

MCP 服务器已**内嵌进后端**，随 `candb-codegenerator` 服务一同启动，**无需单独的
systemd unit**，也无需手工配置后端地址。

端口同源派生，构成绑定三元组：**HTTP = P、WS = P + 1、MCP = P + 2**。默认
`P = 8080`，故 MCP 监听 `http://<host>:8082/mcp`；`--port` 改变时 MCP 自动跟随
（例如 `--port 9090` → MCP 在 9092），且 MCP 永远指向本进程后端，不会失配。

> **端口为何是 P+2**：P+1 已被后端 WS 占用，MCP 需错开一位。

### 8.1 安全建议

MCP 服务携带的是**长期 PAT**，等同任意用户的编辑权限，安全要求高于普通 Web 页面：

1. **MCP 随后端绑定同一地址**：后端 `--host 0.0.0.0` 时 MCP 也对外监听 `8082`；
   MCP 端点本身没有 TLS 层，明文暴露等于泄露令牌。
2. **对外访问走 HTTPS 反向代理**：由 nginx 终结 TLS 并转发到本机 `8082`，
   PAT 只在加密信道内传输；勿在防火墙直接开放 `8082`。
3. 客户端经 `Authorization: Bearer <PAT>` 头认证；PAT 一旦泄露应立即在
   文件列表页 → 个人MCP访问令牌 中吊销。

nginx 反代示例（`/etc/nginx/sites-available/candb-codegenerator-mcp`）：

```nginx
server {
    listen 443 ssl;
    server_name mcp.example.com;

    ssl_certificate     /etc/letsencrypt/live/mcp.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/mcp.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8082;
        proxy_http_version 1.1;
        # Streamable HTTP 需要 SSE 长连接
        proxy_set_header Host $host;
        proxy_set_header Connection "";
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```
