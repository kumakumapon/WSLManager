"""
単体テスト for wsl_core.py

実行方法 (リポジトリルートから):
    python3 -m unittest discover -s tests -v
"""

import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import unittest
from typing import ClassVar
from unittest import mock

# リポジトリルートを sys.path の先頭に挿入して wsl_core をインポートできるようにする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wsl_core

# ---------------------------------------------------------------------------
# decode_wsl_output
# ---------------------------------------------------------------------------

class TestDecodeWslOutput(unittest.TestCase):

    def test_bom_utf16le(self):
        """BOM (FF FE) 付き UTF-16LE バイト列を正しくデコードする。"""
        raw = b"\xff\xfe" + "Ubuntu".encode("utf-16-le")
        self.assertEqual(wsl_core.decode_wsl_output(raw), "Ubuntu")

    def test_bom_utf16le_japanese(self):
        """BOM 付き UTF-16LE で日本語文字列をデコードする。"""
        raw = b"\xff\xfe" + "テスト".encode("utf-16-le")
        self.assertEqual(wsl_core.decode_wsl_output(raw), "テスト")

    def test_bom_utf16le_multiline(self):
        """BOM 付き UTF-16LE で複数行テキストをデコードする。"""
        text = "  NAME   STATE   VERSION\n* Ubuntu  Running  2\n"
        raw = b"\xff\xfe" + text.encode("utf-16-le")
        self.assertEqual(wsl_core.decode_wsl_output(raw), text)

    def test_no_bom_utf16le(self):
        """BOM なし UTF-16LE バイト列 ('Ubuntu' = 6 バイト、偶数長) を正しくデコードする。"""
        raw = "Ubuntu".encode("utf-16-le")  # b'U\x00b\x00u\x00n\x00t\x00u\x00'
        self.assertEqual(wsl_core.decode_wsl_output(raw), "Ubuntu")

    def test_no_bom_utf16le_with_spaces(self):
        """BOM なし UTF-16LE で空白を含む偶数長文字列をデコードする。"""
        text = "Hello World"  # 11 chars -> 22 bytes (偶数)
        raw = text.encode("utf-16-le")
        self.assertEqual(wsl_core.decode_wsl_output(raw), text)

    def test_utf8_fallback_odd_length(self):
        """奇数バイト長の UTF-8 文字列は utf-16-le strict で失敗し UTF-8 フォールバックを使う。"""
        # b'hello' は 5 バイト (奇数) なので utf-16-le strict で UnicodeDecodeError が発生する
        raw = b"hello"
        self.assertEqual(wsl_core.decode_wsl_output(raw), "hello")

    def test_utf8_fallback_three_bytes(self):
        """3 バイトの UTF-8 文字列でも UTF-8 フォールバックが機能する。"""
        raw = b"abc"
        self.assertEqual(wsl_core.decode_wsl_output(raw), "abc")

    def test_utf8_fallback_newline_odd(self):
        """改行を含む奇数長 UTF-8 文字列でフォールバックが機能する。"""
        raw = b"foo\nbar"  # 7 バイト (奇数)
        self.assertEqual(wsl_core.decode_wsl_output(raw), "foo\nbar")

    def test_empty_bytes(self):
        """空バイト列は空文字列を返す (utf-8 フォールバック)。"""
        self.assertEqual(wsl_core.decode_wsl_output(b""), "")

    def test_even_length_ascii_utf8_not_misdetected(self):
        """偶数長の ASCII (UTF-8) バイト列を UTF-16 と誤判定せずそのまま返す。"""
        # 6 バイト (偶数) だが NUL バイトを含まないため UTF-8 として扱う。
        # 旧実装では utf-16-le デコードが「成功」して CJK の文字化けになっていた。
        self.assertEqual(wsl_core.decode_wsl_output(b"hello!"), "hello!")

    def test_even_length_utf8_multiline_not_misdetected(self):
        """wsl -d <name> -- <cmd> 相当の偶数長 UTF-8 出力が文字化けしない。"""
        raw = b"PID USER\n123 root\n"  # 18 バイト (偶数)、NUL なし
        self.assertEqual(wsl_core.decode_wsl_output(raw), "PID USER\n123 root\n")

    def test_even_length_utf8_japanese_not_misdetected(self):
        """偶数長の日本語 UTF-8 バイト列を UTF-8 としてデコードする。"""
        raw = "テスト\n".encode()  # 10 バイト (偶数)、NUL なし
        self.assertEqual(wsl_core.decode_wsl_output(raw), "テスト\n")

    def test_no_bom_utf16le_japanese_with_newline(self):
        """BOM なし UTF-16LE の日本語+改行 (NUL バイトを含む) を正しくデコードする。"""
        raw = "テスト 実行中\n".encode("utf-16-le")
        self.assertEqual(wsl_core.decode_wsl_output(raw), "テスト 実行中\n")

    def test_cp932_fallback(self):
        """UTF-8 として不正で NUL バイトを含まない cp932 バイト列を正しくデコードする。

        errors="replace" は例外を送出しないため、"utf-8" を errors="replace" で
        試すと必ず 1 周目で return してしまい cp932 に進めなくなる (#24)。
        errors="strict" で失敗を検知してフォールバックすることを確認する。
        """
        raw = "テスト日本語".encode("cp932")
        self.assertEqual(wsl_core.decode_wsl_output(raw), "テスト日本語")

    def test_cp932_fallback_odd_length(self):
        """奇数バイト長の cp932 文字列でもフォールバックが機能する。"""
        raw = "あ".encode("cp932")  # 2 バイト (偶数、NUL なし) の単純ケースに加え
        raw += b"a"  # 末尾に ASCII を足して奇数長にする
        self.assertEqual(wsl_core.decode_wsl_output(raw), "あa")

    def test_invalid_bytes_fallback_latin1(self):
        """utf-8 / cp932 のどちらでもデコードできないバイト列は latin-1 で必ず何か返す。"""
        raw = b"\x81\xff"  # cp932 として不正 (0xFF は cp932 の未定義バイト)
        result = wsl_core.decode_wsl_output(raw)
        self.assertEqual(result, raw.decode("latin-1"))


# ---------------------------------------------------------------------------
# is_numeric
# ---------------------------------------------------------------------------

class TestIsNumeric(unittest.TestCase):

    def test_float_string(self):
        self.assertTrue(wsl_core.is_numeric("3.5"))

    def test_integer_string(self):
        self.assertTrue(wsl_core.is_numeric("12"))

    def test_negative_float(self):
        self.assertTrue(wsl_core.is_numeric("-1.5"))

    def test_zero(self):
        self.assertTrue(wsl_core.is_numeric("0"))

    def test_dash(self):
        self.assertFalse(wsl_core.is_numeric("-"))

    def test_empty_string(self):
        self.assertFalse(wsl_core.is_numeric(""))

    def test_alpha(self):
        self.assertFalse(wsl_core.is_numeric("abc"))

    def test_mixed_alphanum(self):
        self.assertFalse(wsl_core.is_numeric("4GB"))

    def test_none(self):
        """None は TypeError → False を返す。"""
        self.assertFalse(wsl_core.is_numeric(None))

    def test_space(self):
        self.assertFalse(wsl_core.is_numeric(" "))


# ---------------------------------------------------------------------------
# normalize_base_path
# ---------------------------------------------------------------------------

class TestNormalizeBasePath(unittest.TestCase):

    def test_strip_prefix(self):
        """\\\\?\\ プレフィックスを除去する。"""
        self.assertEqual(wsl_core.normalize_base_path(r"\\?\C:\foo"), r"C:\foo")

    def test_no_prefix_unchanged(self):
        """プレフィックスがない場合は変化しない。"""
        self.assertEqual(wsl_core.normalize_base_path(r"C:\foo"), r"C:\foo")

    def test_strip_prefix_deep_path(self):
        """深いパスでもプレフィックスのみ除去する。"""
        self.assertEqual(
            wsl_core.normalize_base_path(r"\\?\D:\Users\user\AppData\Local\Packages\Ubuntu"),
            r"D:\Users\user\AppData\Local\Packages\Ubuntu",
        )

    def test_empty_string(self):
        """空文字はそのまま返す。"""
        self.assertEqual(wsl_core.normalize_base_path(""), "")

    def test_already_normal(self):
        """通常の UNC パスは変化しない (先頭4文字が \\\\?\\ でない)。"""
        path = r"\\server\share"
        self.assertEqual(wsl_core.normalize_base_path(path), path)


# ---------------------------------------------------------------------------
# parse_distro_list
# ---------------------------------------------------------------------------

class TestParseDistroList(unittest.TestCase):

    # 典型的な wsl --list --verbose 出力
    TYPICAL_OUTPUT = (
        "  NAME      STATE           VERSION\n"
        "* Ubuntu    Running         2\n"
        "  Debian    Stopped         2\n"
    )

    def _parse(self, text):
        return wsl_core.parse_distro_list(text)

    def test_count(self):
        """2 ディストロを正しく検出する。"""
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertEqual(len(result), 2)

    def test_default_distro(self):
        """'*' 付きの行が default=True になる。"""
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertTrue(result[0]["default"])

    def test_non_default_distro(self):
        """'*' なしの行が default=False になる。"""
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertFalse(result[1]["default"])

    def test_name_extraction(self):
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertEqual(result[0]["name"], "Ubuntu")
        self.assertEqual(result[1]["name"], "Debian")

    def test_state_extraction(self):
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertEqual(result[0]["state"], "Running")
        self.assertEqual(result[1]["state"], "Stopped")

    def test_version_extraction(self):
        result = self._parse(self.TYPICAL_OUTPUT)
        self.assertEqual(result[0]["version"], "2")
        self.assertEqual(result[1]["version"], "2")

    def test_cpu_memory_disk_placeholder(self):
        """cpu / memory / disk / ip は '-' で初期化される。"""
        result = self._parse(self.TYPICAL_OUTPUT)
        for d in result:
            self.assertEqual(d["cpu"], "-")
            self.assertEqual(d["memory"], "-")
            self.assertEqual(d["disk"], "-")
            self.assertEqual(d["ip"], "-")

    def test_empty_lines_ignored(self):
        """空行が混在しても正しく解析される。"""
        output_with_blanks = (
            "  NAME      STATE           VERSION\n"
            "\n"
            "* Ubuntu    Running         2\n"
            "\n"
            "  Debian    Stopped         2\n"
            "\n"
        )
        result = self._parse(output_with_blanks)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["name"], "Ubuntu")
        self.assertEqual(result[1]["name"], "Debian")

    def test_header_line_skipped(self):
        """先頭のヘッダ行はスキップされる。"""
        result = self._parse(self.TYPICAL_OUTPUT)
        names = [d["name"] for d in result]
        self.assertNotIn("NAME", names)

    def test_empty_string(self):
        """空文字列は空リストを返す。"""
        self.assertEqual(self._parse(""), [])

    def test_only_header(self):
        """ヘッダ行だけの場合は空リストを返す。"""
        self.assertEqual(self._parse("  NAME      STATE           VERSION\n"), [])


# ---------------------------------------------------------------------------
# parse_online_distros
# ---------------------------------------------------------------------------

class TestParseOnlineDistros(unittest.TestCase):

    TYPICAL_OUTPUT = (
        "NAME                                   FRIENDLY NAME\n"
        "Ubuntu                                 Ubuntu\n"
        "Debian                                 Debian GNU/Linux\n"
        "kali-linux                             Kali Linux Rolling\n"
    )

    def test_names_extracted(self):
        result = wsl_core.parse_online_distros(self.TYPICAL_OUTPUT)
        self.assertEqual(result, ["Ubuntu", "Debian", "kali-linux"])

    def test_header_name_line_skipped(self):
        """'NAME' で始まる行はスキップされる。"""
        result = wsl_core.parse_online_distros(self.TYPICAL_OUTPUT)
        self.assertNotIn("NAME", result)

    def test_separator_line_skipped(self):
        """'---' で始まる区切り行はスキップされる。"""
        output_with_sep = (
            "NAME                                   FRIENDLY NAME\n"
            "------                                 --------------\n"
            "Ubuntu                                 Ubuntu\n"
            "Debian                                 Debian GNU/Linux\n"
        )
        result = wsl_core.parse_online_distros(output_with_sep)
        self.assertEqual(result, ["Ubuntu", "Debian"])

    def test_empty_lines_skipped(self):
        """空行はスキップされる。"""
        output_with_blanks = (
            "NAME                                   FRIENDLY NAME\n"
            "\n"
            "Ubuntu                                 Ubuntu\n"
            "\n"
            "Debian                                 Debian GNU/Linux\n"
        )
        result = wsl_core.parse_online_distros(output_with_blanks)
        self.assertEqual(result, ["Ubuntu", "Debian"])

    def test_only_first_field_collected(self):
        """フレンドリー名は収集せず、先頭フィールドのみ返す。"""
        result = wsl_core.parse_online_distros(self.TYPICAL_OUTPUT)
        # "Debian GNU/Linux" や "Kali Linux Rolling" が混入していないこと
        self.assertNotIn("Debian GNU/Linux", result)
        self.assertNotIn("Kali Linux Rolling", result)

    def test_empty_string(self):
        self.assertEqual(wsl_core.parse_online_distros(""), [])


# ---------------------------------------------------------------------------
# parse_process_list
# ---------------------------------------------------------------------------

class TestParseProcessList(unittest.TestCase):

    TYPICAL_OUTPUT = (
        "PID USER     %CPU   RSS COMMAND\n"
        "  1 root      0.0  1024 /sbin/init\n"
        " 42 user1     1.5  2048 python3 /path/to/script.py\n"
    )

    def test_count(self):
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        self.assertEqual(len(result), 2)

    def test_pid_is_int(self):
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        self.assertIsInstance(result[0]["pid"], int)
        self.assertEqual(result[0]["pid"], 1)
        self.assertEqual(result[1]["pid"], 42)

    def test_user_field(self):
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        self.assertEqual(result[0]["user"], "root")
        self.assertEqual(result[1]["user"], "user1")

    def test_cpu_format(self):
        """cpu は '.1f' フォーマットの文字列。"""
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        self.assertEqual(result[0]["cpu"], "0.0")
        self.assertEqual(result[1]["cpu"], "1.5")

    def test_memory_format_kb_to_mb(self):
        """memory は RSS(KB) / 1024 を '.1f' フォーマットした文字列。"""
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        # 1024 KB / 1024 = 1.0 MB
        self.assertEqual(result[0]["memory"], "1.0")
        # 2048 KB / 1024 = 2.0 MB
        self.assertEqual(result[1]["memory"], "2.0")

    def test_command_with_spaces(self):
        """空白を含むコマンドが 5 番目フィールドにまとめられる。"""
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        self.assertEqual(result[1]["command"], "python3 /path/to/script.py")

    def test_header_skipped(self):
        """ヘッダ行はスキップされる。"""
        result = wsl_core.parse_process_list(self.TYPICAL_OUTPUT)
        pids = [p["pid"] for p in result]
        # ヘッダが pid として解釈されていないことを確認
        self.assertNotIn("PID", [str(p) for p in pids])

    def test_short_field_line_skipped(self):
        """フィールド不足行 (5 未満) はスキップされる。"""
        output = (
            "PID USER     %CPU   RSS COMMAND\n"
            "  1 root      0.0  1024 /sbin/init\n"
            "  2 root\n"  # フィールド不足
        )
        result = wsl_core.parse_process_list(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pid"], 1)

    def test_non_numeric_field_skipped(self):
        """数値変換不能な行はスキップされる。"""
        output = (
            "PID USER     %CPU   RSS COMMAND\n"
            "  1 root      0.0  1024 /sbin/init\n"
            "  3 root      abc  1024 bad_cpu\n"  # cpu が非数値
        )
        result = wsl_core.parse_process_list(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["pid"], 1)

    def test_empty_string(self):
        self.assertEqual(wsl_core.parse_process_list(""), [])

    def test_only_header(self):
        self.assertEqual(wsl_core.parse_process_list("PID USER %CPU RSS COMMAND\n"), [])


# ---------------------------------------------------------------------------
# parse_resource_usage
# ---------------------------------------------------------------------------

class TestParseResourceUsage(unittest.TestCase):

    def test_normal(self):
        """正常な '12.3 456.7' を (cpu, memory) に変換する。"""
        cpu, mem = wsl_core.parse_resource_usage("12.3 456.7")
        self.assertEqual(cpu, "12.3")
        self.assertEqual(mem, "456.7")

    def test_integer_values(self):
        """整数値も '.1f' フォーマットで返す。"""
        cpu, mem = wsl_core.parse_resource_usage("5 100")
        self.assertEqual(cpu, "5.0")
        self.assertEqual(mem, "100.0")

    def test_single_value_returns_dash(self):
        """要素が 1 つだけの場合は ('-', '-') を返す。"""
        self.assertEqual(wsl_core.parse_resource_usage("5"), ("-", "-"))

    def test_empty_string_returns_dash(self):
        """空文字列は ('-', '-') を返す。"""
        self.assertEqual(wsl_core.parse_resource_usage(""), ("-", "-"))

    def test_non_numeric_returns_dash(self):
        """数値変換不能な場合は ('-', '-') を返す。"""
        self.assertEqual(wsl_core.parse_resource_usage("x y"), ("-", "-"))

    def test_first_non_numeric(self):
        """最初の値が非数値の場合も ('-', '-') を返す。"""
        self.assertEqual(wsl_core.parse_resource_usage("abc 1.0"), ("-", "-"))

    def test_extra_whitespace(self):
        """余分な空白があっても正しく解析される。"""
        cpu, mem = wsl_core.parse_resource_usage("  3.0   9.5  ")
        self.assertEqual(cpu, "3.0")
        self.assertEqual(mem, "9.5")

    def test_returns_tuple(self):
        """戻り値が tuple であることを確認。"""
        result = wsl_core.parse_resource_usage("1.0 2.0")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)


# ---------------------------------------------------------------------------
# parse_wslconfig
# ---------------------------------------------------------------------------

class TestParseWslconfig(unittest.TestCase):

    def test_basic_parse(self):
        """基本的な INI テキストをパースする。"""
        text = "[wsl2]\nmemory=4GB\nlocalhostForwarding=true\n"
        result = wsl_core.parse_wslconfig(text)
        self.assertEqual(result, {"wsl2": {"memory": "4GB", "localhostForwarding": "true"}})

    def test_camelcase_keys_preserved(self):
        """camelCase キーが小文字化されず保持される。"""
        text = "[wsl2]\nlocalhostForwarding=true\nguiApplications=false\n"
        result = wsl_core.parse_wslconfig(text)
        self.assertIn("localhostForwarding", result["wsl2"])
        self.assertNotIn("localhostforwarding", result["wsl2"])
        self.assertIn("guiApplications", result["wsl2"])
        self.assertNotIn("guiapplications", result["wsl2"])

    def test_empty_string_returns_empty_dict(self):
        """空文字列は {} を返す。"""
        self.assertEqual(wsl_core.parse_wslconfig(""), {})

    def test_none_returns_empty_dict(self):
        """None は {} を返す。"""
        self.assertEqual(wsl_core.parse_wslconfig(None), {})

    def test_multiple_sections(self):
        """複数セクションを正しくパースする。"""
        text = (
            "[wsl2]\n"
            "memory=4GB\n"
            "[network]\n"
            "generateResolvConf=false\n"
        )
        result = wsl_core.parse_wslconfig(text)
        self.assertIn("wsl2", result)
        self.assertIn("network", result)
        self.assertEqual(result["wsl2"]["memory"], "4GB")
        self.assertEqual(result["network"]["generateResolvConf"], "false")

    def test_values_as_strings(self):
        """値は常に文字列として返す。"""
        text = "[wsl2]\nprocessors=4\n"
        result = wsl_core.parse_wslconfig(text)
        self.assertIsInstance(result["wsl2"]["processors"], str)
        self.assertEqual(result["wsl2"]["processors"], "4")

    def test_parse_wslconfig_raises_on_malformed_input(self):
        """セクションヘッダーが閉じられていない不正な入力は WslConfigParseError を送出する。"""
        text = "[section\nkey=val"
        with self.assertRaises(wsl_core.WslConfigParseError):
            wsl_core.parse_wslconfig(text)

    def test_parse_wslconfig_empty_string_returns_empty_dict(self):
        """空文字列は例外を送出せず {} を返す（回帰確認）。"""
        self.assertEqual(wsl_core.parse_wslconfig(""), {})


