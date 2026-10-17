"""CLI ランチャー ``wslmgr.bat`` のテスト。

バッチファイルのファイル形式を検査するテストは OS を問わず実行する。実際に起動するテストは
Windows のみ (``cmd.exe`` が必要)。起動するのは ``wslmgr_cli.py --version`` と、引数エラーで
終了する呼び出しだけで、WSL には一切触れない。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

LAUNCHER = Path(__file__).resolve().parents[1] / "wslmgr.bat"


class LauncherFileTests(unittest.TestCase):
    def test_launcher_exists_next_to_the_cli(self) -> None:
        self.assertTrue(LAUNCHER.is_file())
        self.assertTrue((LAUNCHER.parent / "wslmgr_cli.py").is_file())

    def test_is_ascii_only(self) -> None:
        # cmd.exe はコードページ依存で日本語のバッチファイルを誤読するため、ASCII に限定する
        LAUNCHER.read_bytes().decode("ascii")

    def test_uses_crlf_line_endings_only(self) -> None:
        # goto のラベルは LF だけの改行だと正しく解釈されない場合がある (.gitattributes で固定)
        data = LAUNCHER.read_bytes()

        self.assertIn(b"\r\n", data)
        self.assertEqual(data.count(b"\n"), data.count(b"\r\n"), "LF のみの行がある")

    def test_looks_for_python_in_the_documented_order(self) -> None:
        text = LAUNCHER.read_text(encoding="ascii")
        # 冒頭のコメントではなく、実際の判定行の順序を比べる
        venv = text.index('if exist "%VENV_PY%"')
        py_launcher = text.index("where py ")
        python = text.index("where python ")

        self.assertLess(venv, py_launcher)
        self.assertLess(py_launcher, python)

    def test_passes_all_arguments_and_the_exit_code_through(self) -> None:
        text = LAUNCHER.read_text(encoding="ascii")

        self.assertGreaterEqual(text.count('"%CLI%" %*'), 3)  # 3 つの実行経路すべてで %* を渡す
        self.assertGreaterEqual(text.count("exit /b %ERRORLEVEL%"), 3)


@unittest.skipUnless(sys.platform == "win32", "cmd.exe が必要 (Windows のみ)")
class LauncherRunTests(unittest.TestCase):
    @staticmethod
    def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ, PYTHONIOENCODING="utf-8")
        # .bat は Windows が cmd 経由で実行する。cmd /c の引用符の扱いに依存しない呼び方にする
        return subprocess.run(
            [str(LAUNCHER), *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            env=env,
            cwd=cwd,
        )

    def test_version_runs_the_cli(self) -> None:
        result = self._run("--version")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WSL Manager", result.stdout)

    def test_works_from_any_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self._run("--version", cwd=tmp)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("WSL Manager", result.stdout)

    def test_cli_exit_code_is_returned_unchanged(self) -> None:
        # argparse の引数エラーは終了コード 2
        result = self._run("no-such-command")

        self.assertEqual(result.returncode, 2)
        self.assertIn("invalid choice", result.stderr)


if __name__ == "__main__":
    unittest.main()
