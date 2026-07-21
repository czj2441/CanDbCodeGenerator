"""
快照引擎 — 脏版本数据的磁盘持久化。

在关键事件点（心跳超时销毁、WS 断开、进程退出、60s 定时器）自动将脏 db 数据
写入 snapshots/ 目录，用户打开文件时通过 restore() 优先从快照恢复。
"""
from __future__ import annotations

import json
import logging
import os
import time

from .file_persistence import SNAPSHOT_DIR

logger = logging.getLogger(__name__)


def write_snapshot(session) -> bool:
    """写快照（仅 db 状态，不含 undo/redo）。单锁保护。

    Args:
        session: Session 对象（需有 .id, .file_path, .db 属性）

    Returns:
        True 写入成功，False 跳过（未修改）或失败
    """
    try:
        db = session.db
        with db.with_lock():
            if not db.modified:
                return False
            snapshot_data = {
                "version": 1,
                "session_id": session.id,
                "file_name": os.path.basename(session.file_path),
                "file_path": session.file_path,
                "snapshotted_at": time.time(),
                "database": db.to_dict(),
            }
        # 锁外 I/O
        os.makedirs(SNAPSHOT_DIR, exist_ok=True)
        content = json.dumps(snapshot_data, ensure_ascii=False)
        target = os.path.join(SNAPSHOT_DIR, f"{session.id}.snapshot.json")
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, target)
        logger.info("Snapshot written: sid=%s file=%s (%d bytes)",
                     session.id[:8], snapshot_data["file_name"], len(content))
        return True
    except Exception as e:
        logger.error("Snapshot write failed for %s: %s",
                     getattr(session, 'id', '?')[:8], e, exc_info=True)
        return False


def remove_snapshot(session_id: str):
    """删除快照文件（save 成功后调用）。不存在时静默忽略。"""
    target = os.path.join(SNAPSHOT_DIR, f"{session_id}.snapshot.json")
    try:
        os.remove(target)
    except FileNotFoundError:
        pass
    except Exception as e:
        logger.error("Snapshot remove failed for %s: %s", session_id[:8], e)


def find_snapshot_for_file(file_name: str) -> tuple[dict, str] | None:
    """按文件名查找快照（遍历 snapshots/ 目录，匹配 file_name 字段）。

    返回 (snapshot_dict, snapshot_path) 或 None。
    不删除快照文件——调用方在 from_dict 成功后自行删除（消费语义）。
    """
    if not os.path.isdir(SNAPSHOT_DIR):
        return None
    for fname in os.listdir(SNAPSHOT_DIR):
        if not fname.endswith(".snapshot.json"):
            continue
        path = os.path.join(SNAPSHOT_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            if snap.get("file_name") == file_name:
                return snap, path  # 不删除，交给调用方
        except Exception:
            continue
    return None


def cleanup_stale_snapshots(max_age_days: int = 30):
    """清理过期快照（启动时调用一次）。同时清理遗留的 .tmp 文件。"""
    if not os.path.isdir(SNAPSHOT_DIR):
        return
    cutoff = time.time() - max_age_days * 86400
    for fname in os.listdir(SNAPSHOT_DIR):
        path = os.path.join(SNAPSHOT_DIR, fname)
        try:
            if fname.endswith(".tmp"):
                # 遗留的临时文件，直接删除
                os.remove(path)
                continue
            if not fname.endswith(".snapshot.json"):
                continue
            if os.path.getmtime(path) < cutoff:
                os.remove(path)
                logger.info("Stale snapshot cleaned: %s", fname)
        except Exception as e:
            logger.warning("Failed to clean snapshot %s: %s", fname, e)


def _scan_snapshot_filenames() -> set[str]:
    """扫描快照目录，返回所有快照对应的 file_name 集合（供 list_history 使用）。"""
    result: set[str] = set()
    if not os.path.isdir(SNAPSHOT_DIR):
        return result
    for fname in os.listdir(SNAPSHOT_DIR):
        if not fname.endswith(".snapshot.json"):
            continue
        path = os.path.join(SNAPSHOT_DIR, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                snap = json.load(f)
            fn = snap.get("file_name")
            if fn:
                result.add(fn)
        except Exception:
            continue
    return result
