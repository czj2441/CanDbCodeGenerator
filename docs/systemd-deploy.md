# systemd 服务部署指南

> 本文档介绍如何将 CanMatrix Editor 以 systemd 服务方式部署到 Linux 生产环境。
>
> 最后更新：2026-08-14

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
git clone <repo-url> /opt/canmatrix
cd /opt/canmatrix

# 执行构建（自动创建 venv、安装依赖、构建前端）
chmod +x build.sh
./build.sh
```

> **注意**：`build.sh` 会启动服务进行验证，按 `Ctrl+C` 停止后继续部署。

### 2.2 调整服务配置

编辑 `deploy/canmatrix-editor.service`，按实际环境修改路径：

```ini
[Service]
# 修改为你的实际项目路径
WorkingDirectory=/opt/canmatrix
ExecStart=/opt/canmatrix/venv/bin/python -m app.server.lifecycle --host 0.0.0.0 --no-browser
```

**可调整的参数**：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--host` | `0.0.0.0` | 绑定地址。`0.0.0.0` 允许外部访问，`127.0.0.1` 仅本机 |
| `--port` | `8080` | HTTP 端口（WebSocket 自动使用 port+1） |
| `WorkingDirectory` | `/opt/canmatrix` | 项目安装目录 |

示例：绑定到 9090 端口：

```ini
ExecStart=/opt/canmatrix/venv/bin/python -m app.server.lifecycle --host 0.0.0.0 --port 9090 --no-browser
```

### 2.3 安装服务

```bash
# 复制 service 文件到 systemd 目录
sudo cp deploy/canmatrix-editor.service /etc/systemd/system/

# 重载 systemd 配置
sudo systemctl daemon-reload

# 设置开机自启
sudo systemctl enable canmatrix-editor

# 启动服务
sudo systemctl start canmatrix-editor
```

### 2.4 验证服务状态

```bash
# 查看服务状态
sudo systemctl status canmatrix-editor

# 预期输出示例：
# ● canmatrix-editor.service - CanMatrix Editor
#    Loaded: loaded (/etc/systemd/system/canmatrix-editor.service; enabled)
#    Active: active (running) since ...
```

浏览器访问 `http://<服务器IP>:8080` 确认页面可正常加载。

---

## 三、日常运维命令

### 服务管理

```bash
# 启动
sudo systemctl start canmatrix-editor

# 停止
sudo systemctl stop canmatrix-editor

# 重启
sudo systemctl restart canmatrix-editor

# 查看状态
sudo systemctl status canmatrix-editor

# 禁用开机自启
sudo systemctl disable canmatrix-editor
```

### 日志查看

服务日志有两个来源：

**1. journald 日志**（systemd 管理的控制台输出）

```bash
# 实时跟踪日志
sudo journalctl -u canmatrix-editor -f

# 查看最近 100 行
sudo journalctl -u canmatrix-editor -n 100

# 查看今天的日志
sudo journalctl -u canmatrix-editor --since today

# 按时间范围查询
sudo journalctl -u canmatrix-editor --since "2026-08-14 10:00" --until "2026-08-14 12:00"
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
ls -lt /opt/canmatrix/logs/ | head -1
tail -f /opt/canmatrix/logs/<最新目录>/*.log

# 搜索错误
grep -r "ERROR" /opt/canmatrix/logs/
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

```bash
# 1. 拉取最新代码
cd /opt/canmatrix
git pull

# 2. 重新构建前端（如有前端变更）
cd frontend && npm install && npm run build && cd ..

# 3. 重启服务加载新代码
sudo systemctl restart canmatrix-editor

# 4. 确认状态正常
sudo systemctl status canmatrix-editor
```

---

## 六、故障排查

### 服务启动失败

```bash
# 查看详细错误日志
sudo journalctl -u canmatrix-editor --no-pager -n 50

# 常见原因：
# 1. 端口被占用 → 修改 service 中的 --port 参数
# 2. venv 路径错误 → 确认 WorkingDirectory 和 ExecStart 路径一致
# 3. Python 依赖缺失 → 重新执行 build.sh 或 pip install -r requirements.txt
```

### 端口冲突

```bash
# 查看端口占用
ss -tlnp | grep 8080

# 如果旧的 CanMatrix 进程残留：
sudo pkill -f "app.server.lifecycle"

# 然后重启服务
sudo systemctl restart canmatrix-editor
```

### 日志目录权限问题

```bash
# 确保服务用户有权限写入 logs/ 目录
sudo chown -R $(whoami):$(whoami) /opt/canmatrix/logs/

# 或检查 service 中是否配置了 User=（默认以 root 运行）
grep "User=" /etc/systemd/system/canmatrix-editor.service
```

---

## 七、卸载

```bash
sudo systemctl stop canmatrix-editor
sudo systemctl disable canmatrix-editor
sudo rm /etc/systemd/system/canmatrix-editor.service
sudo systemctl daemon-reload
```