# ---------------------------------------------------------------------------
# dump_wslconfig
# ---------------------------------------------------------------------------

class TestDumpWslconfig(unittest.TestCase):

    def test_round_trip(self):
        """parse → dump → parse でデータが保持される (camelCase 含む)。"""
        original = "[wsl2]\nmemory=4GB\nlocalhostForwarding=true\n"
        parsed = wsl_core.parse_wslconfig(original)
        dumped = wsl_core.dump_wslconfig(parsed)
        reparsed = wsl_core.parse_wslconfig(dumped)
        self.assertEqual(parsed, reparsed)

    def test_camelcase_preserved_in_round_trip(self):
        """ラウンドトリップで camelCase キーが保持される。"""
        original = "[wsl2]\nlocalhostForwarding=true\nguiApplications=false\n"
        parsed = wsl_core.parse_wslconfig(original)
        dumped = wsl_core.dump_wslconfig(parsed)
        self.assertIn("localhostForwarding", dumped)
        self.assertNotIn("localhostforwarding", dumped)

    def test_empty_value_key_excluded(self):
        """値が空文字のキーは出力されない。"""
        sections = {"wsl2": {"memory": "4GB", "swap": "", "localhostForwarding": "true"}}
        dumped = wsl_core.dump_wslconfig(sections)
        self.assertNotIn("swap", dumped)
        self.assertIn("memory", dumped)
        self.assertIn("localhostForwarding", dumped)

    def test_all_empty_section_excluded(self):
        """セクション内のキーが全て空文字の場合、そのセクション見出しも出力されない。"""
        sections = {
            "wsl2": {"memory": "", "swap": ""},
            "network": {"generateResolvConf": "true"},
        }
        dumped = wsl_core.dump_wslconfig(sections)
        self.assertNotIn("[wsl2]", dumped)
        self.assertIn("[network]", dumped)

    def test_ends_with_single_newline(self):
        """出力が改行1つで終わる (末尾に余分な空行がない)。"""
        sections = {"wsl2": {"memory": "4GB"}}
        dumped = wsl_core.dump_wslconfig(sections)
        self.assertTrue(dumped.endswith("\n"))
        self.assertFalse(dumped.endswith("\n\n"))

    def test_empty_sections_returns_empty_string_or_newline(self):
        """空の sections dict は空文字列か改行1つを返す (セクション出力なし)。"""
        dumped = wsl_core.dump_wslconfig({})
        # セクションが1つも出力されないことを確認
        self.assertNotIn("[", dumped)

    def test_section_format(self):
        """セクション見出しが正しいフォーマット '[section]' で出力される。"""
        sections = {"wsl2": {"memory": "8GB"}}
        dumped = wsl_core.dump_wslconfig(sections)
        self.assertIn("[wsl2]", dumped)

    def test_multiple_sections_round_trip(self):
        """複数セクションのラウンドトリップ。"""
        original = {
            "wsl2": {"memory": "4GB", "processors": "2"},
            "network": {"generateResolvConf": "false"},
        }
        dumped = wsl_core.dump_wslconfig(original)
        reparsed = wsl_core.parse_wslconfig(dumped)
        self.assertEqual(original, reparsed)


# ---------------------------------------------------------------------------


class TestBuildDiskpartCompactScript(unittest.TestCase):
    """build_diskpart_compact_script のテスト。"""

    def test_contains_required_commands(self):
        """select/attach/compact/detach/exit が順に含まれる。"""
        script = wsl_core.build_diskpart_compact_script(r"C:\wsl\ext4.vhdx")
        for cmd in ("select vdisk", "attach vdisk readonly", "compact vdisk",
                    "detach vdisk", "exit"):
            self.assertIn(cmd, script)

    def test_path_is_quoted(self):
        """空白を含むパスがダブルクォートで囲まれる。"""
        path = r"C:\Program Files\wsl\ext4.vhdx"
        script = wsl_core.build_diskpart_compact_script(path)
        self.assertIn(f'file="{path}"', script)

    def test_ends_with_newline(self):
        """各行が改行区切りで末尾も改行。"""
        script = wsl_core.build_diskpart_compact_script(r"C:\a.vhdx")
        self.assertTrue(script.endswith("\n"))


# ---------------------------------------------------------------------------
# parse_wsl_version
# ---------------------------------------------------------------------------

class TestParseWslVersion(unittest.TestCase):

    JAPANESE_OUTPUT = (
        "WSL バージョン: 2.4.4.0\n"
        "カーネル バージョン: 5.15.167.4-1\n"
        "WSLg バージョン: 1.0.65\n"
        "MSRDC バージョン: 1.2.5620\n"
        "Direct3D バージョン: 1.611.1-81528511\n"
        "DXCore バージョン: 10.0.26100.1-240331-1435.ge-release\n"
        "Windows バージョン: 10.0.22631.4890\n"
    )

    ENGLISH_OUTPUT = (
        "WSL version: 2.4.4.0\n"
        "Kernel version: 5.15.167.4-1\n"
        "WSLg version: 1.0.65\n"
        "MSRDC version: 1.2.5620\n"
        "Direct3D version: 1.611.1-81528511\n"
        "DXCore version: 10.0.26100.1-240331-1435.ge-release\n"
        "Windows version: 10.0.22631.4890\n"
    )

    EXPECTED: ClassVar[dict[str, str]] = {
        "wsl": "2.4.4.0",
        "kernel": "5.15.167.4-1",
        "wslg": "1.0.65",
        "msrdc": "1.2.5620",
        "direct3d": "1.611.1-81528511",
        "dxcore": "10.0.26100.1-240331-1435.ge-release",
        "windows": "10.0.22631.4890",
    }

    def test_japanese_output_all_keys(self):
        """日本語出力から全7キーを正しく抽出する。"""
        result = wsl_core.parse_wsl_version(self.JAPANESE_OUTPUT)
        self.assertEqual(result, self.EXPECTED)

    def test_english_output_all_keys(self):
        """英語出力から全7キーを正しく抽出する。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertEqual(result, self.EXPECTED)

    def test_wsl_key_not_confused_with_wslg(self):
        """「WSL」キーと「WSLg」キーが混同されない。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertEqual(result["wsl"], "2.4.4.0")
        self.assertEqual(result["wslg"], "1.0.65")

    def test_kernel_japanese(self):
        """日本語の「カーネル」が kernel キーにマップされる。"""
        result = wsl_core.parse_wsl_version(self.JAPANESE_OUTPUT)
        self.assertEqual(result["kernel"], "5.15.167.4-1")

    def test_kernel_english(self):
        """英語の「Kernel」が kernel キーにマップされる。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertEqual(result["kernel"], "5.15.167.4-1")

    def test_dxcore_version_with_dots_and_hyphens(self):
        """DXCore バージョン文字列 (点・ハイフン含む) が正確に取得される。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertEqual(result["dxcore"], "10.0.26100.1-240331-1435.ge-release")

    def test_empty_string_returns_empty_dict(self):
        """空文字列は {} を返す。"""
        self.assertEqual(wsl_core.parse_wsl_version(""), {})

    def test_none_returns_empty_dict(self):
        """None は {} を返す。"""
        self.assertEqual(wsl_core.parse_wsl_version(None), {})

    def test_unknown_line_collected_in_unparsed_lines(self):
        """既知パターンに一致しない ``:`` 付きの行は _unparsed_lines に集約される。"""
        output = self.ENGLISH_OUTPUT + "SomeUnknownField: some value\n"
        result = wsl_core.parse_wsl_version(output)
        self.assertIn("_unparsed_lines", result)
        self.assertIn("SomeUnknownField: some value", result["_unparsed_lines"])

    def test_line_without_colon_collected_in_unparsed_lines(self):
        """``:`` を含まない非空行も _unparsed_lines に集約される。"""
        output = self.ENGLISH_OUTPUT + "no colon in this line\n"
        result = wsl_core.parse_wsl_version(output)
        self.assertIn("_unparsed_lines", result)
        self.assertIn("no colon in this line", result["_unparsed_lines"])

    def test_no_unparsed_lines_key_absent_when_all_known(self):
        """未知行が1件もない場合は _unparsed_lines キーが結果に含まれない。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertNotIn("_unparsed_lines", result)

    def test_partial_output_missing_wslg(self):
        """WSLg 行がない部分的な出力では wslg キーが含まれない。"""
        partial = (
            "WSL version: 2.4.4.0\n"
            "Kernel version: 5.15.167.4-1\n"
            "Windows version: 10.0.22631.4890\n"
        )
        result = wsl_core.parse_wsl_version(partial)
        self.assertIn("wsl", result)
        self.assertIn("kernel", result)
        self.assertIn("windows", result)
        self.assertNotIn("wslg", result)
        self.assertNotIn("msrdc", result)

    def test_line_without_colon_skipped(self):
        """コロンを含まない行は既知キーとしては解析されず _unparsed_lines に集約される。"""
        output = (
            "WSL version: 2.4.4.0\n"
            "this line has no colon\n"
            "Kernel version: 5.15.167.4-1\n"
        )
        result = wsl_core.parse_wsl_version(output)
        self.assertEqual(result["wsl"], "2.4.4.0")
        self.assertEqual(result["kernel"], "5.15.167.4-1")
        self.assertEqual(result["_unparsed_lines"], ["this line has no colon"])
        self.assertEqual(len(result), 3)

    def test_unrecognized_line_skipped(self):
        """パターンに一致しない行は既知キーとしては解析されず _unparsed_lines に集約される。"""
        output = (
            "WSL version: 2.4.4.0\n"
            "Unknown field: somevalue\n"
        )
        result = wsl_core.parse_wsl_version(output)
        self.assertIn("wsl", result)
        self.assertNotIn("Unknown field", result)
        self.assertNotIn("somevalue", result.keys())
        self.assertEqual(result["_unparsed_lines"], ["Unknown field: somevalue"])

    def test_value_whitespace_stripped(self):
        """値の前後の空白が除去される。"""
        output = "WSL version:   2.4.4.0   \n"
        result = wsl_core.parse_wsl_version(output)
        self.assertEqual(result["wsl"], "2.4.4.0")

    def test_returns_dict(self):
        """戻り値が dict であることを確認する。"""
        result = wsl_core.parse_wsl_version(self.ENGLISH_OUTPUT)
        self.assertIsInstance(result, dict)


# ---------------------------------------------------------------------------
# parse_wsl_update_output
# ---------------------------------------------------------------------------

class TestParseWslUpdateOutput(unittest.TestCase):

    def test_japanese_up_to_date(self):
        """日本語の「既に最新」出力を up_to_date=True と判定する。"""
        output = "最新バージョンの Windows Subsystem for Linux は既にインストールされています。"
        result = wsl_core.parse_wsl_update_output(output)
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result["updated"])
        self.assertIsNone(result["version"])

    def test_english_up_to_date(self):
        """英語の「既に最新」出力を up_to_date=True と判定する。"""
        output = "The most recent version of Windows Subsystem for Linux is already installed."
        result = wsl_core.parse_wsl_update_output(output)
        self.assertTrue(result["up_to_date"])
        self.assertFalse(result["updated"])
        self.assertIsNone(result["version"])

    def test_english_updated_with_version(self):
        """英語の更新出力からバージョン番号を抽出し updated=True と判定する。"""
        output = "Updating Windows Subsystem for Linux to version: 2.1.5."
        result = wsl_core.parse_wsl_update_output(output)
        self.assertTrue(result["updated"])
        self.assertFalse(result["up_to_date"])
        self.assertEqual(result["version"], "2.1.5")

    def test_japanese_updated_with_version(self):
        """日本語の更新出力からバージョン番号を抽出し updated=True と判定する。"""
        output = "Windows Subsystem for Linux をバージョン 2.1.5 に更新しています。"
        result = wsl_core.parse_wsl_update_output(output)
        self.assertTrue(result["updated"])
        self.assertFalse(result["up_to_date"])
        self.assertEqual(result["version"], "2.1.5")

    def test_message_contains_version_when_updated(self):
        """updated=True の場合、message にバージョン番号が含まれる。"""
        output = "Updating Windows Subsystem for Linux to version: 2.1.5."
        result = wsl_core.parse_wsl_update_output(output)
        self.assertIn("2.1.5", result["message"])

    def test_message_when_up_to_date(self):
        """up_to_date=True の場合の message を確認する。"""
        output = "既にインストールされています。"
        result = wsl_core.parse_wsl_update_output(output)
        self.assertEqual(result["message"], "WSL は既に最新の状態です。")

    def test_empty_string_returns_safe_defaults(self):
        """空文字列は全て False/None の安全側の dict を返す。"""
        result = wsl_core.parse_wsl_update_output("")
        self.assertFalse(result["updated"])
        self.assertFalse(result["up_to_date"])
        self.assertIsNone(result["version"])
        self.assertEqual(result["message"], "")

    def test_none_returns_safe_defaults(self):
        """None は全て False/None の安全側の dict を返す。"""
        result = wsl_core.parse_wsl_update_output(None)
        self.assertFalse(result["updated"])
        self.assertFalse(result["up_to_date"])
        self.assertIsNone(result["version"])

    def test_unknown_output_falls_back_to_raw_text(self):
        """判別不能な出力は message に生テキストを設定し、更新なし扱いにする。"""
        output = "Something completely unexpected happened."
        result = wsl_core.parse_wsl_update_output(output)
        self.assertFalse(result["updated"])
        self.assertFalse(result["up_to_date"])
        self.assertIsNone(result["version"])
        self.assertEqual(result["message"], output)

    def test_returns_dict(self):
        """戻り値が dict であることを確認する。"""
        result = wsl_core.parse_wsl_update_output("既にインストールされています。")
        self.assertIsInstance(result, dict)

    def test_required_keys_present(self):
        """戻り値に必要な4つのキーが全て含まれる。"""
        result = wsl_core.parse_wsl_update_output("既にインストールされています。")
        for key in ("updated", "up_to_date", "version", "message"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# parse_ip_addresses
# ---------------------------------------------------------------------------

class TestParseIpAddresses(unittest.TestCase):

    def test_single_ipv4(self):
        """単一の IPv4 アドレスを返す。"""
        result = wsl_core.parse_ip_addresses("192.168.1.1")
        self.assertEqual(result, ["192.168.1.1"])

    def test_multiple_ipv4(self):
        """複数の IPv4 アドレスをリストで返す。"""
        result = wsl_core.parse_ip_addresses("192.168.1.1 10.0.0.1")
        self.assertEqual(result, ["192.168.1.1", "10.0.0.1"])

    def test_single_ipv6(self):
        """単一の IPv6 アドレスを返す。"""
        result = wsl_core.parse_ip_addresses("fd00::1")
        self.assertEqual(result, ["fd00::1"])

    def test_mixed_ipv4_and_ipv6(self):
        """IPv4 と IPv6 が混在する典型的な hostname -I 出力を解析する。"""
        result = wsl_core.parse_ip_addresses("172.25.160.1 fd00::1 ")
        self.assertEqual(result, ["172.25.160.1", "fd00::1"])

    def test_trailing_spaces_ignored(self):
        """末尾の空白は無視される。"""
        result = wsl_core.parse_ip_addresses("10.0.0.1   ")
        self.assertEqual(result, ["10.0.0.1"])

    def test_multiple_spaces_between_addresses(self):
        """アドレス間に複数の空白があっても正しく分割される。"""
        result = wsl_core.parse_ip_addresses("10.0.0.1   10.0.0.2")
        self.assertEqual(result, ["10.0.0.1", "10.0.0.2"])

    def test_empty_string_returns_empty_list(self):
        """空文字列は [] を返す。"""
        self.assertEqual(wsl_core.parse_ip_addresses(""), [])

    def test_none_returns_empty_list(self):
        """None は [] を返す。"""
        self.assertEqual(wsl_core.parse_ip_addresses(None), [])

    def test_whitespace_only_returns_empty_list(self):
        """空白のみの文字列は [] を返す。"""
        self.assertEqual(wsl_core.parse_ip_addresses("   "), [])

    def test_returns_list(self):
        """戻り値が list であることを確認する。"""
        result = wsl_core.parse_ip_addresses("192.168.0.1")
        self.assertIsInstance(result, list)

    def test_full_ipv6_address(self):
        """完全な IPv6 アドレス表記を正しく扱う。"""
        result = wsl_core.parse_ip_addresses("2001:0db8:85a3:0000:0000:8a2e:0370:7334")
        self.assertEqual(result, ["2001:0db8:85a3:0000:0000:8a2e:0370:7334"])

    def test_multiple_ipv6(self):
        """複数の IPv6 アドレスを返す。"""
        result = wsl_core.parse_ip_addresses("fd00::1 fe80::1")
        self.assertEqual(result, ["fd00::1", "fe80::1"])


# ---------------------------------------------------------------------------
# parse_os_release
# ---------------------------------------------------------------------------

class TestParseOsRelease(unittest.TestCase):

    UBUNTU_OUTPUT = (
        'NAME="Ubuntu"\n'
        'VERSION="22.04.3 LTS (Jammy Jellyfish)"\n'
        'ID=ubuntu\n'
        'ID_LIKE=debian\n'
        'PRETTY_NAME="Ubuntu 22.04.3 LTS"\n'
        'VERSION_ID="22.04"\n'
        'HOME_URL="https://www.ubuntu.com/"\n'
        'SUPPORT_URL="https://help.ubuntu.com/"\n'
        'BUG_REPORT_URL="https://bugs.launchpad.net/ubuntu/"\n'
    )

    def test_ubuntu_output(self):
        """典型的な Ubuntu の os-release 出力を解析する。"""
        result = wsl_core.parse_os_release(self.UBUNTU_OUTPUT)
        self.assertEqual(result["NAME"], "Ubuntu")
        self.assertEqual(result["VERSION_ID"], "22.04")
        self.assertEqual(result["PRETTY_NAME"], "Ubuntu 22.04.3 LTS")
        self.assertEqual(result["ID"], "ubuntu")

    def test_quoted_values(self):
        """ダブルクォートで囲まれた値からクォートが除去される。"""
        result = wsl_core.parse_os_release('KEY="quoted value"\n')
        self.assertEqual(result["KEY"], "quoted value")

    def test_unquoted_values(self):
        """クォートなしの値はそのまま取得される。"""
        result = wsl_core.parse_os_release("KEY=unquoted\n")
        self.assertEqual(result["KEY"], "unquoted")

    def test_comment_lines_skipped(self):
        """# で始まるコメント行はスキップされる。"""
        text = "# これはコメントです\nNAME=Ubuntu\n"
        result = wsl_core.parse_os_release(text)
        self.assertNotIn("# これはコメントです", result)
        self.assertEqual(result["NAME"], "Ubuntu")

    def test_empty_lines_skipped(self):
        """空行はスキップされる。"""
        text = "\nNAME=Ubuntu\n\nVERSION_ID=22.04\n"
        result = wsl_core.parse_os_release(text)
        self.assertEqual(result["NAME"], "Ubuntu")
        self.assertEqual(result["VERSION_ID"], "22.04")

    def test_empty_string(self):
        """空文字列は {} を返す。"""
        self.assertEqual(wsl_core.parse_os_release(""), {})

    def test_none_returns_empty(self):
        """None は {} を返す。"""
        self.assertEqual(wsl_core.parse_os_release(None), {})

    def test_no_equals_line_skipped(self):
        """= を含まない行はスキップされる。"""
        text = "NAME=Ubuntu\nこの行には等号がありません\nID=ubuntu\n"
        result = wsl_core.parse_os_release(text)
        self.assertIn("NAME", result)
        self.assertIn("ID", result)
        self.assertNotIn("この行には等号がありません", result)


