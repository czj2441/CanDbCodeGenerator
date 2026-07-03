#!/usr/bin/env python3
"""
CanMatrix Editor - 桌面应用入口（单窗口架构）
  WinForms 窗口 + SplitContainer：
    - 顶部：菜单栏（工具下拉菜单：打开后端日志、重启后端）
    - 上半部分：WebView2 渲染 Web 编辑器
    - 下半部分：后端日志面板（默认隐藏，通过菜单打开）
"""

import sys
import os
import queue
import threading
import time
import urllib.request
import json
import uuid

# PyInstaller 打包后，资源在 sys._MEIPASS 目录
if getattr(sys, 'frozen', False):
    BASE_DIR = sys._MEIPASS
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    if BASE_DIR not in sys.path:
        sys.path.insert(0, BASE_DIR)


# ──────────────────────────────────────────────────────────────
# .NET / WinForms 初始化
# ──────────────────────────────────────────────────────────────

def _init_dotnet():
    """加载 WinForms 和 WebView2 程序集。"""
    import clr
    clr.AddReference("System.Windows.Forms")
    clr.AddReference("System.Drawing")

    # 加载 pywebview 自带的 WebView2 和 WebBrowserInterop DLL
    try:
        import webview as _wv
        lib_dir = os.path.join(os.path.dirname(_wv.__file__), "lib")
        clr.AddReference(os.path.join(lib_dir, "Microsoft.Web.WebView2.Core"))
        clr.AddReference(os.path.join(lib_dir, "Microsoft.Web.WebView2.WinForms"))
        interop_dll = os.path.join(lib_dir, "WebBrowserInterop.dll")
        if os.path.exists(interop_dll):
            clr.AddReference(interop_dll)
    except Exception:
        pass

_init_dotnet()

import System
from System.Windows.Forms import (
    Application as WinApp,
    Form, FormBorderStyle, FormStartPosition,
    SplitContainer, Orientation, DockStyle,
    Panel, RichTextBox, Label, Button, CheckBox, ComboBox,
    TextBox, ScrollBars, BorderStyle, FlatStyle,
    SaveFileDialog, DialogResult,
    AnchorStyles, Padding,
    Timer as WinTimer,
    ComboBoxStyle,
    RichTextBoxScrollBars,
    WebBrowser,
    MenuStrip, ToolStripMenuItem, ToolStripSeparator,
)
from System.Drawing import (
    Color, Font as NetFont, FontStyle, Point, Size,
    ContentAlignment,
)
from System.Runtime.InteropServices import ComVisibleAttribute

# 加载 pywebview 的 WebBrowserInterop
try:
    from WebBrowserInterop import IWebBrowserInterop, WebBrowserEx
    HAS_WEBBROWSER_INTEROP = True
except ImportError:
    HAS_WEBBROWSER_INTEROP = False

# 加载 WebView2（优先使用）
try:
    from Microsoft.Web.WebView2.WinForms import WebView2, CoreWebView2CreationProperties
    HAS_WEBVIEW2 = True
except ImportError:
    HAS_WEBVIEW2 = False


# ──────────────────────────────────────────────────────────────
# 日志捕获（不变）
# ──────────────────────────────────────────────────────────────

class StdoutCatcher:
    """替换 sys.stdout，将输出转发到队列，供日志面板消费。"""

    def __init__(self, original_stdout):
        self._original = original_stdout
        self._queue = queue.Queue(maxsize=5000)

    def write(self, text):
        if text and text.strip():
            try:
                self._queue.put_nowait(text.rstrip('\n'))
            except queue.Full:
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                self._queue.put_nowait(text.rstrip('\n'))
        if self._original:
            self._original.write(text)

    def flush(self):
        if self._original:
            self._original.flush()

    def get_lines(self):
        """非阻塞取出所有待显示行。"""
        lines = []
        while True:
            try:
                lines.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return lines


# ──────────────────────────────────────────────────────────────
# DesktopApi：原生保存对话框 + JS 桥接
# ──────────────────────────────────────────────────────────────

