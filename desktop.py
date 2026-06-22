#!/usr/bin/env python3
"""
CanMatrix Editor - 桌面应用入口
使用 pywebview 打开原生窗口，内嵌 WebView2（Windows 下基于 Chromium）。
"""

import sys
import os
import threading
import time

# PyInstaller 打包后，资源在 sys._MEIPASS 目录
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # 确保项目根目录在 sys.path 中
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


def main():
    import webview
    from api_server import start_server_background, check_port_available, handle_port_conflict

    # ── 选择可用端口 ──
    port = 8080
    if not check_port_available(port):
        print(f"[WARN] 端口 {port} 被占用，尝试自动清理...")
        if not handle_port_conflict(port, auto_clean=True):
            # 尝试备用端口
            for alt_port in range(8081, 8091):
                if check_port_available(alt_port):
                    port = alt_port
                    break
            else:
                print("[ERROR] 无法找到可用端口，退出。")
                sys.exit(1)

    # ── 启动后台 API 服务器 ──
    server = start_server_background(port)
    url = f"http://localhost:{port}"
    print(f"[Desktop] 打开窗口: {url}")

    # ── 创建 pywebview 窗口 ──
    window = webview.create_window(
        title="CanMatrix Editor",
        url=url,
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
    )

    # ── 启动 webview（阻塞直到窗口关闭）──
    webview.start(debug=False)

    # ── 窗口关闭后，关闭服务器 ──
    print("[Desktop] 窗口已关闭，正在停止服务器...")
    server.shutdown()
    print("[Desktop] 已退出。")


if __name__ == "__main__":
    main()
