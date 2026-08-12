"""app.auth — 用户认证与数据隔离服务。"""

from .service import AuthService, get_auth_service, init_auth_service

__all__ = ['AuthService', 'get_auth_service', 'init_auth_service']