if HAS_WEBBROWSER_INTEROP:
    class DesktopApi(IWebBrowserInterop):
        """处理前端 JS 桥接调用（save_file 等）。继承 IWebBrowserInterop 供 mshtml 使用。"""
        __namespace__ = 'DesktopApi.JSBridge'

        def __init__(self, port, browser_ctrl):
            self._port = port
            self._browser = browser_ctrl

        def save_file(self, format_str, session_id):
            """打开原生保存对话框，返回 JSON 字符串。"""
            ext_map = {'dbc': '.dbc', 'toml': '.toml', 'json': '.json'}
            ext = ext_map.get(format_str, f'.{format_str}')

            dialog = SaveFileDialog()
            dialog.FileName = f"export{ext}"
            dialog.Filter = f"{format_str.upper()} 文件 (*{ext})|*{ext}"
            result = dialog.ShowDialog()

            if result != DialogResult.OK:
                return json.dumps({'success': False, 'error': '用户取消'})

            save_path = dialog.FileName

            try:
                url = (
                    f'http://localhost:{self._port}/api/download'
                    f'?format={format_str}&sid={session_id}'
                )
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=30) as resp:
                    content = resp.read()

                with open(save_path, 'wb') as f:
                    f.write(content)

                return json.dumps({'success': True, 'path': save_path})
            except Exception as e:
                return json.dumps({'success': False, 'error': str(e)})
else:
    class DesktopApi:
        """回退版本：无 IWebBrowserInterop 支持。"""
        def __init__(self, port, browser_ctrl):
            self._port = port
            self._browser = browser_ctrl

        def save_file(self, format_str, session_id):
            return json.dumps({'success': False, 'error': 'JS 桥接不可用'})


# ──────────────────────────────────────────────────────────────
# JS 桥接注入脚本
# ──────────────────────────────────────────────────────────────

# WebView2 版本：通过 postMessage 通信
JS_BRIDGE_WEBVIEW2 = r"""
(function() {
    if (window.__pywebview_bridge_installed) return;
    window.__pywebview_bridge_installed = true;
    window.pywebview = {
        api: {
            save_file: function(format, sessionId) {
                return new Promise(function(resolve) {
                    var callId = 'call_' + Math.random().toString(36).substr(2, 9);
                    window.__pywebview_resolvers = window.__pywebview_resolvers || {};
                    window.__pywebview_resolvers[callId] = resolve;
                    window.chrome.webview.postMessage(JSON.stringify({
                        type: 'pywebview_api',
                        method: 'save_file',
                        args: [format, sessionId],
                        callId: callId
                    }));
                });
            }
        }
    };
    window.on_pywebview_response = function(callId, resultJson) {
        if (window.__pywebview_resolvers && window.__pywebview_resolvers[callId]) {
            window.__pywebview_resolvers[callId](resultJson);
            delete window.__pywebview_resolvers[callId];
        }
    };
})();
"""

# mshtml 版本：通过 window.external 通信
JS_BRIDGE_MSHTML = r"""
(function() {
    if (window.__pywebview_bridge_installed) return;
    window.__pywebview_bridge_installed = true;
    window.pywebview = {
        api: {
            save_file: function(format, sessionId) {
                try {
                    var result = window.external.save_file(format, sessionId);
                    return Promise.resolve(result);
                } catch(e) {
                    return Promise.resolve(JSON.stringify({success: false, error: e.message}));
                }
            }
        }
    };
})();
"""


# ──────────────────────────────────────────────────────────────
# 主窗口
# ──────────────────────────────────────────────────────────────

