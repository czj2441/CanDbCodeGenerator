"""
文件持久化 — DATA_DIR 常量 + Properties 格式读写。
"""

import os
import sys as _sys

# 打包后数据目录放在用户 AppData，未打包时在源码目录
if getattr(_sys, 'frozen', False):
    # PyInstaller 打包：使用 %APPDATA%/CanMatrixEditor/data
    _app_data = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CanMatrixEditor')
    DATA_DIR = os.path.join(_app_data, 'data')
else:
    # 从 app/services/file_persistence.py → 上溯 3 层到项目根目录
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    DATA_DIR = os.path.join(_PROJECT_ROOT, "data")

HEARTBEAT_TIMEOUT = 30       # 30 秒无心跳则视为离线，自动释放文件锁
HEARTBEAT_CHECK_INTERVAL = 30  # 每 30 秒检查一次心跳超时
MAX_ORPHAN_STACKS = 20         # 孤儿撤销栈最大保留数量（LRU 淘汰）


def write_session_file(session, data_dir: str):
    """将会话数据以 Properties 格式写入磁盘。

    调用方必须已持有 session.db 的锁（通过 with_lock()），
    因为 to_properties_str() 内部会获取同一把 RLock，外部持锁可避免
    嵌套并保证写操作原子性。
    """
    content = session.db.to_properties_str()
    base = os.path.basename(session.file_path)
    if not base.endswith(".properties"):
        base += ".properties"
    check = base[:-11].strip() if base.endswith('.properties') else base.strip()
    if not check or not check.strip("_"):
        base = "Untitled.properties"
    # 非 UI 上下文（atexit 保存等）：重名时自动递增 fallback
    target = os.path.join(data_dir, base)
    if os.path.isfile(target) and session.file_path != target:
        base = _resolve_duplicate(base, data_dir)
        target = os.path.join(data_dir, base)
    file_path = target
    session.file_path = file_path
    tmp_path = file_path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp_path, file_path)


def load_session_file(file_path: str, model_factory=None):
    """从磁盘加载 Properties 数据文件，返回 CanDatabase 实例。"""
    if not os.path.isfile(file_path):
        return None
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        if model_factory:
            return model_factory.from_properties_str(content)
        return None
    except Exception:
        return None


def resolve_duplicate(base_name: str, data_dir: str) -> str:
    """重名时生成递增序号的 fallback 文件名。 Untitled.properties → Untitled_1.properties"""
    name, ext = os.path.splitext(base_name)
    i = 1
    while True:
        candidate = f"{name}_{i}{ext}"
        if not os.path.isfile(os.path.join(data_dir, candidate)):
            return candidate
        i += 1


# 内部别名（供 write_session_file 使用）
_resolve_duplicate = resolve_duplicate
