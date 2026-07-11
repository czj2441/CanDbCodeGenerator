"""计算代码哈希版本号，供 build 脚本和运行时使用。"""
import hashlib
import os
import sys
import datetime

# 参与哈希计算的源码扩展名
INCLUDE_EXTS = {'.py', '.js', '.vue', '.html', '.css'}

# 排除的目录名（不参与遍历）
EXCLUDE_DIRS = {
    '__pycache__', 'dist', 'temp', 'data', 'logs',
    'node_modules', '.git', '.pytest_cache', '.qoder',
    'build',
}

# 排除的文件名（不参与哈希）
EXCLUDE_FILES = {'_version.py'}


def compute_auto_version(root_dir: str | None = None) -> str:
    """遍历所有源码文件，计算 SHA-256 哈希前8位 + 时间戳 YYMMDDHHmm。

    Returns:
        形如 'a1b2c3d4_2607101430' 的自动版本号
    """
    if root_dir is None:
        # tools/compute_version.py → 上溯一层到项目根目录
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    h = hashlib.sha256()
    files: list[str] = []

    for dirpath, dirnames, filenames in os.walk(root_dir):
        # 原地修改 dirnames 以剪枝（必须排序保证确定性）
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1].lower()
            if ext in INCLUDE_EXTS and fname not in EXCLUDE_FILES:
                files.append(os.path.join(dirpath, fname))

    # 全局排序（os.walk 已按目录排序，此处保证跨目录确定性）
    for fpath in sorted(files):
        rel = os.path.relpath(fpath, root_dir)
        h.update(rel.encode('utf-8'))
        try:
            with open(fpath, 'rb') as fp:
                while chunk := fp.read(65536):
                    h.update(chunk)
        except (IOError, OSError):
            pass

    code_hash = h.hexdigest()[:8]
    timestamp = datetime.datetime.now().strftime('%y%m%d%H%M')
    return f"{code_hash}_{timestamp}"


def _write_version(auto_version: str) -> None:
    """将自动版本号写入 _version.py 的 AUTO_VERSION 行。"""
    version_file = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app', '_version.py'
    )
    try:
        lines = open(version_file, 'r', encoding='utf-8').readlines()
    except FileNotFoundError:
        # 文件不存在则创建
        with open(version_file, 'w', encoding='utf-8') as f:
            f.write('"""版本号定义 — 构建时由 compute_version.py 更新 AUTO_VERSION。"""\n')
            f.write('MANUAL_VERSION = "v00.00"\n')
            f.write(f'AUTO_VERSION = "{auto_version}"\n')
        return

    with open(version_file, 'w', encoding='utf-8') as f:
        for line in lines:
            if line.startswith('AUTO_VERSION'):
                f.write(f'AUTO_VERSION = "{auto_version}"\n')
            else:
                f.write(line)


if __name__ == '__main__':
    auto_ver = compute_auto_version()
    if '--write' in sys.argv:
        _write_version(auto_ver)
        print(f"[Version] AUTO_VERSION = {auto_ver}")
    else:
        print(auto_ver)
