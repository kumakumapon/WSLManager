"""
単体テスト for wslmgr_cli.py

実行方法 (リポジトリルートから):
    python3 -m pytest tests/test_wslmgr_cli.py -v
"""

import argparse
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, call, mock_open, patch

# リポジトリルートを sys.path の先頭に挿入して wslmgr_cli をインポートできるようにする
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import wslmgr_cli

# ---------------------------------------------------------------------------
# _format_table
# ---------------------------------------------------------------------------

class TestFormatTable(unittest.TestCase):
    """_format_table のテスト。"""

    def test_header_present(self):
        """ヘッダ行に各列名が含まれる。"""
        result = wslmgr_cli._format_table(["Name", "State"], [["Ubuntu", "Running"]])
        lines = result.splitlines()
        self.assertIn("Name", lines[0])
        self.assertIn("State", lines[0])

    def test_separator_line(self):
        """ヘッダの次の行が区切り線 ('-' のみ) である。"""
        result = wslmgr_cli._format_table(["Name"], [["Ubuntu"]])
        lines = result.splitlines()
        self.assertTrue(set(lines[1].strip()) <= {"-", " "})

    def test_row_data_present(self):
        """データ行の内容が出力に含まれる。"""
        result = wslmgr_cli._format_table(
            ["Name", "State"], [["Ubuntu", "Running"], ["Debian", "Stopped"]]
        )
        self.assertIn("Ubuntu", result)
        self.assertIn("Running", result)
        self.assertIn("Debian", result)
        self.assertIn("Stopped", result)

    def test_column_width_min(self):
        """min_width 未満のヘッダ・データでも min_width 分の幅が確保される。"""
        result = wslmgr_cli._format_table(["A"], [["1"]], min_width=10)
        lines = result.splitlines()
        # ヘッダ行の列幅が少なくとも min_width 文字分はある
        self.assertGreaterEqual(len(lines[0].rstrip()), 1)
        self.assertGreaterEqual(len(lines[1]), 10)

    def test_column_width_grows_with_data(self):
        """データの方が長い場合は列幅がデータ長に合わせて広がる。"""
        long_value = "a" * 20
        result = wslmgr_cli._format_table(["Name"], [[long_value]], min_width=4)
        lines = result.splitlines()
        self.assertIn(long_value, lines[2])

    def test_empty_rows(self):
        """データ行が0件でもヘッダと区切り線のみ出力される。"""
        result = wslmgr_cli._format_table(["Name", "State"], [])
        lines = result.splitlines()
        self.assertEqual(len(lines), 2)
        self.assertIn("Name", lines[0])

    def test_multiple_columns_aligned(self):
        """複数列が整列されて出力される (各行が同じ長さ)。"""
        result = wslmgr_cli._format_table(
            ["Name", "State", "Version"],
            [["Ubuntu", "Running", "2"], ["D", "S", "1"]],
        )
        lines = result.splitlines()
        # ヘッダ行とデータ行の長さが一致する (整列されている)
        self.assertEqual(len(lines[0]), len(lines[2]))
        self.assertEqual(len(lines[0]), len(lines[3]))

    def test_returns_string(self):
        """戻り値が str であることを確認する。"""
        result = wslmgr_cli._format_table(["Name"], [["Ubuntu"]])
        self.assertIsInstance(result, str)

    def test_non_string_cell_converted(self):
        """非文字列 (bool 等) のセルも文字列に変換されて出力される。"""
        result = wslmgr_cli._format_table(["Default"], [[True]])
        self.assertIn("True", result)


# ---------------------------------------------------------------------------
# _format_csv
# ---------------------------------------------------------------------------

class TestFormatCsv(unittest.TestCase):
    """_format_csv のテスト。"""

    def test_header_row(self):
        """先頭行がヘッダになる。"""
        result = wslmgr_cli._format_csv(["Name", "State"], [["Ubuntu", "Running"]])
        lines = result.splitlines()
        self.assertEqual(lines[0], "Name,State")

    def test_data_row(self):
        """データ行が正しくカンマ区切りで出力される。"""
        result = wslmgr_cli._format_csv(["Name", "State"], [["Ubuntu", "Running"]])
        lines = result.splitlines()
        self.assertEqual(lines[1], "Ubuntu,Running")

    def test_multiple_rows(self):
        """複数行が正しく出力される。"""
        result = wslmgr_cli._format_csv(
            ["Name", "State"], [["Ubuntu", "Running"], ["Debian", "Stopped"]]
        )
        lines = result.splitlines()
        self.assertEqual(len(lines), 3)
        self.assertEqual(lines[2], "Debian,Stopped")

    def test_empty_rows(self):
        """データ行が0件の場合はヘッダのみ出力される。"""
        result = wslmgr_cli._format_csv(["Name", "State"], [])
        lines = result.splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0], "Name,State")

    def test_value_with_comma_quoted(self):
        """値にカンマが含まれる場合はダブルクォートで囲まれる。"""
        result = wslmgr_cli._format_csv(["Name"], [["foo,bar"]])
        self.assertIn('"foo,bar"', result)

    def test_returns_string(self):
        """戻り値が str であることを確認する。"""
        result = wslmgr_cli._format_csv(["Name"], [["Ubuntu"]])
        self.assertIsInstance(result, str)

    def test_no_trailing_newline(self):
        """末尾に余分な改行が残らない。"""
        result = wslmgr_cli._format_csv(["Name"], [["Ubuntu"]])
        self.assertFalse(result.endswith("\n"))


# ---------------------------------------------------------------------------
# argparse セットアップ
# ---------------------------------------------------------------------------

class TestMainParserSetup(unittest.TestCase):
    """build_parser によるサブコマンド設定のテスト。"""

    def setUp(self):
        self.parser = wslmgr_cli.build_parser()

    def test_list_subcommand_parses(self):
        """list サブコマンドが解析できる。"""
        args = self.parser.parse_args(["list"])
        self.assertEqual(args.format, "table")
        self.assertTrue(hasattr(args, "func"))

    def test_list_format_json(self):
        """list --format json が解析できる。"""
        args = self.parser.parse_args(["list", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_list_format_csv(self):
        """list --format csv が解析できる。"""
        args = self.parser.parse_args(["list", "--format", "csv"])
        self.assertEqual(args.format, "csv")

    def test_list_invalid_format_raises(self):
        """list --format に不正な値を渡すとエラーになる。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["list", "--format", "xml"])

    def test_start_requires_name(self):
        """start サブコマンドは name 引数が必須。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["start"])

    def test_start_parses_name(self):
        """start サブコマンドが name を正しく取得する。"""
        args = self.parser.parse_args(["start", "Ubuntu"])
        self.assertEqual(args.name, "Ubuntu")

    def test_stop_parses_name(self):
        """stop サブコマンドが name を正しく取得する。"""
        args = self.parser.parse_args(["stop", "Debian"])
        self.assertEqual(args.name, "Debian")

    def test_shutdown_no_args(self):
        """shutdown サブコマンドは引数なしで解析できる。"""
        args = self.parser.parse_args(["shutdown"])
        self.assertTrue(hasattr(args, "func"))

    def test_status_default_format(self):
        """status サブコマンドの既定フォーマットは table。"""
        args = self.parser.parse_args(["status"])
        self.assertEqual(args.format, "table")

    def test_export_requires_two_args(self):
        """export サブコマンドは name と path が必須。"""
        args = self.parser.parse_args(["export", "Ubuntu", "C:\\backup.tar"])
        self.assertEqual(args.name, "Ubuntu")
        self.assertEqual(args.path, "C:\\backup.tar")

    def test_export_missing_path_raises(self):
        """export サブコマンドで path を省略するとエラーになる。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["export", "Ubuntu"])

    def test_export_default_yes_false(self):
        """export サブコマンドの --yes は既定で False。"""
        args = self.parser.parse_args(["export", "Ubuntu", "C:\\backup.tar"])
        self.assertFalse(args.yes)

    def test_export_yes_flag_parses(self):
        """export サブコマンドで --yes / -y が解析できる。"""
        args = self.parser.parse_args(["export", "Ubuntu", "C:\\backup.tar", "--yes"])
        self.assertTrue(args.yes)
        args = self.parser.parse_args(["export", "Ubuntu", "C:\\backup.tar", "-y"])
        self.assertTrue(args.yes)

    def test_import_requires_three_args(self):
        """import サブコマンドは name, install_path, image_path が必須。"""
        args = self.parser.parse_args(
            ["import", "NewDistro", "C:\\wsl\\NewDistro", "C:\\image.tar"]
        )
        self.assertEqual(args.name, "NewDistro")
        self.assertEqual(args.install_path, "C:\\wsl\\NewDistro")
        self.assertEqual(args.image_path, "C:\\image.tar")

    def test_import_default_yes_false(self):
        """import サブコマンドの --yes は既定で False。"""
        args = self.parser.parse_args(
            ["import", "NewDistro", "C:\\wsl\\NewDistro", "C:\\image.tar"]
        )
        self.assertFalse(args.yes)

    def test_import_yes_flag_parses(self):
        """import サブコマンドで --yes / -y が解析できる。"""
        args = self.parser.parse_args(
            ["import", "NewDistro", "C:\\wsl\\NewDistro", "C:\\image.tar", "--yes"]
        )
        self.assertTrue(args.yes)

    def test_config_default_format(self):
        """config サブコマンドの既定フォーマットは table。"""
        args = self.parser.parse_args(["config"])
        self.assertEqual(args.format, "table")

    def test_unknown_subcommand_raises(self):
        """未知のサブコマンドはエラーになる。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["frobnicate"])

    def test_no_subcommand_no_func(self):
        """サブコマンドなしの場合 func 属性が設定されない。"""
        args = self.parser.parse_args([])
        self.assertFalse(hasattr(args, "func"))


