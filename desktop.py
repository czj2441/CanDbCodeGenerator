#!/usr/bin/env python3
"""
CanMatrix Editor - 桌面应用入口
使用 pywebview 打开原生窗口，内嵌 WebView2（Windows 下基于 Chromium）。
"""

import sys
import os
import threading
import time
import urllib.request
import json

# PyInstaller 打包后，资源在 sys._MEIPASS 目录
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    # 确保项目根目录在 sys.path 中
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


class DesktopApi:
    """暴露给前端 JS 的原生 API（通过 window.pywebview.api 调用）。"""

    def __init__(self, port):
        self._port = port
        self._window = None

    def set_window(self, window):
        self._window = window

    def save_file(self, format_str, session_id):
        """打开原生保存对话框，将导出内容写入用户选择的路径。
        JS 调用: window.pywebview.api.save_file('dbc', 'session_id_here')
        """
        import webview

        # 确定文件扩展名和过滤器
        ext_map = {'dbc': '.dbc', 'toml': '.toml', 'json': '.json'}
        ext = ext_map.get(format_str, f'.{format_str}')

        # 弹出原生保存对话框
        result = self._window.create_file_dialog(
            webview.SAVE_DIALOG,
            save_filename=f'export{ext}',
            file_types=(f'{format_str.upper()} 文件 (*{ext})',),
        )

        if not result:
            return json.dumps({'success': False, 'error': '用户取消'})

        save_path = result if isinstance(result, str) else result[0]

        # 从本地 API 服务器获取导出内容
        try:
            url = (
                f'http://localhost:{self._port}/api/download'
                f'?format={format_str}&sid={session_id}'
            )
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, timeout=30) as resp:
                content = resp.read()

            # 写入文件
            with open(save_path, 'wb') as f:
                f.write(content)

            return json.dumps({'success': True, 'path': save_path})
        except Exception as e:
            return json.dumps({'success': False, 'error': str(e)})


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

    # ── JS API 桥接对象 ──
    api = DesktopApi(port)

    # ── 创建 pywebview 窗口 ──
    window = webview.create_window(
        title="CanMatrix Editor",
        url=url,
        js_api=api,
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
    )

    # 设置窗口引用（供文件对话框使用）
    api.set_window(window)

    # ── 启动 webview（阻塞直到窗口关闭）──
    webview.start(debug=False)

    # ── 窗口关闭后，关闭服务器 ──
    print("[Desktop] 窗口已关闭，正在停止服务器...")
    server.shutdown()
    print("[Desktop] 已退出。")


if __name__ == "__main__":
    main()
