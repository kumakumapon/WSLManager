"""GUI のディストリビューション一覧取得 (``wsl --list`` と CPU/メモリ/IP の並列取得) のテスト。

実際の ``wsl.exe`` は決して起動しない (``subprocess.run`` をモックする)。レジストリも
読まない (仮想ディスクサイズの取得をモックする)。
"""

from __future__ import annotations

import subprocess
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import MagicMock, patch

from wslmgr_gui import distro_data

# ``_get_distro_vhdx_sizes`` を参照するモジュール (パッチ先)
DATA_MODULE = "wslmgr_gui.distro_data"


# ── 呼び出しの窓口 ────────────────────────────────────────────────────────
# テスト本体は下の 3 つだけを使う。取得処理の置き場所が変わったときは、ここだけ差し替える。
def get_distros() -> tuple[list[dict], str | None]:
    return distro_data.get_distros()


def get_usage(name: str) -> tuple[str, str]:
    return distro_data.get_distro_resource_usage(name)


def get_ip(name: str) -> str:
    return distro_data.get_distro_ip(name)


# ── テスト用データ ────────────────────────────────────────────────────────
LIST_OUTPUT = (
    "  NAME      STATE           VERSION\r\n"
    "* Ubuntu    Stopped         2\r\n"
    "  Debian    Running         2\r\n"
    "  Alpine    Running         2\r\n"
).encode("utf-16-le")


def _completed(stdout: bytes = b"", stderr: bytes = b"", returncode: int = 0) -> MagicMock:
    return MagicMock(stdout=stdout, stderr=stderr, returncode=returncode)


def _fake_wsl(
    *,
    usage: dict[str, Callable[[], MagicMock]] | None = None,
    ip: dict[str, Callable[[], MagicMock]] | None = None,
) -> Callable[..., MagicMock]:
    """``wsl`` の呼び出しの種類ごとに応答を返す、``subprocess.run`` の代役。"""
    usage = usage or {}
    ip = ip or {}

    def fake_run(args: list[str], **kwargs: Any) -> MagicMock:
        if args[:3] == ["wsl", "--list", "--verbose"]:
            return _completed(LIST_OUTPUT)
        name = args[2]
        if args[-2:] == ["hostname", "-I"]:
            return ip[name]() if name in ip else _completed(b"172.20.0.5 \n")
        # ps / awk によるリソース使用量
        return usage[name]() if name in usage else _completed(b"12.5 256.0")

    return fake_run


class ListDistrosTests(unittest.TestCase):
    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("wsl", 15.0))
    def test_timeout_reports_message(self, _run: MagicMock) -> None:
        distros, error = get_distros()

        self.assertEqual(distros, [])
        self.assertEqual(error, "WSL の応答がタイムアウトしました。")

    @patch("subprocess.run", side_effect=FileNotFoundError())
    def test_missing_wsl_exe_reports_install_hint(self, _run: MagicMock) -> None:
        distros, error = get_distros()

        self.assertEqual(distros, [])
        self.assertIn("wsl.exe が見つかりません", error or "")

    @patch("subprocess.run", side_effect=PermissionError("denied"))
    def test_other_os_error_includes_reason(self, _run: MagicMock) -> None:
        distros, error = get_distros()

        self.assertEqual(distros, [])
        self.assertIn("WSL の実行に失敗しました", error or "")
        self.assertIn("denied", error or "")

    @patch("subprocess.run")
    def test_nonzero_exit_returns_stderr_text(self, run: MagicMock) -> None:
        run.return_value = _completed(stderr="boom".encode("utf-16-le"), returncode=1)

        distros, error = get_distros()

        self.assertEqual(distros, [])
        self.assertEqual(error, "boom")

    @patch("subprocess.run")
    def test_nonzero_exit_without_stderr_uses_default_message(self, run: MagicMock) -> None:
        run.return_value = _completed(returncode=1)

        distros, error = get_distros()

        self.assertEqual(distros, [])
        self.assertEqual(error, "ディストリビューション一覧の取得に失敗しました。")

    @patch("subprocess.run")
    def test_list_command_and_timeout(self, run: MagicMock) -> None:
        run.return_value = _completed(returncode=1)

        get_distros()

        self.assertEqual(run.call_args.args[0], ["wsl", "--list", "--verbose"])
        self.assertEqual(run.call_args.kwargs["timeout"], 15.0)
        self.assertTrue(run.call_args.kwargs["capture_output"])

    def test_success_fills_resources_for_running_distros_only(self) -> None:
        with (
            patch("subprocess.run", side_effect=_fake_wsl()),
            patch(f"{DATA_MODULE}._get_distro_vhdx_sizes", return_value={"Ubuntu": 12.34}),
        ):
            distros, error = get_distros()

        self.assertIsNone(error)
        by_name = {d["name"]: d for d in distros}
        self.assertEqual(set(by_name), {"Ubuntu", "Debian", "Alpine"})
        # 停止中のディストロは問い合わせず、既定値 ("-") のまま
        self.assertEqual(
            (by_name["Ubuntu"]["cpu"], by_name["Ubuntu"]["memory"], by_name["Ubuntu"]["ip"]),
            ("-", "-", "-"),
        )
        self.assertEqual(by_name["Ubuntu"]["disk"], "12.3")
        # 実行中は CPU / メモリ / IP が入る
        for name in ("Debian", "Alpine"):
            self.assertEqual(
                (by_name[name]["cpu"], by_name[name]["memory"], by_name[name]["ip"]),
                ("12.5", "256.0", "172.20.0.5"),
                name,
            )
            self.assertEqual(by_name[name]["disk"], "-")  # レジストリに無いサイズは触らない

    def test_one_failing_query_does_not_break_the_others(self) -> None:
        def boom() -> MagicMock:
            raise ValueError("unexpected")

        fake = _fake_wsl(usage={"Debian": boom}, ip={"Alpine": lambda: _completed(returncode=1)})
        with (
            patch("subprocess.run", side_effect=fake),
            patch(f"{DATA_MODULE}._get_distro_vhdx_sizes", return_value={}),
        ):
            distros, error = get_distros()

        self.assertIsNone(error)
        by_name = {d["name"]: d for d in distros}
        # 想定外の例外でも一覧全体は返り、該当ディストロだけが "-" になる
        self.assertEqual((by_name["Debian"]["cpu"], by_name["Debian"]["memory"]), ("-", "-"))
        self.assertEqual(by_name["Debian"]["ip"], "172.20.0.5")
        self.assertEqual(by_name["Alpine"]["ip"], "-")
        self.assertEqual((by_name["Alpine"]["cpu"], by_name["Alpine"]["memory"]), ("12.5", "256.0"))

    def test_unexpected_ip_error_falls_back_for_that_distro_only(self) -> None:
        def boom() -> MagicMock:
            raise ValueError("unexpected")

        fake = _fake_wsl(ip={"Debian": boom})
        with (
            patch("subprocess.run", side_effect=fake),
            patch(f"{DATA_MODULE}._get_distro_vhdx_sizes", return_value={}),
        ):
            distros, error = get_distros()

        self.assertIsNone(error)
        by_name = {d["name"]: d for d in distros}
        self.assertEqual(by_name["Debian"]["ip"], "-")
        self.assertEqual(by_name["Alpine"]["ip"], "172.20.0.5")
        # IP の失敗は CPU・メモリの取得結果に影響しない
        self.assertEqual((by_name["Debian"]["cpu"], by_name["Debian"]["memory"]), ("12.5", "256.0"))

    def test_no_running_distro_skips_per_distro_queries(self) -> None:
        stopped_only = (
            "  NAME      STATE           VERSION\r\n* Ubuntu    Stopped         2\r\n"
        ).encode("utf-16-le")
        with (
            patch("subprocess.run", return_value=_completed(stopped_only)) as run,
            patch(f"{DATA_MODULE}._get_distro_vhdx_sizes", return_value={}),
        ):
            distros, error = get_distros()

        self.assertIsNone(error)
        self.assertEqual(len(distros), 1)
        self.assertEqual(run.call_count, 1)  # 一覧の取得だけ


