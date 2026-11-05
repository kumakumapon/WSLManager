"""配布物 (PyInstaller の spec) とバージョンの整合を守る静的テスト。

ビルドそのものは CI (build ジョブ) が行う。ここでは、ビルドが壊れやすい前提条件
(CLI が tkinter を引き込まないこと、spec の設定、バージョンの一致) をソースだけで検査する。
"""

from __future__ import annotations

import ast
import importlib.util
import re
import shutil
import subprocess
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CLI_SPEC = ROOT / "WSLManagerCLI.spec"
GUI_SPEC = ROOT / "WSLManager.spec"
BUILD_SCRIPT = ROOT / "build.ps1"
SUPPORT = ROOT / "tools" / "pyinstaller_support.py"


def _load_support() -> Any:
    """spec と同じ方法 (sys.path を変えずにファイルから) で補助モジュールを読み込む。"""
    spec = importlib.util.spec_from_file_location("wslmgr_pyinstaller_support", SUPPORT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

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


class ExecutableMetadataTests(unittest.TestCase):
    """両方の exe にアイコンとバージョン情報を付け、GUI は実行時にアイコンを読めるようにする。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.specs = {
            "gui": GUI_SPEC.read_text(encoding="utf-8"),
            "cli": CLI_SPEC.read_text(encoding="utf-8"),
        }

    def test_both_executables_get_the_icon_and_the_version_resource(self) -> None:
        for name, spec in self.specs.items():
            with self.subTest(spec=name):
                self.assertIn("icon='assets/wslmanager.ico'", spec)
                self.assertIn("version=support.build_version_info(", spec)
                self.assertIn("tools', 'pyinstaller_support.py'", spec)

    def test_gui_bundles_the_icon_for_the_window(self) -> None:
        # wslmgr_gui/resources.py が実行時に sys._MEIPASS/assets から読む
        self.assertIn("('assets/wslmanager.ico', 'assets')", self.specs["gui"])
        self.assertIn("('assets/wslmanager.png', 'assets')", self.specs["gui"])
        for file in ("wslmanager.ico", "wslmanager.png"):
            self.assertTrue((ROOT / "assets" / file).is_file(), file)

    def test_icon_has_the_sizes_windows_uses(self) -> None:
        data = (ROOT / "assets" / "wslmanager.ico").read_bytes()
        reserved, kind, count = (int.from_bytes(data[i : i + 2], "little") for i in (0, 2, 4))
        self.assertEqual((reserved, kind), (0, 1))  # ICO ファイル
        sizes = set()
        for index in range(count):
            entry = data[6 + 16 * index : 6 + 16 * (index + 1)]
            size = entry[0] or 256  # 0 は 256 px を表す
            sizes.add(size)
            offset = int.from_bytes(entry[12:16], "little")
            is_png = data[offset : offset + 4] == b"\x89PNG"
            # Tk 8.6 の wm iconbitmap は DIB しか読めない。PNG 圧縮は 256 px だけにする
            self.assertEqual(is_png, size == 256, f"{size} px entry")
        self.assertTrue({16, 32, 48, 256} <= sizes, sizes)

    def test_gui_does_not_use_upx_either(self) -> None:
        # UPX はウイルス対策ソフトの誤検知を増やすため、GUI でも使わない
        self.assertIn("upx=False", self.specs["gui"])
        self.assertNotIn("upx=True", self.specs["gui"])

    def test_pyinstaller_hooks_are_still_used_by_the_gui_only(self) -> None:
        self.assertIn("hookspath=['pyinstaller_hooks']", self.specs["gui"])


class VersionResourceTests(unittest.TestCase):
    def test_reads_the_same_version_as_wsl_core(self) -> None:
        import wsl_core

        self.assertEqual(_load_support().read_version(ROOT), wsl_core.__version__)

    def test_version_tuple_has_four_numbers(self) -> None:
        support = _load_support()

        self.assertEqual(support.version_tuple("1.2.3"), (1, 2, 3, 0))
        for bad in ("1.2.3rc1", "1..2", "", "1.2.3.4.5"):
            with self.subTest(version=bad), self.assertRaises(ValueError):
                support.version_tuple(bad)

    def test_version_strings_name_the_product_and_the_file(self) -> None:
        strings = _load_support().version_strings(
            "1.2.3", description="WSL Manager", internal_name="WSLManager"
        )

        self.assertEqual(strings["ProductName"], "WSL Manager")
        self.assertEqual(strings["ProductVersion"], "1.2.3")
        self.assertEqual(strings["OriginalFilename"], "WSLManager.exe")

    def test_no_version_resource_outside_windows(self) -> None:
        # PyInstaller.utils.win32 は Windows 専用。ほかの OS ではバージョンの検証だけ行う
        support = _load_support()

        self.assertIsNone(
            support.build_version_info(
                ROOT, description="x", internal_name="x", platform="linux"
            )
        )


class BuildScriptTests(unittest.TestCase):
    """build.ps1: 配布物を 1 コマンドで作るスクリプト (CI も同じものを使う)。"""

    @classmethod
    def setUpClass(cls) -> None:
        # Windows PowerShell 5.1 は BOM の無いファイルを ANSI として読むため、ASCII のみ
        cls.text = BUILD_SCRIPT.read_bytes().decode("ascii").replace("\r\n", "\n")

    def test_builds_both_specs_the_installer_and_the_portable_zip(self) -> None:
        for expected in (
            "WSLManager.spec",
            "WSLManagerCLI.spec",
            "installer\\WSLManager.iss",
            "-portable.zip",
            "Compress-Archive",
            "SHA256SUMS.txt",
        ):
            self.assertIn(expected, self.text)

    def test_pins_pyinstaller(self) -> None:
        match = re.search(r'\$PyInstallerVersion = "([^"]+)"', self.text)

        self.assertIsNotNone(match)
        self.assertRegex(match.group(1) if match else "", r"^\d+\.\d+\.\d+$")
        self.assertIn('"pyinstaller==$PyInstallerVersion"', self.text)

    def test_stops_on_the_first_failure(self) -> None:
        self.assertIn('$ErrorActionPreference = "Stop"', self.text)
        self.assertIn("$LASTEXITCODE -ne 0", self.text)

    def test_portable_zip_contains_both_executables_and_the_documents(self) -> None:
        loop = next(ln for ln in self.text.splitlines() if "foreach ($file in @($gui, $cli" in ln)
        for name in ("README.md", "README.ja.md", "LICENSE"):
            self.assertIn(name, loop)

    def test_checks_that_the_cli_reports_the_version(self) -> None:
        self.assertIn("& $cli --version", self.text)

    def test_version_comes_from_wsl_core(self) -> None:
        self.assertIn("wsl_core\\__init__.py", self.text)

    @unittest.skipUnless(shutil.which("pwsh"), "pwsh (PowerShell 7) が見つからない")
    def test_parses_in_powershell(self) -> None:
        command = (
            "$errors = $null; $tokens = $null; "
            f"[void][System.Management.Automation.Language.Parser]::ParseFile('{BUILD_SCRIPT}', "
            "[ref]$tokens, [ref]$errors); "
            "if ($errors.Count -gt 0) { $errors | ForEach-Object { $_.ToString() }; exit 1 }"
        )
        result = subprocess.run(
            ["pwsh", "-NoProfile", "-Command", command], capture_output=True, text=True, timeout=120
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


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