# ---------------------------------------------------------------------------
# cmd_list (subprocess をモック)
# ---------------------------------------------------------------------------

class TestCmdList(unittest.TestCase):
    """cmd_list のテスト (subprocess.run をモック)。"""

    TYPICAL_OUTPUT = (
        "  NAME      STATE           VERSION\n"
        "* Ubuntu    Running         2\n"
        "  Debian    Stopped         2\n"
    )

    def _make_completed_process(self, stdout_text, returncode=0):
        # 実際の wsl.exe は UTF-16LE (BOM 付き) で出力するため、それを模す
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = b"\xff\xfe" + stdout_text.encode("utf-16-le")
        proc.stderr = b""
        return proc

    @patch("wslmgr_cli.subprocess.run")
    def test_table_format_calls_parse_distro_list(self, mock_run):
        """table フォーマットで wsl_core.parse_distro_list の結果が出力される。"""
        mock_run.return_value = self._make_completed_process(self.TYPICAL_OUTPUT)
        args = argparse.Namespace(format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_list(args)
        output = buf.getvalue()
        self.assertIn("Ubuntu", output)
        self.assertIn("Debian", output)
        self.assertIn("Running", output)

    @patch("wslmgr_cli.subprocess.run")
    def test_default_marker_shown(self, mock_run):
        """デフォルトディストロに '*' マーカーが表示される。"""
        mock_run.return_value = self._make_completed_process(self.TYPICAL_OUTPUT)
        args = argparse.Namespace(format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_list(args)
        output = buf.getvalue()
        lines = [line for line in output.splitlines() if "Ubuntu" in line]
        self.assertTrue(any("*" in line for line in lines))

    @patch("wslmgr_cli.subprocess.run")
    def test_json_format_valid_json(self, mock_run):
        """json フォーマットの出力が有効な JSON でパース可能。"""
        mock_run.return_value = self._make_completed_process(self.TYPICAL_OUTPUT)
        args = argparse.Namespace(format="json")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_list(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["name"], "Ubuntu")

    @patch("wslmgr_cli.subprocess.run")
    def test_csv_format_header(self, mock_run):
        """csv フォーマットの出力にヘッダ行が含まれる。"""
        mock_run.return_value = self._make_completed_process(self.TYPICAL_OUTPUT)
        args = argparse.Namespace(format="csv")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_list(args)
        output = buf.getvalue()
        self.assertIn("Name,State,Version,Default", output)

    @patch("wslmgr_cli.subprocess.run")
    def test_command_failure_exits_with_error(self, mock_run):
        """wsl コマンドが失敗した場合 sys.exit(1) する。"""
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = b""
        proc.stderr = "エラー発生".encode()
        mock_run.return_value = proc
        args = argparse.Namespace(format="table")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_list(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_wsl_invoked_with_list_verbose(self, mock_run):
        """subprocess.run が 'wsl --list --verbose' で呼ばれる。"""
        mock_run.return_value = self._make_completed_process(self.TYPICAL_OUTPUT)
        args = argparse.Namespace(format="table")
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_list(args)
        call_args = mock_run.call_args
        self.assertEqual(call_args[0][0], ["wsl", "--list", "--verbose"])


# ---------------------------------------------------------------------------
# cmd_config (ファイル読み込みをモック)
# ---------------------------------------------------------------------------

class TestCmdConfig(unittest.TestCase):
    """cmd_config のテスト (ファイル I/O をモック)。"""

    WSLCONFIG_TEXT = "[wsl2]\nmemory=4GB\nprocessors=2\n"

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=WSLCONFIG_TEXT)
    def test_table_format_shows_keys(self, mock_file, mock_exists):
        """table フォーマットで各キーが表示される。"""
        args = argparse.Namespace(format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_config(args)
        output = buf.getvalue()
        self.assertIn("[wsl2]", output)
        self.assertIn("memory", output)
        self.assertIn("4GB", output)
        self.assertIn("processors", output)

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=WSLCONFIG_TEXT)
    def test_json_format_valid(self, mock_file, mock_exists):
        """json フォーマットの出力が wsl_core.parse_wslconfig と一致する。"""
        args = argparse.Namespace(format="json")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_config(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(data, {"wsl2": {"memory": "4GB", "processors": "2"}})

    @patch("wslmgr_cli.os.path.exists", return_value=False)
    def test_missing_file_exits_with_error(self, mock_exists):
        """.wslconfig が存在しない場合 sys.exit(1) する。"""
        args = argparse.Namespace(format="table")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_config(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data="")
    def test_empty_config_shows_message(self, mock_file, mock_exists):
        """空の .wslconfig では「設定項目がありません」を表示する。"""
        args = argparse.Namespace(format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_config(args)
        self.assertIn("設定項目がありません", buf.getvalue())

    @patch("wslmgr_cli.os.path.expanduser")
    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=WSLCONFIG_TEXT)
    def test_uses_expanduser_path(self, mock_file, mock_exists, mock_expand):
        """~/.wslconfig のパスが os.path.expanduser を経由して取得される。"""
        mock_expand.return_value = "/home/test/.wslconfig"
        args = argparse.Namespace(format="json")
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_config(args)
        mock_expand.assert_called_with("~/.wslconfig")


# ---------------------------------------------------------------------------
# _run_wsl_command
# ---------------------------------------------------------------------------

class TestRunWslCommand(unittest.TestCase):
    """_run_wsl_command のテスト (subprocess.run をモック)。"""

    @patch("wslmgr_cli.subprocess.run")
    def test_success_decodes_output(self, mock_run):
        """成功時に stdout/stderr がデコードされて返る。"""
        proc = MagicMock()
        proc.returncode = 0
        # 実際の wsl.exe は UTF-16LE (BOM 付き) で出力するため、それを模す
        proc.stdout = b"\xff\xfe" + "結果".encode("utf-16-le")
        proc.stderr = b""
        mock_run.return_value = proc
        rc, out, _err = wslmgr_cli._run_wsl_command(["--list"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "結果")

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=__import__("subprocess").TimeoutExpired(cmd="wsl", timeout=10),
    )
    def test_timeout_returns_error(self, mock_run):
        """タイムアウト時に returncode=-1 とエラーメッセージを返す。"""
        rc, _out, err = wslmgr_cli._run_wsl_command(["--list"])
        self.assertEqual(rc, -1)
        self.assertIn("タイムアウト", err)

    @patch("wslmgr_cli.subprocess.run", side_effect=OSError("not found"))
    def test_oserror_returns_error(self, mock_run):
        """OSError 発生時に returncode=-1 とエラーメッセージを返す。"""
        rc, _out, err = wslmgr_cli._run_wsl_command(["--list"])
        self.assertEqual(rc, -1)
        self.assertIn("not found", err)

    @patch("wslmgr_cli.subprocess.run")
    def test_prepends_wsl_to_args(self, mock_run):
        """渡した args の先頭に 'wsl' が付与されて実行される。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b""
        proc.stderr = b""
        mock_run.return_value = proc
        wslmgr_cli._run_wsl_command(["--terminate", "Ubuntu"])
        call_args = mock_run.call_args
        self.assertEqual(call_args[0][0], ["wsl", "--terminate", "Ubuntu"])


# ---------------------------------------------------------------------------
# cmd_export
# ---------------------------------------------------------------------------

class TestCmdExport(unittest.TestCase):
    """cmd_export のテスト。"""

    @patch("wslmgr_cli.subprocess.run")
    def test_success_invokes_wsl_export(self, mock_run):
        """成功時に 'wsl --export <name> <path>' が呼ばれ、完了メッセージが表示される。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b""
        proc.stderr = b""
        mock_run.return_value = proc
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            buf = io.StringIO()
            with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
                with patch("sys.stdout", buf):
                    wslmgr_cli.cmd_export(args)
            mock_run.assert_called_once()
            self.assertEqual(mock_run.call_args[0][0], ["wsl", "--export", "Ubuntu", path])
            self.assertIn("エクスポートが完了しました", buf.getvalue())

    @patch("wslmgr_cli.subprocess.run")
    def test_failure_exits_with_error(self, mock_run):
        """失敗時に exit 1 する。"""
        proc = MagicMock()
        proc.returncode = 1
        proc.stdout = b""
        proc.stderr = "失敗".encode()
        mock_run.return_value = proc
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_export(args)
            self.assertEqual(cm.exception.code, 1)

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="wsl", timeout=600),
    )
    def test_timeout_exits_with_error(self, mock_run):
        """エクスポートがタイムアウトした場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_export(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("wsl not found"))
    def test_filenotfounderror_exits_with_error(self, mock_run):
        """wsl 実行ファイルが見つからない場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_export(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_file_requires_confirmation(self, mock_run):
        """エクスポート先が既に存在する場合、--yes なしでは確認プロンプトを表示する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            with open(path, "wb") as f:
                f.write(b"existing")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n"):
                    with self.assertRaises(SystemExit) as cm:
                        with patch("sys.stdout", io.StringIO()):
                            wslmgr_cli.cmd_export(args)
            self.assertEqual(cm.exception.code, 1)
            mock_run.assert_not_called()

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_file_yes_flag_skips_confirmation(self, mock_run):
        """エクスポート先が既に存在しても --yes 指定時は確認せずに実行される。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b""
        proc.stderr = b""
        mock_run.return_value = proc
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            with open(path, "wb") as f:
                f.write(b"existing")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=True)
            with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_export(args)
            mock_run.assert_called_once()

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_file_non_tty_without_yes_exits(self, mock_run):
        """非対話環境でエクスポート先が既存かつ --yes なしの場合、実行前に exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "backup.tar")
            with open(path, "wb") as f:
                f.write(b"existing")
            args = argparse.Namespace(name="Ubuntu", path=path, yes=False)
            with patch("sys.stdin.isatty", return_value=False):
                with self.assertRaises(SystemExit) as cm:
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_export(args)
            self.assertEqual(cm.exception.code, 1)
            mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_import (validate_distro_name の利用確認)
# ---------------------------------------------------------------------------

class TestCmdImport(unittest.TestCase):
    """cmd_import のテスト。"""

    def test_invalid_name_exits_before_subprocess(self):
        """不正な名前の場合、subprocess を呼ばずに sys.exit(1) する。"""
        args = argparse.Namespace(
            name="bad/name", install_path="C:\\wsl\\bad", image_path="C:\\image.tar"
        )
        with patch("wslmgr_cli.subprocess.run") as mock_run:
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_import(args)
            mock_run.assert_not_called()
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_valid_name_invokes_wsl_import(self, mock_run):
        """有効な名前の場合 'wsl --import' が呼ばれる。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b""
        proc.stderr = b""
        mock_run.return_value = proc
        args = argparse.Namespace(
            name="NewDistro", install_path="C:\\wsl\\NewDistro", image_path="C:\\image.tar"
        )
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_import(args)
        call_args = mock_run.call_args
        self.assertEqual(
            call_args[0][0],
            ["wsl", "--import", "NewDistro", "C:\\wsl\\NewDistro", "C:\\image.tar"],
        )

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_vhdx_requires_confirmation(self, mock_run):
        """インストール先に既に ext4.vhdx がある場合、--yes なしでは確認プロンプトを表示する。"""
        with tempfile.TemporaryDirectory() as install_dir:
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                name="NewDistro", install_path=install_dir, image_path="C:\\image.tar", yes=False,
            )
            with patch("sys.stdin.isatty", return_value=True):
                with patch("builtins.input", return_value="n"):
                    with self.assertRaises(SystemExit) as cm:
                        with patch("sys.stdout", io.StringIO()):
                            wslmgr_cli.cmd_import(args)
            self.assertEqual(cm.exception.code, 1)
            mock_run.assert_not_called()

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_vhdx_yes_flag_skips_confirmation(self, mock_run):
        """インストール先に ext4.vhdx があっても --yes 指定時は確認せずに実行される。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = b""
        proc.stderr = b""
        mock_run.return_value = proc
        with tempfile.TemporaryDirectory() as install_dir:
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                name="NewDistro", install_path=install_dir, image_path="C:\\image.tar", yes=True,
            )
            with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_import(args)
            mock_run.assert_called_once()

    @patch("wslmgr_cli.subprocess.run")
    def test_existing_vhdx_non_tty_without_yes_exits(self, mock_run):
        """非対話環境で ext4.vhdx が存在し --yes なしの場合、実行前に exit 1 する。"""
        with tempfile.TemporaryDirectory() as install_dir:
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                name="NewDistro", install_path=install_dir, image_path="C:\\image.tar", yes=False,
            )
            with patch("sys.stdin.isatty", return_value=False):
                with self.assertRaises(SystemExit) as cm:
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_import(args)
            self.assertEqual(cm.exception.code, 1)
            mock_run.assert_not_called()

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="wsl", timeout=600),
    )
    def test_timeout_exits_with_error(self, mock_run):
        """--import がタイムアウトした場合 exit 1 する。"""
        args = argparse.Namespace(
            name="NewDistro", install_path="C:\\wsl\\NewDistro", image_path="C:\\image.tar",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_import(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("wsl not found"))
    def test_filenotfounderror_exits_with_error(self, mock_run):
        """wsl 実行ファイルが見つからない場合 exit 1 する。"""
        args = argparse.Namespace(
            name="NewDistro", install_path="C:\\wsl\\NewDistro", image_path="C:\\image.tar",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_import(args)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# _run_netsh_portproxy
# ---------------------------------------------------------------------------

class TestRunNetshPortproxy(unittest.TestCase):
    """_run_netsh_portproxy のテスト (subprocess.run をモック)。"""

    @patch("wslmgr_cli.subprocess.run")
    def test_success_returns_text_output(self, mock_run):
        """成功時に stdout/stderr がそのままのテキストとして返る。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = "結果テキスト"
        proc.stderr = ""
        mock_run.return_value = proc
        rc, out, _err = wslmgr_cli._run_netsh_portproxy(["show", "all"])
        self.assertEqual(rc, 0)
        self.assertEqual(out, "結果テキスト")

    @patch("wslmgr_cli.subprocess.run")
    def test_prepends_netsh_args(self, mock_run):
        """渡した args の先頭に 'netsh interface portproxy' が付与される。"""
        proc = MagicMock()
        proc.returncode = 0
        proc.stdout = ""
        proc.stderr = ""
        mock_run.return_value = proc
        wslmgr_cli._run_netsh_portproxy(["show", "all"])
        call_args = mock_run.call_args
        self.assertEqual(
            call_args[0][0], ["netsh", "interface", "portproxy", "show", "all"]
        )
        self.assertTrue(call_args[1]["text"])

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="netsh", timeout=15),
    )
    def test_timeout_returns_error(self, mock_run):
        """タイムアウト時に returncode=-1 とエラーメッセージを返す。"""
        rc, _out, err = wslmgr_cli._run_netsh_portproxy(["show", "all"])
        self.assertEqual(rc, -1)
        self.assertIn("タイムアウト", err)

    @patch("wslmgr_cli.subprocess.run", side_effect=OSError("not found"))
    def test_oserror_returns_error(self, mock_run):
        """OSError 発生時に returncode=-1 とエラーメッセージを返す。"""
        rc, _out, err = wslmgr_cli._run_netsh_portproxy(["show", "all"])
        self.assertEqual(rc, -1)
        self.assertIn("not found", err)


