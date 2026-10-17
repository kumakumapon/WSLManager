"""操作ログ (記録・永続化・ビューアー) の Mixin。"""

from __future__ import annotations

import os
from datetime import datetime
from tkinter import messagebox

import wsl_core
from wslmgr_gui.app.base import AppBase
from wslmgr_gui.dialogs.log_viewer import LogViewerDialog


class OperationLogMixin(AppBase):
    """``WSLManager`` に混ぜ込む、操作ログの記録・永続化・ビューアー表示。"""

    # ── 操作ログ ─────────────────────────────────────────────────────────

    def _load_persisted_log(self) -> None:
        """ログファイルから過去の操作ログを読み込みます。"""
        try:
            if os.path.exists(self._log_file):
                with open(self._log_file, encoding="utf-8") as f:
                    entries = wsl_core.deserialize_log_entries(f.read())
                for entry in entries[-1000:]:
                    self._operation_log.append(wsl_core.format_log_entry_from_dict(entry))
        except OSError:
            pass

    def _persist_log_entry(self, operation: str, target: str, result: str) -> None:
        """操作ログ1件をファイルに追記します（実際の書き込みは別スレッド）。

        呼び出しはキューへの投入のみで完了するため、イベントループを
        ブロックしません。書き込み失敗は :class:`wsl_core.AsyncLogWriter`
        側で無視されます。
        """
        self._log_writer.submit(operation, target, result, source="gui")

    def _log_operation(self, operation: str, target: str, result: str) -> None:
        """操作ログにエントリを追加し、ファイルにも永続化します。

        Args:
            operation: 操作名（例: "停止"）。
            target: 操作対象（例: ディストリビューション名）。
            result: 結果（例: "実行"）。
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] {operation} | {target} | {result}"
        self._operation_log.append(entry)
        # 最大 1000 件を超えたら古いエントリを削除
        if len(self._operation_log) > 1000:
            self._operation_log = self._operation_log[-1000:]
        self._persist_log_entry(operation, target, result)

    def _show_log_viewer(self) -> None:
        """操作ログビューアーダイアログを開きます。"""
        dialog: LogViewerDialog | None = None

        def _clear() -> None:
            # キューに残った書き込みを先に片付けないと、削除直後に
            # 書き戻されて「消したログが復活する」ように見えてしまう
            self._log_writer.flush()
            _deleted, failed = wsl_core.delete_log_files(self._log_dir)
            self._operation_log.clear()
            if failed:
                messagebox.showwarning(
                    "警告",
                    "一部のログファイルを削除できませんでした。\n"
                    "他のプロセスが使用中の可能性があります:\n" + "\n".join(failed),
                    parent=dialog if dialog is not None else self,
                )

        dialog = LogViewerDialog(self, self._operation_log, _clear)
