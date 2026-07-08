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
    [os.path.join(ROOT, 'desktop.py')],
    pathex=[ROOT],
    binaries=[],
    datas=[
        # 前端构建产物 → 打包进 exe 内部 dist/ 目录
        (os.path.join(ROOT, 'dist', 'index.html'), 'dist'),
        (os.path.join(ROOT, 'dist', 'assets', '*'), 'dist/assets'),
    ],
    hiddenimports=[
        'cantools',
        'cantools.database',
        'javaproperties',
        'webview',
        'websockets',
        'models',
        'session_manager',
        'api_server',
        'ws_transport',
        'ws_router',
        'ws_server',
        'handlers',
        'core',
        'core.can_database',
        'core.dbc_io',
        'core.json_io',
        'core.properties_io',
        'core.xml_io',
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