class MainWindow:
    """WinForms 单窗口：WebBrowser(mshtml) + 日志面板 + 控制面板。"""

    MAX_LOG_LINES = 2000

    def __init__(self, port, server_ref, catcher):
        self.port = port
        self.server_ref = server_ref
        self.catcher = catcher
        self._running = True
        self._start_time = time.time()
        self._webview_ready = False
        self._api = None

        self._build_ui()
        self._init_webview()
        self._start_log_timer()

        # 窗口显示后加载页面（需要有效的窗口句柄）
        self.form.Shown += self._on_form_shown

    # ── UI 构建 ─────────────────────────────────────────────

    def _build_ui(self):
        """构建 WinForms 窗口和所有控件。"""
        # ── 主窗口 ──
        self.form = Form()
        self.form.Text = "CanMatrix Editor"
        self.form.Size = Size(1400, 900)
        self.form.MinimumSize = Size(900, 600)
        self.form.StartPosition = FormStartPosition.CenterScreen
        self.form.BackColor = Color.FromArgb(30, 30, 30)

        # ── SplitContainer ──
        self.splitter = SplitContainer()
        self.splitter.Dock = DockStyle.Fill
        self.splitter.Orientation = Orientation.Horizontal
        self.splitter.BackColor = Color.FromArgb(62, 62, 66)  # 分割条颜色
        self.splitter.SplitterWidth = 6
        self.splitter.SplitterDistance = 620  # 上部占 ~70%
        self.splitter.Panel1MinSize = 200
        self.splitter.Panel2MinSize = 140

        # ── 上部：WebView2（优先）或 WebBrowser(mshtml) ──
        self._use_webview2 = HAS_WEBVIEW2
        if self._use_webview2:
            self.webview = WebView2()
            self.webview.Dock = DockStyle.Fill
            self.splitter.Panel1.Controls.Add(self.webview)
            print(f"[Desktop] 使用 WebView2 渲染器")
        else:
            self.webview = WebBrowser()
            self.webview.Dock = DockStyle.Fill
            self.webview.ScriptErrorsSuppressed = True
            self.splitter.Panel1.Controls.Add(self.webview)
            print(f"[Desktop] 使用 mshtml (IE) 渲染器")

        # ── 下部：日志面板（默认隐藏，通过菜单打开）──
        bottom_panel = Panel()
        bottom_panel.Dock = DockStyle.Fill
        bottom_panel.BackColor = Color.FromArgb(37, 37, 38)
        bottom_panel.Visible = False  # 默认隐藏
        self._bottom_panel = bottom_panel

        # 日志工具栏
        toolbar = Panel()
        toolbar.Dock = DockStyle.Top
        toolbar.Height = 30
        toolbar.BackColor = Color.FromArgb(45, 45, 45)
        self._build_log_toolbar(toolbar)

        # 日志文本框（填充剩余空间）
        self.log_text = RichTextBox()
        self.log_text.Dock = DockStyle.Fill
        self.log_text.ReadOnly = True
        self.log_text.BackColor = Color.FromArgb(30, 30, 30)
        self.log_text.ForeColor = Color.FromArgb(212, 212, 212)
        self.log_text.Font = NetFont("Consolas", 9.0)
        self.log_text.BorderStyle = getattr(BorderStyle, 'None')
        self.log_text.ScrollBars = RichTextBoxScrollBars.Vertical
        self.log_text.WordWrap = True

        # 添加到 bottom_panel
        bottom_panel.Controls.Add(self.log_text)    # Fill
        bottom_panel.Controls.Add(toolbar)          # Top

        self.splitter.Panel2.Controls.Add(bottom_panel)
        self.form.Controls.Add(self.splitter)

        # ── 菜单栏（必须在 SplitContainer 之后添加到 Controls，否则会被遮挡）──
        self._build_menu()

        # 默认折叠 Panel2（日志未显示时不占空间）
        self.splitter.Panel2Collapsed = True

        # 窗口关闭事件
        self.form.FormClosing += self._on_form_closing

    def _build_log_toolbar(self, toolbar):
        """构建日志工具栏。"""
        x = 6
        # 标题
        title = Label()
        title.Text = "后端日志"
        title.Font = NetFont("Microsoft YaHei UI", 9.5, FontStyle.Bold)
        title.ForeColor = Color.FromArgb(204, 204, 204)
        title.BackColor = Color.FromArgb(45, 45, 45)
        title.Location = Point(x, 5)
        title.AutoSize = True
        toolbar.Controls.Add(title)
        x += 75

        # 清空按钮
        btn_clear = Button()
        btn_clear.Text = "清空"
        btn_clear.Font = NetFont("Microsoft YaHei UI", 8.5)
        btn_clear.ForeColor = Color.FromArgb(204, 204, 204)
        btn_clear.BackColor = Color.FromArgb(60, 60, 60)
        btn_clear.FlatStyle = FlatStyle.Flat
        btn_clear.FlatAppearance.BorderColor = Color.FromArgb(80, 80, 80)
        btn_clear.Location = Point(x, 3)
        btn_clear.Size = Size(50, 24)
        btn_clear.Click += lambda s, e: self._clear_log()
        toolbar.Controls.Add(btn_clear)
        x += 60

        # 自动滚动复选框
        self.chk_autoscroll = CheckBox()
        self.chk_autoscroll.Text = "自动滚动"
        self.chk_autoscroll.Checked = True
        self.chk_autoscroll.Font = NetFont("Microsoft YaHei UI", 8.5)
        self.chk_autoscroll.ForeColor = Color.FromArgb(204, 204, 204)
        self.chk_autoscroll.BackColor = Color.FromArgb(45, 45, 45)
        self.chk_autoscroll.Location = Point(x, 5)
        self.chk_autoscroll.AutoSize = True
        toolbar.Controls.Add(self.chk_autoscroll)
        x += 90

        # 级别过滤标签
        lbl_filter = Label()
        lbl_filter.Text = "级别:"
        lbl_filter.Font = NetFont("Microsoft YaHei UI", 8.5)
        lbl_filter.ForeColor = Color.FromArgb(153, 153, 153)
        lbl_filter.BackColor = Color.FromArgb(45, 45, 45)
        lbl_filter.Location = Point(x, 5)
        lbl_filter.AutoSize = True
        toolbar.Controls.Add(lbl_filter)
        x += 40

        # 级别过滤下拉
        self.cbo_filter = ComboBox()
        self.cbo_filter.DropDownStyle = ComboBoxStyle.DropDownList
        self.cbo_filter.Font = NetFont("Consolas", 9.0)
        self.cbo_filter.Items.AddRange(["ALL", "INFO", "WARN", "ERROR", "API"])
        self.cbo_filter.SelectedIndex = 0
        self.cbo_filter.Location = Point(x, 3)
        self.cbo_filter.Size = Size(70, 24)
        toolbar.Controls.Add(self.cbo_filter)

    def _build_menu(self):
        """构建顶部菜单栏。"""
        menu_bar = MenuStrip()
        menu_bar.BackColor = Color.FromArgb(45, 45, 45)
        menu_bar.ForeColor = Color.FromArgb(204, 204, 204)

        # ── “工具”下拉菜单 ──
        tool_menu = ToolStripMenuItem("工具")
        tool_menu.BackColor = Color.FromArgb(45, 45, 45)
        tool_menu.ForeColor = Color.FromArgb(204, 204, 204)

        # 打开后端日志
        self._menu_log = ToolStripMenuItem("打开后端日志")
        self._menu_log.Click += self._on_toggle_log
        tool_menu.DropDownItems.Add(self._menu_log)

        tool_menu.DropDownItems.Add(ToolStripSeparator())

        # 重启后端
        self._menu_restart = ToolStripMenuItem("重启后端")
        self._menu_restart.Click += self._on_restart_click
        tool_menu.DropDownItems.Add(self._menu_restart)

        menu_bar.Items.Add(tool_menu)
        self.form.MainMenuStrip = menu_bar
        self.form.Controls.Add(menu_bar)

    def _on_toggle_log(self, sender, args):
        """切换日志面板显示/隐藏。"""
        visible = not self._bottom_panel.Visible
        self._bottom_panel.Visible = visible
        self.splitter.Panel2Collapsed = not visible
        self._menu_log.Text = "关闭后端日志" if visible else "打开后端日志"

    # ── 浏览器初始化 ─────────────────────────────────────

    def _init_webview(self):
        """初始化浏览器控件。"""
        if self._use_webview2:
            # WebView2: 设置 CreationProperties（不指定 BrowserExecutableFolder，让系统自动检测）
            props = CoreWebView2CreationProperties()
            cache_dir = os.path.join(
                os.environ.get('LOCALAPPDATA', os.path.expanduser('~')),
                'CanMatrixEditor', 'WebView2Cache'
            )
            props.UserDataFolder = cache_dir
            self.webview.CreationProperties = props
            print(f"[Desktop] WebView2 UserDataFolder: {cache_dir}")
        else:
            # mshtml: 设置 DocumentCompleted 事件
            self.webview.DocumentCompleted += self._on_document_completed

    def _on_form_shown(self, sender, args):
        """窗口显示后加载页面。"""
        url = f"http://localhost:{self.port}"
        if self._use_webview2:
            print(f"[Desktop] WebView2 初始化中...", flush=True)
            self.webview.CoreWebView2InitializationCompleted += self._on_webview2_ready
            self.webview.NavigationStarting += self._on_webview2_navigation
            self.webview.WebMessageReceived += self._on_webview2_message
            try:
                self.webview.EnsureCoreWebView2Async(None)
            except Exception as e:
                print(f"[Desktop] WebView2 初始化异常: {e}", flush=True)
        else:
            print(f"[Desktop] 加载页面: {url}", flush=True)
            self.webview.Navigate(url)

    # ── WebView2 事件 ──

    def _on_webview2_ready(self, sender, args):
        """WebView2 初始化完成。"""
        if args.IsSuccess:
            self._webview_ready = True
            url = f"http://localhost:{self.port}"
            self.webview.CoreWebView2.Navigate(url)
            self._append_log(f"[Desktop] WebView2 已就绪，加载: {url}")
            print(f"[Desktop] WebView2 初始化成功", flush=True)
        else:
            err = args.InitializationException
            print(f"[Desktop] WebView2 初始化失败: {err}", flush=True)
            self._append_log(f"[Desktop] WebView2 初始化失败: {err}")

    def _on_webview2_navigation(self, sender, args):
        """WebView2 导航开始时注入 JS 桥接。"""
        try:
            self.webview.CoreWebView2.AddScriptToExecuteOnDocumentCreatedAsync(JS_BRIDGE_WEBVIEW2)
        except Exception:
            pass

    def _on_webview2_message(self, sender, args):
        """处理 WebView2 JS 发来的消息。"""
        try:
            msg = json.loads(args.TryGetWebMessageAsString())
        except Exception:
            return

        if msg.get('type') != 'pywebview_api':
            return

        method = msg.get('method')
        call_id = msg.get('callId', '')
        js_args = msg.get('args', [])

        def _handle():
            try:
                if method == 'save_file' and self._api:
                    result = self._api.save_file(*js_args)
                else:
                    result = json.dumps({'success': False, 'error': 'Unknown method'})
            except Exception as e:
                result = json.dumps({'success': False, 'error': str(e)})

            # 将结果回传给 JS
            escaped = result.replace('\\', '\\\\').replace("'", "\\'")
            script = f"window.on_pywebview_response('{call_id}', '{escaped}')"
            try:
                self.webview.CoreWebView2.ExecuteScriptAsync(script)
            except Exception:
                pass

        threading.Thread(target=_handle, daemon=True).start()

    # ── mshtml 事件 ──

    def _on_document_completed(self, sender, args):
        """mshtml 页面加载完成，注入 JS 桥接。"""
        self._webview_ready = True
        print(f"[Desktop] mshtml 页面加载完成: {args.Url}", flush=True)
        try:
            self.webview.Document.InvokeScript("eval", [JS_BRIDGE_MSHTML])
            self._append_log("[Desktop] JS 桥接已注入")
        except Exception as e:
            print(f"[Desktop] JS 注入失败: {e}", flush=True)

    # ── 日志面板 ────────────────────────────────────────────

    def _start_log_timer(self):
        """启动日志轮询定时器。"""
        # 日志轮询（200ms）
        self.log_timer = WinTimer()
        self.log_timer.Interval = 200
        self.log_timer.Tick += self._on_log_tick
        self.log_timer.Start()

    def _on_log_tick(self, sender, args):
        """轮询日志队列。"""
        for line in self.catcher.get_lines():
            self._append_log(line)

    def _append_log(self, line):
        """追加一行日志到 RichTextBox，带颜色标记。"""
        # 过滤
        level = self.cbo_filter.SelectedItem if self.cbo_filter.SelectedItem else "ALL"
        if not self._match_filter(line, level):
            return

        # 判断颜色
        upper = line.upper()
        if "[WARN]" in upper:
            color = Color.FromArgb(206, 145, 120)
        elif "[ERROR]" in upper or "TRACEBACK" in upper or "ERROR" in upper:
            color = Color.FromArgb(244, 71, 71)
        elif "[API]" in upper or "GET " in upper or "POST " in upper:
            color = Color.FromArgb(86, 156, 214)
        elif "[DESKTOP]" in upper:
            color = Color.FromArgb(197, 134, 192)
        else:
            color = Color.FromArgb(106, 153, 85)

        # 追加文本
        start = self.log_text.TextLength
        self.log_text.AppendText(line + "\n")
        self.log_text.Select(start, len(line))
        self.log_text.SelectionColor = color
        self.log_text.Select(self.log_text.TextLength, 0)

        # 限制最大行数
        line_count = self.log_text.Lines.Length
        if line_count > self.MAX_LOG_LINES:
            excess = line_count - self.MAX_LOG_LINES
            idx = self.log_text.GetFirstCharIndexFromLine(excess)
            self.log_text.Select(0, idx)
            self.log_text.SelectedText = ""

        # 自动滚动
        if self.chk_autoscroll.Checked:
            self.log_text.SelectionStart = self.log_text.TextLength
            self.log_text.ScrollToCaret()

    def _match_filter(self, line, level):
        """判断日志行是否匹配过滤级别。"""
        if level == "ALL":
            return True
        upper = line.upper()
        if level == "WARN":
            return "[WARN]" in upper
        elif level == "ERROR":
            return "[ERROR]" in upper or "TRACEBACK" in upper or "ERROR" in upper
        elif level == "API":
            return "[API]" in upper or "GET " in upper or "POST " in upper
        elif level == "INFO":
            return not ("[WARN]" in upper or "[ERROR]" in upper or "TRACEBACK" in upper
                        or "[API]" in upper or "GET " in upper or "POST " in upper)
        return True

    def _clear_log(self):
        """清空日志。"""
        self.log_text.Clear()

    # ── 控制面板 ────────────────────────────────────────────

    def _set_status(self, state):
        """设置状态指示。state: 'running' | 'stopped' | 'restarting'"""
        states = {
            'running':    True,
            'stopped':    True,
            'restarting': False,
        }
        self._menu_restart.Enabled = states.get(state, False)
        if state == 'running':
            self._start_time = time.time()
            self._menu_restart.Text = "重启后端"
        elif state == 'stopped':
            self._menu_restart.Text = "启动后端"
        elif state == 'restarting':
            self._menu_restart.Text = "重启中..."

    def _on_restart_click(self, sender, args):
        """重启按钮点击事件。"""
        self._set_status('restarting')
        self._append_log("[Desktop] 正在停止后端服务...")

        def _do_restart():
            from api_server import (
                start_server_background,
                check_port_available,
            )
            try:
                self.server_ref[0].shutdown()
                self.server_ref[0].server_close()
            except Exception as e:
                self._append_log(f"[Desktop] 停止服务器异常: {e}")

            # 等待端口释放
            for _ in range(20):
                time.sleep(0.25)
                if check_port_available(self.port):
                    break

            self._append_log(f"[Desktop] 端口 {self.port} 已释放")

            try:
                new_server = start_server_background(self.port)
                self.server_ref[0] = new_server
                self._append_log(f"[Desktop] 后端已重启，端口 {self.port}")
                self.form.Invoke(System.Action(lambda: self._set_status('running')))
            except Exception as e:
                self._append_log(f"[Desktop] 重启失败: {e}")
                self.form.Invoke(System.Action(lambda: self._set_status('stopped')))

        threading.Thread(target=_do_restart, daemon=True).start()

    # ── 窗口关闭 ────────────────────────────────────────────

    def _on_form_closing(self, sender, args):
        """窗口关闭时清理资源。"""
        self.log_timer.Stop()
        try:
            self.server_ref[0].shutdown()
        except Exception:
            pass
        self.catcher.flush()
        if self.catcher._original:
            sys.stdout = self.catcher._original
        print("[Desktop] 已退出。")