# ---------------------------------------------------------------------------
# _confirm_or_exit
# ---------------------------------------------------------------------------

class TestConfirmOrExit(unittest.TestCase):
    """_confirm_or_exit のテスト。"""

    def test_assume_yes_returns_immediately(self):
        """assume_yes=True の場合は確認せずに戻る。"""
        # input が呼ばれたら失敗させることで、確認をスキップしたことを検証する
        with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
            wslmgr_cli._confirm_or_exit("続行しますか?", True)

    @patch("sys.stdin.isatty", return_value=False)
    def test_non_tty_without_yes_exits(self, mock_isatty):
        """非対話環境で assume_yes=False の場合 exit 1 する。"""
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli._confirm_or_exit("続行しますか?", False)
        self.assertEqual(cm.exception.code, 1)

    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_tty_yes_input_continues(self, mock_input, mock_isatty):
        """TTY で 'y' が入力された場合は例外を出さずに戻る。"""
        wslmgr_cli._confirm_or_exit("続行しますか?", False)

    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="YES")
    def test_tty_yes_uppercase_continues(self, mock_input, mock_isatty):
        """大文字の 'YES' も有効な肯定応答として扱われる。"""
        wslmgr_cli._confirm_or_exit("続行しますか?", False)

    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_tty_no_input_exits(self, mock_input, mock_isatty):
        """TTY で 'n' が入力された場合は exit 1 する。"""
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli._confirm_or_exit("続行しますか?", False)
        self.assertEqual(cm.exception.code, 1)

    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", side_effect=EOFError)
    def test_tty_eof_input_exits(self, mock_input, mock_isatty):
        """TTY で入力が EOF (Ctrl-D) の場合は「いいえ」として exit 1 する。"""
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli._confirm_or_exit("続行しますか?", False)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# cmd_set_default
# ---------------------------------------------------------------------------

