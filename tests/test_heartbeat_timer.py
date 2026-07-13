"""心跳定时器异常恢复 — 单元测试。

验证 _cleanup_stale_heartbeats() 在 _destroy() 或 fire_lock_released() 抛异常时
仍能正确清理其他会话并重启定时器。
"""

import threading
import unittest
from unittest.mock import MagicMock, patch


class TestHeartbeatTimerRecovery(unittest.TestCase):
    """测试心跳定时器在异常后能正确恢复。"""

    def _make_manager(self):
        """构造一个轻量级 SessionManager mock，仅保留心跳相关逻辑。"""
        from app.services.session_manager import SessionManager
        from app.services.file_persistence import HEARTBEAT_TIMEOUT

        # 不初始化完整 SessionManager（避免启动真实定时器）
        mgr = object.__new__(SessionManager)
        mgr._lock = threading.RLock()
        mgr._file_lock = MagicMock()
        mgr._undo = MagicMock()
        mgr._sessions = {}
        mgr._heartbeat_timer = None
        mgr._history_cache = {}
        mgr._data_dir = "/tmp/test"
        mgr._data_dir_real = "/tmp/test"

        # get_stale_sessions 返回空列表（由测试用例覆盖）
        mgr._file_lock.get_stale_sessions.return_value = []

        return mgr

    def test_normal_case_no_exception(self):
        """正常情况：无 stale session，定时器正常重启。"""
        mgr = self._make_manager()
        mgr._file_lock.get_stale_sessions.return_value = []

        # 用 mock 跟踪 _start_heartbeat_checker 调用
        with patch.object(mgr, '_start_heartbeat_checker') as mock_start:
            mgr._cleanup_stale_heartbeats()
            mock_start.assert_called_once()

    def test_destroy_exception_timer_still_restarts(self):
        """_destroy() 抛异常时，定时器仍重启。"""
        mgr = self._make_manager()
        stale_sid = "stale-session-id-12345678"
        mgr._file_lock.get_stale_sessions.return_value = [stale_sid]

        # 让 _destroy 抛异常
        with patch.object(mgr, '_destroy', side_effect=RuntimeError("destroy failed")):
            with patch.object(mgr, '_start_heartbeat_checker') as mock_start:
                # 不应抛出
                mgr._cleanup_stale_heartbeats()
                # 定时器应重启
                mock_start.assert_called_once()

    def test_destroy_exception_other_sessions_still_cleaned(self):
        """多个 stale session 中一个 _destroy 失败，其余仍被清理。"""
        mgr = self._make_manager()
        sid_fail = "fail-session-00000001"
        sid_ok1 = "ok-session-0000000001"
        sid_ok2 = "ok-session-0000000002"
        mgr._file_lock.get_stale_sessions.return_value = [sid_fail, sid_ok1, sid_ok2]

        destroy_calls = []

        def mock_destroy(sid):
            destroy_calls.append(sid)
            if sid == sid_fail:
                raise RuntimeError("destroy failed for this session")

        with patch.object(mgr, '_destroy', side_effect=mock_destroy):
            with patch.object(mgr, '_start_heartbeat_checker') as mock_start:
                mgr._cleanup_stale_heartbeats()

                # 三个 session 的 _destroy 都应被调用
                self.assertEqual(destroy_calls, [sid_fail, sid_ok1, sid_ok2])
                # fire_lock_released 只为成功的 session 调用
                self.assertEqual(mgr._file_lock.fire_lock_released.call_count, 2)
                # 定时器应重启
                mock_start.assert_called_once()

    def test_fire_lock_released_exception_timer_still_restarts(self):
        """fire_lock_released() 抛异常时，定时器仍重启。"""
        mgr = self._make_manager()
        stale_sid = "stale-session-id-99999999"
        mgr._file_lock.get_stale_sessions.return_value = [stale_sid]

        # _destroy 正常，fire_lock_released 抛异常
        with patch.object(mgr, '_destroy', return_value=True):
            mgr._file_lock.fire_lock_released.side_effect = RuntimeError("callback failed")
            with patch.object(mgr, '_start_heartbeat_checker') as mock_start:
                # 不应抛出
                mgr._cleanup_stale_heartbeats()
                # 定时器应重启
                mock_start.assert_called_once()

    def test_multiple_stale_sessions_all_cleaned(self):
        """多个 stale session 全部正常清理。"""
        mgr = self._make_manager()
        sids = ["session-001", "session-002", "session-003"]
        mgr._file_lock.get_stale_sessions.return_value = sids

        with patch.object(mgr, '_destroy', return_value=True) as mock_destroy:
            with patch.object(mgr, '_start_heartbeat_checker') as mock_start:
                mgr._cleanup_stale_heartbeats()

                # 每个 session 都应调用 _destroy
                self.assertEqual(mock_destroy.call_count, 3)
                # 每个 session 都应调用 fire_lock_released
                self.assertEqual(mgr._file_lock.fire_lock_released.call_count, 3)
                # 定时器应重启
                mock_start.assert_called_once()

    def test_error_is_logged_not_silent(self):
        """异常被捕获且有日志输出（不静默吞掉）。"""
        mgr = self._make_manager()
        stale_sid = "stale-session-abcdef123456"
        mgr._file_lock.get_stale_sessions.return_value = [stale_sid]

        with patch.object(mgr, '_destroy', side_effect=ValueError("test error")):
            with patch.object(mgr, '_start_heartbeat_checker'):
                # 捕获 print 输出
                with patch('builtins.print') as mock_print:
                    mgr._cleanup_stale_heartbeats()
                    # 应有 print 输出包含错误信息
                    mock_print.assert_called_once()
                    log_msg = mock_print.call_args[0][0]
                    self.assertIn("[SessionManager]", log_msg)
                    self.assertIn("ERROR", log_msg)
                    # sid[:8] 截断
                    self.assertIn("stale-se", log_msg)
                    self.assertIn("test error", log_msg)


