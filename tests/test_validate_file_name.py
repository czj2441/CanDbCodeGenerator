"""validate_file_name 单元测试 — 验证入口防御层。"""

import pytest
from app.ws.handlers._common import validate_file_name


class TestValidateFileName_Normal:
    """正常文件名 — 应通过验证。"""

    def test_simple_name(self):
        """1.1: 简单 ASCII 名称"""
        assert validate_file_name("test") == "test"

    def test_name_with_extension(self):
        """1.2: 含点和下划线"""
        assert validate_file_name("my_file.properties") == "my_file.properties"

    def test_chinese_name(self):
        """1.3: 中文名称（回归）"""
        assert validate_file_name("中文项目名") == "中文项目名"


class TestValidateFileName_HeaderInjection:
    """HTTP 头注入字符 — 应被新增防御拦截。"""

    def test_rejects_double_quote(self):
        """1.4: 双引号注入"""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_file_name('te"st')

    def test_rejects_cr(self):
        """1.5: CR 注入"""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_file_name("te\rst")

    def test_rejects_lf(self):
        """1.6: LF 注入"""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_file_name("te\nst")

    def test_rejects_crlf(self):
        """1.7: CRLF 注入"""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_file_name("te\r\nst")

    def test_rejects_mixed_injection(self):
        """1.8: 三种注入字符混合"""
        with pytest.raises(ValueError, match="Invalid characters"):
            validate_file_name('a"b\rc\nd')


class TestValidateFileName_ExistingChecks:
    """已有校验逻辑 — 回归确认。"""

    def test_rejects_empty_string(self):
        """1.9: 空字符串"""
        with pytest.raises(ValueError, match="Invalid file name"):
            validate_file_name("")

    def test_rejects_none(self):
        """1.10: None 输入"""
        with pytest.raises(ValueError, match="Invalid file name"):
            validate_file_name(None)

    def test_rejects_path_separator_unix(self):
        """1.11: Unix 路径分隔符"""
        with pytest.raises(ValueError, match="Path separator"):
            validate_file_name("../etc/passwd")

    def test_rejects_null_byte(self):
        """1.12: Null 字节注入"""
        with pytest.raises(ValueError, match="Null byte"):
            validate_file_name("file\x00name")
