"""配布物 (PyInstaller の spec) とバージョンの整合を守る静的テスト。

ビルドそのものは CI (build ジョブ) が行う。ここでは、ビルドが壊れやすい前提条件
(CLI が tkinter を引き込まないこと、spec の設定、バージョンの一致) をソースだけで検査する。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI_SPEC = ROOT / "WSLManagerCLI.spec"
GUI_SPEC = ROOT / "WSLManager.spec"

# CLI の exe に含めてはいけないモジュール (tkinter と GUI)。
# winreg (Windows 版 Python の標準モジュール) は、仮想ディスクのサイズを読むために CLI も使う。
# Python に組み込まれているので凍結した exe でも動くことを確認済み。
FORBIDDEN_FOR_CLI = {"tkinter", "_tkinter", "wslmgr", "wslmgr_gui"}


def _imported_roots(path: Path) -> set[str]:
    """ファイル内の import 文 (関数内を含む) が参照する最上位モジュール名を返す。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


class CliSpecTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.spec = CLI_SPEC.read_text(encoding="utf-8")

    def test_builds_the_cli_entry_point_as_a_console_exe_named_wslmgr(self) -> None:
        self.assertIn("['wslmgr_cli.py']", self.spec)
        self.assertIn("name='wslmgr'", self.spec)
        self.assertIn("console=True", self.spec)
        self.assertNotIn("console=False", self.spec)

    def test_excludes_tkinter(self) -> None:
        match = re.search(r"excludes=\[([^\]]*)\]", self.spec)

        self.assertIsNotNone(match)
        excluded = match.group(1) if match else ""
        self.assertIn("'tkinter'", excluded)
        self.assertIn("'_tkinter'", excluded)

    def test_is_independent_of_the_gui_build(self) -> None:
        # 変更禁止領域 (pyinstaller_hooks/) とは独立に作る。GUI 用のフックは使わない
        self.assertIn("hookspath=[]", self.spec)
        for line in self.spec.splitlines():
            if not line.lstrip().startswith("#"):
                self.assertNotIn("pyinstaller_hooks", line)

    def test_does_not_use_upx(self) -> None:
        # UPX はウイルス対策ソフトの誤検知を増やすため使わない
        self.assertIn("upx=False", self.spec)
        self.assertNotIn("upx=True", self.spec)

    def test_spec_file_is_not_ignored_by_git(self) -> None:
        gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        self.assertIn("!WSLManagerCLI.spec", gitignore)  # `*.spec` の例外が無いと追跡されない
        self.assertIn("!WSLManager.spec", gitignore)

    def test_gui_spec_still_builds_the_windowed_exe(self) -> None:
        gui = GUI_SPEC.read_text(encoding="utf-8")

        self.assertIn("['wslmgr.py']", gui)
        self.assertIn("name='WSLManager'", gui)
        self.assertIn("console=False", gui)


class CliDependencyTests(unittest.TestCase):
    """CLI の exe は tkinter や GUI を取り込まない (spec の excludes の前提)。"""

    def test_cli_module_does_not_import_gui_or_tkinter(self) -> None:
        roots = _imported_roots(ROOT / "wslmgr_cli.py")

        self.assertEqual(roots & FORBIDDEN_FOR_CLI, set())

    def test_wsl_core_does_not_import_gui_or_tkinter(self) -> None:
        offenders: dict[str, set[str]] = {}
        for path in sorted((ROOT / "wsl_core").glob("*.py")):
            found = _imported_roots(path) & FORBIDDEN_FOR_CLI
            if found:
                offenders[path.name] = found

        self.assertEqual(offenders, {})


class VersionTests(unittest.TestCase):
    def test_pyproject_and_wsl_core_versions_match(self) -> None:
        # tomllib は 3.11 以降なので、Python 3.10 でも動くよう正規表現で読む
        pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        match = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.MULTILINE)
        self.assertIsNotNone(match, "pyproject.toml に version が見つからない")

        import wsl_core

        self.assertEqual(wsl_core.__version__, match.group(1) if match else None)

    def test_version_is_a_plain_numeric_release(self) -> None:
        # インストーラ (VersionInfoVersion) は数値 X.Y.Z だけを受け付ける
        import wsl_core

        self.assertRegex(wsl_core.__version__, r"^\d+\.\d+\.\d+$")


if __name__ == "__main__":
    unittest.main()
