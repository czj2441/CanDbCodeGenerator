# -*- mode: python ; coding: utf-8 -*-
"""
CanMatrix Editor - PyInstaller 打包配置
用法: pyinstaller desktop.spec
"""

import os

block_cipher = None

# 项目根目录（spec 文件所在目录）
ROOT = os.path.dirname(os.path.abspath(SPEC))

a = Analysis(
    [os.path.join(ROOT, 'tools', 'desktop.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # 前端构建产物 → 打包进 exe 内部 dist/ 目录
        (os.path.join(ROOT, 'dist', 'index.html'), 'dist'),
        (os.path.join(ROOT, 'dist', 'assets', '*'), 'dist/assets'),
        (os.path.join(ROOT, 'app', 'io', 'templates', 'c'), 'app/io/templates/c'),
    ],
    hiddenimports=[
        'cantools',
        'cantools.database',
        'javaproperties',
        'webview',
        'websockets',
        'app',
        'app.models',
        'app.models.signal',
        'app.models.message',
        'app.models.database',
        'app.server',
        'app.server.http_handler',
        'app.server.port_utils',
        'app.server.lifecycle',
        'app.ws',
        'app.ws.transport',
        'app.ws.router',
        'app.ws.server',
        'app.ws.handlers',
        'app.ws.handlers.file_handlers',
        'app.ws.handlers.message_handlers',
        'app.ws.handlers.signal_handlers',
        'app.ws.handlers.system_handlers',
        'app.services',
        'app.services.session',
        'app.services.session_manager',
        'app.services.undo_engine',
        'app.services.file_lock',
        'app.services.file_persistence',
        'app.io',
        'app.io.properties_io',
        'app.io.dbc_io',
        'app.io.json_io',
        'app.io.xml_io',
        'app.io.c_code_gen',
        'jinja2',
        'jinja2.ext',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'unittest'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='CanMatrixEditor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 不显示控制台窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
