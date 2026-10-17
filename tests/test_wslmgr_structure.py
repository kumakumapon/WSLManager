"""``WSLManager`` の Mixin 分割の構造を守るテスト。

メソッドを Mixin へ移すと、同名メソッドが MRO で後勝ちになって本体のメソッドを
黙って隠したり、ダイアログが親 (``WSLManager``) に要求するメンバーが失われたりする
恐れがある。実際のウィンドウは作らず、クラスの構造だけを検証する。
"""

from __future__ import annotations

import tkinter as tk
import unittest
from unittest.mock import MagicMock

try:
    import wslmgr
except ImportError as exc:  # tkinter が無い環境のみ
    wslmgr = None
    _IMPORT_ERROR = str(exc)
else:
    _IMPORT_ERROR = ""

# ダイアログ (wslmgr_gui/dialogs/*) が親ウィンドウに要求するメソッド
# (``_settings`` / ``_all_distros`` / ``_transfer_dialogs`` は __init__ で作る属性なので対象外)
DIALOG_PARENT_API = (
    "_snapshot_dir",
    "_set_status",
    "_save_settings",
    "_log_operation",
    "_execute_mount",
    "_execute_unmount",
    "_run_wsl_cmd",
    "_refresh",
)


def _mixin_bases() -> list[type]:
    """``WSLManager`` の直接の基底のうち、Tk 以外 (= Mixin) を返す。"""
    return [base for base in wslmgr.WSLManager.__bases__ if base is not tk.Tk]


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class WslManagerStructureTests(unittest.TestCase):
    def test_tk_is_last_in_mro(self) -> None:
        mro = wslmgr.WSLManager.__mro__

        self.assertIn(tk.Tk, mro)
        for mixin in _mixin_bases():
            self.assertLess(mro.index(mixin), mro.index(tk.Tk), mixin.__name__)

    def test_mixins_do_not_define_init(self) -> None:
        # 初期化順は WSLManager.__init__ に集約する (Mixin に __init__ を置かない)
        for mixin in _mixin_bases():
            self.assertNotIn("__init__", vars(mixin), mixin.__name__)

    def test_no_method_is_defined_twice(self) -> None:
        # 同名メソッドは MRO で WSLManager > Mixin の順に後勝ちになり、片方が黙って無効になる
        owners: dict[str, list[str]] = {}
        for cls in (wslmgr.WSLManager, *_mixin_bases()):
            for name, value in vars(cls).items():
                if callable(value) or isinstance(value, (staticmethod, classmethod)):
                    if name.startswith("__") and name.endswith("__"):
                        continue
                    owners.setdefault(name, []).append(cls.__name__)
        duplicates = {name: who for name, who in owners.items() if len(who) > 1}

        self.assertEqual(duplicates, {})

    def test_dialog_parent_api_is_available_on_manager(self) -> None:
        for name in DIALOG_PARENT_API:
            self.assertTrue(hasattr(wslmgr.WSLManager, name), name)

    def test_moved_names_stay_importable_from_wslmgr(self) -> None:
        # 従来どおり wslmgr 経由で参照できる (tests や外部コードの互換性)
        for name in (
            "ProcessWindow",
            "SnapshotManagerDialog",
            "TransferProgressDialog",
            "TreeviewSorter",
            "CREATE_NO_WINDOW",
        ):
            self.assertTrue(hasattr(wslmgr, name), name)


@unittest.skipIf(wslmgr is None, f"wslmgr を import できません: {_IMPORT_ERROR}")
class ResourceHistoryMixinTests(unittest.TestCase):
    """Mixin に移したリソース履歴グラフの、ウィンドウを作らずに試せる部分。"""

    def test_manager_inherits_the_history_methods(self) -> None:
        for name in (
            "_build_resource_history_panel",
            "_toggle_resource_history",
            "_draw_resource_history",
            "_draw_history_canvas",
            "_on_history_canvas_motion",
            "_on_history_canvas_leave",
            "_draw_history_tooltip",
            "_clear_history_tooltip",
            "_resource_value_label",
        ):
            self.assertTrue(hasattr(wslmgr.WSLManager, name), name)

    def test_resource_value_label_formats_cpu_and_memory(self) -> None:
        label = wslmgr.WSLManager._resource_value_label

        self.assertEqual(label("cpu", 12.34), "12.3%")
        self.assertEqual(label("memory", 512.0), "512.0 MB")

    def test_clear_tooltip_removes_only_tooltip_items(self) -> None:
        canvas = MagicMock()

        wslmgr.WSLManager._clear_history_tooltip(canvas)

        canvas.delete.assert_called_once_with("history-tooltip")

    def test_draw_skips_hidden_panel(self) -> None:
        manager = MagicMock()
        manager._resource_history_visible = False

        wslmgr.WSLManager._draw_resource_history(manager)

        manager._draw_history_canvas.assert_not_called()

    def test_draw_renders_both_canvases_when_visible(self) -> None:
        manager = MagicMock()
        manager._resource_history_visible = True

        wslmgr.WSLManager._draw_resource_history(manager)

        self.assertEqual(manager._draw_history_canvas.call_count, 2)


if __name__ == "__main__":
    unittest.main()
