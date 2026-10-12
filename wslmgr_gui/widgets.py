"""テーブル系の共通ウィジェット・ヘルパー。"""

from __future__ import annotations

import functools
from tkinter import ttk

import wsl_core


class TreeviewSorter:
    """Treeview の列ヘッダクリックによるソート機能を提供するヘルパークラス。

    コンストラクタで全列のヘッダに ``command=`` を仕込み、クリックごとに
    昇順→降順をトグルします。``numeric_columns`` に含まれる列は数値ソート、
    それ以外は文字列(casefold)ソートを行います。
    """

    def __init__(self, tree: ttk.Treeview, numeric_columns: set[str]) -> None:
        self._tree = tree
        self._numeric_columns = numeric_columns
        # ソート状態: (列ID, 逆順フラグ) または None
        self._sort_col: str | None = None
        self._sort_reverse: bool = False
        # 各列の元のヘッダテキスト(マーカーなし)を保持
        self._orig_headings: dict[str, str] = {}
        for col in tree["columns"]:
            heading_info = tree.heading(col)
            orig_text = heading_info["text"]
            self._orig_headings[col] = orig_text
            tree.heading(col, command=functools.partial(self._on_header_click, col))

    def _on_header_click(self, col: str) -> None:
        """ヘッダクリック時にソート状態を更新して並べ替えを実行します。"""
        if self._sort_col == col:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_col = col
            self._sort_reverse = False
        self._do_sort()

    def _do_sort(self) -> None:
        """現在のソート設定に従って行を並べ替えます。"""
        if self._sort_col is None:
            return
        col = self._sort_col
        reverse = self._sort_reverse
        tree = self._tree

        # ヘッダのマーカーを更新
        for c in tree["columns"]:
            base = self._orig_headings[c]
            if c == col:
                marker = " ▼" if reverse else " ▲"
                tree.heading(c, text=base + marker)
            else:
                tree.heading(c, text=base)

        # ソートキーを生成して並べ替える
        items = [(tree.set(iid, col), iid) for iid in tree.get_children("")]

        if col in self._numeric_columns:
            # 数値に変換できない値("-" など)は昇順・降順とも常に末尾に置く
            numeric_items = [x for x in items if wsl_core.is_numeric(x[0])]
            other_items = [x for x in items if not wsl_core.is_numeric(x[0])]
            numeric_items.sort(key=lambda item: float(item[0]), reverse=reverse)
            items = numeric_items + other_items
        else:
            items.sort(key=lambda item: item[0].casefold(), reverse=reverse)

        for index, (_, iid) in enumerate(items):
            tree.move(iid, "", index)

    def apply(self) -> None:
        """現在のソート設定を再適用します。未ソートなら何もしません。"""
        if self._sort_col is not None:
            self._do_sort()

    def get_state(self) -> tuple[str | None, bool]:
        """現在のソート状態を (列ID, 逆順フラグ) のタプルで返します。"""
        return (self._sort_col, self._sort_reverse)

    def set_state(self, col: str | None, reverse: bool) -> None:
        """ソート状態を外部から復元します。

        ``col`` が None または現在の列一覧に存在しない場合は未ソート状態に
        リセットします。この時点では並べ替えは行わず、状態の保持のみを
        行います (実際の並べ替えは後続の ``apply()`` 呼び出しで行われます)。
        """
        if col is None or col not in self._tree["columns"]:
            self._sort_col = None
            self._sort_reverse = False
        else:
            self._sort_col = col
            self._sort_reverse = reverse
