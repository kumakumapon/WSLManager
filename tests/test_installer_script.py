"""インストーラ (Inno Setup) スクリプトを守るテスト。

静的な検査 (OS を問わず実行) と、`iscc` が見つかる環境でだけ行う実コンパイルがある。
インストール/アンインストールそのものの試験は CI の Windows ランナーで行う。
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "installer"
ISS = INSTALLER / "WSLManager.iss"
MESSAGES_EN = INSTALLER / "CustomMessages.en.isl"
MESSAGES_JA = INSTALLER / "CustomMessages.ja.isl"

# アップグレード・アンインストールの識別子。一度公開したら変えてはいけない。
APP_ID = "8B6B5F71-92D9-4A1C-9145-812D3E9E9C6A"

# Inno Setup が最初から持っているメッセージ (自前で定義しなくてよい)
BUILTIN_MESSAGES = {"CreateDesktopIcon", "AdditionalIcons", "LaunchProgram"}


def _section(text: str, name: str) -> str:
    """[Section] の本文 (次の [Section] の手前まで) を返す。"""
    match = re.search(rf"^\[{name}\]\s*$(.*?)(?=^\[\w+\]\s*$|\Z)", text, re.MULTILINE | re.DOTALL)
    return match.group(1) if match else ""


def _code_lines(section: str) -> list[str]:
    """コメント (; で始まる行) と空行を除いた行を返す。"""
    return [
        ln.strip() for ln in section.splitlines() if ln.strip() and not ln.strip().startswith(";")
    ]


def _define(text: str, name: str) -> str:
    match = re.search(rf'^#define {name} "([^"]*)"', text, re.MULTILINE)
    assert match, f"#define {name} が見つからない"
    return match.group(1)


def _message_names(path: Path) -> set[str]:
    text = path.read_bytes().decode("utf-8-sig").replace("\r\n", "\n")
    return set(re.findall(r"^(\w+)=", _section(text, "CustomMessages"), re.MULTILINE))


def _find_iscc() -> str | None:
    candidates = [os.environ.get("ISCC"), shutil.which("iscc")]
    for base in (
        os.environ.get("PROGRAMFILES(X86)"),
        os.environ.get("PROGRAMFILES"),
        os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs"),
    ):
        if base:
            candidates.append(os.path.join(base, "Inno Setup 6", "ISCC.exe"))
    for candidate in candidates:
        if candidate and os.path.isfile(candidate):
            return candidate
    return None


class InstallerScriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # ASCII 以外が混ざると、文字コードの違う環境で読み違える (日本語は .isl に分離する)
        # 改行 (CRLF / LF) の違いで結果が変わらないよう LF にそろえる
        cls.text = ISS.read_bytes().decode("ascii").replace("\r\n", "\n")

    def test_message_files_have_the_right_encoding(self) -> None:
        MESSAGES_EN.read_bytes().decode("ascii")
        ja = MESSAGES_JA.read_bytes()

        self.assertTrue(ja.startswith(b"\xef\xbb\xbf"), "日本語のメッセージは UTF-8 (BOM 付き)")
        self.assertTrue(any(b > 0x7F for b in ja), "日本語の文字が含まれていない")

    def test_app_id_is_pinned(self) -> None:
        match = re.search(r"^AppId=\{\{([0-9A-F-]+)\}$", self.text, re.MULTILINE)

        self.assertIsNotNone(match, "AppId の書式が違う ({{GUID} の形)")
        self.assertEqual(match.group(1) if match else None, APP_ID, "AppId は変更してはいけない")

    def test_version_comes_from_the_build(self) -> None:
        self.assertIn("#ifndef AppVersion", self.text)
        self.assertIn("AppVersion={#AppVersion}", self.text)
        self.assertIn("OutputBaseFilename=WSLManager-Setup-{#AppVersion}", self.text)
        # 4 桁の数値だけを受け付ける VersionInfoVersion は X.Y.Z + ".0" で作る
        self.assertIn("VersionInfoVersion={#AppVersion}.0", self.text)
        self.assertNotRegex(self.text, r"(?m)^AppVersion=\d", "バージョンを直書きしてはいけない")

    def test_requires_a_recent_enough_inno_setup(self) -> None:
        self.assertIn("#if VER < EncodeVer(6, 3, 0)", self.text)  # x64compatible は 6.3 以降
        self.assertIn("ArchitecturesAllowed=x64compatible", self.text)
        self.assertIn("ArchitecturesInstallIn64BitMode=x64compatible", self.text)

    def test_installs_per_user_by_default_and_can_be_all_users(self) -> None:
        self.assertIn("PrivilegesRequired=lowest", self.text)
        match = re.search(r"^PrivilegesRequiredOverridesAllowed=(.*)$", self.text, re.MULTILINE)

        self.assertIsNotNone(match)
        allowed = (match.group(1) if match else "").split()
        self.assertIn("dialog", allowed)  # インストール時に全ユーザー向けを選べる
        self.assertIn("commandline", allowed)  # /CURRENTUSER / /ALLUSERS を使える

    def test_app_mutex_matches_the_gui(self) -> None:
        source = (ROOT / "wslmgr.py").read_text(encoding="utf-8")
        match = re.search(r'mutex_name = ("[^"]+")', source)
        self.assertIsNotNone(match, "wslmgr.py の Mutex 名が見つからない")
        gui_mutex = ast.literal_eval(match.group(1)) if match else None

        self.assertEqual(_define(self.text, "AppMutexName"), gui_mutex)
        self.assertIn("AppMutex={#AppMutexName}", self.text)

    def test_path_tasks_are_off_by_default(self) -> None:
        tasks = [ln for ln in _code_lines(_section(self.text, "Tasks")) if "addtopath" in ln]

        self.assertEqual(len(tasks), 2, "ユーザー PATH とシステム PATH の 2 つのタスクがあるはず")
        for line in tasks:
            self.assertIn("unchecked", line, line)
        # ユーザー単位ではユーザー PATH、全ユーザーではシステム PATH だけを見せる
        self.assertTrue(any("not IsAdminInstallMode" in ln for ln in tasks))
        self.assertTrue(any(ln.endswith("Check: IsAdminInstallMode") for ln in tasks))

    def test_desktop_icon_is_optional(self) -> None:
        tasks = _code_lines(_section(self.text, "Tasks"))
        desktop = [ln for ln in tasks if '"desktopicon"' in ln]

        self.assertEqual(len(desktop), 1)
        self.assertIn("unchecked", desktop[0])

    def test_ships_both_executables_and_the_license(self) -> None:
        files = "\n".join(_code_lines(_section(self.text, "Files")))
        gui_name = _define(self.text, "AppExeName")
        cli_name = _define(self.text, "CliExeName")

        self.assertIn("{#AppExeName}", files)
        self.assertIn("{#CliExeName}", files)
        self.assertIn(r"..\LICENSE", files)
        # spec の出力名と一致している
        self.assertIn("name='WSLManager'", (ROOT / "WSLManager.spec").read_text(encoding="utf-8"))
        self.assertEqual(gui_name, "WSLManager.exe")
        self.assertIn("name='wslmgr'", (ROOT / "WSLManagerCLI.spec").read_text(encoding="utf-8"))
        self.assertEqual(cli_name, "wslmgr.exe")

    def test_launches_the_gui_as_the_original_user(self) -> None:
        # 全ユーザー向け (昇格した Setup) でも、GUI が管理者権限のまま起動しない
        # (設定の保存先 %APPDATA% が、昇格に使った管理者アカウントのものになるのを防ぐ)
        run = [ln for ln in _code_lines(_section(self.text, "Run")) if "AppExeName" in ln]

        self.assertEqual(len(run), 1)
        for flag in ("postinstall", "skipifsilent", "runasoriginaluser"):
            self.assertIn(flag, run[0])

    def test_does_not_close_a_running_cli_on_its_own(self) -> None:
        # AppMutex が止めるのは GUI だけ。実行中の wslmgr.exe (エクスポートや定期スナップショット
        # の最中かもしれない) を、Restart Manager が確認なしで閉じてバックアップを壊さない
        self.assertIn("CloseApplications=no", self.text)

    def test_never_deletes_user_data(self) -> None:
        # 設定・ログ・スナップショット (WSL のバックアップ) はインストール先の外にあり、消さない
        self.assertEqual(_section(self.text, "UninstallDelete").strip(), "")
        code = "\n".join(_code_lines(self.text))
        for forbidden in (
            "WSLSnapshots",
            "{userappdata}",
            "{%USERPROFILE",
            "{userdocs}",
            "{localappdata}",
        ):
            self.assertNotIn(forbidden, code, forbidden)
        self.assertNotIn("uninsneveruninstall", self.text.lower())
        self.assertNotIn("DelTree", self.text)  # [Code] でフォルダを再帰削除しない

    def test_languages_and_custom_messages_are_consistent(self) -> None:
        languages = _section(self.text, "Languages")
        self.assertIn("compiler:Default.isl,CustomMessages.en.isl", languages)
        self.assertIn(r"compiler:Languages\Japanese.isl,CustomMessages.ja.isl", languages)

        referenced = set(re.findall(r"\{cm:(\w+)", self.text))
        referenced |= set(re.findall(r"CustomMessage\('(\w+)'\)", self.text))
        referenced -= BUILTIN_MESSAGES
        english, japanese = _message_names(MESSAGES_EN), _message_names(MESSAGES_JA)

        self.assertTrue(referenced, "自前のメッセージが 1 つも参照されていない")
        self.assertEqual(referenced - english, set(), "英語のメッセージが足りない")
        self.assertEqual(referenced - japanese, set(), "日本語のメッセージが足りない")
        self.assertEqual(english, japanese, "英語と日本語で定義されているメッセージが違う")

    def test_path_is_changed_only_for_the_chosen_task_and_removed_on_uninstall(self) -> None:
        code = _section(self.text, "Code")

        self.assertIn("WizardIsTaskSelected('addtopath_user')", code)
        self.assertIn("WizardIsTaskSelected('addtopath_system')", code)
        # REG_EXPAND_SZ を保つ (追加と除去の 2 か所)。
        # REG_SZ で書くと %USERPROFILE% などが展開されなくなる
        self.assertGreaterEqual(code.count("RegWriteExpandStringValue"), 2)
        self.assertNotIn("RegWriteStringValue", code)
        self.assertIn("usPostUninstall", code)  # アンインストール時に自分のエントリだけ除去
        self.assertIn("ChangesEnvironment=yes", self.text)
        self.assertNotIn("setx", code.lower())  # setx は 1024 文字で切り詰める


class InstallerCiTests(unittest.TestCase):
    # Chocolatey のコミュニティフィードに実在することを確認済みの innosetup の版。
    # (手元に入れた公式配布の 6.7.3 は、Chocolatey には存在せず、404 になる)
    # 版を上げるときは、フィードに実在することを確認してから、ここに足す (確認日: 2026-10-18)。
    KNOWN_CHOCOLATEY_VERSIONS = frozenset({"6.7.1", "6.7.0", "6.6.1"})

    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    def test_chocolatey_fallback_pins_a_published_version(self) -> None:
        match = re.search(r"choco install innosetup --version=(\S+)", self.workflow)

        self.assertIsNotNone(match, "Chocolatey のフォールバックが見つからない")
        version = match.group(1) if match else ""
        self.assertIn(version, self.KNOWN_CHOCOLATEY_VERSIONS)
        # .iss の最小版 (6.3) 以上であること
        major_minor = tuple(int(x) for x in version.split(".")[:2])
        self.assertGreaterEqual(major_minor, (6, 3))

    def test_installer_steps_end_with_an_explicit_exit_zero(self) -> None:
        # Actions の pwsh は最後に `exit $LASTEXITCODE` を付ける。最後に実行したネイティブコマンドの
        # 終了コードが残ると、検証がすべて成功していてもステップが失敗扱いになる
        for step in ("Locate Inno Setup", "Build installer (Inno Setup)"):
            block = self.workflow.split(f"name: {step}", 1)[1].split("      - name:", 1)[0]
            self.assertTrue(block.rstrip().endswith("exit 0"), step)

    def test_builds_the_installer_on_every_run_and_uploads_it(self) -> None:
        self.assertIn("name: Build installer (Inno Setup)", self.workflow)
        self.assertIn("name: WSLManager-installer", self.workflow)
        # 数値の X.Y.Z 以外のバージョンでは失敗させる (インストーラの VersionInfoVersion の前提)
        self.assertIn("numeric X.Y.Z", self.workflow)


@unittest.skipUnless(_find_iscc(), "iscc (Inno Setup 6) が見つからない")
class InstallerCompileTests(unittest.TestCase):
    """実際に iscc でコンパイルできること (ダミーの exe を使う)。"""

    def _compile(self, version: str, *, with_cli: bool = True) -> tuple[int, str, Path]:
        iscc = _find_iscc()
        assert iscc
        tmp = Path(tempfile.mkdtemp(prefix="wslm_iss_"))
        self.addCleanup(shutil.rmtree, tmp, True)
        dist, out = tmp / "dist", tmp / "out"
        dist.mkdir()
        (dist / "WSLManager.exe").write_bytes(b"MZ" + b"\0" * 2048)
        if with_cli:
            (dist / "wslmgr.exe").write_bytes(b"MZ" + b"\0" * 2048)
        result = subprocess.run(
            [
                iscc,
                f"/DAppVersion={version}",
                f"/DDistDir={dist}",
                f"/DOutputDirPath={out}",
                str(ISS),
            ],
            capture_output=True,
            timeout=300,
        )
        text = (result.stdout + result.stderr).decode("cp932", errors="replace")
        return result.returncode, text, out

    def test_compiles_and_names_the_output_after_the_version(self) -> None:
        code, text, out = self._compile("1.2.3")

        self.assertEqual(code, 0, text)
        self.assertTrue((out / "WSLManager-Setup-1.2.3.exe").is_file(), list(out.glob("*")))

    def test_compile_fails_when_an_executable_is_missing(self) -> None:
        # exe を作り忘れたまま「成功」した Setup.exe を配ってしまわない
        code, _text, out = self._compile("1.2.3", with_cli=False)

        self.assertNotEqual(code, 0)
        self.assertFalse(list(out.glob("*.exe")) if out.exists() else [])


if __name__ == "__main__":
    unittest.main()
