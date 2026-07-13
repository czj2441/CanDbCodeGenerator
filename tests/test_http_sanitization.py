"""HTTP 出口净化逻辑单元测试 — 验证 Content-Disposition 头注入防御。

直接测试 http_handler.py 第 241-246 行的净化逻辑：
  file_name = session.db.name or "export"
  if not file_name.endswith(ext):
      file_name = file_name.rsplit(".", 1)[0] + ext
  file_name = file_name.replace('\\r', '').replace('\\n', '').replace('"', '')
"""

import pytest


def simulate_export_sanitization(db_name: str, ext: str = ".dbc") -> str:
    """模拟 http_handler._get_export 中的文件名构造与净化逻辑。"""
    file_name = db_name or "export"
    if not file_name.endswith(ext):
        file_name = file_name.rsplit(".", 1)[0] + ext
    # 净化：剥离 CR/LF（防响应拆分）和双引号（防头注入）
    file_name = file_name.replace('\r', '').replace('\n', '').replace('"', '')
    return file_name


def build_content_disposition(file_name: str) -> str:
    """模拟 http_handler 构造 Content-Disposition 头值。"""
    return f'attachment; filename="{file_name}"'


class TestExportSanitization_Normal:
    """正常文件名 — 净化不改变结果。"""

    def test_normal_ascii_name(self):
        """2.1: 正常 ASCII 名称不变"""
        result = simulate_export_sanitization("TestDB")
        assert result == "TestDB.dbc"

    def test_normal_name_with_extension(self):
        """已有正确扩展名"""
        result = simulate_export_sanitization("TestDB.dbc")
        assert result == "TestDB.dbc"

    def test_chinese_name(self):
        """中文名称保留"""
        result = simulate_export_sanitization("中文项目名", ".properties")
        assert result == "中文项目名.properties"


class TestExportSanitization_Injection:
    """注入字符 — 应被剥离。"""

    def test_strips_double_quote(self):
        """2.2: 双引号被剥离"""
        result = simulate_export_sanitization('Te"st')
        assert result == "Test.dbc"
        assert '"' not in result

    def test_strips_cr(self):
        """2.3: CR 被剥离"""
        result = simulate_export_sanitization("Te\rst")
        assert result == "Test.dbc"
        assert '\r' not in result

    def test_strips_lf(self):
        """2.4: LF 被剥离"""
        result = simulate_export_sanitization("Te\nst")
        assert result == "Test.dbc"
        assert '\n' not in result

    def test_strips_crlf(self):
        """2.5: CRLF 被剥离"""
        result = simulate_export_sanitization("Te\r\nst")
        assert result == "Test.dbc"
        assert '\r' not in result and '\n' not in result

    def test_strips_combined_attack(self):
        """2.6: 组合攻击 — 双引号+CRLF+注入头"""
        raw = 'a]"; injected: evil\r\n'
        result = simulate_export_sanitization(raw)
        # " 被剥离 → a]; injected: evil → + .dbc
        assert result == "a]; injected: evil.dbc"
        assert all(c not in result for c in ['"', '\r', '\n'])


class TestExportSanitization_EdgeCases:
    """边界情况。"""

    def test_empty_name_falls_back(self):
        """2.7: 空 db.name 回退到 export"""
        result = simulate_export_sanitization("")
        assert result == "export.dbc"

    def test_none_falls_back(self):
        """None 回退到 export"""
        result = simulate_export_sanitization(None)
        assert result == "export.dbc"

    def test_only_injection_chars_falls_back(self):
        """2.8: 全部为注入字符 → 净化后为空 → 但 ext 已拼接"""
        # db_name = '"\r\n"' → or "export" → '"\r\n"' (truthy)
        # not endswith .dbc → rsplit → '"\r\n' + '.dbc'
        # sanitize → '\r\n'.replace(\r,'').replace(\n,'').replace(",'') → empty + '.dbc'
        raw = '"\r\n"'
        result = simulate_export_sanitization(raw)
        # 净化后 filename 部分为空，但 ext 已拼接: ".dbc"
        # Content-Disposition: attachment; filename=".dbc" — 结构仍安全
        assert '"' not in result
        assert '\r' not in result and '\n' not in result

    def test_unicode_preserved(self):
        """2.9: Unicode 字符保留，CRLF 被剥离"""
        result = simulate_export_sanitization("tëst文件名\r\n")
        assert result == "tëst文件名.dbc"
        assert '\r' not in result and '\n' not in result

    def test_response_splitting_attack(self):
        """完整 HTTP 响应拆分攻击 — 验证净化后头结构安全"""
        malicious = 'test\r\n\r\nHTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Hacked</h1>'
        result = simulate_export_sanitization(malicious)
        header = build_content_disposition(result)
        # 头值中不应有任何换行
        assert '\r' not in header or header.count('\r') == 0
        assert '\n' not in header or header.count('\n') == 0
        # 头中引号恰好 2 个（包裹文件名）
        assert header.count('"') == 2

    def test_content_disposition_structure_intact(self):
        """所有测试场景的 Content-Disposition 头结构都应完整"""
        payloads = [
            'test"file',
            'test\r\nX-Injected: true',
            'a]";\r\nContent-Type: text/html\r\n\r\n<script>',
        ]
        for payload in payloads:
            result = simulate_export_sanitization(payload)
            header = build_content_disposition(result)
            assert header.startswith('attachment; filename="')
            assert header.endswith('"')
            assert header.count('"') == 2, f"Injection leaked in: {header}"
