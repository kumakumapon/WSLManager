"""``wsl_core.actions`` (操作の可否・引数組み立て・フォーム検証) と、関連する表示文言のテスト。

GUI (tkinter) は使わない。ファイルシステムを見る検証は、一時ディレクトリか
差し替え関数 (``isfile`` / ``listdir``) で行う。
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest
from datetime import date

import wsl_core


def _distro(**overrides: object) -> dict:
    distro = {
        "name": "Ubuntu",
        "state": "Running",
        "version": "2",
        "default": False,
        "ip": "172.20.0.5",
    }
    distro.update(overrides)
    return distro


class ActionAvailabilityTests(unittest.TestCase):
    def test_nothing_is_available_without_a_selection(self) -> None:
        availability = wsl_core.action_availability(None)

        self.assertEqual(set(availability), set(wsl_core.DISTRO_ACTIONS))
        self.assertFalse(any(availability.values()))

    def test_running_distribution(self) -> None:
        availability = wsl_core.action_availability(_distro())

        self.assertFalse(availability["start"])
        self.assertTrue(availability["stop"])
        self.assertTrue(availability["processes"])
        self.assertTrue(availability["copy_ip"])

    def test_stopped_distribution(self) -> None:
        availability = wsl_core.action_availability(_distro(state="Stopped", ip="-"))

        self.assertTrue(availability["start"])
        self.assertFalse(availability["stop"])
        self.assertFalse(availability["processes"])
        self.assertFalse(availability["copy_ip"])
        # 停止中でも WSL が自動で起動するため、ターミナル・バックアップ・削除は使える
        for action in ("terminal", "explorer", "snapshot", "export", "clone", "unregister"):
            self.assertTrue(availability[action], action)

    def test_default_distribution_cannot_be_set_as_default_again(self) -> None:
        self.assertFalse(wsl_core.action_availability(_distro(default=True))["set_default"])
        self.assertTrue(wsl_core.action_availability(_distro(default=False))["set_default"])

    def test_wsl1_has_no_virtual_disk_to_optimize(self) -> None:
        self.assertFalse(wsl_core.action_availability(_distro(version="1"))["optimize"])
        self.assertTrue(wsl_core.action_availability(_distro(version="2"))["optimize"])

    def test_only_details_while_wsl_is_still_working_on_it(self) -> None:
        for state in ("Installing", "Converting", "Uninstalling"):
            with self.subTest(state=state):
                availability = wsl_core.action_availability(_distro(state=state))

                self.assertEqual([a for a, ok in availability.items() if ok], ["details"])

    def test_unknown_version_cannot_be_converted(self) -> None:
        self.assertFalse(wsl_core.action_availability(_distro(version=""))["convert"])
        self.assertTrue(wsl_core.action_availability(_distro(version="1"))["convert"])

    def test_conversion_target(self) -> None:
        self.assertEqual(wsl_core.conversion_target("1"), "2")
        self.assertEqual(wsl_core.conversion_target("2"), "1")
        self.assertEqual(wsl_core.conversion_target(2), "1")
        self.assertIsNone(wsl_core.conversion_target(""))
        self.assertIsNone(wsl_core.conversion_target(None))


class CommandArgumentTests(unittest.TestCase):
    def test_export_args(self) -> None:
        self.assertEqual(
            wsl_core.build_export_args("Ubuntu", "C:/b/u.tar", vhd=False),
            ["--export", "Ubuntu", "C:/b/u.tar"],
        )
        self.assertEqual(
            wsl_core.build_export_args("Ubuntu", "C:/b/u.vhdx", vhd=True),
            ["--export", "Ubuntu", "C:/b/u.vhdx", "--vhd"],
        )

    def test_import_tar_passes_the_version(self) -> None:
        self.assertEqual(
            wsl_core.build_import_args("New", "C:/wsl/New", "C:/b/u.tar", "1"),
            ["--import", "New", "C:/wsl/New", "C:/b/u.tar", "--version", "1"],
        )

    def test_import_vhdx_needs_the_vhd_flag_and_no_version(self) -> None:
        # --vhd が無いと wsl --import は VHDX を tar として読もうとして失敗する
        for image in ("C:/b/u.vhdx", "C:/b/U.VHD"):
            with self.subTest(image=image):
                self.assertEqual(
                    wsl_core.build_import_args("New", "C:/wsl/New", image, "1"),
                    ["--import", "New", "C:/wsl/New", image, "--vhd"],
                )

    def test_import_without_a_known_version_omits_it(self) -> None:
        self.assertEqual(
            wsl_core.build_import_args("New", "C:/wsl/New", "C:/b/u.tar", ""),
            ["--import", "New", "C:/wsl/New", "C:/b/u.tar"],
        )

    def test_is_vhd_image(self) -> None:
        self.assertTrue(wsl_core.is_vhd_image("a.vhdx"))
        self.assertTrue(wsl_core.is_vhd_image("A.VHD"))
        self.assertFalse(wsl_core.is_vhd_image("a.tar"))
        self.assertFalse(wsl_core.is_vhd_image("a.tar.gz"))
        self.assertFalse(wsl_core.is_vhd_image("vhdx"))


class SuggestionTests(unittest.TestCase):
    def test_default_install_base_uses_userprofile(self) -> None:
        base = wsl_core.default_install_base({"USERPROFILE": os.path.join("C:", "Users", "me")})

        self.assertEqual(base, os.path.join("C:", "Users", "me", "WSL"))

    def test_suggest_install_dir(self) -> None:
        self.assertEqual(
            wsl_core.suggest_install_dir(" Ubuntu ", "D:/WSL"), os.path.join("D:/WSL", "Ubuntu")
        )
        self.assertEqual(wsl_core.suggest_install_dir("", "D:/WSL"), "D:/WSL")

    def test_suggest_export_filename(self) -> None:
        day = date(2026, 1, 2)

        self.assertEqual(
            wsl_core.suggest_export_filename("Ubuntu", False, day), "Ubuntu-20260102.tar"
        )
        self.assertEqual(
            wsl_core.suggest_export_filename("Ubuntu", True, day), "Ubuntu-20260102.vhdx"
        )

    def test_replace_export_extension(self) -> None:
        self.assertEqual(wsl_core.replace_export_extension("C:/b/u.tar", True), "C:/b/u.vhdx")
        self.assertEqual(wsl_core.replace_export_extension("C:/b/u.vhdx", False), "C:/b/u.tar")
        self.assertEqual(wsl_core.replace_export_extension("C:/b/u.VHD", False), "C:/b/u.tar")
        # 利用者が独自に付けた拡張子は変えない
        self.assertEqual(wsl_core.replace_export_extension("C:/b/u.bak", True), "C:/b/u.bak")
        self.assertEqual(wsl_core.replace_export_extension("C:/b/u", True), "C:/b/u")


class FormValidationTests(unittest.TestCase):
    @staticmethod
    def _keys(errors: list[wsl_core.FormError]) -> list[str]:
        return [key for key, _values in errors]

    def test_valid_import(self) -> None:
        errors = wsl_core.validate_import_form(
            "New",
            "C:/b/u.tar",
            "C:/wsl/New",
            ["Ubuntu"],
            isfile=lambda _p: True,
            listdir=lambda _p: [],
        )

        self.assertEqual(errors, [])

    def test_import_reports_every_problem_at_once(self) -> None:
        errors = wsl_core.validate_import_form(
            "", "", "", ["Ubuntu"], isfile=lambda _p: True, listdir=lambda _p: []
        )

        self.assertEqual(
            self._keys(errors),
            ["form.error.name_invalid", "form.error.image_required", "form.error.folder_required"],
        )

    def test_import_rejects_an_existing_name_case_insensitively(self) -> None:
        errors = wsl_core.validate_import_form(
            "ubuntu", "u.tar", "C:/wsl/x", ["Ubuntu"], isfile=lambda _p: True, listdir=lambda _p: []
        )

        self.assertEqual(self._keys(errors), ["form.error.name_exists"])

    def test_import_rejects_a_missing_image(self) -> None:
        errors = wsl_core.validate_import_form(
            "New", "C:/nope.tar", "C:/wsl/x", [], isfile=lambda _p: False, listdir=lambda _p: []
        )

        self.assertEqual(self._keys(errors), ["form.error.image_missing"])

    def test_install_dir_that_already_holds_a_virtual_disk_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "ext4.vhdx"), "wb").close()

            errors = wsl_core.validate_clone_form("New", tmp, [])

        self.assertEqual(self._keys(errors), ["form.error.folder_has_vhdx"])

    def test_install_dir_may_be_missing_or_hold_other_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            open(os.path.join(tmp, "notes.txt"), "wb").close()

            self.assertEqual(wsl_core.validate_clone_form("New", tmp, []), [])
            self.assertEqual(
                wsl_core.validate_clone_form("New", os.path.join(tmp, "missing"), []), []
            )

    def test_install_dir_that_is_a_file_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "file")
            open(path, "wb").close()

            errors = wsl_core.validate_clone_form("New", path, [])

        self.assertEqual(self._keys(errors), ["form.error.folder_not_dir"])

    def test_export_needs_a_destination(self) -> None:
        self.assertEqual(
            self._keys(wsl_core.validate_export_form("  ")), ["form.error.destination_required"]
        )
        self.assertEqual(wsl_core.validate_export_form("C:/b/u.tar", isdir=lambda _p: True), [])

    def test_export_destination_folder_must_exist(self) -> None:
        # wsl --export は保存先のフォルダーを作らない
        errors = wsl_core.validate_export_form("C:/nope/u.tar", isdir=lambda _p: False)

        self.assertEqual(self._keys(errors), ["form.error.destination_folder_missing"])

    def test_relative_paths_are_rejected(self) -> None:
        # 相対パスだと、exe の作業フォルダー (起動方法で変わる) に書き込まれてしまう
        self.assertEqual(
            self._keys(wsl_core.validate_export_form("u.tar", isdir=lambda _p: True)),
            ["form.error.path_not_absolute"],
        )
        self.assertEqual(
            self._keys(wsl_core.validate_clone_form("New", "WSL\\New", [])),
            ["form.error.path_not_absolute"],
        )

    def test_windows_paths_count_as_absolute_on_any_os(self) -> None:
        self.assertEqual(
            wsl_core.validate_clone_form("New", "D:\\WSL\\New", [], listdir=lambda _p: []), []
        )

    def test_every_form_error_has_a_translation(self) -> None:
        from wsl_core.i18n import _MESSAGES

        with open(wsl_core.actions.__file__, encoding="utf-8") as f:
            source = f.read()
        for key in sorted(set(re.findall(r'"(form\.error\.[a-z_]+)"', source))):
            with self.subTest(key=key):
                self.assertIn(key, _MESSAGES)


class LocalizedTextTests(unittest.TestCase):
    def test_distro_name_reasons_default_to_japanese(self) -> None:
        # CLI と既存の呼び出し元は日本語の理由を前提にしている
        self.assertEqual(
            wsl_core.validate_distro_name(""), (False, "ディストリビューション名を入力してください")
        )
        self.assertEqual(
            wsl_core.validate_clone_name("Ubuntu", ["ubuntu"]),
            (False, "同名のディストリビューションが既に存在します。"),
        )

    def test_distro_name_reasons_in_english(self) -> None:
        valid, reason = wsl_core.validate_distro_name("a/b", language="en")

        self.assertFalse(valid)
        self.assertEqual(reason, "Contains characters that cannot be used: /")
        self.assertEqual(
            wsl_core.validate_clone_name("Ubuntu", ["ubuntu"], language="en")[1],
            "A distribution with the same name already exists.",
        )

    def test_transfer_status_in_english(self) -> None:
        self.assertEqual(
            wsl_core.format_transfer_status(1024, None, 83, language="en"),
            "1.0 KiB written ・ Elapsed 1:23",
        )

    def test_transfer_status_defaults_to_japanese(self) -> None:
        self.assertEqual(
            wsl_core.format_transfer_status(1024, None, 83), "1.0 KiB 書き込み済み ・ 経過 1:23"
        )

    def test_chart_time_labels_follow_the_language(self) -> None:
        history = {"Ubuntu": [wsl_core.ResourceSample(1000.0, 1.0, 1.0)]}

        en = wsl_core.prepare_chart_layout(history, "cpu", 400, 200, now=1000.0, language="en")
        ja = wsl_core.prepare_chart_layout(history, "cpu", 400, 200, now=1000.0)

        self.assertEqual([t.label for t in en.x_ticks], ["-30 min", "-20 min", "-10 min", "now"])
        self.assertEqual([t.label for t in ja.x_ticks], ["-30分", "-20分", "-10分", "現在"])


class NoDistributionsMessageTests(unittest.TestCase):
    def test_recognises_the_messages_wsl_prints_when_nothing_is_installed(self) -> None:
        for text in (
            "Windows Subsystem for Linux has no installed distributions.\r\n",
            "Error code: Wsl/WSL_E_DEFAULT_DISTRO_NOT_FOUND",
            "Linux 用 Windows サブシステムには、"
            "ディストリビューションがインストールされていません。",
        ):
            with self.subTest(text=text):
                self.assertTrue(wsl_core.is_no_distributions_message(text))

    def test_other_errors_are_not_mistaken_for_an_empty_list(self) -> None:
        for text in ("", "The service cannot be started.", "Access is denied."):
            with self.subTest(text=text):
                self.assertFalse(wsl_core.is_no_distributions_message(text))


if __name__ == "__main__":
    unittest.main()