# ---------------------------------------------------------------------------
# parse_disk_usage
# ---------------------------------------------------------------------------

class TestParseDiskUsage(unittest.TestCase):

    TYPICAL_OUTPUT = (
        "Filesystem       1B-blocks        Used   Available Use% Mounted on\n"
        "none           270389592064 16416915456 253972676608   7% /mnt/wslg\n"
        "/dev/sdb       270389592064  2147483648 268242108416   1% /\n"
        "tmpfs            8589934592           0   8589934592   0% /dev/shm\n"
    )

    def test_typical_output(self):
        """典型的な df -B1 出力を解析する。"""
        result = wsl_core.parse_disk_usage(self.TYPICAL_OUTPUT)
        self.assertEqual(len(result), 3)
        self.assertEqual(result[0]["filesystem"], "none")
        self.assertEqual(result[1]["filesystem"], "/dev/sdb")
        self.assertEqual(result[2]["mount_point"], "/dev/shm")

    def test_header_skipped(self):
        """先頭のヘッダ行はスキップされる。"""
        result = wsl_core.parse_disk_usage(self.TYPICAL_OUTPUT)
        filesystems = [r["filesystem"] for r in result]
        self.assertNotIn("Filesystem", filesystems)

    def test_types_correct(self):
        """total/used/available は int、use_percent と mount_point は str。"""
        result = wsl_core.parse_disk_usage(self.TYPICAL_OUTPUT)
        self.assertIsInstance(result[0]["total"], int)
        self.assertIsInstance(result[0]["used"], int)
        self.assertIsInstance(result[0]["available"], int)
        self.assertIsInstance(result[0]["use_percent"], str)
        self.assertIsInstance(result[0]["mount_point"], str)

    def test_short_line_skipped(self):
        """6フィールド未満の行はスキップされる。"""
        output = (
            "Filesystem  1B-blocks  Used  Available Use% Mounted on\n"
            "/dev/sdb   1000000000  500000000\n"  # フィールド不足
            "/dev/sdc   2000000000  100000000  1900000000  5% /data\n"
        )
        result = wsl_core.parse_disk_usage(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filesystem"], "/dev/sdc")

    def test_empty_string(self):
        """空文字列は [] を返す。"""
        self.assertEqual(wsl_core.parse_disk_usage(""), [])

    def test_none_returns_empty(self):
        """None は [] を返す。"""
        self.assertEqual(wsl_core.parse_disk_usage(None), [])

    def test_non_numeric_size_skipped(self):
        """サイズフィールドが数値でない行はスキップされる。"""
        output = (
            "Filesystem  1B-blocks  Used  Available Use% Mounted on\n"
            "/dev/sdb   INVALID    500000  1000000   5% /mnt\n"
            "/dev/sdc   2000000    100000  1900000   5% /data\n"
        )
        result = wsl_core.parse_disk_usage(output)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["filesystem"], "/dev/sdc")


# ---------------------------------------------------------------------------
# parse_uptime
# ---------------------------------------------------------------------------

class TestParseUptime(unittest.TestCase):

    def test_hours_minutes(self):
        """時間と分を含む uptime -p 出力をそのまま返す。"""
        self.assertEqual(wsl_core.parse_uptime("up 2 hours, 30 minutes"), "up 2 hours, 30 minutes")

    def test_days(self):
        """日数と時間を含む uptime -p 出力をそのまま返す。"""
        self.assertEqual(wsl_core.parse_uptime("up 3 days, 1 hour"), "up 3 days, 1 hour")

    def test_with_whitespace(self):
        """前後の空白が除去される。"""
        self.assertEqual(
            wsl_core.parse_uptime("  up 2 hours, 30 minutes  "), "up 2 hours, 30 minutes"
        )

    def test_empty_returns_dash(self):
        """空文字列は '-' を返す。"""
        self.assertEqual(wsl_core.parse_uptime(""), "-")

    def test_none_returns_dash(self):
        """None は '-' を返す。"""
        self.assertEqual(wsl_core.parse_uptime(None), "-")


# ---------------------------------------------------------------------------
# validate_distro_name
# ---------------------------------------------------------------------------

class TestValidateDistroName(unittest.TestCase):

    def test_valid_name(self):
        """通常のディストロ名は有効。"""
        valid, reason = wsl_core.validate_distro_name("Ubuntu")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_valid_with_hyphen(self):
        """ハイフンを含む名前は有効。"""
        valid, reason = wsl_core.validate_distro_name("my-distro")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_empty(self):
        """空文字列は無効。"""
        valid, reason = wsl_core.validate_distro_name("")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_whitespace_only(self):
        """空白のみは無効。"""
        valid, reason = wsl_core.validate_distro_name("  ")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_invalid_chars(self):
        """使用禁止文字を含む名前は無効。"""
        invalid_chars = ['/', '\\', ':', '*', '?', '"', '<', '>', '|']
        for char in invalid_chars:
            with self.subTest(char=char):
                valid, reason = wsl_core.validate_distro_name(f"distro{char}name")
                self.assertFalse(valid)
                self.assertNotEqual(reason, "")

    def test_shell_metachars_invalid(self):
        """cmd.exe/wt.exe のコマンドライン区切り文字を含む名前は無効。

        `wslmgr.WSLManager._open_terminal` がこの名前を含めて cmd.exe/wt.exe を
        起動するため、それらが特別扱いする文字は使用禁止とする (#security)。
        """
        shell_metachars = ['&', ';', '%', '^', '(', ')']
        for char in shell_metachars:
            with self.subTest(char=char):
                valid, reason = wsl_core.validate_distro_name(f"distro{char}name")
                self.assertFalse(valid)
                self.assertNotEqual(reason, "")

    def test_too_long(self):
        """65文字以上の名前は無効。"""
        name = "a" * 65
        valid, reason = wsl_core.validate_distro_name(name)
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_max_length_valid(self):
        """64文字の名前は有効。"""
        name = "a" * 64
        valid, reason = wsl_core.validate_distro_name(name)
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_reserved_device_names(self):
        """Windows の予約デバイス名は大文字小文字を区別せず無効。"""
        reserved = ["CON", "con", "Nul", "COM1", "LPT9", "nul.txt"]
        for name in reserved:
            with self.subTest(name=name):
                valid, reason = wsl_core.validate_distro_name(name)
                self.assertFalse(valid)
                self.assertNotEqual(reason, "")

    def test_reserved_like_names_are_valid(self):
        """予約名に似ているだけの名前 (前方一致しない) は有効。"""
        for name in ["CONSOLE", "COM10", "LPT0", "falcon"]:
            with self.subTest(name=name):
                valid, reason = wsl_core.validate_distro_name(name)
                self.assertTrue(valid)
                self.assertEqual(reason, "")

    def test_trailing_dot_invalid(self):
        """末尾がドットの名前は無効。"""
        valid, reason = wsl_core.validate_distro_name("ubuntu.")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_dot_not_at_end_valid(self):
        """末尾以外のドットは有効。"""
        valid, reason = wsl_core.validate_distro_name("ubuntu.22.04")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_trailing_whitespace_invalid(self):
        """末尾が空白の名前は無効。"""
        valid, reason = wsl_core.validate_distro_name("ubuntu ")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_leading_whitespace_invalid(self):
        """先頭が空白の名前は無効。"""
        valid, reason = wsl_core.validate_distro_name(" ubuntu")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_control_characters_invalid(self):
        """制御文字を含む名前は無効。"""
        for name in ["ubu\tntu", "ubu\x01ntu"]:
            with self.subTest(name=name):
                valid, reason = wsl_core.validate_distro_name(name)
                self.assertFalse(valid)
                self.assertNotEqual(reason, "")

    def test_existing_valid_names_still_valid(self):
        """既存の有効な名前は新ルール適用後も引き続き有効。"""
        for name in ["Ubuntu-22.04", "Ubuntu", "my-distro"]:
            with self.subTest(name=name):
                valid, reason = wsl_core.validate_distro_name(name)
                self.assertTrue(valid)
                self.assertEqual(reason, "")


# ---------------------------------------------------------------------------
# default_clone_name
# ---------------------------------------------------------------------------

class TestDefaultCloneName(unittest.TestCase):

    def test_no_conflict(self):
        """衝突がない場合は '-copy' を返す。"""
        self.assertEqual(
            wsl_core.default_clone_name("Ubuntu", ["Ubuntu", "Debian"]), "Ubuntu-copy"
        )

    def test_copy_exists(self):
        """'-copy' が既に存在する場合は '-copy2' を返す。"""
        self.assertEqual(
            wsl_core.default_clone_name("Ubuntu", ["Ubuntu", "Ubuntu-copy"]),
            "Ubuntu-copy2",
        )

    def test_copy_and_copy2_exist(self):
        """'-copy' と '-copy2' が既に存在する場合は '-copy3' を返す。"""
        self.assertEqual(
            wsl_core.default_clone_name(
                "Ubuntu", ["Ubuntu", "Ubuntu-copy", "Ubuntu-copy2"]
            ),
            "Ubuntu-copy3",
        )

    def test_case_insensitive_conflict(self):
        """大文字小文字違いの衝突も回避する。"""
        self.assertEqual(
            wsl_core.default_clone_name("Ubuntu", ["Ubuntu", "Ubuntu-COPY"]),
            "Ubuntu-copy2",
        )

    def test_empty_existing(self):
        """existing が空リストの場合は '-copy' を返す。"""
        self.assertEqual(wsl_core.default_clone_name("Ubuntu", []), "Ubuntu-copy")


# ---------------------------------------------------------------------------
# validate_clone_name
# ---------------------------------------------------------------------------

class TestValidateCloneName(unittest.TestCase):

    def test_valid_name_not_in_existing(self):
        """existing に無い有効な名前は有効。"""
        valid, reason = wsl_core.validate_clone_name("Ubuntu-copy", ["Ubuntu"])
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_rejected_by_validate_distro_name_empty(self):
        """空文字は validate_distro_name によって無効と判定される。"""
        valid, reason = wsl_core.validate_clone_name("", ["Ubuntu"])
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_rejected_by_validate_distro_name_invalid_chars(self):
        """不正な文字を含む名前は validate_distro_name によって無効と判定される。"""
        valid, reason = wsl_core.validate_clone_name("Ubuntu/copy", ["Ubuntu"])
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_exact_duplicate(self):
        """existing と完全一致する名前は無効。"""
        valid, reason = wsl_core.validate_clone_name("Ubuntu", ["Ubuntu", "Debian"])
        self.assertFalse(valid)
        self.assertIn("既に存在", reason)

    def test_rejected_by_validate_distro_name_reserved_name(self):
        """Windows 予約デバイス名は validate_distro_name によって無効と判定される。"""
        valid, reason = wsl_core.validate_clone_name("CON", ["Ubuntu"])
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_casefold_duplicate(self):
        """大文字小文字の違いのみの重複も無効。"""
        valid, reason = wsl_core.validate_clone_name("UBUNTU", ["ubuntu"])
        self.assertFalse(valid)
        self.assertIn("既に存在", reason)


# ---------------------------------------------------------------------------
# format_bytes
# ---------------------------------------------------------------------------

class TestFormatBytes(unittest.TestCase):

    def test_zero(self):
        """0 は '0 B' を返す。"""
        self.assertEqual(wsl_core.format_bytes(0), "0 B")

    def test_negative(self):
        """負の値は '0 B' を返す。"""
        self.assertEqual(wsl_core.format_bytes(-1), "0 B")

    def test_bytes(self):
        """1 KiB 未満はバイト表示。"""
        self.assertEqual(wsl_core.format_bytes(512), "512 B")

    def test_kib(self):
        """1024 バイトは '1.0 KiB'。"""
        self.assertEqual(wsl_core.format_bytes(1024), "1.0 KiB")

    def test_kib_fraction(self):
        """1536 バイトは '1.5 KiB'。"""
        self.assertEqual(wsl_core.format_bytes(1536), "1.5 KiB")

    def test_mib(self):
        """1048576 バイトは '1.0 MiB'。"""
        self.assertEqual(wsl_core.format_bytes(1048576), "1.0 MiB")

    def test_gib(self):
        """1073741824 バイトは '1.0 GiB'。"""
        self.assertEqual(wsl_core.format_bytes(1073741824), "1.0 GiB")

    def test_tib(self):
        """1099511627776 バイトは '1.0 TiB'。"""
        self.assertEqual(wsl_core.format_bytes(1099511627776), "1.0 TiB")

    def test_float_input(self):
        """float 入力も正しく処理される。"""
        self.assertEqual(wsl_core.format_bytes(1024.0), "1.0 KiB")


# ---------------------------------------------------------------------------
# build_distro_snapshot
# ---------------------------------------------------------------------------

class TestBuildDistroSnapshot(unittest.TestCase):
    """build_distro_snapshot のテスト。"""

    DISTROS: ClassVar[list[dict[str, object]]] = [
        {"name": "Ubuntu", "state": "Running", "version": "2", "default": True,
         "cpu": "-", "memory": "-", "disk": "-", "ip": "-"},
        {"name": "Debian", "state": "Stopped", "version": "2", "default": False,
         "cpu": "-", "memory": "-", "disk": "-", "ip": "-"},
    ]

    def test_explicit_timestamp_preserved(self):
        """明示的に渡した timestamp がそのまま格納される。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["timestamp"], "2024-01-01T00:00:00")

    def test_count(self):
        """count がディストロ数と一致する。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["count"], 2)

    def test_running_count(self):
        """running が state='Running' のディストロ数を返す。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["running"], 1)

    def test_distros_stored(self):
        """渡した distros リストがそのまま格納される。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        self.assertIs(snap["distros"], self.DISTROS)

    def test_empty_distro_list(self):
        """空のディストロリストでも正しく動作する。"""
        snap = wsl_core.build_distro_snapshot([], timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["count"], 0)
        self.assertEqual(snap["running"], 0)
        self.assertEqual(snap["distros"], [])

    def test_all_running(self):
        """全ディストロが Running の場合 running == count になる。"""
        distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Running"},
        ]
        snap = wsl_core.build_distro_snapshot(distros, timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["running"], 2)
        self.assertEqual(snap["count"], 2)

    def test_none_running(self):
        """全ディストロが Stopped の場合 running == 0 になる。"""
        distros = [
            {"name": "Ubuntu", "state": "Stopped"},
            {"name": "Debian", "state": "Stopped"},
        ]
        snap = wsl_core.build_distro_snapshot(distros, timestamp="2024-01-01T00:00:00")
        self.assertEqual(snap["running"], 0)

    def test_auto_timestamp_is_iso_format(self):
        """timestamp=None の場合に ISO 8601 形式のタイムスタンプが自動設定される。"""
        snap = wsl_core.build_distro_snapshot([], timestamp=None)
        # ISO 8601 の基本パターン: YYYY-MM-DDTHH:MM:SS[.ffffff]
        iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertRegex(snap["timestamp"], iso_pattern)

    def test_returns_dict(self):
        """戻り値が dict であることを確認する。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        self.assertIsInstance(snap, dict)

    def test_required_keys_present(self):
        """必須キー timestamp/distros/count/running が全て存在する。"""
        snap = wsl_core.build_distro_snapshot(self.DISTROS, timestamp="2024-01-01T00:00:00")
        for key in ("timestamp", "distros", "count", "running"):
            self.assertIn(key, snap)


# ---------------------------------------------------------------------------
# format_snapshot_summary
# ---------------------------------------------------------------------------

class TestFormatSnapshotSummary(unittest.TestCase):
    """format_snapshot_summary のテスト。"""

    DISTROS: ClassVar[list[dict[str, str]]] = [
        {"name": "Ubuntu", "state": "Running"},
        {"name": "Debian", "state": "Stopped"},
    ]

    def _make_snapshot(self, distros=None, timestamp="2024-06-01T12:00:00"):
        d = distros if distros is not None else self.DISTROS
        return wsl_core.build_distro_snapshot(d, timestamp=timestamp)

    def test_contains_timestamp(self):
        """サマリーにタイムスタンプが含まれる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("2024-06-01T12:00:00", summary)

    def test_contains_count_and_running(self):
        """ディストリビューション数と実行中の数がサマリーに含まれる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("2", summary)  # count
        self.assertIn("1", summary)  # running

    def test_each_distro_name_appears(self):
        """各ディストロ名がサマリーに含まれる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("Ubuntu", summary)
        self.assertIn("Debian", summary)

    def test_each_distro_state_appears(self):
        """各ディストロの state がサマリーに含まれる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("Running", summary)
        self.assertIn("Stopped", summary)

    def test_distro_line_indented(self):
        """各ディストロ行が2スペースのインデントで始まる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("  Ubuntu:", summary)
        self.assertIn("  Debian:", summary)

    def test_ends_with_newline(self):
        """サマリーは改行で終わる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertTrue(summary.endswith("\n"))

    def test_empty_distro_list(self):
        """ディストロが0件でも正常に動作する。"""
        snap = self._make_snapshot(distros=[])
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("0", summary)
        self.assertIsInstance(summary, str)

    def test_returns_string(self):
        """戻り値が str であることを確認する。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIsInstance(summary, str)

    def test_format_label_japanese(self):
        """日本語のラベル文字列が含まれる。"""
        snap = self._make_snapshot()
        summary = wsl_core.format_snapshot_summary(snap)
        self.assertIn("スナップショット", summary)
        self.assertIn("ディストリビューション数", summary)
        self.assertIn("実行中", summary)


# ---------------------------------------------------------------------------
# format_operation_log_entry
# ---------------------------------------------------------------------------

