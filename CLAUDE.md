# 项目记忆

## 修改代码后的必要步骤

修改前端代码（`frontend/src/`）后：
1. **重新构建**：`cd frontend && npx vite build`（输出到 `../dist/`）
2. **重启后端服务**：Python 服务从 `dist/` 提供静态文件，需要重启才能加载新构建产物

修改后端 Python 代码（`api_server.py`、`models.py`、`session_manager.py`、`core/`）后：
- 重启 `python api_server.py` 服务即可

## MCP Puppeteer 连接方法

当 puppeteer MCP 工具连接 Chrome 失败时，按以下步骤操作：

### 启动带远程调试的 Chrome

```bash
# 关键点：
# 1. 必须用独立 user-data-dir，避免与已运行的 Chrome 实例冲突
# 2. 必须在后台运行（&）且给足 sleep 时间
# 3. bash timeout 必须大于 Chrome 启动时间，否则子进程会被杀
"C:\Program Files\Google\Chrome\Application\chrome.exe" \
  --remote-debugging-port=9222 \
  --remote-debugging-address=127.0.0.1 \
  --user-data-dir="C:\Temp\chrome-mcp" \
  http://localhost:8080 2>&1 &
sleep 8
```

### 连接步骤

1. 先杀死所有 Chrome 进程（可选，避免 profile 冲突）
2. 执行上述 bash 命令启动 Chrome（允许足够 timeout）
3. 调用 `puppeteer_puppeteer_connect_active_tab` 连接到页面
4. 如遇 "detached Frame" 错误，重新 connect 即可