# ──────────────────────────────────────────────────────────────
# 主流程
# ──────────────────────────────────────────────────────────────

def _set_ie_emulation():
    """设置 WebBrowser 控件使用 IE11 仿真模式（通过注册表）。"""
    import winreg
    try:
        ie_key = winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r'Software\Microsoft\Internet Explorer'
        )
        try:
            version, _ = winreg.QueryValueEx(ie_key, 'svcVersion')
        except Exception:
            try:
                version, _ = winreg.QueryValueEx(ie_key, 'Version')
            except Exception:
                version = '11.0'
        winreg.CloseKey(ie_key)

        if version.startswith('11'):
            mode = 0x2AF9  # IE11
        elif version.startswith('10'):
            mode = 0x2711  # IE10
        else:
            mode = 0x2AF9  # 默认 IE11

        exe_name = os.path.basename(sys.executable)
        try:
            reg_key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION',
                0, winreg.KEY_ALL_ACCESS,
            )
        except OSError:
            reg_key = winreg.CreateKeyEx(
                winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Internet Explorer\Main\FeatureControl\FEATURE_BROWSER_EMULATION',
                0, winreg.KEY_ALL_ACCESS,
            )
        winreg.SetValueEx(reg_key, exe_name, 0, winreg.REG_DWORD, mode)
        winreg.CloseKey(reg_key)
        print(f"[Desktop] IE 仿真模式已设置: {exe_name} -> 0x{mode:04X}")
    except Exception as e:
        print(f"[Desktop] 设置 IE 仿真模式失败: {e}")