class TestFormatOperationLogEntry(unittest.TestCase):
    """format_operation_log_entry のテスト。"""

    def test_explicit_timestamp(self):
        """明示的な timestamp が角括弧で囲まれてエントリに含まれる。"""
        entry = wsl_core.format_operation_log_entry(
            "起動", "Ubuntu", "成功", timestamp="2024-01-01T10:00:00"
        )
        self.assertIn("[2024-01-01T10:00:00]", entry)

    def test_operation_in_entry(self):
        """operation がエントリに含まれる。"""
        entry = wsl_core.format_operation_log_entry(
            "停止", "Debian", "成功", timestamp="2024-01-01T10:00:00"
        )
        self.assertIn("停止", entry)

    def test_target_in_entry(self):
        """target がエントリに含まれる。"""
        entry = wsl_core.format_operation_log_entry(
            "インストール", "kali-linux", "失敗", timestamp="2024-01-01T10:00:00"
        )
        self.assertIn("kali-linux", entry)

    def test_result_in_entry(self):
        """result がエントリに含まれる。"""
        entry = wsl_core.format_operation_log_entry(
            "エクスポート", "Ubuntu", "完了", timestamp="2024-01-01T10:00:00"
        )
        self.assertIn("完了", entry)

    def test_pipe_separator(self):
        """フィールドが '|' で区切られている。"""
        entry = wsl_core.format_operation_log_entry(
            "起動", "Ubuntu", "成功", timestamp="2024-01-01T10:00:00"
        )
        self.assertEqual(entry.count("|"), 2)

    def test_format_structure(self):
        """エントリが '[timestamp] op | target | result' 形式である。"""
        entry = wsl_core.format_operation_log_entry(
            "起動", "Ubuntu", "成功", timestamp="2024-01-01T10:00:00"
        )
        self.assertEqual(entry, "[2024-01-01T10:00:00] 起動 | Ubuntu | 成功")

    def test_auto_timestamp_is_iso_format(self):
        """timestamp=None の場合に ISO 8601 形式のタイムスタンプが自動設定される。"""
        entry = wsl_core.format_operation_log_entry("起動", "Ubuntu", "成功", timestamp=None)
        iso_pattern = re.compile(r"\[\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}")
        self.assertRegex(entry, iso_pattern)

    def test_returns_string(self):
        """戻り値が str であることを確認する。"""
        entry = wsl_core.format_operation_log_entry(
            "起動", "Ubuntu", "成功", timestamp="2024-01-01T10:00:00"
        )
        self.assertIsInstance(entry, str)

    def test_various_operations(self):
        """複数の operation 文字列が正しく埋め込まれる。"""
        for op in ("起動", "停止", "インストール", "エクスポート"):
            with self.subTest(operation=op):
                entry = wsl_core.format_operation_log_entry(
                    op, "Ubuntu", "成功", timestamp="2024-01-01T10:00:00"
                )
                self.assertIn(op, entry)


# ---------------------------------------------------------------------------
# diff_snapshots
# ---------------------------------------------------------------------------

class TestDiffSnapshots(unittest.TestCase):
    """diff_snapshots のテスト。"""

    TS_OLD = "2024-01-01T00:00:00"
    TS_NEW = "2024-01-01T01:00:00"

    def _snap(self, distros, ts):
        return wsl_core.build_distro_snapshot(distros, timestamp=ts)

    def test_no_changes(self):
        """同一ディストロで差分なし。"""
        distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        old = self._snap(distros, self.TS_OLD)
        new = self._snap(distros, self.TS_NEW)
        diff = wsl_core.diff_snapshots(old, new)
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_added_distro(self):
        """新規ディストロが added リストに含まれる。"""
        old_distros = [{"name": "Ubuntu", "state": "Running"}]
        new_distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        diff = wsl_core.diff_snapshots(
            self._snap(old_distros, self.TS_OLD),
            self._snap(new_distros, self.TS_NEW),
        )
        self.assertIn("Debian", diff["added"])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_removed_distro(self):
        """削除されたディストロが removed リストに含まれる。"""
        old_distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        new_distros = [{"name": "Ubuntu", "state": "Running"}]
        diff = wsl_core.diff_snapshots(
            self._snap(old_distros, self.TS_OLD),
            self._snap(new_distros, self.TS_NEW),
        )
        self.assertIn("Debian", diff["removed"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_state_changed(self):
        """state が変化したディストロが state_changed に含まれる。"""
        old_distros = [{"name": "Ubuntu", "state": "Stopped"}]
        new_distros = [{"name": "Ubuntu", "state": "Running"}]
        diff = wsl_core.diff_snapshots(
            self._snap(old_distros, self.TS_OLD),
            self._snap(new_distros, self.TS_NEW),
        )
        self.assertEqual(len(diff["state_changed"]), 1)
        entry = diff["state_changed"][0]
        self.assertEqual(entry["name"], "Ubuntu")
        self.assertEqual(entry["old_state"], "Stopped")
        self.assertEqual(entry["new_state"], "Running")
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])

    def test_empty_both_snapshots(self):
        """両方のスナップショットが空の場合、差分なし。"""
        diff = wsl_core.diff_snapshots(
            self._snap([], self.TS_OLD),
            self._snap([], self.TS_NEW),
        )
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_old_empty_new_has_distros(self):
        """旧スナップショットが空で新しいほうにディストロがある場合、全て added。"""
        new_distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        diff = wsl_core.diff_snapshots(
            self._snap([], self.TS_OLD),
            self._snap(new_distros, self.TS_NEW),
        )
        self.assertIn("Ubuntu", diff["added"])
        self.assertIn("Debian", diff["added"])
        self.assertEqual(diff["removed"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_new_empty_old_has_distros(self):
        """新スナップショットが空で旧スナップショットにディストロがある場合、全て removed。"""
        old_distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        diff = wsl_core.diff_snapshots(
            self._snap(old_distros, self.TS_OLD),
            self._snap([], self.TS_NEW),
        )
        self.assertIn("Ubuntu", diff["removed"])
        self.assertIn("Debian", diff["removed"])
        self.assertEqual(diff["added"], [])
        self.assertEqual(diff["state_changed"], [])

    def test_combined_add_remove_state_change(self):
        """追加・削除・状態変化が同時に発生する場合。"""
        old_distros = [
            {"name": "Ubuntu", "state": "Running"},
            {"name": "Debian", "state": "Stopped"},
        ]
        new_distros = [
            {"name": "Ubuntu", "state": "Stopped"},   # state 変化
            {"name": "kali-linux", "state": "Running"},  # 追加
            # Debian は削除
        ]
        diff = wsl_core.diff_snapshots(
            self._snap(old_distros, self.TS_OLD),
            self._snap(new_distros, self.TS_NEW),
        )
        self.assertIn("kali-linux", diff["added"])
        self.assertIn("Debian", diff["removed"])
        self.assertEqual(len(diff["state_changed"]), 1)
        self.assertEqual(diff["state_changed"][0]["name"], "Ubuntu")
        self.assertEqual(diff["state_changed"][0]["old_state"], "Running")
        self.assertEqual(diff["state_changed"][0]["new_state"], "Stopped")

    def test_returns_required_keys(self):
        """戻り値に added/removed/state_changed キーが存在する。"""
        diff = wsl_core.diff_snapshots(
            self._snap([], self.TS_OLD),
            self._snap([], self.TS_NEW),
        )
        for key in ("added", "removed", "state_changed"):
            self.assertIn(key, diff)

    def test_returns_dict(self):
        """戻り値が dict であることを確認する。"""
        diff = wsl_core.diff_snapshots(
            self._snap([], self.TS_OLD),
            self._snap([], self.TS_NEW),
        )
        self.assertIsInstance(diff, dict)


# ---------------------------------------------------------------------------
# validate_memory_string
# ---------------------------------------------------------------------------

class TestValidateMemoryString(unittest.TestCase):

    def test_empty_string_is_valid(self):
        """空文字列は有効 (未設定)。"""
        valid, reason = wsl_core.validate_memory_string("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_bare_number_is_valid(self):
        """単位なしの数字はバイト数として有効。"""
        valid, reason = wsl_core.validate_memory_string("1024")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_gb_uppercase(self):
        """大文字の GB は有効。"""
        valid, reason = wsl_core.validate_memory_string("4GB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_mb_uppercase(self):
        """大文字の MB は有効。"""
        valid, reason = wsl_core.validate_memory_string("512MB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_kb_uppercase(self):
        """大文字の KB は有効。"""
        valid, reason = wsl_core.validate_memory_string("1024KB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_tb_uppercase(self):
        """大文字の TB は有効。"""
        valid, reason = wsl_core.validate_memory_string("2TB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_gb_lowercase(self):
        """小文字の gb は有効。"""
        valid, reason = wsl_core.validate_memory_string("4gb")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_mb_lowercase(self):
        """小文字の mb は有効。"""
        valid, reason = wsl_core.validate_memory_string("512mb")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_kb_lowercase(self):
        """小文字の kb は有効。"""
        valid, reason = wsl_core.validate_memory_string("256kb")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_large_value_mb(self):
        """大きな数値も有効。"""
        valid, reason = wsl_core.validate_memory_string("16384MB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_alpha_only_invalid(self):
        """英字のみは無効。"""
        valid, reason = wsl_core.validate_memory_string("abc")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_unknown_unit_invalid(self):
        """不明な単位 (XB) は無効。"""
        valid, reason = wsl_core.validate_memory_string("4XB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_negative_value_invalid(self):
        """負の値は無効 (先頭の '-' が不正文字)。"""
        valid, reason = wsl_core.validate_memory_string("-1GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_zero_gb_invalid(self):
        """0GB は無効。"""
        valid, reason = wsl_core.validate_memory_string("0GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_zero_bare_invalid(self):
        """単位なし 0 は無効。"""
        valid, reason = wsl_core.validate_memory_string("0")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_float_value_invalid(self):
        """小数点を含む値は無効。"""
        valid, reason = wsl_core.validate_memory_string("1.5GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_space_between_number_unit_invalid(self):
        """数値と単位の間にスペースがある場合は無効。"""
        valid, reason = wsl_core.validate_memory_string("4 GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_returns_tuple(self):
        """戻り値が (bool, str) の tuple であることを確認。"""
        result = wsl_core.validate_memory_string("4GB")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)

    def test_invalid_reason_is_nonempty(self):
        """無効時の理由が空文字でないことを確認。"""
        _, reason = wsl_core.validate_memory_string("bad")
        self.assertTrue(len(reason) > 0)

    def test_valid_reason_is_empty(self):
        """有効時の理由が空文字であることを確認。"""
        _, reason = wsl_core.validate_memory_string("8GB")
        self.assertEqual(reason, "")


# ---------------------------------------------------------------------------
# validate_processors_string
# ---------------------------------------------------------------------------

class TestValidateProcessorsString(unittest.TestCase):

    def test_empty_string_is_valid(self):
        """空文字列は有効 (未設定)。"""
        valid, reason = wsl_core.validate_processors_string("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_one_is_valid(self):
        """1 は有効。"""
        valid, reason = wsl_core.validate_processors_string("1")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_typical_value_valid(self):
        """典型的な値 (4) は有効。"""
        valid, reason = wsl_core.validate_processors_string("4")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_large_number_valid(self):
        """大きな整数も有効。"""
        valid, reason = wsl_core.validate_processors_string("128")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_zero_invalid(self):
        """0 は無効。"""
        valid, reason = wsl_core.validate_processors_string("0")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_negative_invalid(self):
        """負の整数は無効。"""
        valid, reason = wsl_core.validate_processors_string("-1")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_float_invalid(self):
        """小数点を含む値は無効。"""
        valid, reason = wsl_core.validate_processors_string("2.5")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_alpha_invalid(self):
        """英字は無効。"""
        valid, reason = wsl_core.validate_processors_string("abc")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_alphanumeric_invalid(self):
        """英数混在は無効。"""
        valid, reason = wsl_core.validate_processors_string("4cores")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_whitespace_only_invalid(self):
        """スペースのみは無効。"""
        valid, reason = wsl_core.validate_processors_string(" ")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_returns_tuple(self):
        """戻り値が (bool, str) の tuple であることを確認。"""
        result = wsl_core.validate_processors_string("4")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)

    def test_valid_reason_is_empty(self):
        """有効時の理由が空文字であることを確認。"""
        _, reason = wsl_core.validate_processors_string("8")
        self.assertEqual(reason, "")

    def test_invalid_reason_is_nonempty(self):
        """無効時の理由が空文字でないことを確認。"""
        _, reason = wsl_core.validate_processors_string("0")
        self.assertTrue(len(reason) > 0)


# ---------------------------------------------------------------------------
# validate_swap_string
# ---------------------------------------------------------------------------

class TestValidateSwapString(unittest.TestCase):

    def test_empty_string_is_valid(self):
        """空文字列は有効 (未設定)。"""
        valid, reason = wsl_core.validate_swap_string("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_gb_value_valid(self):
        """有効な GB 値。"""
        valid, reason = wsl_core.validate_swap_string("8GB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_mb_value_valid(self):
        """有効な MB 値。"""
        valid, reason = wsl_core.validate_swap_string("2048MB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_kb_lowercase_valid(self):
        """小文字 kb も有効。"""
        valid, reason = wsl_core.validate_swap_string("512kb")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_tb_value_valid(self):
        """有効な TB 値。"""
        valid, reason = wsl_core.validate_swap_string("1TB")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_bare_number_valid(self):
        """単位なしの数字はバイト数として有効。"""
        valid, reason = wsl_core.validate_swap_string("4096")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_zero_gb_invalid(self):
        """0GB は無効。"""
        valid, reason = wsl_core.validate_swap_string("0GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_negative_invalid(self):
        """負の値は無効。"""
        valid, reason = wsl_core.validate_swap_string("-1GB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_unknown_unit_invalid(self):
        """不明な単位は無効。"""
        valid, reason = wsl_core.validate_swap_string("4XB")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_alpha_only_invalid(self):
        """英字のみは無効。"""
        valid, reason = wsl_core.validate_swap_string("abc")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_returns_tuple(self):
        """戻り値が (bool, str) の tuple であることを確認。"""
        result = wsl_core.validate_swap_string("2GB")
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result[0], bool)
        self.assertIsInstance(result[1], str)

    def test_valid_reason_is_empty(self):
        """有効時の理由が空文字であることを確認。"""
        _, reason = wsl_core.validate_swap_string("4GB")
        self.assertEqual(reason, "")

    def test_invalid_reason_is_nonempty(self):
        """無効時の理由が空文字でないことを確認。"""
        _, reason = wsl_core.validate_swap_string("0GB")
        self.assertTrue(len(reason) > 0)


# ---------------------------------------------------------------------------
# parse_memory_to_bytes
# ---------------------------------------------------------------------------

class TestParseMemoryToBytes(unittest.TestCase):

    def test_gb(self):
        """4GB → 4 * 1024^3 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("4GB"), 4 * 1024 ** 3)

    def test_mb(self):
        """512MB → 512 * 1024^2 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("512MB"), 512 * 1024 ** 2)

    def test_kb(self):
        """1024KB → 1024 * 1024 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1024KB"), 1024 * 1024)

    def test_tb(self):
        """2TB → 2 * 1024^4 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("2TB"), 2 * 1024 ** 4)

    def test_bare_number(self):
        """単位なし数字はそのままバイト数として返す。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1024"), 1024)

    def test_lowercase_gb(self):
        """小文字 gb も正しく変換される。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("4gb"), 4 * 1024 ** 3)

    def test_lowercase_mb(self):
        """小文字 mb も正しく変換される。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("256mb"), 256 * 1024 ** 2)

    def test_lowercase_kb(self):
        """小文字 kb も正しく変換される。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("512kb"), 512 * 1024)

    def test_one_byte(self):
        """1 (単位なし) → 1 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1"), 1)

    def test_one_kb(self):
        """1KB → 1024 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1KB"), 1024)

    def test_one_mb(self):
        """1MB → 1048576 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1MB"), 1048576)

    def test_one_gb(self):
        """1GB → 1073741824 バイト。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("1GB"), 1073741824)

    def test_empty_string_returns_none(self):
        """空文字列は None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes(""))

    def test_alpha_returns_none(self):
        """英字のみは None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes("abc"))

    def test_unknown_unit_returns_none(self):
        """不明な単位は None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes("4XB"))

    def test_negative_returns_none(self):
        """負の値は None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes("-1GB"))

    def test_float_returns_none(self):
        """小数点を含む値は None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes("1.5GB"))

    def test_space_returns_none(self):
        """数値と単位の間にスペースがある場合は None を返す。"""
        self.assertIsNone(wsl_core.parse_memory_to_bytes("4 GB"))

    def test_returns_int(self):
        """有効な入力では int を返す。"""
        result = wsl_core.parse_memory_to_bytes("4GB")
        self.assertIsInstance(result, int)

    def test_zero_bare(self):
        """0 (単位なし) → 0 バイト (変換自体は成功)。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("0"), 0)

    def test_large_value(self):
        """大きな値でも正確に変換される。"""
        self.assertEqual(wsl_core.parse_memory_to_bytes("16384MB"), 16384 * 1024 ** 2)


# ---------------------------------------------------------------------------
# get_default_log_dir
# ---------------------------------------------------------------------------

class TestGetDefaultLogDir(unittest.TestCase):

    def test_windows_uses_appdata(self):
        """Windows 環境では APPDATA 配下の WSLManager/logs を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\test\AppData\Roaming"}):
                result = wsl_core.get_default_log_dir()
        self.assertEqual(
            result, os.path.join(r"C:\Users\test\AppData\Roaming", "WSLManager", "logs")
        )

    def test_windows_missing_appdata_uses_empty(self):
        """Windows 環境で APPDATA が未設定の場合は空文字を基点にする。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            env = dict(os.environ)
            env.pop("APPDATA", None)
            with mock.patch.dict(os.environ, env, clear=True):
                result = wsl_core.get_default_log_dir()
        self.assertEqual(result, os.path.join("", "WSLManager", "logs"))

    def test_non_windows_uses_home(self):
        """非 Windows 環境では ~/.wslmgr/logs を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_log_dir()
        self.assertEqual(result, os.path.expanduser("~/.wslmgr/logs"))

    def test_non_windows_darwin(self):
        """macOS (darwin) でも非 Windows 用パスを返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "darwin"):
            result = wsl_core.get_default_log_dir()
        self.assertEqual(result, os.path.expanduser("~/.wslmgr/logs"))

    def test_non_windows_returns_string(self):
        """戻り値は文字列型である。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_log_dir()
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# serialize_log_entry
# ---------------------------------------------------------------------------

class TestSerializeLogEntry(unittest.TestCase):

    def test_with_explicit_timestamp(self):
        """timestamp を指定した場合はその値がそのまま使われる。"""
        result = wsl_core.serialize_log_entry(
            "起動", "Ubuntu", "成功", timestamp="2026-01-01T00:00:00"
        )
        data = json.loads(result)
        self.assertEqual(data["timestamp"], "2026-01-01T00:00:00")

    def test_without_timestamp_uses_now(self):
        """timestamp を省略すると現在時刻が設定される。"""
        result = wsl_core.serialize_log_entry("停止", "Debian", "失敗")
        data = json.loads(result)
        # ISO 8601 形式としてパースできることを確認する
        datetime_value = data["timestamp"]
        self.assertTrue(datetime_value)

    def test_returns_valid_json(self):
        """戻り値は json.loads で正しくパースできる単一行の JSON である。"""
        result = wsl_core.serialize_log_entry("再起動", "Ubuntu-22.04", "成功", timestamp="t")
        self.assertEqual(result.count("\n"), 0)
        data = json.loads(result)
        self.assertEqual(
            data,
            {
                "schema_version": 1,
                "timestamp": "t",
                "operation": "再起動",
                "target": "Ubuntu-22.04",
                "result": "成功",
            },
        )

    def test_japanese_text_not_escaped(self):
        """ensure_ascii=False により日本語がそのまま出力される (\\u エスケープされない)。"""
        result = wsl_core.serialize_log_entry(
            "エクスポート", "テスト用ディストロ", "成功", timestamp="t"
        )
        self.assertIn("エクスポート", result)
        self.assertIn("テスト用ディストロ", result)
        self.assertNotIn("\\u", result)

    def test_no_trailing_newline(self):
        """戻り値の末尾に改行は含まれない。"""
        result = wsl_core.serialize_log_entry("起動", "Ubuntu", "成功", timestamp="t")
        self.assertFalse(result.endswith("\n"))

    def test_keys_present(self):
        """必須キー (timestamp, operation, target, result, schema_version) がすべて含まれる。"""
        result = wsl_core.serialize_log_entry("削除", "OldDistro", "成功", timestamp="t")
        data = json.loads(result)
        self.assertEqual(
            set(data.keys()),
            {"timestamp", "operation", "target", "result", "schema_version"},
        )

    def test_source_omitted_by_default(self):
        """source を指定しない場合、出力に "source" キーは含まれない (#27, 後方互換)。"""
        result = wsl_core.serialize_log_entry("起動", "Ubuntu", "成功", timestamp="t")
        data = json.loads(result)
        self.assertNotIn("source", data)

    def test_source_included_when_given(self):
        """source を指定すると "source" キーとして出力される。"""
        result = wsl_core.serialize_log_entry(
            "起動", "Ubuntu", "成功", timestamp="t", source="cli"
        )
        data = json.loads(result)
        self.assertEqual(data["source"], "cli")

    def test_source_gui_value(self):
        """source="gui" もそのまま出力される。"""
        result = wsl_core.serialize_log_entry(
            "停止", "Ubuntu", "成功", timestamp="t", source="gui"
        )
        data = json.loads(result)
        self.assertEqual(data["source"], "gui")


# ---------------------------------------------------------------------------
# deserialize_log_entries
# ---------------------------------------------------------------------------

class TestDeserializeLogEntries(unittest.TestCase):

    def test_valid_json_lines(self):
        """有効な JSON Lines を複数行パースしてリストを返す。"""
        text = (
            '{"timestamp": "t1", "operation": "起動", "target": "Ubuntu", "result": "成功"}\n'
            '{"timestamp": "t2", "operation": "停止", "target": "Debian", "result": "失敗"}'
        )
        result = wsl_core.deserialize_log_entries(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["operation"], "起動")
        self.assertEqual(result[1]["operation"], "停止")

    def test_skips_blank_lines(self):
        """空行はスキップされる。"""
        text = (
            '{"timestamp": "t1", "operation": "起動", "target": "Ubuntu", "result": "成功"}\n'
            "\n"
            "   \n"
            '{"timestamp": "t2", "operation": "停止", "target": "Debian", "result": "失敗"}'
        )
        result = wsl_core.deserialize_log_entries(text)
        self.assertEqual(len(result), 2)

    def test_skips_invalid_json(self):
        """JSON としてパースできない行はスキップされる。"""
        text = (
            '{"timestamp": "t1", "operation": "起動", "target": "Ubuntu", "result": "成功"}\n'
            "this is not json\n"
            '{"timestamp": "t2", "operation": "停止", "target": "Debian", "result": "失敗"}'
        )
        result = wsl_core.deserialize_log_entries(text)
        self.assertEqual(len(result), 2)

    def test_empty_string_returns_empty_list(self):
        """空文字列を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.deserialize_log_entries(""), [])

    def test_none_returns_empty_list(self):
        """None を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.deserialize_log_entries(None), [])

    def test_round_trip_with_serialize(self):
        """serialize_log_entry の出力を deserialize_log_entries で復元できる。"""
        line1 = wsl_core.serialize_log_entry("起動", "Ubuntu", "成功", timestamp="t1")
        line2 = wsl_core.serialize_log_entry("停止", "Debian", "失敗", timestamp="t2")
        text = line1 + "\n" + line2
        result = wsl_core.deserialize_log_entries(text)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["target"], "Ubuntu")
        self.assertEqual(result[1]["target"], "Debian")


# ---------------------------------------------------------------------------
# format_log_entry_from_dict
# ---------------------------------------------------------------------------

class TestFormatLogEntryFromDict(unittest.TestCase):

    def test_normal_dict(self):
        """すべてのキーが揃った dict を正しくフォーマットする。"""
        entry = {
            "timestamp": "2026-01-01T00:00:00",
            "operation": "起動",
            "target": "Ubuntu",
            "result": "成功",
        }
        result = wsl_core.format_log_entry_from_dict(entry)
        self.assertEqual(result, "[2026-01-01T00:00:00] 起動 | Ubuntu | 成功")

    def test_missing_timestamp(self):
        """timestamp キーが欠けている場合は '-' を使う。"""
        entry = {"operation": "停止", "target": "Debian", "result": "成功"}
        result = wsl_core.format_log_entry_from_dict(entry)
        self.assertEqual(result, "[-] 停止 | Debian | 成功")

    def test_missing_multiple_keys(self):
        """複数キーが欠けている場合もそれぞれ '-' を使う。"""
        entry = {"operation": "削除"}
        result = wsl_core.format_log_entry_from_dict(entry)
        self.assertEqual(result, "[-] 削除 | - | -")

    def test_empty_dict(self):
        """空 dict の場合はすべて '-' になる。"""
        result = wsl_core.format_log_entry_from_dict({})
        self.assertEqual(result, "[-] - | - | -")

    def test_returns_string(self):
        """戻り値は文字列型である。"""
        result = wsl_core.format_log_entry_from_dict({"timestamp": "t"})
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# rotate_log_files
# ---------------------------------------------------------------------------

class TestRotateLogFiles(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_noop_when_file_missing(self):
        """対象ファイルが存在しない場合は何もしない (例外も発生しない)。"""
        wsl_core.rotate_log_files(self.tmpdir, max_size=100)
        self.assertEqual(os.listdir(self.tmpdir), [])

    def test_noop_when_under_max_size(self):
        """ファイルサイズが上限以下の場合はローテーションしない。"""
        path = os.path.join(self.tmpdir, "operations.jsonl")
        with open(path, "wb") as f:
            f.write(b"x" * 10)
        wsl_core.rotate_log_files(self.tmpdir, max_size=100)
        self.assertTrue(os.path.exists(path))
        self.assertEqual(sorted(os.listdir(self.tmpdir)), ["operations.jsonl"])

    def test_rotates_when_over_max_size(self):
        """上限を超えると operations.jsonl が operations.1.jsonl にリネームされる。"""
        path = os.path.join(self.tmpdir, "operations.jsonl")
        with open(path, "wb") as f:
            f.write(b"x" * 200)
        wsl_core.rotate_log_files(self.tmpdir, max_size=100, max_backups=5)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "operations.1.jsonl")))

    def test_existing_backups_shift_up(self):
        """既存のバックアップ番号が1つずつ繰り上がる。"""
        base = os.path.join(self.tmpdir, "operations.jsonl")
        backup1 = os.path.join(self.tmpdir, "operations.1.jsonl")
        with open(base, "wb") as f:
            f.write(b"new" * 100)
        with open(backup1, "wb") as f:
            f.write(b"old")
        wsl_core.rotate_log_files(self.tmpdir, max_size=100, max_backups=5)
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "operations.2.jsonl")))
        with open(os.path.join(self.tmpdir, "operations.2.jsonl"), "rb") as f:
            self.assertEqual(f.read(), b"old")
        with open(backup1, "rb") as f:
            self.assertEqual(f.read(), b"new" * 100)

    def test_old_backups_beyond_max_are_deleted(self):
        """max_backups を超える番号の古いバックアップは削除される。"""
        base = os.path.join(self.tmpdir, "operations.jsonl")
        oldest = os.path.join(self.tmpdir, "operations.3.jsonl")
        with open(base, "wb") as f:
            f.write(b"x" * 200)
        with open(oldest, "wb") as f:
            f.write(b"oldest")
        wsl_core.rotate_log_files(self.tmpdir, max_size=100, max_backups=3)
        self.assertFalse(os.path.exists(oldest))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "operations.1.jsonl")))

    def test_custom_base_name(self):
        """base_name を指定すると別のファイル名でローテーションされる。"""
        path = os.path.join(self.tmpdir, "custom.log")
        with open(path, "wb") as f:
            f.write(b"x" * 200)
        wsl_core.rotate_log_files(self.tmpdir, base_name="custom.log", max_size=100)
        self.assertFalse(os.path.exists(path))
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "custom.1.log")))