class TestHeartbeatTimerIntegration(unittest.TestCase):
    """集成测试：验证定时器真实重启机制。"""

    def test_timer_actually_restarts_after_exception(self):
        """验证 _start_heartbeat_checker 真实创建并启动新定时器。"""
        from app.services.session_manager import SessionManager

        mgr = object.__new__(SessionManager)
        mgr._lock = threading.RLock()
        mgr._file_lock = MagicMock()
        mgr._undo = MagicMock()
        mgr._sessions = {}
        mgr._heartbeat_timer = None
        mgr._history_cache = {}
        mgr._data_dir = "/tmp/test"
        mgr._data_dir_real = "/tmp/test"
        mgr._file_lock.get_stale_sessions.return_value = []

        # 先确认没有定时器
        self.assertIsNone(mgr._heartbeat_timer)

        # 调用 cleanup（会调用 _start_heartbeat_checker）
        mgr._cleanup_stale_heartbeats()

        # 应创建新定时器
        self.assertIsNotNone(mgr._heartbeat_timer)
        self.assertTrue(mgr._heartbeat_timer.is_alive())

        # 清理：取消定时器避免测试泄漏
        mgr._heartbeat_timer.cancel()

    def test_timer_restarts_even_with_destroy_exception(self):
        """_destroy 抛异常后，真实定时器仍被创建。"""
        from app.services.session_manager import SessionManager

        mgr = object.__new__(SessionManager)
        mgr._lock = threading.RLock()
        mgr._file_lock = MagicMock()
        mgr._undo = MagicMock()
        mgr._sessions = {}
        mgr._heartbeat_timer = None
        mgr._history_cache = {}
        mgr._data_dir = "/tmp/test"
        mgr._data_dir_real = "/tmp/test"
        mgr._file_lock.get_stale_sessions.return_value = ["bad-session-id"]

        # 让 _destroy 抛异常
        mgr._destroy = MagicMock(side_effect=RuntimeError("boom"))

        # 调用 cleanup
        mgr._cleanup_stale_heartbeats()

        # 定时器应被创建
        self.assertIsNotNone(mgr._heartbeat_timer)
        self.assertTrue(mgr._heartbeat_timer.is_alive())

        # 清理
        mgr._heartbeat_timer.cancel()


if __name__ == "__main__":
    unittest.main()
