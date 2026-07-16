"""
port_utils.py — 端口检测与冲突处理工具。
"""

import logging
import socket
import subprocess
import platform
import time

logger = logging.getLogger(__name__)


def check_port_available(port: int) -> bool:
    """检查端口是否可用。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('localhost', port))
            return True
        except OSError:
            return False


def find_processes_on_port(port: int) -> list:
    """查找占用指定端口的进程。"""
    system = platform.system()
    try:
        if system == 'Windows':
            result = subprocess.run(
                ['netstat', '-ano'],
                capture_output=True, text=True, timeout=5
            )
            pids = []
            for line in result.stdout.split('\n'):
                if f':{port}' in line and 'LISTENING' in line:
                    parts = line.split()
                    if len(parts) >= 5:
                        pid = parts[-1]
                        if pid.isdigit():
                            pids.append(int(pid))
            return pids

        elif system in ('Linux', 'Darwin'):
            try:
                result = subprocess.run(
                    ['ss', '-tlnp', f'sport = :{port}'],
                    capture_output=True, text=True, timeout=5
                )
                pids = []
                for line in result.stdout.split('\n'):
                    if 'pid=' in line:
                        import re
                        pid_match = re.search(r'pid=(\d+)', line)
                        if pid_match:
                            pids.append(int(pid_match.group(1)))
                if pids:
                    return pids
            except FileNotFoundError:
                pass

            result = subprocess.run(
                ['lsof', '-i', f':{port}', '-t'],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0:
                pids = []
                for line in result.stdout.strip().split('\n'):
                    if line.strip().isdigit():
                        pids.append(int(line.strip()))
                return pids

        return []
    except Exception as e:
        logger.debug("Failed to find processes on port %d: %s", port, e)
        return []


def kill_process(pid: int) -> bool:
    """终止指定进程。"""
    try:
        system = platform.system()
        if system == 'Windows':
            subprocess.run(
                ['taskkill', '/F', '/PID', str(pid)],
                capture_output=True, timeout=5
            )
        elif system in ('Linux', 'Darwin'):
            subprocess.run(
                ['kill', '-9', str(pid)],
                capture_output=True, timeout=5
            )
        else:
            return False
        return True
    except Exception as e:
        logger.warning("Failed to kill process %d: %s", pid, e)
        return False


def handle_port_conflict(port: int, auto_clean: bool = False) -> bool:
    """处理端口冲突，返回是否成功解决。"""
    logger.error("端口 %d 已被占用", port)

    system = platform.system()
    pids = find_processes_on_port(port)

    if not pids:
        logger.info("端口 %d 被占用，但无法检测到占用进程。", port)
        logger.info("可能的原因：")
        logger.info("  1. 其他程序正在使用该端口")
        logger.info("  2. 端口处于 TIME_WAIT 状态（等待关闭）")
        logger.info("建议操作：")
        logger.info("  - 使用其他端口启动：python -m app.server.lifecycle <端口号>")
        logger.info("  - 等待几秒后重试（如果是 TIME_WAIT 状态）")
        return False

    api_server_pids = []

    if system == 'Windows':
        try:
            result = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV'],
                capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.split('\n'):
                if 'python.exe' in line.lower():
                    for pid in pids:
                        if str(pid) in line:
                            api_server_pids.append(pid)
        except Exception:
            pass
    else:
        api_server_pids = pids[:10]

    if api_server_pids:
        logger.info("检测到 %d 个占用端口的进程：", len(api_server_pids))
        for pid in api_server_pids:
            logger.info("  - PID: %d", pid)

        if auto_clean:
            logger.info("[Auto-cleaning] 正在终止旧进程...")
        else:
            try:
                response = input("是否自动终止旧进程并重启？(Y/n): ").strip().lower()
                if response not in ['', 'y', 'yes']:
                    print("\n已取消自动清理。")
                    logger.info("手动操作建议：")
                    if system == 'Windows':
                        logger.info("  Windows: taskkill /F /PID <进程ID>")
                    elif system == 'Linux':
                        logger.info("  Linux: kill -9 <进程ID> 或 pkill -f app.server.lifecycle")
                    elif system == 'Darwin':
                        logger.info("  macOS: kill -9 <进程ID>")
                    else:
                        logger.info("  %s: kill <进程ID>", system)
                    return False
            except (KeyboardInterrupt, EOFError):
                print("\n\n已取消操作。")
                return False

            logger.info("正在终止旧进程...")

        for pid in api_server_pids:
            if kill_process(pid):
                logger.info("已终止进程 %d", pid)
            else:
                logger.error("无法终止进程 %d", pid)

        logger.info("等待端口释放...")
        for i in range(10):
            if check_port_available(port):
                logger.info("端口已释放")
                return True
            time.sleep(0.5)

        logger.warning("端口仍未释放，请手动检查")
        return False
    else:
        logger.warning("端口 %d 被其他程序占用（PID: %s）", port, ', '.join(map(str, pids)))
        logger.info("建议操作：")
        logger.info("  1. 终止占用端口的程序")
        logger.info("  2. 使用其他端口启动：python -m app.server.lifecycle <端口号>")
        return False