# ---------------------------------------------------------------------------
# tail_entries
# ---------------------------------------------------------------------------

class TestTailEntries(unittest.TestCase):

    def test_n_less_than_len(self):
        """n が要素数未満の場合は末尾 n 件を返す。"""
        self.assertEqual(wsl_core.tail_entries([1, 2, 3, 4, 5], 2), [4, 5])

    def test_n_equal_len(self):
        """n が要素数と等しい場合は全件を返す。"""
        self.assertEqual(wsl_core.tail_entries([1, 2, 3], 3), [1, 2, 3])

    def test_n_greater_than_len(self):
        """n が要素数より大きい場合は全件を返す。"""
        self.assertEqual(wsl_core.tail_entries([1, 2, 3], 10), [1, 2, 3])

    def test_n_zero(self):
        """n が 0 の場合は空リストを返す。"""
        self.assertEqual(wsl_core.tail_entries([1, 2, 3], 0), [])

    def test_n_negative(self):
        """n が負の場合は空リストを返す。"""
        self.assertEqual(wsl_core.tail_entries([1, 2, 3], -1), [])

    def test_empty_list(self):
        """空リストに対しては常に空リストを返す。"""
        self.assertEqual(wsl_core.tail_entries([], 5), [])

    def test_does_not_mutate_original(self):
        """元のリストは変更されない。"""
        original = [1, 2, 3, 4]
        result = wsl_core.tail_entries(original, 2)
        self.assertEqual(original, [1, 2, 3, 4])
        result.append(99)
        self.assertEqual(original, [1, 2, 3, 4])

    def test_n_equal_len_returns_copy(self):
        """n が全件と一致する場合でも別オブジェクト (コピー) を返す。"""
        original = [1, 2, 3]
        result = wsl_core.tail_entries(original, 3)
        self.assertIsNot(result, original)


# ---------------------------------------------------------------------------
# validate_port_number
# ---------------------------------------------------------------------------

class TestValidatePortNumber(unittest.TestCase):

    def test_empty_string(self):
        """空文字列は無効。"""
        valid, reason = wsl_core.validate_port_number("")
        self.assertFalse(valid)
        self.assertIn("入力してください", reason)

    def test_none(self):
        """None は無効。"""
        valid, reason = wsl_core.validate_port_number(None)
        self.assertFalse(valid)
        self.assertIn("入力してください", reason)

    def test_non_integer(self):
        """整数に変換できない文字列は無効。"""
        valid, reason = wsl_core.validate_port_number("abc")
        self.assertFalse(valid)
        self.assertIn("整数", reason)

    def test_zero_out_of_range(self):
        """0 は範囲外で無効。"""
        valid, reason = wsl_core.validate_port_number("0")
        self.assertFalse(valid)
        self.assertIn("1〜65535", reason)

    def test_negative_out_of_range(self):
        """負の値は範囲外で無効。"""
        valid, reason = wsl_core.validate_port_number("-1")
        self.assertFalse(valid)
        self.assertIn("1〜65535", reason)

    def test_too_large_out_of_range(self):
        """65536 は範囲外で無効。"""
        valid, reason = wsl_core.validate_port_number("65536")
        self.assertFalse(valid)
        self.assertIn("1〜65535", reason)

    def test_valid_lower_bound(self):
        """1 は有効な下限値。"""
        valid, reason = wsl_core.validate_port_number("1")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_valid_upper_bound(self):
        """65535 は有効な上限値。"""
        valid, reason = wsl_core.validate_port_number("65535")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_valid_typical(self):
        """典型的なポート番号 8080 は有効。"""
        valid, reason = wsl_core.validate_port_number("8080")
        self.assertTrue(valid)
        self.assertEqual(reason, "")


# ---------------------------------------------------------------------------
# parse_portproxy_output
# ---------------------------------------------------------------------------

class TestParsePortproxyOutput(unittest.TestCase):

    def test_typical_output(self):
        """典型的な netsh portproxy 出力を解析する。"""
        output = (
            "Listen on ipv4:             Connect to ipv4:\n"
            "\n"
            "Address         Port        Address         Port\n"
            "--------------- ----------  --------------- ----------\n"
            "192.168.1.1     8080        172.20.0.2      8080\n"
        )
        result = wsl_core.parse_portproxy_output(output)
        self.assertEqual(
            result,
            [
                {
                    "listen_address": "192.168.1.1",
                    "listen_port": 8080,
                    "connect_address": "172.20.0.2",
                    "connect_port": 8080,
                }
            ],
        )

    def test_multiple_rules(self):
        """複数のルールがある場合はすべて解析される。"""
        output = (
            "Listen on ipv4:             Connect to ipv4:\n"
            "\n"
            "Address         Port        Address         Port\n"
            "--------------- ----------  --------------- ----------\n"
            "192.168.1.1     8080        172.20.0.2      8080\n"
            "0.0.0.0         3000        172.20.0.2      3000\n"
        )
        result = wsl_core.parse_portproxy_output(output)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["listen_port"], 3000)
        self.assertEqual(result[1]["connect_port"], 3000)

    def test_empty_output(self):
        """空文字列を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.parse_portproxy_output(""), [])

    def test_none_output(self):
        """None を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.parse_portproxy_output(None), [])

    def test_no_rules_present(self):
        """ルールが1つもない (ヘッダのみの) 出力では空リストを返す。"""
        output = (
            "Listen on ipv4:             Connect to ipv4:\n"
            "\n"
            "Address         Port        Address         Port\n"
            "--------------- ----------  --------------- ----------\n"
        )
        self.assertEqual(wsl_core.parse_portproxy_output(output), [])

    def test_port_values_are_int(self):
        """ポート番号は int 型として返される。"""
        output = (
            "Address         Port        Address         Port\n"
            "--------------- ----------  --------------- ----------\n"
            "127.0.0.1       80          172.20.0.2      8080\n"
        )
        result = wsl_core.parse_portproxy_output(output)
        self.assertIsInstance(result[0]["listen_port"], int)
        self.assertIsInstance(result[0]["connect_port"], int)


# ---------------------------------------------------------------------------
# parse_ss_output
# ---------------------------------------------------------------------------

class TestParseSsOutput(unittest.TestCase):

    def test_ipv4_entry(self):
        """IPv4 のリスニングソケットを解析する。"""
        output = (
            "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port   Process\n"
            'LISTEN   0        128      0.0.0.0:22           0.0.0.0:*           '
            'users:(("sshd",pid=1,fd=3))\n'
        )
        result = wsl_core.parse_ss_output(output)
        self.assertEqual(
            result,
            [{"state": "LISTEN", "local_address": "0.0.0.0", "local_port": 22, "process": "sshd"}],
        )

    def test_ipv6_entry(self):
        """IPv6 (角括弧表記) のリスニングソケットを解析する。"""
        output = (
            "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port   Process\n"
            'LISTEN   0        128      [::]:22              [::]:*              '
            'users:(("sshd",pid=1,fd=4))\n'
        )
        result = wsl_core.parse_ss_output(output)
        self.assertEqual(result[0]["local_address"], "::")
        self.assertEqual(result[0]["local_port"], 22)
        self.assertEqual(result[0]["process"], "sshd")

    def test_multiple_listeners(self):
        """複数のリスニングソケットをすべて解析する。"""
        output = (
            "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port   Process\n"
            'LISTEN   0        128      0.0.0.0:22           0.0.0.0:*           '
            'users:(("sshd",pid=1,fd=3))\n'
            'LISTEN   0        511      127.0.0.1:3000       0.0.0.0:*           '
            'users:(("node",pid=42,fd=18))\n'
        )
        result = wsl_core.parse_ss_output(output)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["local_address"], "127.0.0.1")
        self.assertEqual(result[1]["local_port"], 3000)
        self.assertEqual(result[1]["process"], "node")

    def test_no_process_info(self):
        """プロセス情報がない場合でもエラーにならず解析できる。"""
        output = (
            "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port\n"
            "LISTEN   0        128      0.0.0.0:80           0.0.0.0:*\n"
        )
        result = wsl_core.parse_ss_output(output)
        self.assertEqual(result[0]["local_port"], 80)
        # users:(...) パターンに一致しないため、生の文字列 (空なら "-") が使われる
        self.assertTrue(result[0]["process"])

    def test_empty_output(self):
        """空文字列を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.parse_ss_output(""), [])

    def test_none_output(self):
        """None を渡すと空リストを返す。"""
        self.assertEqual(wsl_core.parse_ss_output(None), [])

    def test_skips_header_line(self):
        """ヘッダ行 (State で始まる) はデータとして扱われない。"""
        output = "State    Recv-Q   Send-Q   Local Address:Port   Peer Address:Port   Process\n"
        self.assertEqual(wsl_core.parse_ss_output(output), [])


# ---------------------------------------------------------------------------
# detect_network_mode
# ---------------------------------------------------------------------------

class TestDetectNetworkMode(unittest.TestCase):

    def test_mirrored_mode(self):
        """networkingMode が mirrored の場合は 'mirrored' を返す。"""
        config = {"wsl2": {"networkingMode": "mirrored"}}
        self.assertEqual(wsl_core.detect_network_mode(config), "mirrored")

    def test_mirrored_mode_case_insensitive(self):
        """大文字混じりの 'Mirrored' でも 'mirrored' と判定される。"""
        config = {"wsl2": {"networkingMode": "Mirrored"}}
        self.assertEqual(wsl_core.detect_network_mode(config), "mirrored")

    def test_nat_mode(self):
        """networkingMode が nat の場合は 'nat' を返す。"""
        config = {"wsl2": {"networkingMode": "NAT"}}
        self.assertEqual(wsl_core.detect_network_mode(config), "nat")

    def test_empty_value_defaults_to_nat(self):
        """networkingMode が空文字 (未設定) の場合は 'nat' を返す (デフォルト)。"""
        config = {"wsl2": {"networkingMode": ""}}
        self.assertEqual(wsl_core.detect_network_mode(config), "nat")

    def test_missing_section_defaults_to_nat(self):
        """wsl2 セクション自体が存在しない場合も 'nat' を返す。"""
        self.assertEqual(wsl_core.detect_network_mode({}), "nat")

    def test_missing_key_defaults_to_nat(self):
        """wsl2 セクションはあるが networkingMode キーがない場合も 'nat' を返す。"""
        config = {"wsl2": {"memory": "4GB"}}
        self.assertEqual(wsl_core.detect_network_mode(config), "nat")

    def test_unknown_value_returned_lowered(self):
        """未知の値の場合はその値を小文字化してそのまま返す。"""
        config = {"wsl2": {"networkingMode": "Bridged"}}
        self.assertEqual(wsl_core.detect_network_mode(config), "bridged")


# ---------------------------------------------------------------------------
# get_default_settings_path
# ---------------------------------------------------------------------------

class TestGetDefaultSettingsPath(unittest.TestCase):

    def test_windows_uses_appdata(self):
        """Windows 環境では APPDATA 配下の WSLManager/settings.json を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\test\AppData\Roaming"}):
                result = wsl_core.get_default_settings_path()
        self.assertEqual(
            result,
            os.path.join(r"C:\Users\test\AppData\Roaming", "WSLManager", "settings.json"),
        )

    def test_windows_missing_appdata_uses_empty(self):
        """Windows 環境で APPDATA が未設定の場合は空文字を基点にする。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            env = dict(os.environ)
            env.pop("APPDATA", None)
            with mock.patch.dict(os.environ, env, clear=True):
                result = wsl_core.get_default_settings_path()
        self.assertEqual(result, os.path.join("", "WSLManager", "settings.json"))

    def test_non_windows_uses_home(self):
        """非 Windows 環境では ~/.wslmgr/settings.json を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_settings_path()
        self.assertEqual(result, os.path.expanduser("~/.wslmgr/settings.json"))

    def test_non_windows_darwin(self):
        """macOS (darwin) でも非 Windows 用パスを返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "darwin"):
            result = wsl_core.get_default_settings_path()
        self.assertEqual(result, os.path.expanduser("~/.wslmgr/settings.json"))

    def test_non_windows_returns_string(self):
        """戻り値は文字列型である。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_settings_path()
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# is_valid_geometry
# ---------------------------------------------------------------------------

