"""
AuthService — 用户认证 + Token 管理 + 文件所有权。

单一服务类，覆盖用户 CRUD、Token 生命周期、文件权限侧车文件管理。
配置热重载由 watchdog 文件监听驱动。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import sys
import threading
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── 路径常量（与 file_persistence.py 同模式） ──
if getattr(sys, 'frozen', False):
    _app_data = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'CanMatrixEditor')
    CONFIG_DIR = os.path.join(_app_data, 'config')
else:
    _PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    CONFIG_DIR = os.path.join(_PROJECT_ROOT, 'config')

USERS_FILE = os.path.join(CONFIG_DIR, 'users.json')
USERS_DEFAULT_FILE = os.path.join(CONFIG_DIR, 'users.json.default')

# 与 file_persistence.DATA_DIR 保持一致
if getattr(sys, 'frozen', False):
    DATA_DIR = os.path.join(_app_data, 'data')
else:
    DATA_DIR = os.path.join(_PROJECT_ROOT, 'data')

DEFAULT_TOKEN_TTL_HOURS = 8

# ── 默认配置模板 ──
_DEFAULT_CONFIG = {
    "users": [
        {
            "username": "admin",
            "password_hash": "",  # 首次运行时填充
            "salt": "",
            "role": "admin",
            "must_change_password": True,
        }
    ],
    "token_ttl_hours": DEFAULT_TOKEN_TTL_HOURS,
}


def _hash_password(password: str, salt: str) -> str:
    """SHA-256 + salt 哈希密码。"""
    return hashlib.sha256((salt + password).encode('utf-8')).hexdigest()


def _generate_salt() -> str:
    """生成 16 字节随机 salt（hex 编码 = 32 字符）。"""
    return secrets.token_hex(16)


class AuthService:
    """用户认证 + Token 管理 + 文件所有权服务。"""

    def __init__(self):
        self._users: list[dict] = []
        self._token_ttl_hours: int = DEFAULT_TOKEN_TTL_HOURS
        self._tokens: dict[str, dict] = {}  # {token: {username, expires_at}}
        self._token_lock = threading.Lock()
        self._config_path: str = USERS_FILE
        self._watchdog_observer = None

        # 初始化配置
        self._ensure_config_exists()
        self._load_config()

    # ── 配置管理 ──

    def _ensure_config_exists(self):
        """确保 users.json 存在，不存在则生成默认模板。"""
        os.makedirs(CONFIG_DIR, exist_ok=True)
        if os.path.isfile(self._config_path):
            return

        # 生成默认 admin 密码
        salt = _generate_salt()
        password_hash = _hash_password("admin", salt)
        config = json.loads(json.dumps(_DEFAULT_CONFIG))  # deep copy
        config["users"][0]["password_hash"] = password_hash
        config["users"][0]["salt"] = salt

        # 写入默认模板
        with open(self._config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        logger.info("Generated default users.json at %s", self._config_path)

        # 同时写一份 .default 副本供参考
        if not os.path.isfile(USERS_DEFAULT_FILE):
            with open(USERS_DEFAULT_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2, ensure_ascii=False)

    def _load_config(self):
        """加载并验证配置文件，启动时验证失败则抛出异常。"""
        with open(self._config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        errors = self._validate_config(data)
        if errors:
            raise ValueError(f"users.json 配置验证失败:\n" + "\n".join(f"  - {e}" for e in errors))
        self._users = data["users"]
        self._token_ttl_hours = data.get("token_ttl_hours", DEFAULT_TOKEN_TTL_HOURS)
        logger.info("Auth config loaded: %d user(s)", len(self._users))

    def _validate_config(self, data: dict) -> list[str]:
        """验证配置 JSON schema，返回错误列表（空列表 = 验证通过）。"""
        errors = []
        if not isinstance(data, dict):
            return ["配置必须是 JSON 对象"]
        if "users" not in data or not isinstance(data["users"], list):
            return ["缺少 'users' 数组"]
        if len(data["users"]) == 0:
            errors.append("至少需要一个用户")

        admin_count = 0
        usernames = set()
        for i, u in enumerate(data.get("users", [])):
            if not isinstance(u, dict):
                errors.append(f"users[{i}] 必须是对象")
                continue
            uname = u.get("username", "")
            if not uname or not isinstance(uname, str) or not uname.strip():
                errors.append(f"users[{i}].username 不能为空")
            elif uname in usernames:
                errors.append(f"users[{i}].username '{uname}' 重复")
            else:
                usernames.add(uname)

            role = u.get("role", "")
            if role not in ("admin", "user"):
                errors.append(f"users[{i}].role 必须是 'admin' 或 'user'，当前: '{role}'")
            elif role == "admin":
                admin_count += 1

            pw_hash = u.get("password_hash", "")
            if not isinstance(pw_hash, str):
                errors.append(f"users[{i}].password_hash 格式错误")
            salt = u.get("salt", "")
            if not isinstance(salt, str):
                errors.append(f"users[{i}].salt 格式错误")

        if admin_count == 0 and not errors:
            errors.append("至少需要一个 admin 角色用户")
        return errors

    def reload_config(self) -> bool:
        """热重载配置文件。验证通过则替换内存数据返回 True，失败则维持旧配置返回 False。"""
        try:
            with open(self._config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            errors = self._validate_config(data)
            if errors:
                logger.error("users.json 热重载验证失败:\n%s",
                             "\n".join(f"  - {e}" for e in errors))
                return False
            # 原子替换
            self._users = data["users"]
            self._token_ttl_hours = data.get("token_ttl_hours", DEFAULT_TOKEN_TTL_HOURS)
            logger.info("users.json 热重载成功: %d user(s)", len(self._users))
            return True
        except Exception as e:
            logger.error("users.json 热重载失败: %s", e, exc_info=True)
            return False

    def _save_config(self):
        """将当前用户数据写回 users.json。"""
        data = {
            "users": self._users,
            "token_ttl_hours": self._token_ttl_hours,
        }
        tmp = self._config_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, self._config_path)

    # ── watchdog 热重载 ──

    def start_watchdog(self):
        """启动 watchdog 文件监听，监听 users.json 变化。"""
        try:
            from watchdog.observers import Observer
            from watchdog.events import FileSystemEventHandler

            class _ConfigHandler(FileSystemEventHandler):
                def __init__(self, auth_service: AuthService):
                    self._auth = auth_service
                    self._last_mtime = 0

                def on_modified(self, event):
                    if event.is_directory:
                        return
                    if os.path.basename(event.src_path) != 'users.json':
                        return
                    # 防抖：1 秒内不重复触发
                    now = time.time()
                    if now - self._last_mtime < 1.0:
                        return
                    self._last_mtime = now
                    logger.info("Detected users.json change, reloading...")
                    self._auth.reload_config()

            observer = Observer()
            observer.schedule(_ConfigHandler(self), CONFIG_DIR, recursive=False)
            observer.daemon = True
            observer.start()
            self._watchdog_observer = observer
            logger.info("Watchdog started: monitoring %s", CONFIG_DIR)
        except ImportError:
            logger.warning("watchdog 未安装，配置热重载不可用")
        except Exception as e:
            logger.error("Watchdog 启动失败: %s", e, exc_info=True)

    def stop_watchdog(self):
        """停止 watchdog 文件监听。"""
        if self._watchdog_observer:
            self._watchdog_observer.stop()
            self._watchdog_observer.join(timeout=3)
            self._watchdog_observer = None

    # ── 密码验证 ──

    def is_enabled(self) -> bool:
        """认证始终启用。"""
        return True

    def verify_password(self, username: str, password: str) -> dict | None:
        """验证密码，成功返回 {username, role, must_change_password}，失败返回 None。"""
        user = self._find_user(username)
        if not user:
            return None
        expected = _hash_password(password, user.get("salt", ""))
        if not hmac.compare_digest(expected, user.get("password_hash", "")):
            return None
        return {
            "username": user["username"],
            "role": user.get("role", "user"),
            "must_change_password": user.get("must_change_password", False),
        }

    def change_password(self, username: str, old_password: str, new_password: str) -> bool:
        """用户修改自己的密码。验证旧密码 → 更新 hash → 清除 must_change_password。"""
        user = self._find_user(username)
        if not user:
            return False
        expected = _hash_password(old_password, user.get("salt", ""))
        if not hmac.compare_digest(expected, user.get("password_hash", "")):
            return False
        new_salt = _generate_salt()
        user["password_hash"] = _hash_password(new_password, new_salt)
        user["salt"] = new_salt
        user["must_change_password"] = False
        self._save_config()
        # 修改密码后失效该用户所有旧 token
        self.revoke_user_tokens(username)
        return True

    def reset_user_password(self, username: str, new_password: str) -> bool:
        """管理员重置用户密码。"""
        user = self._find_user(username)
        if not user:
            return False
        new_salt = _generate_salt()
        user["password_hash"] = _hash_password(new_password, new_salt)
        user["salt"] = new_salt
        user["must_change_password"] = True
        self._save_config()
        self.revoke_user_tokens(username)
        return True

    # ── Token 管理 ──

    def create_token(self, username: str) -> str:
        """创建认证 token，存入内存 dict。"""
        token = secrets.token_hex(32)
        expires_at = time.time() + self._token_ttl_hours * 3600
        with self._token_lock:
            self._tokens[token] = {"username": username, "expires_at": expires_at}
        return token

    def validate_token(self, token: str) -> dict | None:
        """验证 token + 滑动续期。返回 {username, role} 或 None。"""
        with self._token_lock:
            entry = self._tokens.get(token)
            if not entry:
                return None
            if time.time() > entry["expires_at"]:
                del self._tokens[token]
                return None
            username = entry["username"]
            # 检查用户是否仍存在
            user = self._find_user(username)
            if not user:
                del self._tokens[token]
                return None
            # 滑动续期
            entry["expires_at"] = time.time() + self._token_ttl_hours * 3600

        return {"username": username, "role": user.get("role", "user")}

    def revoke_token(self, token: str):
        """登出：删除 token。"""
        with self._token_lock:
            self._tokens.pop(token, None)

    def revoke_user_tokens(self, username: str):
        """删除指定用户的所有 token。"""
        with self._token_lock:
            to_remove = [t for t, v in self._tokens.items() if v["username"] == username]
            for t in to_remove:
                del self._tokens[t]

    def cleanup_expired(self):
        """清理过期 token（由心跳定时器附带调用）。"""
        now = time.time()
        with self._token_lock:
            expired = [t for t, v in self._tokens.items() if now > v["expires_at"]]
            for t in expired:
                del self._tokens[t]

    # ── 用户查询 ──

    def is_admin(self, username: str) -> bool:
        """判断用户是否为 admin。"""
        user = self._find_user(username)
        return user is not None and user.get("role") == "admin"

    def user_exists(self, username: str) -> bool:
        """检查用户是否存在于用户数据库中。"""
        return self._find_user(username) is not None

    def list_users(self) -> list[dict]:
        """列出所有用户信息（不含密码 hash 和 salt）。"""
        result = []
        for u in self._users:
            result.append({
                "username": u["username"],
                "role": u.get("role", "user"),
                "must_change_password": u.get("must_change_password", False),
            })
        return result

    def count_admins(self) -> int:
        """统计当前 admin 数量。"""
        return sum(1 for u in self._users if u.get("role") == "admin")

    # ── 用户 CRUD ──

    def create_user(self, username: str, password: str, role: str = "user") -> dict:
        """创建用户，写入 users.json。自动设置 must_change_password: true。"""
        if self._find_user(username):
            raise ValueError(f"用户名 '{username}' 已存在")
        if role not in ("admin", "user"):
            raise ValueError(f"非法角色: {role}")
        salt = _generate_salt()
        user = {
            "username": username,
            "password_hash": _hash_password(password, salt),
            "salt": salt,
            "role": role,
            "must_change_password": True,
        }
        self._users.append(user)
        self._save_config()
        return {"username": username, "role": role}

    def delete_user(self, username: str, operator: str = "") -> dict:
        """删除用户。

        安全检查：
        - 用户名下有文件 → 拒绝（409）
        - 是最后一个 admin → 拒绝（409）

        Returns:
            {"success": True} 或 {"success": False, "error": ..., "files": [...]}
        """
        user = self._find_user(username)
        if not user:
            return {"success": False, "error": f"用户 '{username}' 不存在"}

        # 检查是否有文件
        user_files = self._get_user_files(username)
        if user_files:
            return {
                "success": False,
                "error": f"用户 '{username}' 名下有 {len(user_files)} 个文件，请先转移所有权",
                "files": user_files,
            }

        # 检查是否为最后一个 admin
        if user.get("role") == "admin" and self.count_admins() <= 1:
            return {
                "success": False,
                "error": "不能删除最后一个管理员",
            }

        self._users = [u for u in self._users if u["username"] != username]
        self._save_config()
        self.revoke_user_tokens(username)
        return {"success": True}

    def update_user_role(self, username: str, role: str, operator: str = "") -> dict:
        """修改用户角色。降级 admin 时检查是否为最后一个 admin。

        Returns:
            {"success": True} 或 {"success": False, "error": ...}
        """
        if role not in ("admin", "user"):
            return {"success": False, "error": f"非法角色: {role}"}
        user = self._find_user(username)
        if not user:
            return {"success": False, "error": f"用户 '{username}' 不存在"}

        # 降级 admin → 检查是否为最后一个
        if user.get("role") == "admin" and role != "admin" and self.count_admins() <= 1:
            return {"success": False, "error": "不能降级最后一个管理员"}

        user["role"] = role
        self._save_config()
        return {"success": True}

    # ── 文件权限 ──

    def get_file_permission(self, file_name: str) -> dict | None:
        """读取 data/{file_name}.perm.json 权限侧车文件。"""
        perm_path = self._perm_path(file_name)
        if not os.path.isfile(perm_path):
            return None
        try:
            with open(perm_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error("读取权限文件失败 %s: %s", perm_path, e)
            return None

    def set_file_permission(self, file_name: str, owner: str, **kwargs):
        """创建/更新权限侧车文件。"""
        perm_path = self._perm_path(file_name)
        data = {"owner": owner, "created_at": time.time()}
        data.update(kwargs)
        tmp = perm_path + ".tmp"
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, perm_path)

    def remove_file_permission(self, file_name: str):
        """删除权限侧车文件。"""
        perm_path = self._perm_path(file_name)
        try:
            os.remove(perm_path)
        except FileNotFoundError:
            pass

    def can_write(self, file_name: str, username: str) -> bool:
        """严格所有权：仅 owner 可写。无侧车文件时全员只读（含 admin）。"""
        perm = self.get_file_permission(file_name)
        if not perm:
            return False
        return perm.get("owner") == username

    def is_owner(self, file_name: str, username: str) -> bool:
        """判断用户是否为文件 owner。"""
        perm = self.get_file_permission(file_name)
        if not perm:
            return False
        return perm.get("owner") == username

    def has_user_files(self, username: str) -> bool:
        """检查用户名下是否有文件。"""
        return len(self._get_user_files(username)) > 0

    # ── 内部辅助 ──

    def _find_user(self, username: str) -> dict | None:
        """在内存用户列表中查找用户。"""
        for u in self._users:
            if u["username"] == username:
                return u
        return None

    def _perm_path(self, file_name: str) -> str:
        """计算权限侧车文件路径。"""
        return os.path.join(DATA_DIR, f"{file_name}.perm.json")

    def _get_user_files(self, username: str) -> list[str]:
        """扫描 data 目录，找出指定用户名下的文件列表。"""
        files = []
        if not os.path.isdir(DATA_DIR):
            return files
        for fname in os.listdir(DATA_DIR):
            if not fname.endswith(".perm.json"):
                continue
            perm_path = os.path.join(DATA_DIR, fname)
            try:
                with open(perm_path, 'r', encoding='utf-8') as f:
                    perm = json.load(f)
                if perm.get("owner") == username:
                    # 从侧车文件名推导数据文件名
                    data_fname = fname[:-len(".perm.json")]
                    files.append(data_fname)
            except Exception:
                continue
        return files


# ── 全局单例 ──
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """获取全局 AuthService 实例。"""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


def init_auth_service() -> AuthService:
    """初始化全局 AuthService 实例。"""
    global _auth_service
    _auth_service = AuthService()
    return _auth_service