class PerDistroQueryTests(unittest.TestCase):
    @patch("subprocess.run")
    def test_usage_command_and_timeout(self, run: MagicMock) -> None:
        run.return_value = _completed(b"3.0 100.5")

        result = get_usage("Debian")

        self.assertEqual(result, ("3.0", "100.5"))
        args = run.call_args.args[0]
        self.assertEqual(args[:5], ["wsl", "-d", "Debian", "--", "sh"])
        self.assertIn("ps -eo pcpu=,rss=", args[-1])
        self.assertEqual(run.call_args.kwargs["timeout"], 8.0)

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("wsl", 8.0))
    def test_usage_timeout_returns_placeholders(self, _run: MagicMock) -> None:
        self.assertEqual(get_usage("Debian"), ("-", "-"))

    @patch("subprocess.run", side_effect=FileNotFoundError())
    def test_usage_os_error_returns_placeholders(self, _run: MagicMock) -> None:
        self.assertEqual(get_usage("Debian"), ("-", "-"))

    @patch("subprocess.run")
    def test_usage_nonzero_exit_returns_placeholders(self, run: MagicMock) -> None:
        run.return_value = _completed(b"1.0 2.0", returncode=1)

        self.assertEqual(get_usage("Debian"), ("-", "-"))

    @patch("subprocess.run")
    def test_ip_returns_first_address_and_uses_timeout(self, run: MagicMock) -> None:
        run.return_value = _completed(b"172.20.1.2 fd00::1 \n")

        self.assertEqual(get_ip("Debian"), "172.20.1.2")
        self.assertEqual(run.call_args.args[0], ["wsl", "-d", "Debian", "--", "hostname", "-I"])
        self.assertEqual(run.call_args.kwargs["timeout"], 8.0)

    @patch("subprocess.run")
    def test_ip_without_address_returns_placeholder(self, run: MagicMock) -> None:
        run.return_value = _completed(b"\n")

        self.assertEqual(get_ip("Debian"), "-")

    @patch("subprocess.run", side_effect=subprocess.TimeoutExpired("wsl", 8.0))
    def test_ip_timeout_returns_placeholder(self, _run: MagicMock) -> None:
        self.assertEqual(get_ip("Debian"), "-")

    @patch("subprocess.run")
    def test_ip_nonzero_exit_returns_placeholder(self, run: MagicMock) -> None:
        run.return_value = _completed(b"172.20.1.2", returncode=1)

        self.assertEqual(get_ip("Debian"), "-")


if __name__ == "__main__":
    unittest.main()