class TestIsValidGeometry(unittest.TestCase):

    def test_valid_with_offsets(self):
        """"WxH+X+Y" 形式は妥当と判定される。"""
        self.assertTrue(wsl_core.is_valid_geometry("960x460+100+50"))

    def test_valid_without_offsets(self):
        """"WxH" のみの形式も妥当と判定される。"""
        self.assertTrue(wsl_core.is_valid_geometry("100x200"))

    def test_valid_negative_offsets(self):
        """負のオフセット ("+-X-Y" 形式) も妥当と判定される。"""
        self.assertTrue(wsl_core.is_valid_geometry("960x460+-10-20"))

    def test_valid_mixed_sign_offsets(self):
        """符号が混在するオフセットも妥当と判定される。"""
        self.assertTrue(wsl_core.is_valid_geometry("800x600-5+5"))

    def test_invalid_empty_string(self):
        """空文字は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry(""))

    def test_invalid_none(self):
        """None は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry(None))

    def test_invalid_non_string_type(self):
        """int など str 以外の型は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry(123))

    def test_invalid_missing_height(self):
        """高さが欠けている場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("960x"))

    def test_invalid_missing_width(self):
        """幅が欠けている場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("x460+1+1"))

    def test_invalid_zero_width(self):
        """幅が 0 の場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("0x100+1+1"))

    def test_invalid_zero_height(self):
        """高さが 0 の場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("100x0"))

    def test_invalid_incomplete_offset(self):
        """オフセットが X のみで Y が欠けている場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("960x460+1"))

    def test_invalid_not_geometry_string(self):
        """ジオメトリ形式でない文字列は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("abc"))

    def test_invalid_extra_offset(self):
        """オフセットが3つ以上ある場合は無効。"""
        self.assertFalse(wsl_core.is_valid_geometry("960x460+1+1+1"))


# ---------------------------------------------------------------------------
# normalize_settings
# ---------------------------------------------------------------------------

class TestNormalizeSettings(unittest.TestCase):

    def test_non_dict_returns_defaults(self):
        """dict でない入力の場合はデフォルト値を返す。"""
        for value in (None, "text", 123, [1, 2, 3]):
            with self.subTest(value=value):
                self.assertEqual(wsl_core.normalize_settings(value), wsl_core.DEFAULT_SETTINGS)

    def test_empty_dict_returns_defaults(self):
        """空 dict の場合はデフォルト値を返す。"""
        self.assertEqual(wsl_core.normalize_settings({}), wsl_core.DEFAULT_SETTINGS)

    def test_full_valid_dict_roundtrips(self):
        """すべてのキーが妥当な値であればそのまま維持される。"""
        data = {
            "schema_version": 1,
            "theme": "clam",
            "auto_refresh": True,
            "window_geometry": "800x600+10+20",
            "sort_column": "name",
            "sort_desc": True,
            "snapshot_dir": "/mnt/snapshots",
        }
        self.assertEqual(wsl_core.normalize_settings(data), data)

    def test_invalid_theme_type_falls_back(self):
        """theme が str 以外の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"theme": 123})
        self.assertEqual(result["theme"], wsl_core.DEFAULT_SETTINGS["theme"])

    def test_empty_theme_falls_back(self):
        """theme が空文字の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"theme": ""})
        self.assertEqual(result["theme"], wsl_core.DEFAULT_SETTINGS["theme"])

    def test_invalid_auto_refresh_type_falls_back(self):
        """auto_refresh が bool 以外 (文字列 "true" など) の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"auto_refresh": "true"})
        self.assertEqual(result["auto_refresh"], wsl_core.DEFAULT_SETTINGS["auto_refresh"])

    def test_auto_refresh_int_falls_back(self):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """auto_refresh が int (bool のサブクラスでも True/False 以外扱いされない値) の場合を確認する。"""  # noqa: E501
        result = wsl_core.normalize_settings({"auto_refresh": 1})
        self.assertEqual(result["auto_refresh"], wsl_core.DEFAULT_SETTINGS["auto_refresh"])

    def test_invalid_geometry_falls_back(self):
        """window_geometry が不正な形式の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"window_geometry": "invalid"})
        self.assertEqual(result["window_geometry"], wsl_core.DEFAULT_SETTINGS["window_geometry"])

    def test_invalid_sort_column_type_falls_back(self):
        """sort_column が空文字の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"sort_column": ""})
        self.assertEqual(result["sort_column"], wsl_core.DEFAULT_SETTINGS["sort_column"])

    def test_invalid_sort_desc_type_falls_back(self):
        """sort_desc が int (1) の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"sort_desc": 1})
        self.assertEqual(result["sort_desc"], wsl_core.DEFAULT_SETTINGS["sort_desc"])

    def test_valid_snapshot_dir_kept(self):
        """snapshot_dir が非空文字列であればそのまま維持される。"""
        result = wsl_core.normalize_settings({"snapshot_dir": "/mnt/snapshots"})
        self.assertEqual(result["snapshot_dir"], "/mnt/snapshots")

    def test_none_snapshot_dir_falls_back(self):
        """snapshot_dir が None の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"snapshot_dir": None})
        self.assertEqual(result["snapshot_dir"], wsl_core.DEFAULT_SETTINGS["snapshot_dir"])

    def test_empty_snapshot_dir_falls_back(self):
        """snapshot_dir が空文字の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"snapshot_dir": ""})
        self.assertEqual(result["snapshot_dir"], wsl_core.DEFAULT_SETTINGS["snapshot_dir"])

    def test_invalid_snapshot_dir_type_falls_back(self):
        """snapshot_dir が str 以外の場合はデフォルト値になる。"""
        result = wsl_core.normalize_settings({"snapshot_dir": 123})
        self.assertEqual(result["snapshot_dir"], wsl_core.DEFAULT_SETTINGS["snapshot_dir"])

    def test_default_settings_has_snapshot_dir_key(self):
        """DEFAULT_SETTINGS に snapshot_dir キーが存在し None である。"""
        self.assertIn("snapshot_dir", wsl_core.DEFAULT_SETTINGS)
        self.assertIsNone(wsl_core.DEFAULT_SETTINGS["snapshot_dir"])

    def test_unknown_keys_dropped(self):
        """未知のキーは結果に含まれない。"""
        result = wsl_core.normalize_settings({"theme": "clam", "unknown_key": "value"})
        self.assertNotIn("unknown_key", result)
        self.assertEqual(set(result.keys()), set(wsl_core.DEFAULT_SETTINGS.keys()))

    def test_input_not_mutated(self):
        """引数の dict は変更されない。"""
        data = {"theme": "clam"}
        original = dict(data)
        wsl_core.normalize_settings(data)
        self.assertEqual(data, original)

    def test_result_is_new_object_not_sharing_default(self):
        """戻り値を変更しても DEFAULT_SETTINGS は変化しない。"""
        result = wsl_core.normalize_settings({})
        result["theme"] = "mutated"
        self.assertIsNone(wsl_core.DEFAULT_SETTINGS["theme"])


# ---------------------------------------------------------------------------
# load_settings / save_settings
# ---------------------------------------------------------------------------

class TestLoadSettings(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_returns_defaults(self):
        """ファイルが存在しない場合はデフォルト値を返す。"""
        path = os.path.join(self.tmpdir, "no_such.json")
        self.assertEqual(wsl_core.load_settings(path), wsl_core.DEFAULT_SETTINGS)

    def test_broken_json_returns_defaults(self):
        """JSON として不正な内容の場合はデフォルト値を返す。"""
        path = os.path.join(self.tmpdir, "broken.json")
        with open(path, "w", encoding="utf-8") as f:
            f.write("{not valid json")
        self.assertEqual(wsl_core.load_settings(path), wsl_core.DEFAULT_SETTINGS)

    def test_json_array_returns_defaults(self):
        """JSON が dict でない (配列など) 場合はデフォルト値を返す。"""
        path = os.path.join(self.tmpdir, "array.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump([1, 2, 3], f)
        self.assertEqual(wsl_core.load_settings(path), wsl_core.DEFAULT_SETTINGS)

    def test_valid_file_returns_normalized_values(self):
        """妥当な内容のファイルは正規化された値で返される。"""
        path = os.path.join(self.tmpdir, "settings.json")
        data = {
            "schema_version": 1,
            "theme": "clam",
            "auto_refresh": True,
            "window_geometry": "800x600+10+20",
            "sort_column": "name",
            "sort_desc": True,
            "snapshot_dir": "/mnt/snapshots",
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertEqual(wsl_core.load_settings(path), data)


class TestSaveSettings(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_nested_directory(self):
        """保存先の親ディレクトリが存在しない場合は作成される。"""
        path = os.path.join(self.tmpdir, "nested", "dir", "settings.json")
        result = wsl_core.save_settings(path, {"theme": "clam"})
        self.assertTrue(result)
        self.assertTrue(os.path.exists(path))

    def test_saved_file_is_valid_json_with_all_keys(self):
        """保存されたファイルは全キーを含む妥当な JSON である。"""
        path = os.path.join(self.tmpdir, "settings.json")
        wsl_core.save_settings(path, {"theme": "clam"})
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(set(data.keys()), set(wsl_core.DEFAULT_SETTINGS.keys()))

    def test_roundtrip_preserves_values(self):
        """save_settings で保存した内容を load_settings で読み戻すと一致する。"""
        path = os.path.join(self.tmpdir, "settings.json")
        data = {
            "schema_version": 1,
            "theme": "alt",
            "auto_refresh": True,
            "window_geometry": "960x460+0+0",
            "sort_column": "state",
            "sort_desc": False,
            "snapshot_dir": "/mnt/snapshots",
        }
        wsl_core.save_settings(path, data)
        self.assertEqual(wsl_core.load_settings(path), data)

    def test_returns_true_on_success(self):
        """保存に成功した場合は True を返す。"""
        path = os.path.join(self.tmpdir, "settings.json")
        result = wsl_core.save_settings(path, {})
        self.assertTrue(result)

    def test_returns_false_when_path_unwritable(self):
        """親ディレクトリの位置に既存ファイルがあり書き込み不能な場合は False を返す。"""
        blocker = os.path.join(self.tmpdir, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("dummy")
        path = os.path.join(blocker, "settings.json")
        result = wsl_core.save_settings(path, {})
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# atomic_write_text
# ---------------------------------------------------------------------------

class TestAtomicWriteText(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_content_to_new_file(self):
        """新規ファイルへの書き込みが読み戻せる。"""
        path = os.path.join(self.tmpdir, "out.txt")
        result = wsl_core.atomic_write_text(path, "hello world")
        self.assertTrue(result)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "hello world")

    def test_replaces_existing_file(self):
        """既存ファイルは新しい内容で完全に置き換えられる。"""
        path = os.path.join(self.tmpdir, "out.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("old content that is longer than new")
        result = wsl_core.atomic_write_text(path, "new")
        self.assertTrue(result)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "new")

    def test_no_partial_file_left_in_dir_on_success(self):
        """成功後、ディレクトリ内には対象ファイルのみが残る（一時ファイルは残らない）。"""
        path = os.path.join(self.tmpdir, "out.txt")
        wsl_core.atomic_write_text(path, "content")
        self.assertEqual(os.listdir(self.tmpdir), ["out.txt"])

    def test_returns_false_when_dir_uncreatable(self):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """親ディレクトリの位置に既存ファイルがある場合は False を返し、対象ファイルは変化しない。"""  # noqa: E501
        blocker = os.path.join(self.tmpdir, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("dummy")
        path = os.path.join(blocker, "out.txt")
        result = wsl_core.atomic_write_text(path, "content")
        self.assertFalse(result)
        self.assertTrue(os.path.isfile(blocker))

    def test_does_not_truncate_existing_on_write_error(self):
        """os.replace が失敗しても既存ファイルは元の内容のまま残り、一時ファイルも残らない。"""
        path = os.path.join(self.tmpdir, "out.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write("original content")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            result = wsl_core.atomic_write_text(path, "new content")
        self.assertFalse(result)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "original content")
        remaining = os.listdir(self.tmpdir)
        self.assertEqual(remaining, ["out.txt"])


# ---------------------------------------------------------------------------
# save_wslconfig
# ---------------------------------------------------------------------------

class TestSaveWslconfig(unittest.TestCase):
    """save_wslconfig (#25: .wslconfig をアトミックに保存する合成 API) のテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_writes_dumped_sections(self):
        """sections を dump_wslconfig した内容がそのままファイルに書き込まれる。"""
        path = os.path.join(self.tmpdir, ".wslconfig")
        sections = {"wsl2": {"memory": "4GB"}}
        result = wsl_core.save_wslconfig(path, sections)
        self.assertTrue(result)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), wsl_core.dump_wslconfig(sections))

    def test_round_trip_via_parse(self):
        """保存した内容を parse_wslconfig で読み戻すと元の sections と一致する。"""
        path = os.path.join(self.tmpdir, ".wslconfig")
        sections = {"wsl2": {"memory": "4GB", "localhostForwarding": "true"}}
        wsl_core.save_wslconfig(path, sections)
        with open(path, encoding="utf-8") as f:
            reparsed = wsl_core.parse_wslconfig(f.read())
        self.assertEqual(reparsed, sections)

    def test_does_not_truncate_existing_on_write_error(self):
        """書き込み中の失敗で既存の .wslconfig が 0 バイトや途中状態にならない (#25)。"""
        path = os.path.join(self.tmpdir, ".wslconfig")
        with open(path, "w", encoding="utf-8") as f:
            f.write("[wsl2]\nmemory=2GB\n")
        with mock.patch("os.replace", side_effect=OSError("boom")):
            result = wsl_core.save_wslconfig(path, {"wsl2": {"memory": "8GB"}})
        self.assertFalse(result)
        with open(path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "[wsl2]\nmemory=2GB\n")

    def test_returns_false_when_dir_uncreatable(self):
        """保存先ディレクトリが作成できない場合は False を返す。"""
        blocker = os.path.join(self.tmpdir, "blocker")
        with open(blocker, "w", encoding="utf-8") as f:
            f.write("dummy")
        path = os.path.join(blocker, ".wslconfig")
        result = wsl_core.save_wslconfig(path, {"wsl2": {"memory": "4GB"}})
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# estimate_transfer_progress
# ---------------------------------------------------------------------------

class TestEstimateTransferProgress(unittest.TestCase):

    def test_normal_progress(self):
        """途中経過の進捗率を計算する。"""
        self.assertEqual(wsl_core.estimate_transfer_progress(50, 200), 25.0)

    def test_zero_current(self):
        """転送前は 0.0 を返す。"""
        self.assertEqual(wsl_core.estimate_transfer_progress(0, 100), 0.0)

    def test_caps_at_100(self):
        """current が total を超えても 100.0 で頭打ちにする。"""
        self.assertEqual(wsl_core.estimate_transfer_progress(300, 200), 100.0)

    def test_negative_current_treated_as_zero(self):
        """current が負の場合は 0 として扱う。"""
        self.assertEqual(wsl_core.estimate_transfer_progress(-10, 100), 0.0)

    def test_none_total_returns_none(self):
        """total が None の場合は None を返す。"""
        self.assertIsNone(wsl_core.estimate_transfer_progress(50, None))

    def test_zero_total_returns_none(self):
        """total が 0 以下の場合は None を返す。"""
        self.assertIsNone(wsl_core.estimate_transfer_progress(50, 0))
        self.assertIsNone(wsl_core.estimate_transfer_progress(50, -1))


# ---------------------------------------------------------------------------
# estimate_remaining_seconds
# ---------------------------------------------------------------------------

class TestEstimateRemainingSeconds(unittest.TestCase):

    def test_linear_estimate(self):
        """平均速度から残り時間を線形推定する。"""
        # 10秒で100バイト → 10バイト/秒。残り300バイト → 30秒
        self.assertAlmostEqual(
            wsl_core.estimate_remaining_seconds(100, 400, 10), 30.0
        )

    def test_completed_returns_zero(self):
        """current が total 以上なら 0.0 を返す。"""
        self.assertEqual(wsl_core.estimate_remaining_seconds(400, 400, 10), 0.0)
        self.assertEqual(wsl_core.estimate_remaining_seconds(500, 400, 10), 0.0)

    def test_none_total_returns_none(self):
        """total が不明なら None を返す。"""
        self.assertIsNone(wsl_core.estimate_remaining_seconds(100, None, 10))

    def test_zero_elapsed_returns_none(self):
        """経過時間が 0 以下なら速度を計算できないため None を返す。"""
        self.assertIsNone(wsl_core.estimate_remaining_seconds(100, 400, 0))

    def test_zero_current_returns_none(self):
        """転送が始まっていない場合は None を返す。"""
        self.assertIsNone(wsl_core.estimate_remaining_seconds(0, 400, 10))


# ---------------------------------------------------------------------------
# format_duration
# ---------------------------------------------------------------------------

class TestFormatDuration(unittest.TestCase):

    def test_seconds_only(self):
        self.assertEqual(wsl_core.format_duration(5), "0:05")

    def test_minutes_and_seconds(self):
        self.assertEqual(wsl_core.format_duration(83), "1:23")

    def test_hours(self):
        self.assertEqual(wsl_core.format_duration(3723), "1:02:03")

    def test_negative_treated_as_zero(self):
        self.assertEqual(wsl_core.format_duration(-10), "0:00")

    def test_float_truncated(self):
        self.assertEqual(wsl_core.format_duration(59.9), "0:59")