def main():
    from api_server import (
        start_server_background,
        check_port_available,
        handle_port_conflict,
    )

    # ── 日志捕获 ──
    catcher = StdoutCatcher(sys.stdout)
    sys.stdout = catcher

    # ── 选择可用端口（HTTP + WS 双端口） ──
    port = 8080
    if not check_port_available(port) or not check_port_available(port + 1):
        print(f"[WARN] 端口 {port} 或 {port+1} 被占用，尝试自动清理...")
        if not handle_port_conflict(port, auto_clean=True):
            for alt_port in range(8082, 8092, 2):  # 步进 2，确保连续两端口可用
                if check_port_available(alt_port) and check_port_available(alt_port + 1):
                    port = alt_port
                    break
            else:
                print("[ERROR] 无法找到可用端口对（HTTP+WS），退出。")
                sys.exit(1)

    # ── 启动后端 ──
    server = start_server_background(port)
    server_ref = [server]
    print(f"[Desktop] 服务已启动: http://localhost:{port}")

    # ── 创建主窗口 ──
    # WebBrowser 控件需要 STA 线程
    import System.Threading
    System.Threading.Thread.CurrentThread.SetApartmentState(
        System.Threading.ApartmentState.STA
    )

    # 必须在创建任何 WinForms 控件之前调用
    WinApp.EnableVisualStyles()
    WinApp.SetCompatibleTextRenderingDefault(False)

    # 设置 IE11 仿真模式（仅 mshtml 需要）
    if not HAS_WEBVIEW2:
        _set_ie_emulation()

    window = MainWindow(port, server_ref, catcher)
    window._api = DesktopApi(port, window.webview)

    # mshtml: 设置 ObjectForScripting（必须在 Navigate 之前）
    if not window._use_webview2:
        window.webview.ObjectForScripting = window._api

    # ── 启动 WinForms 消息循环（阻塞直到窗口关闭）──
    WinApp.Run(window.form)


if __name__ == "__main__":
    main()