class TestCmdSetDefault(unittest.TestCase):
    """cmd_set_default のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_message(self, mock_run):
        """成功時に正しいメッセージが表示される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_set_default(args)
        self.assertIn("Ubuntu", buf.getvalue())
        self.assertIn("デフォルトに設定しました", buf.getvalue())
        mock_run.assert_called_once_with(["--set-default", "Ubuntu"], timeout=30.0)

    @patch("wslmgr_cli._run_wsl_command")
    def test_failure_exits_with_error(self, mock_run):
        """失敗時に exit 1 する。"""
        mock_run.return_value = (1, "", "エラー")
        args = argparse.Namespace(name="Ubuntu")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_set_default(args)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# cmd_unregister
# ---------------------------------------------------------------------------

class TestCmdUnregister(unittest.TestCase):
    """cmd_unregister のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_yes_flag_skips_confirmation(self, mock_run):
        """--yes 指定時は確認なしで実行される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", yes=True)
        with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_unregister(args)
        mock_run.assert_called_once_with(["--unregister", "Ubuntu"], timeout=120.0)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=False)
    def test_non_tty_without_yes_exits_before_run(self, mock_isatty, mock_run):
        """非対話環境で --yes なしの場合、コマンド実行前に exit 1 する。"""
        args = argparse.Namespace(name="Ubuntu", yes=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_unregister(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_tty_yes_input_executes(self, mock_input, mock_isatty, mock_run):
        """TTY で 'y' 入力の場合は実行される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", yes=False)
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_unregister(args)
        mock_run.assert_called_once_with(["--unregister", "Ubuntu"], timeout=120.0)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_tty_no_input_exits_before_run(self, mock_input, mock_isatty, mock_run):
        """TTY で 'n' 入力の場合は exit 1 し、コマンドは実行されない。"""
        args = argparse.Namespace(name="Ubuntu", yes=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_unregister(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_install
# ---------------------------------------------------------------------------

class TestCmdInstall(unittest.TestCase):
    """cmd_install のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_invokes_wsl_install(self, mock_run):
        """成功時に正しい wsl 引数で実行される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_install(args)
        mock_run.assert_called_once_with(
            ["--install", "-d", "Ubuntu", "--no-launch"], timeout=1800.0
        )
        self.assertIn("インストールが完了しました", buf.getvalue())

    @patch("wslmgr_cli._run_wsl_command")
    def test_failure_exits_with_error(self, mock_run):
        """失敗時に exit 1 する。"""
        mock_run.return_value = (1, "", "エラー")
        args = argparse.Namespace(name="Ubuntu")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_install(args)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# cmd_optimize
# ---------------------------------------------------------------------------

class TestCmdOptimize(unittest.TestCase):
    """cmd_optimize のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_sparse_terminates_then_manages(self, mock_run):
        """--sparse 指定時、terminate してから --manage --set-sparse true が呼ばれる。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=True, compact=False)
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_optimize(args)
        self.assertEqual(
            mock_run.call_args_list,
            [
                call(["--terminate", "Ubuntu"], timeout=30.0),
                call(["--manage", "Ubuntu", "--set-sparse", "true"], timeout=120.0),
            ],
        )

    @patch("wslmgr_cli._run_wsl_command")
    def test_sparse_failure_exits_with_error(self, mock_run):
        """--sparse の --manage が失敗した場合 exit 1 する。"""
        mock_run.side_effect = [(0, "", ""), (1, "", "エラー")]
        args = argparse.Namespace(name="Ubuntu", sparse=True, compact=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=None)
    def test_compact_vhdx_not_found_exits(self, mock_vhdx, mock_run):
        """--compact で vhdx が見つからない場合 exit 1 する。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.os.remove")
    @patch("wslmgr_cli.subprocess.run")
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_vhdx_found_runs_diskpart(
        self, mock_run_wsl, mock_vhdx, mock_subprocess_run, mock_remove
    ):
        """--compact で vhdx が見つかった場合、diskpart /s script_path が実行される。"""
        mock_run_wsl.return_value = (0, "", "")
        proc = MagicMock()
        proc.returncode = 0
        mock_subprocess_run.return_value = proc
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=True)
        buf = io.StringIO()
        with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
            with patch("sys.stdout", buf):
                wslmgr_cli.cmd_optimize(args)
        call_args = mock_subprocess_run.call_args
        self.assertEqual(call_args[0][0][0], "diskpart")
        self.assertEqual(call_args[0][0][1], "/s")
        self.assertIn("圧縮しました", buf.getvalue())
        mock_remove.assert_called_once()

    @patch("wslmgr_cli.os.remove")
    @patch("wslmgr_cli.subprocess.run")
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_diskpart_failure_exits(
        self, mock_run_wsl, mock_vhdx, mock_subprocess_run, mock_remove
    ):
        """diskpart が失敗した (returncode != 0) 場合 exit 1 する。"""
        mock_run_wsl.return_value = (0, "", "")
        proc = MagicMock()
        proc.returncode = 1
        mock_subprocess_run.return_value = proc
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=True)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_without_yes_requires_confirmation(
        self, mock_run_wsl, mock_vhdx, mock_subprocess_run
    ):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """--compact は --yes なしでは常に確認プロンプトを表示し、'n' の場合 diskpart を呼ばない。"""  # noqa: E501
        mock_run_wsl.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=False)
        with patch("sys.stdin.isatty", return_value=True):
            with patch("builtins.input", return_value="n"):
                with self.assertRaises(SystemExit) as cm:
                    with patch("sys.stdout", io.StringIO()):
                        wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)
        mock_subprocess_run.assert_not_called()

    @patch("wslmgr_cli.subprocess.run")
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_non_tty_without_yes_exits_before_diskpart(
        self, mock_run_wsl, mock_vhdx, mock_subprocess_run
    ):
        """非対話環境で --yes なしの場合、diskpart を呼ばずに exit 1 する。"""
        mock_run_wsl.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=False)
        with patch("sys.stdin.isatty", return_value=False):
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)
        mock_subprocess_run.assert_not_called()

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="diskpart", timeout=600),
    )
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_diskpart_timeout_exits(self, mock_run_wsl, mock_vhdx, mock_subprocess_run):
        """diskpart がタイムアウトした場合 exit 1 する。"""
        mock_run_wsl.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=True)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("diskpart not found"))
    @patch("wslmgr_cli._get_distro_vhdx_path", return_value=r"C:\wsl\Ubuntu\ext4.vhdx")
    @patch("wslmgr_cli._run_wsl_command")
    def test_compact_diskpart_filenotfounderror_exits(
        self, mock_run_wsl, mock_vhdx, mock_subprocess_run
    ):
        """diskpart 実行ファイルが見つからない場合 exit 1 する。"""
        mock_run_wsl.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", sparse=False, compact=True, yes=True)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch(
        "wslmgr_cli.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="wsl", timeout=120)
    )
    def test_sparse_manage_timeout_exits(self, mock_subprocess_run):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """--sparse の --manage がタイムアウトした場合 exit 1 する (subprocess.run を直接タイムアウトさせる)。"""  # noqa: E501
        args = argparse.Namespace(name="Ubuntu", sparse=True, compact=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("wsl not found"))
    def test_sparse_manage_filenotfounderror_exits(self, mock_subprocess_run):
        """--sparse の実行時に wsl が見つからない場合 exit 1 する。"""
        args = argparse.Namespace(name="Ubuntu", sparse=True, compact=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_optimize(args)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# cmd_set_version
# ---------------------------------------------------------------------------

class TestCmdSetVersion(unittest.TestCase):
    """cmd_set_version のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_yes_flag_skips_confirmation(self, mock_run):
        """--yes 指定時は確認なしで実行される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", version="2", yes=True)
        with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_set_version(args)
        mock_run.assert_called_once_with(["--set-version", "Ubuntu", "2"], timeout=1800.0)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=False)
    def test_non_tty_without_yes_exits_before_run(self, mock_isatty, mock_run):
        """非対話環境で --yes なしの場合 exit 1 し、コマンドは実行されない。"""
        args = argparse.Namespace(name="Ubuntu", version="1", yes=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_set_version(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_tty_yes_input_executes(self, mock_input, mock_isatty, mock_run):
        """TTY で 'y' 入力の場合は実行される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(name="Ubuntu", version="2", yes=False)
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_set_version(args)
        mock_run.assert_called_once_with(["--set-version", "Ubuntu", "2"], timeout=1800.0)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_tty_no_input_exits_before_run(self, mock_input, mock_isatty, mock_run):
        """TTY で 'n' 入力の場合は exit 1 し、コマンドは実行されない。"""
        args = argparse.Namespace(name="Ubuntu", version="2", yes=False)
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_set_version(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()


# ---------------------------------------------------------------------------
# cmd_processes
# ---------------------------------------------------------------------------

class TestCmdProcesses(unittest.TestCase):
    """cmd_processes のテスト。"""

    PS_OUTPUT = (
        "  PID USER     %CPU   RSS COMMAND\n"
        "    1 root      0.5  2048 systemd\n"
        "  100 user     10.0 40960 python3\n"
    )

    @patch("wslmgr_cli._run_wsl_command")
    def test_table_format(self, mock_run):
        """table フォーマットで parse_process_list の結果が出力される。"""
        mock_run.return_value = (0, self.PS_OUTPUT, "")
        args = argparse.Namespace(name="Ubuntu", format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_processes(args)
        output = buf.getvalue()
        self.assertIn("systemd", output)
        self.assertIn("python3", output)

    @patch("wslmgr_cli._run_wsl_command")
    def test_json_format_valid(self, mock_run):
        """json フォーマットの出力が有効な JSON でパース可能。"""
        mock_run.return_value = (0, self.PS_OUTPUT, "")
        args = argparse.Namespace(name="Ubuntu", format="json")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_processes(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 2)
        self.assertEqual(data[1]["command"], "python3")

    @patch("wslmgr_cli._run_wsl_command")
    def test_csv_format_header(self, mock_run):
        """csv フォーマットの出力にヘッダ行が含まれる。"""
        mock_run.return_value = (0, self.PS_OUTPUT, "")
        args = argparse.Namespace(name="Ubuntu", format="csv")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_processes(args)
        self.assertIn("PID,User,CPU(%),Memory(MB),Command", buf.getvalue())

    @patch("wslmgr_cli._run_wsl_command")
    def test_failure_exits_with_error(self, mock_run):
        """wsl コマンドが失敗した場合 exit 1 する。"""
        mock_run.return_value = (1, "", "エラー")
        args = argparse.Namespace(name="Ubuntu", format="table")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_processes(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_invoked_with_ps_command(self, mock_run):
        """wsl -d <name> -- sh -lc '<ps コマンド>' で呼び出される。"""
        mock_run.return_value = (0, self.PS_OUTPUT, "")
        args = argparse.Namespace(name="Ubuntu", format="table")
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_processes(args)
        call_args = mock_run.call_args
        self.assertEqual(call_args[0][0][:3], ["-d", "Ubuntu", "--"])
        self.assertIn("ps -eo pid,user,pcpu,rss,comm", call_args[0][0][-1])


# ---------------------------------------------------------------------------
# cmd_log
# ---------------------------------------------------------------------------

class TestCmdLog(unittest.TestCase):
    """cmd_log のテスト。"""

    LOG_TEXT = (
        '{"timestamp": "2026-01-01T00:00:00", "operation": "起動", '
        '"target": "Ubuntu", "result": "成功"}\n'
        '{"timestamp": "2026-01-02T00:00:00", "operation": "停止", '
        '"target": "Ubuntu", "result": "成功"}\n'
        '{"timestamp": "2026-01-03T00:00:00", "operation": "起動", '
        '"target": "Debian", "result": "失敗"}\n'
    )

    @patch("wslmgr_cli.os.path.exists", return_value=False)
    def test_missing_file_shows_message(self, mock_exists):
        """ログファイルが存在しない場合、案内メッセージを表示し例外を出さない。"""
        args = argparse.Namespace(tail=50, format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_log(args)
        self.assertIn("操作ログはまだありません。", buf.getvalue())

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=LOG_TEXT)
    def test_tail_applied_table_format(self, mock_file, mock_exists):
        """--tail が適用され、指定件数分のみ table 形式で出力される。"""
        args = argparse.Namespace(tail=2, format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_log(args)
        output = buf.getvalue()
        lines = [line for line in output.splitlines() if line.strip()]
        self.assertEqual(len(lines), 2)
        self.assertIn("Debian", output)
        self.assertNotIn("2026-01-01", output)

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=LOG_TEXT)
    def test_json_format_valid(self, mock_file, mock_exists):
        """json フォーマットの出力が有効な JSON でパース可能。"""
        args = argparse.Namespace(tail=50, format="json")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_log(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data), 3)

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", side_effect=OSError("読み込み失敗"))
    def test_read_oserror_exits(self, mock_file, mock_exists):
        """ファイル読み込みで OSError が発生した場合 exit 1 する。"""
        args = argparse.Namespace(tail=50, format="table")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_log(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.os.path.exists", return_value=True)
    @patch("builtins.open", new_callable=mock_open, read_data=LOG_TEXT)
    def test_uses_default_log_dir(self, mock_file, mock_exists):
        """wsl_core.get_default_log_dir 配下の operations.jsonl を参照する。"""
        args = argparse.Namespace(tail=50, format="table")
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_log(args)
        # mock_open は open() の呼び出し引数を記録している
        opened_path = mock_file.call_args[0][0]
        self.assertTrue(opened_path.endswith("operations.jsonl"))


# ---------------------------------------------------------------------------
# cmd_portproxy_list / cmd_portproxy_add / cmd_portproxy_delete
# ---------------------------------------------------------------------------

class TestCmdPortproxyList(unittest.TestCase):
    """cmd_portproxy_list のテスト。"""

    NETSH_OUTPUT = (
        "Address         Port        Address         Port\n"
        "--------------- ----------  --------------- ----------\n"
        "0.0.0.0         8080        172.20.0.2      8080\n"
    )

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_table_format_shows_rule(self, mock_run):
        """table フォーマットでルールが表示される。"""
        mock_run.return_value = (0, self.NETSH_OUTPUT, "")
        args = argparse.Namespace(format="table")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_portproxy_list(args)
        output = buf.getvalue()
        self.assertIn("172.20.0.2", output)
        self.assertIn("8080", output)

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_json_format_valid(self, mock_run):
        """json フォーマットの出力が有効な JSON でパース可能。"""
        mock_run.return_value = (0, self.NETSH_OUTPUT, "")
        args = argparse.Namespace(format="json")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_portproxy_list(args)
        data = json.loads(buf.getvalue())
        self.assertEqual(data[0]["connect_address"], "172.20.0.2")

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_failure_exits_with_error(self, mock_run):
        """netsh が失敗した場合 exit 1 する。"""
        mock_run.return_value = (1, "", "アクセスが拒否されました")
        args = argparse.Namespace(format="table")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_list(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_invoked_with_show_all(self, mock_run):
        """'show all' 引数で _run_netsh_portproxy が呼ばれる。"""
        mock_run.return_value = (0, self.NETSH_OUTPUT, "")
        args = argparse.Namespace(format="table")
        with patch("sys.stdout", io.StringIO()):
            wslmgr_cli.cmd_portproxy_list(args)
        mock_run.assert_called_once_with(["show", "all"])


class TestCmdPortproxyAdd(unittest.TestCase):
    """cmd_portproxy_add のテスト。"""

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_invalid_listen_port_exits_before_netsh(self, mock_run):
        """listen_port が不正な場合、netsh を呼ばずに exit 1 する。"""
        args = argparse.Namespace(
            listen_port="not-a-port", connect_port="80",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_add(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_invalid_connect_port_exits_before_netsh(self, mock_run):
        """connect_port が不正な場合、netsh を呼ばずに exit 1 する。"""
        args = argparse.Namespace(
            listen_port="8080", connect_port="99999",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_add(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_success_invokes_netsh_add(self, mock_run):
        """成功時に正しい netsh 引数で呼ばれ、成功メッセージが表示される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(
            listen_port="8080", connect_port="80",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_portproxy_add(args)
        mock_run.assert_called_once_with(
            [
                "add", "v4tov4",
                "listenport=8080",
                "listenaddress=0.0.0.0",
                "connectport=80",
                "connectaddress=172.20.0.2",
            ]
        )
        self.assertIn("追加しました", buf.getvalue())

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_netsh_failure_exits_with_error(self, mock_run):
        """netsh が失敗した場合 exit 1 し、管理者権限に関するメッセージを含む。"""
        mock_run.return_value = (1, "", "アクセスが拒否されました")
        args = argparse.Namespace(
            listen_port="8080", connect_port="80",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        stderr_buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", stderr_buf):
                wslmgr_cli.cmd_portproxy_add(args)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("管理者権限", stderr_buf.getvalue())

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="netsh", timeout=15),
    )
    def test_timeout_exits_with_error(self, mock_run):
        """netsh がタイムアウトした場合 exit 1 する。"""
        args = argparse.Namespace(
            listen_port="8080", connect_port="80",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_add(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("netsh not found"))
    def test_filenotfounderror_exits_with_error(self, mock_run):
        """netsh 実行ファイルが見つからない場合 exit 1 する。"""
        args = argparse.Namespace(
            listen_port="8080", connect_port="80",
            connect_address="172.20.0.2", listen_address="0.0.0.0",
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_add(args)
        self.assertEqual(cm.exception.code, 1)


class TestCmdPortproxyDelete(unittest.TestCase):
    """cmd_portproxy_delete のテスト。"""

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_invalid_listen_port_exits_before_netsh(self, mock_run):
        """listen_port が不正な場合、netsh を呼ばずに exit 1 する。"""
        args = argparse.Namespace(listen_port="0", listen_address="0.0.0.0")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_delete(args)
        self.assertEqual(cm.exception.code, 1)
        mock_run.assert_not_called()

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_success_invokes_netsh_delete(self, mock_run):
        """成功時に正しい netsh 引数で呼ばれ、成功メッセージが表示される。"""
        mock_run.return_value = (0, "", "")
        args = argparse.Namespace(listen_port="8080", listen_address="0.0.0.0")
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            wslmgr_cli.cmd_portproxy_delete(args)
        mock_run.assert_called_once_with(
            ["delete", "v4tov4", "listenport=8080", "listenaddress=0.0.0.0"]
        )
        self.assertIn("削除しました", buf.getvalue())

    @patch("wslmgr_cli._run_netsh_portproxy")
    def test_netsh_failure_exits_with_error(self, mock_run):
        """netsh が失敗した場合 exit 1 し、管理者権限に関するメッセージを含む。"""
        mock_run.return_value = (1, "", "アクセスが拒否されました")
        args = argparse.Namespace(listen_port="8080", listen_address="0.0.0.0")
        stderr_buf = io.StringIO()
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", stderr_buf):
                wslmgr_cli.cmd_portproxy_delete(args)
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("管理者権限", stderr_buf.getvalue())

    @patch(
        "wslmgr_cli.subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="netsh", timeout=15),
    )
    def test_timeout_exits_with_error(self, mock_run):
        """netsh がタイムアウトした場合 exit 1 する。"""
        args = argparse.Namespace(listen_port="8080", listen_address="0.0.0.0")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_delete(args)
        self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run", side_effect=FileNotFoundError("netsh not found"))
    def test_filenotfounderror_exits_with_error(self, mock_run):
        """netsh 実行ファイルが見つからない場合 exit 1 する。"""
        args = argparse.Namespace(listen_port="8080", listen_address="0.0.0.0")
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_portproxy_delete(args)
        self.assertEqual(cm.exception.code, 1)


# ---------------------------------------------------------------------------
# _get_distro_vhdx_path
# ---------------------------------------------------------------------------

class TestGetDistroVhdxPath(unittest.TestCase):
    """_get_distro_vhdx_path のテスト。"""

    def test_winreg_import_error_returns_none(self):
        """winreg が import できない環境 (Linux など) では None を返す。"""
        # 開発環境 (Linux) では winreg が存在しないため、素の呼び出しで None を確認できる。
        result = wslmgr_cli._get_distro_vhdx_path("Ubuntu")
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# build_parser (拡張サブコマンド)
# ---------------------------------------------------------------------------

class TestBuildParserExtendedSubcommands(unittest.TestCase):
    """新しいサブコマンドが build_parser で解析できることを確認する。"""

    def setUp(self):
        self.parser = wslmgr_cli.build_parser()

    def test_set_default_parses(self):
        args = self.parser.parse_args(["set-default", "Ubuntu"])
        self.assertEqual(args.name, "Ubuntu")
        self.assertTrue(hasattr(args, "func"))

    def test_unregister_parses_with_yes(self):
        args = self.parser.parse_args(["unregister", "Ubuntu", "--yes"])
        self.assertEqual(args.name, "Ubuntu")
        self.assertTrue(args.yes)

    def test_unregister_default_yes_false(self):
        args = self.parser.parse_args(["unregister", "Ubuntu"])
        self.assertFalse(args.yes)

    def test_install_parses(self):
        args = self.parser.parse_args(["install", "Ubuntu"])
        self.assertEqual(args.name, "Ubuntu")

    def test_optimize_sparse_parses(self):
        args = self.parser.parse_args(["optimize", "Ubuntu", "--sparse"])
        self.assertTrue(args.sparse)
        self.assertFalse(args.compact)

    def test_optimize_compact_parses(self):
        args = self.parser.parse_args(["optimize", "Ubuntu", "--compact"])
        self.assertTrue(args.compact)

    def test_optimize_default_yes_false(self):
        """optimize サブコマンドの --yes は既定で False。"""
        args = self.parser.parse_args(["optimize", "Ubuntu", "--compact"])
        self.assertFalse(args.yes)

    def test_optimize_yes_flag_parses(self):
        """optimize サブコマンドで --yes / -y が解析できる。"""
        args = self.parser.parse_args(["optimize", "Ubuntu", "--compact", "--yes"])
        self.assertTrue(args.yes)
        args = self.parser.parse_args(["optimize", "Ubuntu", "--compact", "-y"])
        self.assertTrue(args.yes)

    def test_optimize_requires_one_option(self):
        """--sparse も --compact も指定しない場合はエラーになる。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["optimize", "Ubuntu"])

    def test_optimize_mutually_exclusive(self):
        """--sparse と --compact を同時に指定するとエラーになる。"""
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["optimize", "Ubuntu", "--sparse", "--compact"])

    def test_set_version_parses(self):
        args = self.parser.parse_args(["set-version", "Ubuntu", "2", "--yes"])
        self.assertEqual(args.version, "2")
        self.assertTrue(args.yes)

    def test_set_version_invalid_choice_raises(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["set-version", "Ubuntu", "3"])

    def test_processes_default_format(self):
        args = self.parser.parse_args(["processes", "Ubuntu"])
        self.assertEqual(args.format, "table")

    def test_processes_format_json(self):
        args = self.parser.parse_args(["processes", "Ubuntu", "--format", "json"])
        self.assertEqual(args.format, "json")

    def test_log_default_tail(self):
        args = self.parser.parse_args(["log"])
        self.assertEqual(args.tail, 50)
        self.assertEqual(args.format, "table")

    def test_log_custom_tail(self):
        args = self.parser.parse_args(["log", "--tail", "10", "--format", "json"])
        self.assertEqual(args.tail, 10)
        self.assertEqual(args.format, "json")

    def test_portproxy_no_subcommand_has_func(self):
        """portproxy のみ指定した場合でも func 属性が設定される (ヘルプ表示用)。"""
        args = self.parser.parse_args(["portproxy"])
        self.assertTrue(hasattr(args, "func"))

    def test_portproxy_list_parses(self):
        args = self.parser.parse_args(["portproxy", "list"])
        self.assertEqual(args.format, "table")

    def test_portproxy_add_parses(self):
        args = self.parser.parse_args(
            ["portproxy", "add", "8080", "80", "--connect-address", "172.20.0.2"]
        )
        self.assertEqual(args.listen_port, "8080")
        self.assertEqual(args.connect_port, "80")
        self.assertEqual(args.connect_address, "172.20.0.2")
        self.assertEqual(args.listen_address, "0.0.0.0")

    def test_portproxy_add_requires_connect_address(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["portproxy", "add", "8080", "80"])

    def test_portproxy_delete_parses(self):
        args = self.parser.parse_args(["portproxy", "delete", "8080"])
        self.assertEqual(args.listen_port, "8080")
        self.assertEqual(args.listen_address, "0.0.0.0")


# ---------------------------------------------------------------------------
# snapshot / clone サブコマンド
# ---------------------------------------------------------------------------

DISTRO_LIST_OUTPUT = (
    "  NAME      STATE           VERSION\n"
    "* Ubuntu    Running         2\n"
    "  Debian    Stopped         2\n"
)


def _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_20260101-000000.tar",
                     wsl_version="2", comment="", size_bytes=1024,
                     created_at="2026-01-01T00:00:00", write_tar=True):
    """テスト用のスナップショット (json + 任意で tar) をディレクトリに書き込むヘルパー。"""
    if write_tar:
        with open(os.path.join(tmpdir, tar_file), "wb") as f:
            f.write(b"x" * size_bytes)
    json_name = os.path.splitext(tar_file)[0] + ".json"
    metadata = wslmgr_cli.wsl_core.build_snapshot_metadata(
        distro_name, wsl_version, comment, size_bytes, created_at, tar_file
    )
    wslmgr_cli.wsl_core.write_snapshot_metadata(os.path.join(tmpdir, json_name), metadata)
    return tar_file


class TestCmdSnapshotCreate(unittest.TestCase):
    """cmd_snapshot_create のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_creates_tar_and_json(self, mock_run):
        """成功時に export が正しい引数で呼ばれ、json メタデータが書き込まれる。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(name="Ubuntu", comment="test comment", dir=tmpdir)
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_snapshot_create(args)

            export_call = mock_run.call_args_list[1]
            export_args = export_call[0][0]
            self.assertEqual(export_args[0], "--export")
            self.assertEqual(export_args[1], "Ubuntu")
            tar_path = export_args[2]
            self.assertTrue(tar_path.startswith(tmpdir))
            self.assertTrue(tar_path.endswith(".tar"))

            json_files = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
            self.assertEqual(len(json_files), 1)
            with open(os.path.join(tmpdir, json_files[0]), encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["distro_name"], "Ubuntu")
            self.assertEqual(data["comment"], "test comment")
            self.assertEqual(data["wsl_version"], "2")

    @patch("wslmgr_cli._run_wsl_command")
    def test_unknown_distro_exits(self, mock_run):
        """存在しないディストロ名の場合、export を呼ばずに exit 1 する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(name="NoSuchDistro", comment="", dir=tmpdir)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_create(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_export_failure_exits(self, mock_run):
        """export が失敗した場合 exit 1 し、json は書き込まれない。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (1, "", "エクスポート失敗")]
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(name="Ubuntu", comment="", dir=tmpdir)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_create(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual([f for f in os.listdir(tmpdir) if f.endswith(".json")], [])

    @patch("wslmgr_cli.subprocess.run")
    def test_export_timeout_exits(self, mock_run):
        """export がタイムアウトした場合 exit 1 し、json は書き込まれない。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, subprocess.TimeoutExpired(cmd="wsl", timeout=600)]
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(name="Ubuntu", comment="", dir=tmpdir)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_create(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual([f for f in os.listdir(tmpdir) if f.endswith(".json")], [])

    @patch("wslmgr_cli.subprocess.run")
    def test_export_filenotfounderror_exits(self, mock_run):
        """wsl 実行ファイルが見つからない場合 exit 1 する。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, FileNotFoundError("wsl not found")]
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(name="Ubuntu", comment="", dir=tmpdir)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_create(args)
            self.assertEqual(cm.exception.code, 1)


class TestCmdSnapshotList(unittest.TestCase):
    """cmd_snapshot_list のテスト。"""

    def test_empty_dir_shows_message(self):
        """スナップショットが無い場合、案内メッセージを表示する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(dir=tmpdir, format="table")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                wslmgr_cli.cmd_snapshot_list(args)
            self.assertIn("スナップショットがありません。", buf.getvalue())

    def test_table_format_shows_entries_and_total(self):
        """table フォーマットでエントリと合計サイズが表示される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar", size_bytes=2048)
            args = argparse.Namespace(dir=tmpdir, format="table")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                wslmgr_cli.cmd_snapshot_list(args)
            output = buf.getvalue()
            self.assertIn("Ubuntu", output)
            self.assertIn("Ubuntu_1.tar", output)
            self.assertIn("合計", output)

    def test_json_format_valid(self):
        """json フォーマットの出力が有効な JSON でパース可能。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(dir=tmpdir, format="json")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                wslmgr_cli.cmd_snapshot_list(args)
            data = json.loads(buf.getvalue())
            self.assertEqual(len(data), 1)
            self.assertEqual(data[0]["distro_name"], "Ubuntu")
            self.assertTrue(data[0]["tar_exists"])

    def test_missing_tar_shown_as_missing(self):
        """tar ファイルが欠損している場合 MISSING と表示される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, tar_file="Gone.tar", write_tar=False)
            args = argparse.Namespace(dir=tmpdir, format="table")
            buf = io.StringIO()
            with patch("sys.stdout", buf):
                wslmgr_cli.cmd_snapshot_list(args)
            self.assertIn("MISSING", buf.getvalue())


class TestCmdSnapshotRestore(unittest.TestCase):
    """cmd_snapshot_restore のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_with_explicit_name(self, mock_run):
        """--name 指定時、その名前で import が呼ばれる。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar", wsl_version="2")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name="Restored",
                dir=tmpdir, yes=True,
            )
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_snapshot_restore(args)
            import_call = mock_run.call_args_list[1]
            import_args = import_call[0][0]
            self.assertEqual(import_args[0], "--import")
            self.assertEqual(import_args[1], "Restored")
            self.assertEqual(import_args[2], install_dir)
            self.assertTrue(import_args[3].endswith("Ubuntu_1.tar"))
            self.assertEqual(import_args[4:], ["--version", "2"])

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_with_auto_name(self, mock_run):
        """--name 未指定時、default_clone_name による自動名で import が呼ばれる。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar", wsl_version="2")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name=None,
                dir=tmpdir, yes=True,
            )
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_snapshot_restore(args)
            import_call = mock_run.call_args_list[1]
            import_args = import_call[0][0]
            self.assertEqual(import_args[1], "Ubuntu-copy")

    def test_unknown_tar_file_exits(self):
        """未知の tar_file を指定した場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(
                tar_file="NoSuch.tar", install_path="/tmp/x", name=None, dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_duplicate_name_exits(self, mock_run):
        """指定した --name が既存ディストロと重複する場合 exit 1 する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path="/tmp/x", name="Ubuntu",
                dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)

    def test_missing_tar_exits(self):
        """tar ファイルが欠損している場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Gone.tar", write_tar=False)
            args = argparse.Namespace(
                tar_file="Gone.tar", install_path="/tmp/x", name=None, dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_confirmation_declined_aborts(self, mock_input, mock_isatty, mock_run):
        """確認プロンプトで 'n' の場合、import を呼ばずに中止する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path="/tmp/x", name="Restored",
                dir=tmpdir, yes=False,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=False)
    def test_non_tty_without_yes_exits_before_import(self, mock_isatty, mock_run):
        """非対話環境で --yes なしの場合、import を呼ばずに exit 1 する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as tmpdir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path="/tmp/x", name="Restored",
                dir=tmpdir, yes=False,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_existing_vhdx_warns_and_confirms(self, mock_run):
        """復元先に ext4.vhdx が既に存在する場合、上書き警告を表示して確認する。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name="Restored",
                dir=tmpdir, yes=True,
            )
            buf = io.StringIO()
            with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
                with patch("sys.stdout", buf):
                    wslmgr_cli.cmd_snapshot_restore(args)
            self.assertIn("既に仮想ディスク", buf.getvalue())
            self.assertEqual(mock_run.call_count, 2)

    @patch("wslmgr_cli._run_wsl_command")
    def test_import_failure_exits(self, mock_run):
        """import が失敗した (returncode != 0) 場合 exit 1 する。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (1, "", "インポート失敗")]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name="Restored",
                dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_import_timeout_exits(self, mock_run):
        """import がタイムアウトした場合 exit 1 する。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, subprocess.TimeoutExpired(cmd="wsl", timeout=1800)]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name="Restored",
                dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_import_filenotfounderror_exits(self, mock_run):
        """wsl 実行ファイルが見つからない場合 exit 1 する。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, FileNotFoundError("wsl not found")]
        with tempfile.TemporaryDirectory() as tmpdir, tempfile.TemporaryDirectory() as install_dir:
            _write_snapshot(tmpdir, distro_name="Ubuntu", tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(
                tar_file="Ubuntu_1.tar", install_path=install_dir, name="Restored",
                dir=tmpdir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_restore(args)
            self.assertEqual(cm.exception.code, 1)


class TestCmdSnapshotDelete(unittest.TestCase):
    """cmd_snapshot_delete のテスト。"""

    def test_yes_flag_deletes_files(self):
        """--yes 指定時、確認なしで tar と json が削除される。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_file = _write_snapshot(tmpdir, tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(tar_file=tar_file, dir=tmpdir, yes=True)
            with patch("builtins.input", side_effect=AssertionError("input が呼ばれてはいけない")):
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_delete(args)
            self.assertEqual(os.listdir(tmpdir), [])

    def test_unknown_tar_file_exits(self):
        """未知の tar_file を指定した場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            args = argparse.Namespace(tar_file="NoSuch.tar", dir=tmpdir, yes=True)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stderr", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_delete(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("builtins.input", return_value="n")
    def test_confirmation_declined_keeps_files(self, mock_input):
        """確認プロンプトで 'n' の場合、ファイルは削除されない。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_file = _write_snapshot(tmpdir, tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(tar_file=tar_file, dir=tmpdir, yes=False)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_snapshot_delete(args)
            # _confirm_or_exit に統一したため、中止時の終了コードは
            # unregister / set-version と同じ 1 になる
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(len(os.listdir(tmpdir)), 2)

    @patch("wslmgr_cli.os.remove", side_effect=OSError("permission denied"))
    def test_removal_oserror_exits(self, mock_remove):
        """tar / json の削除で OSError が発生した場合 exit 1 する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            tar_file = _write_snapshot(tmpdir, tar_file="Ubuntu_1.tar")
            args = argparse.Namespace(tar_file=tar_file, dir=tmpdir, yes=True)
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_snapshot_delete(args)
            self.assertEqual(cm.exception.code, 1)


class TestCmdClone(unittest.TestCase):
    """cmd_clone のテスト。"""

    @patch("wslmgr_cli._run_wsl_command")
    def test_success_exports_then_imports(self, mock_run):
        """export の後に import が正しい引数で呼ばれ、中間 tar が渡される。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=True,
            )
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_clone(args)

            export_call = mock_run.call_args_list[1]
            import_call = mock_run.call_args_list[2]
            export_args = export_call[0][0]
            import_args = import_call[0][0]
            self.assertEqual(export_args[0], "--export")
            self.assertEqual(export_args[1], "Ubuntu")
            tmp_tar = export_args[2]
            self.assertTrue(tmp_tar.endswith(".tar"))

            self.assertEqual(import_args[0], "--import")
            self.assertEqual(import_args[1], "Ubuntu-copy")
            self.assertEqual(import_args[2], install_dir)
            self.assertEqual(import_args[3], tmp_tar)
            self.assertEqual(import_args[4:], ["--version", "2"])

            # 一時ファイル・ディレクトリは後始末される
            self.assertFalse(os.path.exists(tmp_tar))
            self.assertFalse(os.path.exists(os.path.dirname(tmp_tar)))

    @patch("wslmgr_cli._run_wsl_command")
    def test_invalid_new_name_exits_before_export(self, mock_run):
        """new_name が不正な場合、export を呼ばずに exit 1 する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        args = argparse.Namespace(
            name="Ubuntu", new_name="bad/name", install_path="/tmp/x", yes=True,
        )
        with self.assertRaises(SystemExit) as cm:
            with patch("sys.stderr", io.StringIO()):
                wslmgr_cli.cmd_clone(args)
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_export_failure_skips_import(self, mock_run):
        """export が失敗した場合、import は呼ばれず exit 1 する。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (1, "", "エクスポート失敗")]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 2)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_confirmation_declined_aborts(self, mock_input, mock_isatty, mock_run):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """複製先に ext4.vhdx が既に存在し、確認プロンプトで 'n' の場合、export を呼ばずに中止する。"""  # noqa: E501
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as install_dir:
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=False,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=False)
    def test_non_tty_without_yes_exits_when_vhdx_exists(self, mock_isatty, mock_run):
        # 日本語の1文なので途中改行は読みにくく、() による暗黙連結では
        # docstring の見た目が不自然になるため、1 行のまま noqa で許容する。
        """非対話環境で複製先に ext4.vhdx が存在し --yes なしの場合、export を呼ばずに exit 1 する。"""  # noqa: E501
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as install_dir:
            with open(os.path.join(install_dir, "ext4.vhdx"), "wb") as f:
                f.write(b"x")
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=False,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="y")
    def test_confirms_even_without_existing_vhdx(self, mock_input, mock_isatty, mock_run):
        """複製先が空でも新規登録を伴うため必ず確認し、承諾すれば実行される。"""
        mock_run.side_effect = [(0, DISTRO_LIST_OUTPUT, ""), (0, "", ""), (0, "", "")]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=False,
            )
            with patch("sys.stdout", io.StringIO()):
                wslmgr_cli.cmd_clone(args)
            self.assertEqual(mock_input.call_count, 1)
            self.assertEqual(mock_run.call_count, 3)

    @patch("wslmgr_cli._run_wsl_command")
    @patch("sys.stdin.isatty", return_value=True)
    @patch("builtins.input", return_value="n")
    def test_declining_confirmation_skips_export(self, mock_input, mock_isatty, mock_run):
        """確認を拒否した場合、export / import を呼ばずに exit 1 する。"""
        mock_run.return_value = (0, DISTRO_LIST_OUTPUT, "")
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=False,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)
            # --list --verbose の 1 回だけで、export は呼ばれていない
            self.assertEqual(mock_run.call_count, 1)

    @patch("wslmgr_cli._run_wsl_command")
    def test_import_failure_exits(self, mock_run):
        """import が失敗した場合、exit 1 する (tmp ファイルは後始末される)。"""
        mock_run.side_effect = [
            (0, DISTRO_LIST_OUTPUT, ""), (0, "", ""), (1, "", "インポート失敗"),
        ]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)
            self.assertEqual(mock_run.call_count, 3)

    @patch("wslmgr_cli.subprocess.run")
    def test_export_timeout_exits(self, mock_run):
        """export がタイムアウトした場合 exit 1 する。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, subprocess.TimeoutExpired(cmd="wsl", timeout=1800)]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)

    @patch("wslmgr_cli.subprocess.run")
    def test_export_filenotfounderror_exits(self, mock_run):
        """wsl 実行ファイルが見つからない場合 exit 1 する。"""
        list_proc = MagicMock()
        list_proc.returncode = 0
        list_proc.stdout = b"\xff\xfe" + DISTRO_LIST_OUTPUT.encode("utf-16-le")
        list_proc.stderr = b""
        mock_run.side_effect = [list_proc, FileNotFoundError("wsl not found")]
        with tempfile.TemporaryDirectory() as install_dir:
            args = argparse.Namespace(
                name="Ubuntu", new_name="Ubuntu-copy", install_path=install_dir, yes=True,
            )
            with self.assertRaises(SystemExit) as cm:
                with patch("sys.stdout", io.StringIO()):
                    with patch("sys.stderr", io.StringIO()):
                        wslmgr_cli.cmd_clone(args)
            self.assertEqual(cm.exception.code, 1)


class TestBuildParserSnapshotClone(unittest.TestCase):
    """build_parser で snapshot / clone サブコマンドが解析できることを確認する。"""

    def setUp(self):
        self.parser = wslmgr_cli.build_parser()

    def test_snapshot_no_subcommand_has_func(self):
        args = self.parser.parse_args(["snapshot"])
        self.assertTrue(hasattr(args, "func"))

    def test_snapshot_create_parses(self):
        args = self.parser.parse_args(["snapshot", "create", "Ubuntu", "--comment", "hi"])
        self.assertEqual(args.name, "Ubuntu")
        self.assertEqual(args.comment, "hi")
        self.assertIsNone(args.dir)

    def test_snapshot_list_default_format(self):
        args = self.parser.parse_args(["snapshot", "list"])
        self.assertEqual(args.format, "table")

    def test_snapshot_restore_requires_install_path(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["snapshot", "restore", "Ubuntu_1.tar"])

    def test_snapshot_restore_parses(self):
        args = self.parser.parse_args(
            ["snapshot", "restore", "Ubuntu_1.tar", "--install-path", "C:\\wsl\\R", "--yes"]
        )
        self.assertEqual(args.tar_file, "Ubuntu_1.tar")
        self.assertEqual(args.install_path, "C:\\wsl\\R")
        self.assertTrue(args.yes)

    def test_snapshot_delete_parses(self):
        args = self.parser.parse_args(["snapshot", "delete", "Ubuntu_1.tar"])
        self.assertEqual(args.tar_file, "Ubuntu_1.tar")
        self.assertFalse(args.yes)

    def test_clone_requires_install_path(self):
        with self.assertRaises(SystemExit):
            self.parser.parse_args(["clone", "Ubuntu", "Ubuntu-copy"])

    def test_clone_parses(self):
        args = self.parser.parse_args(
            ["clone", "Ubuntu", "Ubuntu-copy", "--install-path", "C:\\wsl\\C", "--yes"]
        )
        self.assertEqual(args.name, "Ubuntu")
        self.assertEqual(args.new_name, "Ubuntu-copy")
        self.assertEqual(args.install_path, "C:\\wsl\\C")
        self.assertTrue(args.yes)


class TestResolveSnapshotDir(unittest.TestCase):
    """_resolve_snapshot_dir のテスト。"""

    def test_explicit_dir_takes_precedence(self):
        """--dir が指定されている場合、それを返す。"""
        args = argparse.Namespace(dir="/custom/path")
        with patch("wslmgr_cli.wsl_core.load_settings") as mock_load:
            result = wslmgr_cli._resolve_snapshot_dir(args)
        self.assertEqual(result, "/custom/path")
        mock_load.assert_not_called()

    def test_falls_back_to_settings(self):
        """--dir 未指定時、設定ファイルの snapshot_dir を使う。"""
        args = argparse.Namespace(dir=None)
        with patch(
            "wslmgr_cli.wsl_core.load_settings", return_value={"snapshot_dir": "/from/settings"}
        ):
            result = wslmgr_cli._resolve_snapshot_dir(args)
        self.assertEqual(result, "/from/settings")

    def test_falls_back_to_default_when_settings_empty(self):
        """設定に snapshot_dir が無い場合、wsl_core.get_default_snapshot_dir() を使う。"""
        args = argparse.Namespace(dir=None)
        with patch("wslmgr_cli.wsl_core.load_settings", return_value={}):
            with patch(
                "wslmgr_cli.wsl_core.get_default_snapshot_dir", return_value="/default/dir"
            ):
                result = wslmgr_cli._resolve_snapshot_dir(args)
        self.assertEqual(result, "/default/dir")


if __name__ == "__main__":
    unittest.main()