# ---------------------------------------------------------------------------
# format_transfer_status
# ---------------------------------------------------------------------------

class TestFormatTransferStatus(unittest.TestCase):

    def test_with_total(self):
        """total が分かる場合はサイズ・進捗率・経過・残り時間を含む。"""
        # 10秒で 1 GiB / 4 GiB → 25%、残り 30 秒
        gib = 1024 ** 3
        result = wsl_core.format_transfer_status(gib, 4 * gib, 10)
        self.assertIn("1.0 GiB / 4.0 GiB", result)
        self.assertIn("(25.0%)", result)
        self.assertIn("経過 0:10", result)
        self.assertIn("残り約 0:30", result)

    def test_without_total(self):
        """total が不明な場合は書き込み済みサイズと経過時間のみ。"""
        result = wsl_core.format_transfer_status(1024 ** 2, None, 65)
        self.assertIn("1.0 MiB 書き込み済み", result)
        self.assertIn("経過 1:05", result)
        self.assertNotIn("残り", result)

    def test_no_remaining_before_transfer_starts(self):
        """転送開始前 (current=0) は残り時間を表示しない。"""
        result = wsl_core.format_transfer_status(0, 100, 5)
        self.assertIn("(0.0%)", result)
        self.assertNotIn("残り", result)


# ---------------------------------------------------------------------------
# validate_wslconf_bool
# ---------------------------------------------------------------------------

class TestValidateWslconfBool(unittest.TestCase):

    def test_empty_is_valid(self):
        """空文字列は未設定として有効。"""
        valid, reason = wsl_core.validate_wslconf_bool("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_true_is_valid(self):
        """"true" は有効。"""
        valid, reason = wsl_core.validate_wslconf_bool("true")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_false_is_valid(self):
        """"false" は有効。"""
        valid, reason = wsl_core.validate_wslconf_bool("false")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_uppercase_is_invalid(self):
        """大文字を含む "True" は無効 (true/false のみ許可)。"""
        valid, reason = wsl_core.validate_wslconf_bool("True")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_other_string_is_invalid(self):
        """true/false 以外の文字列は無効。"""
        valid, reason = wsl_core.validate_wslconf_bool("yes")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_numeric_string_is_invalid(self):
        """数値文字列は無効。"""
        valid, reason = wsl_core.validate_wslconf_bool("1")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")


# ---------------------------------------------------------------------------
# validate_linux_username
# ---------------------------------------------------------------------------

class TestValidateLinuxUsername(unittest.TestCase):

    def test_empty_is_valid(self):
        """空文字列は未設定として有効。"""
        valid, reason = wsl_core.validate_linux_username("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_typical_name_is_valid(self):
        """通常のユーザー名は有効。"""
        valid, reason = wsl_core.validate_linux_username("ubuntu")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_underscore_prefix_is_valid(self):
        """アンダースコアで始まる名前は有効。"""
        valid, reason = wsl_core.validate_linux_username("_daemon")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_with_digits_and_hyphen_is_valid(self):
        """数字・ハイフンを含む名前は有効。"""
        valid, reason = wsl_core.validate_linux_username("user-01")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_starts_with_digit_is_invalid(self):
        """数字で始まる名前は無効。"""
        valid, reason = wsl_core.validate_linux_username("1user")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_uppercase_is_invalid(self):
        """大文字を含む名前は無効。"""
        valid, reason = wsl_core.validate_linux_username("User")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_invalid_character_is_invalid(self):
        """使用できない記号を含む名前は無効。"""
        valid, reason = wsl_core.validate_linux_username("user.name")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_too_long_is_invalid(self):
        """33文字以上の名前は無効。"""
        valid, reason = wsl_core.validate_linux_username("a" * 33)
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_max_length_is_valid(self):
        """32文字の名前は有効。"""
        valid, reason = wsl_core.validate_linux_username("a" * 32)
        self.assertTrue(valid)
        self.assertEqual(reason, "")


# ---------------------------------------------------------------------------
# validate_mount_root
# ---------------------------------------------------------------------------

class TestValidateMountRoot(unittest.TestCase):

    def test_empty_is_valid(self):
        """空文字列は未設定として有効。"""
        valid, reason = wsl_core.validate_mount_root("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_typical_path_is_valid(self):
        """典型的なマウント先は有効。"""
        valid, reason = wsl_core.validate_mount_root("/mnt/")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_root_only_is_valid(self):
        """ルートのみの指定も有効。"""
        valid, reason = wsl_core.validate_mount_root("/")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_relative_path_is_invalid(self):
        """相対パスは無効。"""
        valid, reason = wsl_core.validate_mount_root("mnt/")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_windows_style_path_is_invalid(self):
        """Windows 形式のパスは無効。"""
        valid, reason = wsl_core.validate_mount_root("C:\\mnt")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")


# ---------------------------------------------------------------------------
# validate_hostname
# ---------------------------------------------------------------------------

class TestValidateHostname(unittest.TestCase):

    def test_empty_is_valid(self):
        """空文字列は未設定として有効。"""
        valid, reason = wsl_core.validate_hostname("")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_simple_hostname_is_valid(self):
        """単純なホスト名は有効。"""
        valid, reason = wsl_core.validate_hostname("my-host")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_fqdn_is_valid(self):
        """FQDN 形式 (複数ラベル) も有効。"""
        valid, reason = wsl_core.validate_hostname("host.example.com")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_single_char_label_is_valid(self):
        """1文字のラベルも有効。"""
        valid, reason = wsl_core.validate_hostname("a")
        self.assertTrue(valid)
        self.assertEqual(reason, "")

    def test_leading_hyphen_is_invalid(self):
        """ハイフンで始まるラベルは無効。"""
        valid, reason = wsl_core.validate_hostname("-host")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_trailing_hyphen_is_invalid(self):
        """ハイフンで終わるラベルは無効。"""
        valid, reason = wsl_core.validate_hostname("host-")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_underscore_is_invalid(self):
        """アンダースコアを含む名前は無効。"""
        valid, reason = wsl_core.validate_hostname("my_host")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_consecutive_dots_is_invalid(self):
        """連続するドット（空ラベル）は無効。"""
        valid, reason = wsl_core.validate_hostname("host..example")
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")

    def test_too_long_is_invalid(self):
        """254文字以上のホスト名は無効。"""
        valid, reason = wsl_core.validate_hostname("a" * 254)
        self.assertFalse(valid)
        self.assertNotEqual(reason, "")


# ---------------------------------------------------------------------------
# get_default_snapshot_dir
# ---------------------------------------------------------------------------

class TestGetDefaultSnapshotDir(unittest.TestCase):

    def test_windows_uses_userprofile(self):
        """Windows 環境では USERPROFILE 配下の WSLSnapshots を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            with mock.patch.dict(os.environ, {"USERPROFILE": r"C:\Users\test"}):
                result = wsl_core.get_default_snapshot_dir()
        self.assertEqual(result, os.path.join(r"C:\Users\test", "WSLSnapshots"))

    def test_windows_missing_userprofile_uses_empty(self):
        """Windows 環境で USERPROFILE が未設定の場合は空文字を基点にする。"""
        with mock.patch.object(wsl_core.sys, "platform", "win32"):
            env = dict(os.environ)
            env.pop("USERPROFILE", None)
            with mock.patch.dict(os.environ, env, clear=True):
                result = wsl_core.get_default_snapshot_dir()
        self.assertEqual(result, os.path.join("", "WSLSnapshots"))

    def test_non_windows_uses_home(self):
        """非 Windows 環境では ~/WSLSnapshots を返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_snapshot_dir()
        self.assertEqual(result, os.path.expanduser("~/WSLSnapshots"))

    def test_non_windows_darwin(self):
        """macOS (darwin) でも非 Windows 用パスを返す。"""
        with mock.patch.object(wsl_core.sys, "platform", "darwin"):
            result = wsl_core.get_default_snapshot_dir()
        self.assertEqual(result, os.path.expanduser("~/WSLSnapshots"))

    def test_non_windows_returns_string(self):
        """戻り値は文字列型である。"""
        with mock.patch.object(wsl_core.sys, "platform", "linux"):
            result = wsl_core.get_default_snapshot_dir()
        self.assertIsInstance(result, str)


# ---------------------------------------------------------------------------
# sanitize_snapshot_name
# ---------------------------------------------------------------------------

class TestSanitizeSnapshotName(unittest.TestCase):

    def test_normal_name_unchanged(self):
        """通常のディストリ名はそのまま維持される。"""
        self.assertEqual(wsl_core.sanitize_snapshot_name("Ubuntu-22.04"), "Ubuntu-22.04")

    def test_forbidden_chars_replaced(self):
        """禁止文字はすべて _ に置換される。"""
        result = wsl_core.sanitize_snapshot_name('a\\b/c:d*e?f"g<h>i|j')
        self.assertEqual(result, "a_b_c_d_e_f_g_h_i_j")

    def test_whitespace_replaced(self):
        """空白文字は _ に置換される。"""
        result = wsl_core.sanitize_snapshot_name("my distro name")
        self.assertEqual(result, "my_distro_name")

    def test_control_chars_replaced(self):
        """制御文字は _ に置換される。"""
        result = wsl_core.sanitize_snapshot_name("a\tb\nc\x01d")
        self.assertEqual(result, "a_b_c_d")

    def test_leading_trailing_underscore_stripped(self):
        """前後に生成された _ は除去される。"""
        result = wsl_core.sanitize_snapshot_name("/Ubuntu/")
        self.assertEqual(result, "Ubuntu")

    def test_empty_result_falls_back_to_distro(self):
        """結果が空文字列になる場合は "distro" を返す。"""
        result = wsl_core.sanitize_snapshot_name("///")
        self.assertEqual(result, "distro")

    def test_empty_input_falls_back_to_distro(self):
        """空文字列の入力の場合も "distro" を返す。"""
        self.assertEqual(wsl_core.sanitize_snapshot_name(""), "distro")


# ---------------------------------------------------------------------------
# build_snapshot_basename
# ---------------------------------------------------------------------------

class TestBuildSnapshotBasename(unittest.TestCase):

    def test_combines_sanitized_name_and_timestamp(self):
        """サニタイズされた名前とタイムスタンプを _ で結合する。"""
        result = wsl_core.build_snapshot_basename("Ubuntu", "20260101-120000")
        self.assertEqual(result, "Ubuntu_20260101-120000")

    def test_sanitizes_forbidden_chars_in_name(self):
        """ディストリ名の禁止文字はサニタイズされる。"""
        result = wsl_core.build_snapshot_basename("my distro", "20260101-120000")
        self.assertEqual(result, "my_distro_20260101-120000")

    def test_no_extension_appended(self):
        """拡張子は付与されない。"""
        result = wsl_core.build_snapshot_basename("Ubuntu", "20260101-120000")
        self.assertNotIn(".", result.replace("20260101-120000", "").rstrip("_"))


# ---------------------------------------------------------------------------
# build_snapshot_metadata
# ---------------------------------------------------------------------------

class TestBuildSnapshotMetadata(unittest.TestCase):

    def test_returns_all_six_keys(self):
        """指定したキー（schema_version 含む）をすべて含む dict を返す。"""
        result = wsl_core.build_snapshot_metadata(
            "Ubuntu", "2", "テスト", 12345, "2026-01-01T00:00:00", "Ubuntu_20260101.tar"
        )
        self.assertEqual(
            set(result.keys()),
            {
                "schema_version",
                "distro_name",
                "wsl_version",
                "comment",
                "size_bytes",
                "created_at",
                "tar_file",
            },
        )

    def test_values_pass_through_unchanged(self):
        """渡した値がそのまま格納される。"""
        result = wsl_core.build_snapshot_metadata(
            "Debian", "1", "備考", 999, "2026-02-02T03:04:05", "Debian_x.tar"
        )
        self.assertEqual(result["distro_name"], "Debian")
        self.assertEqual(result["wsl_version"], "1")
        self.assertEqual(result["comment"], "備考")
        self.assertEqual(result["size_bytes"], 999)
        self.assertEqual(result["created_at"], "2026-02-02T03:04:05")
        self.assertEqual(result["tar_file"], "Debian_x.tar")


# ---------------------------------------------------------------------------
# normalize_snapshot_metadata
# ---------------------------------------------------------------------------

class TestNormalizeSnapshotMetadata(unittest.TestCase):

    def test_valid_data_passthrough(self):
        """妥当なデータはそのまま維持される。"""
        data = {
            "schema_version": 1,
            "distro_name": "Ubuntu",
            "wsl_version": "2",
            "comment": "コメント",
            "size_bytes": 1000,
            "created_at": "2026-01-01T00:00:00",
            "tar_file": "Ubuntu_20260101.tar",
        }
        self.assertEqual(wsl_core.normalize_snapshot_metadata(data), data)

    def test_non_dict_returns_none(self):
        """dict でない入力の場合は None を返す。"""
        for value in (None, "text", 123, [1, 2, 3]):
            with self.subTest(value=value):
                self.assertIsNone(wsl_core.normalize_snapshot_metadata(value))

    def test_missing_distro_name_returns_none(self):
        """distro_name が欠落している場合は None を返す。"""
        data = {"tar_file": "a.tar"}
        self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_empty_distro_name_returns_none(self):
        """distro_name が空文字の場合は None を返す。"""
        data = {"distro_name": "", "tar_file": "a.tar"}
        self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_non_str_distro_name_returns_none(self):
        """distro_name が文字列でない場合は None を返す。"""
        data = {"distro_name": 123, "tar_file": "a.tar"}
        self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_missing_tar_file_returns_none(self):
        """tar_file が欠落している場合は None を返す。"""
        data = {"distro_name": "Ubuntu"}
        self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_empty_tar_file_returns_none(self):
        """tar_file が空文字の場合は None を返す。"""
        data = {"distro_name": "Ubuntu", "tar_file": ""}
        self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_tar_file_with_path_separator_returns_none(self):
        """tar_file にパス区切りや ".." を含む場合は None を返す (パストラバーサル対策)。"""
        for tar_file in (
            "../evil.tar",
            "..\\evil.tar",
            "sub/evil.tar",
            "sub\\evil.tar",
            "/etc/passwd",
            "C:\\Windows\\evil.tar",
            ".",
            "..",
        ):
            with self.subTest(tar_file=tar_file):
                data = {"distro_name": "Ubuntu", "tar_file": tar_file}
                self.assertIsNone(wsl_core.normalize_snapshot_metadata(data))

    def test_wsl_version_int_converted_to_str(self):
        """wsl_version が int (1, 2) の場合は文字列に変換される。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "wsl_version": 2}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["wsl_version"], "2")

    def test_wsl_version_valid_str_kept(self):
        """wsl_version が文字列 "1"/"2" の場合はそのまま維持される。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "wsl_version": "1"}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["wsl_version"], "1")

    def test_wsl_version_invalid_falls_back_to_empty(self):
        """wsl_version が不正な値の場合は空文字になる。"""
        for value in ("3", 3, None, 1.5, "two"):
            with self.subTest(value=value):
                data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "wsl_version": value}
                result = wsl_core.normalize_snapshot_metadata(data)
                self.assertEqual(result["wsl_version"], "")

    def test_wsl_version_bool_falls_back_to_empty(self):
        """wsl_version が bool の場合は int として扱われず空文字になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "wsl_version": True}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["wsl_version"], "")

    def test_non_str_comment_falls_back_to_empty(self):
        """comment が文字列でない場合は空文字になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "comment": 123}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["comment"], "")

    def test_non_str_created_at_falls_back_to_empty(self):
        """created_at が文字列でない場合は空文字になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "created_at": 123}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["created_at"], "")

    def test_bool_size_bytes_falls_back_to_zero(self):
        """size_bytes が bool の場合は int として扱われず 0 になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "size_bytes": True}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["size_bytes"], 0)

    def test_negative_size_bytes_falls_back_to_zero(self):
        """size_bytes が負の値の場合は 0 になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "size_bytes": -5}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["size_bytes"], 0)

    def test_non_int_size_bytes_falls_back_to_zero(self):
        """size_bytes が int でない場合は 0 になる。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar", "size_bytes": "1000"}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(result["size_bytes"], 0)

    def test_result_has_exactly_six_keys(self):
        """戻り値のキーは schema_version を含み 7 個である。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar"}
        result = wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(
            set(result.keys()),
            {
                "schema_version",
                "distro_name",
                "wsl_version",
                "comment",
                "size_bytes",
                "created_at",
                "tar_file",
            },
        )

    def test_input_not_mutated(self):
        """引数の dict は変更されない。"""
        data = {"distro_name": "Ubuntu", "tar_file": "a.tar"}
        original = dict(data)
        wsl_core.normalize_snapshot_metadata(data)
        self.assertEqual(data, original)


# ---------------------------------------------------------------------------
# load_snapshots
# ---------------------------------------------------------------------------

class TestLoadSnapshots(unittest.TestCase):

    def _write_json(self, dir_path, filename, data):
        path = os.path.join(dir_path, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_valid_json_with_tar_exists_true(self):
        """対応する tar ファイルが存在する場合は tar_exists が True になる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_json(
                tmpdir,
                "a.json",
                {
                    "distro_name": "Ubuntu",
                    "tar_file": "a.tar",
                    "created_at": "2026-01-01T00:00:00",
                },
            )
            open(os.path.join(tmpdir, "a.tar"), "w").close()
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual(len(result), 1)
        self.assertTrue(result[0]["tar_exists"])
        self.assertEqual(result[0]["json_path"], os.path.join(tmpdir, "a.json"))
        self.assertEqual(result[0]["tar_path"], os.path.join(tmpdir, "a.tar"))

    def test_valid_json_without_tar_exists_false(self):
        """対応する tar ファイルが存在しない場合は tar_exists が False になる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_json(
                tmpdir, "a.json", {"distro_name": "Ubuntu", "tar_file": "missing.tar"}
            )
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0]["tar_exists"])

    def test_broken_json_skipped(self):
        """壊れた JSON ファイルは読み飛ばされる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with open(os.path.join(tmpdir, "broken.json"), "w", encoding="utf-8") as f:
                f.write("{not valid json")
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual(result, [])

    def test_normalizes_to_none_skipped(self):
        """正規化できないデータのファイルは読み飛ばされる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_json(tmpdir, "invalid.json", {"comment": "no distro_name or tar_file"})
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual(result, [])

    def test_non_json_files_ignored(self):
        """.json 以外のファイルは無視される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "note.txt"), "w").close()
            open(os.path.join(tmpdir, "a.tar"), "w").close()
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual(result, [])

    def test_sorted_by_created_at_descending(self):
        """created_at の降順にソートされる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_json(
                tmpdir,
                "old.json",
                {
                    "distro_name": "Ubuntu",
                    "tar_file": "old.tar",
                    "created_at": "2026-01-01T00:00:00",
                },
            )
            self._write_json(
                tmpdir,
                "new.json",
                {
                    "distro_name": "Ubuntu",
                    "tar_file": "new.tar",
                    "created_at": "2026-06-01T00:00:00",
                },
            )
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual([entry["tar_file"] for entry in result], ["new.tar", "old.tar"])

    def test_missing_created_at_sorts_last(self):
        """created_at が空のエントリは末尾にソートされる。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            self._write_json(
                tmpdir,
                "has_date.json",
                {
                    "distro_name": "Ubuntu",
                    "tar_file": "has_date.tar",
                    "created_at": "2026-01-01T00:00:00",
                },
            )
            self._write_json(
                tmpdir, "no_date.json", {"distro_name": "Ubuntu", "tar_file": "no_date.tar"}
            )
            result = wsl_core.load_snapshots(tmpdir)
        self.assertEqual([entry["tar_file"] for entry in result], ["has_date.tar", "no_date.tar"])

    def test_nonexistent_dir_returns_empty_list(self):
        """存在しないディレクトリを指定した場合は空リストを返す。"""
        result = wsl_core.load_snapshots("/no/such/directory/for/wslmgr/tests")
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# total_snapshots_size
# ---------------------------------------------------------------------------

class TestTotalSnapshotsSize(unittest.TestCase):

    def test_sums_existing_tar_sizes_only(self):
        """tar_exists が True のエントリのみ合計する。"""
        snapshots = [
            {"size_bytes": 100, "tar_exists": True},
            {"size_bytes": 200, "tar_exists": False},
            {"size_bytes": 300, "tar_exists": True},
        ]
        self.assertEqual(wsl_core.total_snapshots_size(snapshots), 400)

    def test_missing_tar_exists_key_treated_as_true(self):
        """tar_exists キーが無いエントリは True として扱われる。"""
        snapshots = [{"size_bytes": 50}]
        self.assertEqual(wsl_core.total_snapshots_size(snapshots), 50)

    def test_empty_list_returns_zero(self):
        """空リストの場合は 0 を返す。"""
        self.assertEqual(wsl_core.total_snapshots_size([]), 0)

    def test_invalid_size_bytes_contributes_zero(self):
        """size_bytes が非負整数でない場合は 0 として扱われる。"""
        snapshots = [
            {"size_bytes": -10, "tar_exists": True},
            {"size_bytes": "100", "tar_exists": True},
            {"size_bytes": 100, "tar_exists": True},
        ]
        self.assertEqual(wsl_core.total_snapshots_size(snapshots), 100)


# ---------------------------------------------------------------------------
# write_snapshot_metadata
# ---------------------------------------------------------------------------

class TestWriteSnapshotMetadata(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_nested_directory(self):
        """保存先の親ディレクトリが存在しない場合は作成される。"""
        path = os.path.join(self.tmpdir, "nested", "dir", "snap.json")
        metadata = wsl_core.build_snapshot_metadata(
            "Ubuntu", "2", "", 1000, "2026-01-01T00:00:00", "Ubuntu_x.tar"
        )
        result = wsl_core.write_snapshot_metadata(path, metadata)
        self.assertTrue(result)
        self.assertTrue(os.path.exists(path))

    def test_roundtrip_through_load_snapshots(self):
        """書き込んだメタデータは load_snapshots で読み戻せる。"""
        metadata = wsl_core.build_snapshot_metadata(
            "Ubuntu", "2", "コメント", 2048, "2026-03-03T03:03:03", "Ubuntu_x.tar"
        )
        json_path = os.path.join(self.tmpdir, "Ubuntu_x.json")
        wsl_core.write_snapshot_metadata(json_path, metadata)
        open(os.path.join(self.tmpdir, "Ubuntu_x.tar"), "w").close()
        result = wsl_core.load_snapshots(self.tmpdir)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["distro_name"], "Ubuntu")
        self.assertEqual(result[0]["comment"], "コメント")
        self.assertEqual(result[0]["size_bytes"], 2048)
        self.assertTrue(result[0]["tar_exists"])

    def test_failure_when_parent_is_a_file(self):
        """親ディレクトリの位置に既にファイルがある場合は False を返す。"""
        blocker = os.path.join(self.tmpdir, "blocker")
        open(blocker, "w").close()
        path = os.path.join(blocker, "snap.json")
        result = wsl_core.write_snapshot_metadata(path, {"distro_name": "Ubuntu"})
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# partial_write_path / finalize_partial_write / discard_partial_write
# ---------------------------------------------------------------------------

class TestFinalizePartialWrite(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_partial_write_path_appends_suffix(self):
        """partial_write_path は最終パスに規定のサフィックスを付与する。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        result = wsl_core.partial_write_path(final_path)
        self.assertEqual(result, final_path + ".wslmgr-partial")

    def test_finalize_moves_partial_to_final(self):
        """部分ファイルを最終パスに移動する。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        partial_path = wsl_core.partial_write_path(final_path)
        with open(partial_path, "w", encoding="utf-8") as f:
            f.write("partial data")
        result = wsl_core.finalize_partial_write(partial_path, final_path)
        self.assertTrue(result)
        self.assertFalse(os.path.exists(partial_path))
        with open(final_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "partial data")

    def test_finalize_overwrites_existing_final(self):
        """既存の最終ファイルは部分ファイルの内容で置き換えられる。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        with open(final_path, "w", encoding="utf-8") as f:
            f.write("old data")
        partial_path = wsl_core.partial_write_path(final_path)
        with open(partial_path, "w", encoding="utf-8") as f:
            f.write("new data")
        result = wsl_core.finalize_partial_write(partial_path, final_path)
        self.assertTrue(result)
        with open(final_path, encoding="utf-8") as f:
            self.assertEqual(f.read(), "new data")

    def test_finalize_returns_false_when_partial_absent(self):
        """部分ファイルが存在しない場合は False を返す。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        partial_path = wsl_core.partial_write_path(final_path)
        result = wsl_core.finalize_partial_write(partial_path, final_path)
        self.assertFalse(result)
        self.assertFalse(os.path.exists(final_path))

    def test_discard_removes_partial(self):
        """部分ファイルを削除する。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        partial_path = wsl_core.partial_write_path(final_path)
        open(partial_path, "w").close()
        wsl_core.discard_partial_write(partial_path)
        self.assertFalse(os.path.exists(partial_path))

    def test_discard_noop_when_absent(self):
        """部分ファイルが存在しない場合も例外を送出しない。"""
        final_path = os.path.join(self.tmpdir, "out.tar")
        partial_path = wsl_core.partial_write_path(final_path)
        wsl_core.discard_partial_write(partial_path)  # 例外を送出しないことを確認


# ---------------------------------------------------------------------------
# log_file_paths / delete_log_files
# ---------------------------------------------------------------------------


class TestLogFilePaths(unittest.TestCase):

    def test_includes_base_and_backups(self):
        paths = wsl_core.log_file_paths("/logs", max_backups=3)
        self.assertEqual(
            paths,
            [
                os.path.join("/logs", "operations.jsonl"),
                os.path.join("/logs", "operations.1.jsonl"),
                os.path.join("/logs", "operations.2.jsonl"),
                os.path.join("/logs", "operations.3.jsonl"),
            ],
        )

    def test_respects_custom_base_name(self):
        paths = wsl_core.log_file_paths("/logs", base_name="audit.log", max_backups=1)
        self.assertEqual(
            paths,
            [
                os.path.join("/logs", "audit.log"),
                os.path.join("/logs", "audit.1.log"),
            ],
        )

    def test_matches_rotate_log_files_naming(self):
        """rotate_log_files が作るバックアップ名と一致することを確認する。"""
        tmpdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmpdir, True)
        base = os.path.join(tmpdir, "operations.jsonl")
        with open(base, "w", encoding="utf-8") as f:
            f.write("x" * 32)
        wsl_core.rotate_log_files(tmpdir, max_size=8)
        rotated = os.path.join(tmpdir, "operations.1.jsonl")
        self.assertTrue(os.path.exists(rotated))
        self.assertIn(rotated, wsl_core.log_file_paths(tmpdir))


class TestDeleteLogFiles(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _touch(self, name):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write("entry\n")
        return path

    def test_deletes_base_and_rotated_files(self):
        base = self._touch("operations.jsonl")
        b1 = self._touch("operations.1.jsonl")
        b2 = self._touch("operations.2.jsonl")
        deleted, failed = wsl_core.delete_log_files(self.tmpdir)
        self.assertEqual(deleted, 3)
        self.assertEqual(failed, [])
        for path in (base, b1, b2):
            self.assertFalse(os.path.exists(path))

    def test_skips_missing_files(self):
        deleted, failed = wsl_core.delete_log_files(self.tmpdir)
        self.assertEqual(deleted, 0)
        self.assertEqual(failed, [])

    def test_leaves_unrelated_files_untouched(self):
        keep = self._touch("settings.json")
        self._touch("operations.jsonl")
        deleted, failed = wsl_core.delete_log_files(self.tmpdir)
        self.assertEqual(deleted, 1)
        self.assertEqual(failed, [])
        self.assertTrue(os.path.exists(keep))

    def test_reports_failed_paths(self):
        base = self._touch("operations.jsonl")
        with mock.patch("wsl_core.os.remove", side_effect=OSError("busy")):
            deleted, failed = wsl_core.delete_log_files(self.tmpdir)
        self.assertEqual(deleted, 0)
        self.assertEqual(failed, [base])
        self.assertTrue(os.path.exists(base))

    def test_partial_failure_still_deletes_others(self):
        base = os.path.join(self.tmpdir, "operations.jsonl")
        self._touch("operations.jsonl")
        self._touch("operations.1.jsonl")
        real_remove = os.remove

        def _remove(path):
            if path == base:
                raise OSError("busy")
            real_remove(path)

        with mock.patch("wsl_core.os.remove", side_effect=_remove):
            deleted, failed = wsl_core.delete_log_files(self.tmpdir)
        self.assertEqual(deleted, 1)
        self.assertEqual(failed, [base])


# ---------------------------------------------------------------------------
# AsyncLogWriter
# ---------------------------------------------------------------------------


class TestAsyncLogWriter(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.writer = None

    def tearDown(self):
        if self.writer is not None:
            self.writer.stop()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make(self, **kwargs):
        self.writer = wsl_core.AsyncLogWriter(self.tmpdir, **kwargs)
        return self.writer

    def _read_entries(self):
        with open(self.writer.log_path, encoding="utf-8") as f:
            return wsl_core.deserialize_log_entries(f.read())

    def test_log_path_uses_base_name(self):
        writer = self._make()
        self.assertEqual(
            writer.log_path, os.path.join(self.tmpdir, "operations.jsonl")
        )

    def test_submit_writes_entry_after_flush(self):
        writer = self._make()
        writer.submit("停止", "Ubuntu", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        entries = self._read_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["operation"], "停止")
        self.assertEqual(entries[0]["target"], "Ubuntu")
        self.assertEqual(entries[0]["result"], "実行")

    def test_preserves_submit_order(self):
        writer = self._make()
        for i in range(20):
            writer.submit("操作", f"distro-{i}", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        entries = self._read_entries()
        self.assertEqual(
            [e["target"] for e in entries], [f"distro-{i}" for i in range(20)]
        )

    def test_appends_to_existing_file(self):
        writer = self._make()
        writer.submit("一件目", "A", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        writer.submit("二件目", "B", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        entries = self._read_entries()
        self.assertEqual([e["operation"] for e in entries], ["一件目", "二件目"])

    def test_creates_missing_log_dir(self):
        nested = os.path.join(self.tmpdir, "a", "b")
        self.writer = wsl_core.AsyncLogWriter(nested)
        self.writer.submit("操作", "A", "実行")
        self.assertTrue(self.writer.flush(timeout=5.0))
        self.assertTrue(os.path.exists(os.path.join(nested, "operations.jsonl")))

    def test_explicit_timestamp_is_used(self):
        writer = self._make()
        writer.submit("操作", "A", "実行", timestamp="2026-01-01T00:00:00")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertEqual(self._read_entries()[0]["timestamp"], "2026-01-01T00:00:00")

    def test_rotates_when_over_max_size(self):
        writer = self._make(max_size=64, max_backups=2)
        for i in range(20):
            writer.submit("操作", f"distro-{i}", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertTrue(
            os.path.exists(os.path.join(self.tmpdir, "operations.1.jsonl"))
        )

    def test_flush_returns_true_when_nothing_submitted(self):
        writer = self._make()
        self.assertTrue(writer.flush(timeout=5.0))

    def test_write_errors_are_swallowed(self):
        writer = self._make()
        with mock.patch("wsl_core.open", side_effect=OSError("disk full")):
            writer.submit("操作", "A", "実行")
            self.assertTrue(writer.flush(timeout=5.0))
        # スレッドは生存し、以降の書き込みは成功する
        writer.submit("操作", "B", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertEqual([e["target"] for e in self._read_entries()], ["B"])

    def test_write_error_increments_write_error_count(self):
        """#35: _write で OSError が発生すると write_error_count が増える。"""
        writer = self._make()
        self.assertEqual(writer.write_error_count, 0)
        with mock.patch("wsl_core.open", side_effect=OSError("disk full")):
            writer.submit("操作", "A", "実行")
            self.assertTrue(writer.flush(timeout=5.0))
        self.assertEqual(writer.write_error_count, 1)

    def test_default_maxsize_is_not_unlimited(self):
        """#35: デフォルトの maxsize は無制限 (0) ではない。"""
        writer = self._make()
        self.assertGreater(writer._queue.maxsize, 0)

    def test_submit_drops_and_increments_dropped_count_when_queue_full(self):
        """#35: キュー溢れ時に dropped_count が増え、submit はブロックしない。"""
        writer = self._make(maxsize=1)
        block = threading.Event()
        original_write = writer._write

        def blocking_write(line):
            block.wait(5.0)
            original_write(line)

        writer._write = blocking_write
        try:
            writer.submit("操作", "A", "実行")
            # ライタスレッドが "A" をキューから取り出しブロックするまで待つ
            time.sleep(0.2)
            writer.submit("操作", "B", "実行")  # キュー枠 (maxsize=1) を埋める
            self.assertEqual(writer.dropped_count, 0)
            start = time.monotonic()
            writer.submit("操作", "C", "実行")  # キュー満杯 -> 破棄されるはず
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 1.0)
            self.assertEqual(writer.dropped_count, 1)
        finally:
            block.set()
        self.assertTrue(writer.flush(timeout=5.0))

    def test_stop_flushes_pending_entries(self):
        writer = self._make()
        writer.submit("操作", "A", "実行")
        self.assertTrue(writer.stop(timeout=5.0))
        self.assertEqual([e["target"] for e in self._read_entries()], ["A"])

    def test_submit_after_stop_is_ignored(self):
        writer = self._make()
        writer.submit("操作", "A", "実行")
        self.assertTrue(writer.stop(timeout=5.0))
        writer.submit("操作", "B", "実行")
        self.assertEqual([e["target"] for e in self._read_entries()], ["A"])

    def test_stop_is_idempotent(self):
        writer = self._make()
        writer.submit("操作", "A", "実行")
        self.assertTrue(writer.stop(timeout=5.0))
        self.assertTrue(writer.stop(timeout=5.0))

    def test_stop_without_submit_does_not_start_thread(self):
        writer = self._make()
        self.assertTrue(writer.stop(timeout=5.0))
        self.assertFalse(os.path.exists(writer.log_path))

    def test_flush_after_stop_returns_true(self):
        writer = self._make()
        writer.submit("操作", "A", "実行")
        self.assertTrue(writer.stop(timeout=5.0))
        self.assertTrue(writer.flush(timeout=5.0))

    def test_submit_forwards_source(self):
        """submit の source 引数が書き込まれるエントリに反映される (#27)。"""
        writer = self._make()
        writer.submit("起動", "Ubuntu", "成功", source="gui")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertEqual(self._read_entries()[0]["source"], "gui")

    def test_submit_without_source_omits_key(self):
        """source を指定しない場合、書き込まれるエントリに "source" キーが含まれない。"""
        writer = self._make()
        writer.submit("起動", "Ubuntu", "成功")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertNotIn("source", self._read_entries()[0])

    def test_writer_thread_is_daemon(self):
        writer = self._make()
        writer.submit("操作", "A", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        self.assertTrue(writer._thread.daemon)

    def test_delete_log_files_after_flush_removes_everything(self):
        """#9: クリア相当の操作でファイルが残らないことを確認する。"""
        writer = self._make(max_size=64, max_backups=3)
        for i in range(20):
            writer.submit("操作", f"distro-{i}", "実行")
        self.assertTrue(writer.flush(timeout=5.0))
        deleted, failed = wsl_core.delete_log_files(
            self.tmpdir, max_backups=3
        )
        self.assertGreaterEqual(deleted, 2)
        self.assertEqual(failed, [])
        self.assertEqual(
            [p for p in wsl_core.log_file_paths(self.tmpdir, max_backups=3)
             if os.path.exists(p)],
            [],
        )


# ---------------------------------------------------------------------------
# append_log_entry
# ---------------------------------------------------------------------------


class TestAppendLogEntry(unittest.TestCase):
    """append_log_entry (#27: CLI 用の同期版ログ追記ヘルパー) のテスト。"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _read_entries(self):
        path = os.path.join(self.tmpdir, "operations.jsonl")
        with open(path, encoding="utf-8") as f:
            return wsl_core.deserialize_log_entries(f.read())

    def test_writes_entry_synchronously(self):
        """呼び出し直後にファイルへ反映されている (非同期キューを経由しない)。"""
        wsl_core.append_log_entry(self.tmpdir, "起動", "Ubuntu", "成功", source="cli")
        entries = self._read_entries()
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["operation"], "起動")
        self.assertEqual(entries[0]["target"], "Ubuntu")
        self.assertEqual(entries[0]["result"], "成功")
        self.assertEqual(entries[0]["source"], "cli")

    def test_appends_to_existing_file(self):
        """既存ファイルへ追記される (上書きしない)。"""
        wsl_core.append_log_entry(self.tmpdir, "一件目", "A", "成功", source="cli")
        wsl_core.append_log_entry(self.tmpdir, "二件目", "B", "成功", source="cli")
        entries = self._read_entries()
        self.assertEqual([e["operation"] for e in entries], ["一件目", "二件目"])

    def test_creates_missing_log_dir(self):
        """ログディレクトリが存在しない場合は作成する。"""
        nested = os.path.join(self.tmpdir, "a", "b")
        wsl_core.append_log_entry(nested, "起動", "Ubuntu", "成功", source="cli")
        self.assertTrue(os.path.exists(os.path.join(nested, "operations.jsonl")))

    def test_source_omitted_when_none(self):
        """source を指定しない場合、書き込まれるエントリに "source" キーが含まれない。"""
        wsl_core.append_log_entry(self.tmpdir, "起動", "Ubuntu", "成功")
        self.assertNotIn("source", self._read_entries()[0])

    def test_rotates_when_over_max_size(self):
        """max_size を超えるとローテーションされる (AsyncLogWriter と同じロジック)。"""
        for i in range(20):
            wsl_core.append_log_entry(
                self.tmpdir, "操作", f"distro-{i}", "実行", max_size=64, max_backups=2
            )
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "operations.1.jsonl")))

    def test_write_errors_are_swallowed(self):
        """書き込み失敗時も例外を送出しない (呼び出し元コマンドの成否に影響させない)。"""
        with mock.patch("wsl_core.open", side_effect=OSError("disk full")):
            wsl_core.append_log_entry(self.tmpdir, "操作", "A", "実行", source="cli")
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, "operations.jsonl")))


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
