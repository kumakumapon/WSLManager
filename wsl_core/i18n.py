"""Small, dependency-free translation helpers for WSL Manager.

The application deliberately keeps translations in source rather than adding a
runtime dependency or a catalog compilation step.  ``auto`` follows the
system locale; explicit ``ja`` and ``en`` preferences are persisted by the
settings module.
"""

from __future__ import annotations

import locale
import os
from collections.abc import Mapping

LANGUAGE_AUTO = "auto"
SUPPORTED_LANGUAGES = ("ja", "en")

_MESSAGES: Mapping[str, Mapping[str, str]] = {
    "containers.session": {"ja": "既存セッション名", "en": "Existing session name"},
    "containers.all": {"ja": "停止中も表示", "en": "Include stopped containers"},
    "containers.name": {"ja": "名前", "en": "Name"},
    "containers.image": {"ja": "イメージ", "en": "Image"},
    "containers.status": {"ja": "状態", "en": "Status"},
    "containers.health": {"ja": "ヘルス", "en": "Health"},
    "containers.created": {"ja": "作成日時", "en": "Created"},
    "containers.inspect": {"ja": "コンテナ詳細", "en": "Inspect container"},
    "containers.loading": {"ja": "WSL Containers を確認中…", "en": "Checking WSL Containers…"},
    "containers.error": {"ja": "取得失敗: {error}", "en": "Request failed: {error}"},
    "containers.count": {
        "ja": "{count} 件。読み取り専用（作成・停止・削除は行いません）。",
        "en": "{count} container(s). Read-only (no create, stop or delete actions).",
    },
    "containers.select": {
        "ja": "既存セッションを選択してください。",
        "en": "Select an existing session.",
    },
    "containers.none": {
        "ja": "既存セッションがありません。自動作成は行いません。",
        "en": "No existing sessions. Sessions are not created automatically.",
    },
    "containers.missing_id": {
        "ja": "コンテナ ID または名前がないため詳細を取得できません。",
        "en": "Cannot inspect a row without a container ID or name.",
    },
    "containers.inspected": {"ja": "詳細を取得しました。", "en": "Inspection complete."},
    "containers.eligible": {
        "ja": "WSL Containers: バージョン条件を満たします（サービスの利用可否は未確認）。",
        "en": "WSL Containers: version eligible (service availability not checked).",
    },
    "containers.session_help": {
        "ja": "container system-info に表示される既存セッションの Name",
        "en": "Existing session Name from container system-info",
    },
    # ── 言語名 ──
    "language.system": {"ja": "システム設定", "en": "System default"},
    "language.auto": {"ja": "システムの設定に合わせる", "en": "Follow the system"},
    "language.ja": {"ja": "日本語", "en": "Japanese"},
    "language.en": {"ja": "English", "en": "English"},
    # ── 共通アクション・ボタン・ダイアログ ──
    "gui.common.ok": {"ja": "OK", "en": "OK"},
    "gui.common.cancel": {"ja": "キャンセル", "en": "Cancel"},
    "gui.common.close": {"ja": "閉じる", "en": "Close"},
    "gui.common.save": {"ja": "保存", "en": "Save"},
    "gui.common.confirm": {"ja": "確認", "en": "Confirm"},
    "gui.common.error": {"ja": "エラー", "en": "Error"},
    "gui.common.warning": {"ja": "警告", "en": "Warning"},
    "gui.common.info": {"ja": "情報", "en": "Information"},
    "gui.common.filter": {"ja": "フィルタ:", "en": "Filter:"},
    "gui.common.filter_clear": {"ja": "×", "en": "×"},
    "gui.common.refresh": {"ja": "更新", "en": "Refresh"},
    "gui.common.name": {"ja": "名前:", "en": "Name:"},
    "gui.common.success": {"ja": "成功", "en": "Success"},
    # ── メインメニュー ──
    "gui.menu.file": {"ja": "ファイル", "en": "File"},
    "gui.menu.distribution": {"ja": "ディストリビューション", "en": "Distribution"},
    "gui.menu.wsl": {"ja": "WSL", "en": "WSL"},
    "gui.menu.view": {"ja": "表示", "en": "View"},
    "gui.menu.tools": {"ja": "ツール", "en": "Tools"},
    "gui.menu.help": {"ja": "ヘルプ", "en": "Help"},
    "gui.menu.language": {"ja": "言語", "en": "Language"},
    # ── アクション (メニュー) ──
    "gui.action.import": {"ja": "インポート...", "en": "Import..."},
    "gui.action.export": {"ja": "エクスポート...", "en": "Export..."},
    "gui.action.exit": {"ja": "終了", "en": "Exit"},
    "gui.action.start_terminal": {"ja": "ターミナルを開く", "en": "Open terminal"},
    "gui.action.start": {"ja": "起動 (バックグラウンド)", "en": "Start (in background)"},
    "gui.action.stop": {"ja": "停止", "en": "Stop"},
    "gui.action.shutdown": {"ja": "WSL を全停止...", "en": "Shut down WSL..."},
    "gui.action.set_default": {"ja": "既定に設定", "en": "Set as default"},
    "gui.action.convert": {"ja": "WSL1/WSL2 変換...", "en": "Convert WSL1/WSL2..."},
    "gui.action.install": {"ja": "インストール...", "en": "Install..."},
    "gui.action.unregister": {"ja": "登録解除 (削除)...", "en": "Unregister (delete)..."},
    "gui.action.details": {"ja": "詳細情報...", "en": "Details..."},
    "gui.action.processes": {"ja": "プロセス一覧...", "en": "Processes..."},
    "gui.action.explorer": {"ja": "エクスプローラーで開く", "en": "Open in Explorer"},
    "gui.action.copy_ip": {"ja": "IP アドレスをコピー", "en": "Copy IP address"},
    "gui.action.optimize": {"ja": "ディスク最適化...", "en": "Optimize disk..."},
    "gui.action.snapshot": {"ja": "スナップショットを作成...", "en": "Create snapshot..."},
    "gui.action.snapshots": {"ja": "スナップショット管理...", "en": "Manage snapshots..."},
    "gui.action.mount": {"ja": "ディスクのマウント...", "en": "Mount disk..."},
    "gui.action.unmount": {"ja": "ディスクのアンマウント...", "en": "Unmount disk..."},
    "gui.action.containers": {"ja": "WSL Containers...", "en": "WSL Containers..."},
    "gui.action.wsl_config": {
        "ja": "WSL 全体の設定 (.wslconfig)...",
        "en": "Global WSL settings (.wslconfig)...",
    },
    "gui.action.distro_conf": {
        "ja": "ディストリビューション設定 (wsl.conf)...",
        "en": "Distribution settings (wsl.conf)...",
    },
    "gui.action.clone": {"ja": "複製...", "en": "Clone..."},
    "gui.action.log": {"ja": "操作ログ...", "en": "Operation log..."},
    "gui.action.theme": {"ja": "テーマ", "en": "Theme"},
    "gui.action.refresh": {"ja": "最新の情報に更新", "en": "Refresh"},
    "gui.action.wsl_version": {"ja": "WSL のバージョン情報...", "en": "WSL version..."},
    "gui.action.update_wsl": {"ja": "WSL を更新...", "en": "Update WSL..."},
    "gui.action.shortcuts": {"ja": "キーボード ショートカット", "en": "Keyboard shortcuts"},
    "gui.action.cli_help": {
        "ja": "コマンドライン版 (wslmgr)...",
        "en": "Command-line tool (wslmgr)...",
    },
    "gui.action.project_page": {"ja": "GitHub のページを開く", "en": "Open the GitHub page"},
    "gui.action.about": {"ja": "WSL Manager について", "en": "About WSL Manager"},
    # ── 表示メニュー ──
    "gui.view.detail_panel": {"ja": "詳細パネル", "en": "Detail panel"},
    "gui.view.history": {"ja": "リソース履歴グラフ", "en": "Resource history chart"},
    "gui.view.interval": {"ja": "自動更新の間隔", "en": "Auto refresh interval"},
    "gui.view.interval_seconds": {"ja": "{seconds} 秒", "en": "{seconds} seconds"},
    # ── ツールバー ──
    "gui.toolbar.start": {"ja": "▶ 起動", "en": "▶ Start"},
    "gui.toolbar.stop": {"ja": "■ 停止", "en": "■ Stop"},
    "gui.toolbar.terminal": {"ja": "ターミナル", "en": "Terminal"},
    "gui.toolbar.explorer": {"ja": "エクスプローラー", "en": "Explorer"},
    "gui.toolbar.add": {"ja": "＋ 追加", "en": "+ Add"},
    "gui.toolbar.snapshots": {"ja": "スナップショット", "en": "Snapshots"},
    "gui.toolbar.refresh": {"ja": "↻ 更新", "en": "↻ Refresh"},
    "gui.toolbar.search": {"ja": "検索:", "en": "Search:"},
    "gui.auto_refresh": {"ja": "自動更新", "en": "Auto refresh"},
    # ── リソース履歴パネル ──
    "gui.history.title": {
        "ja": "リソース履歴（直近30分）",
        "en": "Resource history (last 30 min)",
    },
    "gui.history.cpu": {"ja": "CPU 使用率", "en": "CPU usage"},
    "gui.history.memory": {"ja": "メモリ使用量", "en": "Memory usage"},
    "gui.history.empty": {
        "ja": "有効な履歴データはありません",
        "en": "No history data yet",
    },
    "chart.now": {"ja": "現在", "en": "now"},
    "chart.minutes_ago": {"ja": "-{minutes}分", "en": "-{minutes} min"},
    # ── テーブル列ヘッダー ──
    "gui.column.default": {"ja": "既定", "en": "Default"},
    "gui.column.name": {"ja": "ディストリビューション", "en": "Distribution"},
    "gui.column.state": {"ja": "状態", "en": "State"},
    "gui.column.version": {"ja": "WSL", "en": "WSL"},
    "gui.column.cpu": {"ja": "CPU (%)", "en": "CPU (%)"},
    "gui.column.memory": {"ja": "メモリ (MB)", "en": "Memory (MB)"},
    "gui.column.disk": {"ja": "ディスク (GB)", "en": "Disk (GB)"},
    "gui.column.ip": {"ja": "IP アドレス", "en": "IP address"},
    # ── 状態 ──
    "gui.state.running": {"ja": "実行中", "en": "Running"},
    "gui.state.stopped": {"ja": "停止中", "en": "Stopped"},
    # ── 詳細パネル ──
    "gui.panel.placeholder": {
        "ja": "一覧からディストリビューションを選択すると、ここに情報と操作が表示されます。",
        "en": "Select a distribution in the list to see its details and actions here.",
    },
    "gui.panel.badge_default": {"ja": "★ 既定", "en": "★ Default"},
    "gui.panel.memory": {"ja": "メモリ", "en": "Memory"},
    "gui.panel.disk": {"ja": "ディスク", "en": "Disk"},
    "gui.panel.location": {"ja": "場所", "en": "Location"},
    "gui.panel.copy": {"ja": "コピー", "en": "Copy"},
    "gui.panel.terminal": {"ja": "ターミナルを開く", "en": "Open terminal"},
    "gui.panel.start": {"ja": "▶ 起動", "en": "▶ Start"},
    "gui.panel.stop": {"ja": "■ 停止", "en": "■ Stop"},
    "gui.panel.explorer": {"ja": "エクスプローラー", "en": "Explorer"},
    "gui.panel.processes": {"ja": "プロセス", "en": "Processes"},
    "gui.panel.section_backup": {"ja": "バックアップ", "en": "Backup"},
    "gui.panel.snapshot": {"ja": "スナップショット", "en": "Snapshot"},
    "gui.panel.export": {"ja": "エクスポート...", "en": "Export..."},
    "gui.panel.clone": {"ja": "複製...", "en": "Clone..."},
    "gui.panel.section_manage": {"ja": "設定・管理", "en": "Settings"},
    "gui.panel.set_default": {"ja": "既定に設定", "en": "Set as default"},
    "gui.panel.convert": {"ja": "WSL1/2 変換...", "en": "Convert WSL1/2..."},
    "gui.panel.distro_conf": {"ja": "wsl.conf...", "en": "wsl.conf..."},
    "gui.panel.optimize": {"ja": "ディスク最適化...", "en": "Optimize disk..."},
    "gui.panel.details": {"ja": "詳細情報...", "en": "Details..."},
    "gui.panel.section_danger": {"ja": "削除", "en": "Delete"},
    "gui.panel.unregister": {"ja": "登録解除 (削除)...", "en": "Unregister (delete)..."},
    # ── 一覧が空のとき ──
    "gui.empty.loading": {"ja": "読み込み中…", "en": "Loading…"},
    "gui.empty.none_title": {
        "ja": "ディストリビューションがありません",
        "en": "No distributions yet",
    },
    "gui.empty.none_hint": {
        "ja": "公式のディストリビューションをインストールするか、"
        "バックアップ (tar / vhdx) をインポートしてください。",
        "en": "Install an official distribution, or import a backup (tar / vhdx).",
    },
    "gui.empty.error_title": {
        "ja": "ディストリビューションの一覧を取得できませんでした",
        "en": "Could not get the list of distributions",
    },
    "gui.empty.error_hint": {
        "ja": "WSL がインストールされていない場合は、管理者の PowerShell で "
        "「wsl --install」を実行してから再試行してください。",
        "en": "If WSL is not installed, run 'wsl --install' in an administrator "
        "PowerShell, then try again.",
    },
    "gui.empty.retry": {"ja": "再試行", "en": "Try again"},
    "gui.empty.no_match": {
        "ja": "「{text}」に一致するディストリビューションはありません",
        "en": "No distributions match '{text}'",
    },
    "gui.empty.clear_filter": {"ja": "検索をクリア", "en": "Clear search"},
    # ── ステータス・メッセージ ──
    "gui.status.ready": {"ja": "準備完了", "en": "Ready"},
    "gui.status.refreshing": {"ja": "更新中…", "en": "Refreshing…"},
    "gui.status.refreshed": {
        "ja": "ディストリビューション情報を更新しました。",
        "en": "Distribution list refreshed.",
    },
    "gui.status.refresh_failed": {
        "ja": "一覧の取得に失敗しました: {error}",
        "en": "Failed to get the list: {error}",
    },
    "gui.status.updated_at": {"ja": "最終更新 {time}", "en": "Updated {time}"},
    "gui.status.summary": {
        "ja": "{count} 件 (実行中 {running})",
        "en": "{count} distribution(s), {running} running",
    },
    "gui.status.filtered": {"ja": "表示 {shown} 件", "en": "{shown} shown"},
    "gui.status.log_warning": {
        "ja": "警告: 操作ログの書き込みに問題が発生しています"
        "（キュー溢れによる破棄: {dropped} 件 / 書き込み失敗: {errors} 件）",
        "en": "Warning: problems writing the operation log "
        "(dropped: {dropped}, write errors: {errors})",
    },
    "gui.status.theme_changed": {
        "ja": "テーマを「{theme}」に変更しました。",
        "en": "Theme changed to '{theme}'.",
    },
    "gui.status.theme_failed": {
        "ja": "テーマ「{theme}」の適用に失敗しました。",
        "en": "Failed to apply theme '{theme}'.",
    },
    "gui.status.interval_changed": {
        "ja": "自動更新の間隔を {seconds} 秒にしました。",
        "en": "Auto refresh interval set to {seconds} seconds.",
    },
    "gui.language_changed": {
        "ja": "表示言語を切り替えました。",
        "en": "Display language changed.",
    },
    # ── 確認ダイアログ ──
    "gui.confirm.stop": {
        "ja": "「{name}」を停止しますか？\n（未保存の作業内容は失われる可能性があります）",
        "en": "Stop '{name}'?\n(Unsaved work may be lost)",
    },
    "gui.confirm.shutdown": {
        "ja": "実行中のすべての WSL ディストリビューションを停止しますか？\n"
        "（未保存の作業内容は失われる可能性があります）",
        "en": "Shut down all running WSL distributions?\n(Unsaved work may be lost)",
    },
    "gui.confirm.unregister": {
        "ja": "ディストリビューション「{name}」を登録解除（削除）しますか？\n\n"
        "警告: ディストリビューション内のすべてのデータが完全に削除されます。\n"
        "この操作は取り消せません。必要なら先にスナップショットを作成してください。",
        "en": "Unregister (delete) distribution '{name}'?\n\n"
        "WARNING: All data in this distribution will be permanently deleted.\n"
        "This operation cannot be undone. Create a snapshot first if needed.",
    },
    "gui.confirm.unregister_retype": {
        "ja": "誤操作防止のため、削除するディストリビューション名を\n"
        "正確に入力してください: {name}",
        "en": "To prevent mistakes, please re-enter the exact distribution name:\n{name}",
    },
    "gui.confirm.unregister_partial": {
        "ja": "処理を中断したため、不完全な登録が残っている可能性があります。\n"
        "「{name}」の登録を解除しますか？",
        "en": "The operation was interrupted, so an incomplete registration may remain.\n"
        "Unregister '{name}'?",
    },
    "gui.confirm.convert": {
        "ja": "ディストリビューション「{name}」を WSL{target} に変換しますか？\n"
        "（変換には数分かかる場合があります）",
        "en": "Convert distribution '{name}' to WSL{target}?\n"
        "(This conversion may take several minutes)",
    },
    "gui.confirm.convert_from": {
        "ja": "「{name}」を WSL{current} から WSL{target} に変換しますか？\n"
        "（変換には数分かかる場合があります）",
        "en": "Convert '{name}' from WSL{current} to WSL{target}?\n"
        "(This conversion may take several minutes)",
    },
    "gui.confirm.overwrite": {
        "ja": "既存のファイルを上書きしますか？\n{path}",
        "en": "Overwrite the existing file?\n{path}",
    },
    "gui.confirm.import": {
        "ja": "次の内容でインポートします。\n\n名前: {name}\nイメージ: {image}\n"
        "インストール先: {folder}\nバージョン: WSL{version}",
        "en": "Import with the following settings?\n\nName: {name}\nImage: {image}\n"
        "Install location: {folder}\nVersion: WSL{version}",
    },
    "gui.confirm.clone": {
        "ja": "次の内容で複製します。\n\n複製元: {name}\n複製先の名前: {new_name}\n"
        "複製先フォルダ: {folder}\n\n複製中は一時 tar ファイルが複製先フォルダに作成され、"
        "完了後に削除されます。",
        "en": "Clone with the following settings?\n\nSource: {name}\nNew name: {new_name}\n"
        "Destination folder: {folder}\n\nA temporary tar file is created in the destination "
        "folder and deleted when the clone finishes.",
    },
    "gui.confirm.install": {
        "ja": "「{name}」をインストールしますか？\n（ダウンロードに数分かかる場合があります）",
        "en": "Install '{name}'?\n(The download may take several minutes)",
    },
    "gui.confirm.quit_running": {
        "ja": "実行中の処理が {count} 件あります。中断して終了しますか？\n"
        "中断すると、処理中だったファイルが不完全な状態で残る場合があります。",
        "en": "{count} operation(s) are still running. Cancel them and quit?\n"
        "Files that were being written may be left incomplete.",
    },
    # ── 結果メッセージ ──
    "gui.msg.select_distro": {
        "ja": "ディストリビューションを選択してください。",
        "en": "Please select a distribution.",
    },
    "gui.msg.already_version": {
        "ja": "「{name}」は既に WSL{version} です。",
        "en": "'{name}' is already WSL{version}.",
    },
    "gui.msg.exit_code": {"ja": "終了コード {code}", "en": "exit code {code}"},
    "gui.msg.timeout": {
        "ja": "WSL の応答がタイムアウトしました。",
        "en": "WSL did not respond in time.",
    },
    "gui.msg.command_failed": {"ja": "WSL の操作に失敗しました。", "en": "The WSL command failed."},
    "gui.msg.already_running": {
        "ja": "「{name}」は既に実行中です。",
        "en": "'{name}' is already running.",
    },
    "gui.msg.starting": {"ja": "「{name}」を起動中…", "en": "Starting '{name}'…"},
    "gui.msg.started": {"ja": "「{name}」を起動しました。", "en": "Started '{name}'."},
    "gui.msg.start_failed": {
        "ja": "「{name}」の起動に失敗しました。",
        "en": "Failed to start '{name}'.",
    },
    "gui.msg.stopping": {"ja": "「{name}」を停止中…", "en": "Stopping '{name}'…"},
    "gui.msg.stopped": {"ja": "「{name}」を停止しました。", "en": "Stopped '{name}'."},
    "gui.msg.stop_failed": {
        "ja": "「{name}」の停止に失敗しました。",
        "en": "Failed to stop '{name}'.",
    },
    "gui.msg.shutting_down": {"ja": "WSL を全停止中…", "en": "Shutting down WSL…"},
    "gui.msg.shutdown_done": {"ja": "WSL を全停止しました。", "en": "WSL has been shut down."},
    "gui.msg.shutdown_failed": {
        "ja": "WSL の全停止に失敗しました。",
        "en": "Failed to shut down WSL.",
    },
    "gui.msg.setting_default": {
        "ja": "「{name}」を既定に設定中…",
        "en": "Setting '{name}' as default…",
    },
    "gui.msg.set_default_success": {
        "ja": "「{name}」を既定のディストリビューションに設定しました。",
        "en": "Set '{name}' as the default distribution.",
    },
    "gui.msg.set_default_failed": {
        "ja": "「{name}」を既定に設定できませんでした。",
        "en": "Failed to set '{name}' as default.",
    },
    "gui.msg.terminal_bad_name": {
        "ja": "「{name}」はターミナル起動時に使用できない名前です: {reason}",
        "en": "'{name}' cannot be used to open a terminal: {reason}",
    },
    "gui.msg.terminal_opened": {
        "ja": "「{name}」のターミナルを開きました ({app})。",
        "en": "Opened a terminal for '{name}' ({app}).",
    },
    "gui.msg.terminal_failed": {
        "ja": "ターミナルを開けませんでした。",
        "en": "Could not open a terminal.",
    },
    "gui.msg.processes_need_running": {
        "ja": "「{name}」は停止中です。起動してからプロセスを確認してください。",
        "en": "'{name}' is stopped. Please start it before checking processes.",
    },
    "gui.msg.folder_failed": {
        "ja": "フォルダを作成できませんでした: {path}",
        "en": "Could not create the folder: {path}",
    },
    "gui.msg.move_failed": {
        "ja": "一時ファイルを保存先へ移動できませんでした。",
        "en": "Could not move the temporary file to the destination.",
    },
    "gui.msg.exporting": {"ja": "「{name}」をエクスポート中…", "en": "Exporting '{name}'…"},
    "gui.msg.exported": {
        "ja": "「{name}」をエクスポートしました: {path}",
        "en": "Exported '{name}': {path}",
    },
    "gui.msg.export_cancelled": {
        "ja": "「{name}」のエクスポートをキャンセルしました。",
        "en": "Cancelled the export of '{name}'.",
    },
    "gui.msg.export_failed": {
        "ja": "「{name}」のエクスポートに失敗しました。",
        "en": "Failed to export '{name}'.",
    },
    "gui.msg.importing": {"ja": "「{name}」をインポート中…", "en": "Importing '{name}'…"},
    "gui.msg.imported": {"ja": "「{name}」をインポートしました。", "en": "Imported '{name}'."},
    "gui.msg.import_cancelled": {
        "ja": "「{name}」のインポートをキャンセルしました。",
        "en": "Cancelled the import of '{name}'.",
    },
    "gui.msg.import_failed": {
        "ja": "「{name}」のインポートに失敗しました。",
        "en": "Failed to import '{name}'.",
    },
    "gui.msg.clone_step": {
        "ja": "「{name}」を複製中… ({step})",
        "en": "Cloning '{name}'… ({step})",
    },
    "gui.msg.clone_done": {
        "ja": "「{name}」を「{new_name}」として複製しました。",
        "en": "Cloned '{name}' as '{new_name}'.",
    },
    "gui.msg.clone_cancelled": {
        "ja": "「{name}」の複製をキャンセルしました。",
        "en": "Cancelled cloning '{name}'.",
    },
    "gui.msg.snapshot_creating": {
        "ja": "「{name}」のスナップショットを作成中…",
        "en": "Creating a snapshot of '{name}'…",
    },
    "gui.msg.snapshot_created": {
        "ja": "「{name}」のスナップショットを作成しました。",
        "en": "Created a snapshot of '{name}'.",
    },
    "gui.msg.snapshot_cancelled": {
        "ja": "「{name}」のスナップショット作成をキャンセルしました。",
        "en": "Cancelled the snapshot of '{name}'.",
    },
    "gui.msg.snapshot_failed": {
        "ja": "「{name}」のスナップショット作成に失敗しました。",
        "en": "Failed to create a snapshot of '{name}'.",
    },
    "gui.msg.snapshot_meta_failed": {
        "ja": "「{name}」のスナップショットを作成しましたが、メタデータの保存に失敗しました。",
        "en": "Created a snapshot of '{name}', but its metadata could not be saved.",
    },
    "gui.msg.online_loading": {
        "ja": "インストール可能な一覧を取得中…",
        "en": "Getting the list of installable distributions…",
    },
    "gui.msg.online_timeout": {
        "ja": "オンライン一覧の取得がタイムアウトしました。",
        "en": "Timed out getting the online list.",
    },
    "gui.msg.online_failed": {
        "ja": "インストール可能な一覧の取得に失敗しました。",
        "en": "Failed to get the list of installable distributions.",
    },
    "gui.msg.wsl_missing": {
        "ja": "wsl.exe が見つかりません。WSL がインストールされているか確認してください。",
        "en": "wsl.exe was not found. Check that WSL is installed.",
    },
    "gui.msg.list_failed": {
        "ja": "ディストリビューション一覧の取得に失敗しました。",
        "en": "Failed to get the list of distributions.",
    },
    "gui.msg.wsl_failed": {
        "ja": "WSL の実行に失敗しました: {error}",
        "en": "Failed to run WSL: {error}",
    },
    "gui.msg.installing": {"ja": "「{name}」をインストール中…", "en": "Installing '{name}'…"},
    "gui.msg.installed": {
        "ja": "「{name}」をインストールしました。"
        "初回起動時にユーザー作成などの初期設定が始まります。",
        "en": "Installed '{name}'. Initial setup (creating a user) starts on the first launch.",
    },
    "gui.msg.install_cancelled": {
        "ja": "インストールをキャンセルしました。",
        "en": "Installation cancelled.",
    },
    "gui.msg.install_failed": {
        "ja": "「{name}」のインストールに失敗しました。",
        "en": "Failed to install '{name}'.",
    },
    "gui.msg.unregistering": {
        "ja": "「{name}」を登録解除中…",
        "en": "Unregistering '{name}'…",
    },
    "gui.msg.unregister_mismatch": {
        "ja": "入力された名前が一致しないため、登録解除を中止しました。",
        "en": "Unregistration cancelled because the entered name did not match.",
    },
    "gui.msg.unregister_success": {
        "ja": "「{name}」を登録解除しました。",
        "en": "Unregistered '{name}'.",
    },
    "gui.msg.unregister_failed": {
        "ja": "「{name}」の登録解除に失敗しました。",
        "en": "Failed to unregister '{name}'.",
    },
    "gui.msg.wslconfig_saved": {
        "ja": ".wslconfig を保存しました。反映には WSL の全停止が必要です。",
        "en": "Saved .wslconfig. Shut down WSL to apply the changes.",
    },
    "gui.msg.distroconf_saved": {
        "ja": "「{name}」の wsl.conf を保存しました。",
        "en": "Saved wsl.conf for '{name}'.",
    },
    "gui.msg.vhdx_missing": {
        "ja": "「{name}」の仮想ディスク (ext4.vhdx) が見つかりません。\n"
        "WSL1 か、ディスク情報を取得できない構成の可能性があります。",
        "en": "The virtual disk (ext4.vhdx) of '{name}' was not found.\n"
        "It may be WSL1, or its disk information is unavailable.",
    },
    "gui.msg.explorer_opened": {
        "ja": "「{name}」をエクスプローラーで開きました。",
        "en": "Opened '{name}' in Explorer.",
    },
    "gui.msg.explorer_failed": {
        "ja": "エクスプローラーを開けませんでした。",
        "en": "Could not open Explorer.",
    },
    "gui.msg.ip_copied": {
        "ja": "IP アドレスをコピーしました: {ip}",
        "en": "Copied the IP address: {ip}",
    },
    "gui.msg.ip_unavailable": {
        "ja": "IP アドレスを取得できていません。",
        "en": "The IP address is not available.",
    },
    "gui.msg.converting": {
        "ja": "「{name}」を WSL{version} に変換中…",
        "en": "Converting '{name}' to WSL{version}…",
    },
    "gui.msg.convert_success": {
        "ja": "「{name}」を WSL{version} に変換しました。",
        "en": "Converted '{name}' to WSL{version}.",
    },
    "gui.msg.convert_cancelled": {
        "ja": "「{name}」の WSL バージョン変換を中断しました。",
        "en": "Cancelled WSL version conversion for '{name}'.",
    },
    "gui.msg.convert_failed": {
        "ja": "「{name}」の WSL バージョン変換に失敗しました。",
        "en": "Failed to convert '{name}'.",
    },
    "gui.msg.mounting": {"ja": "「{disk}」をマウント中…", "en": "Mounting '{disk}'…"},
    "gui.msg.mounted": {"ja": "「{disk}」をマウントしました。", "en": "Mounted '{disk}'."},
    "gui.msg.mount_failed": {
        "ja": "「{disk}」のマウントに失敗しました。",
        "en": "Failed to mount '{disk}'.",
    },
    "gui.msg.all_disks": {"ja": "すべてのマウントディスク", "en": "all mounted disks"},
    "gui.msg.unmounting": {"ja": "「{disk}」をアンマウント中…", "en": "Unmounting '{disk}'…"},
    "gui.msg.unmounted": {
        "ja": "「{disk}」をアンマウントしました。",
        "en": "Unmounted '{disk}'.",
    },
    "gui.msg.unmount_failed": {
        "ja": "「{disk}」のアンマウントに失敗しました。",
        "en": "Failed to unmount '{disk}'.",
    },
    "gui.msg.admin_hint": {
        "ja": "管理者権限が必要な場合があります。",
        "en": "Administrator privileges may be required.",
    },
    "gui.msg.updating": {
        "ja": "WSL を更新しています…（数分かかる場合があります）",
        "en": "Updating WSL… (this may take a few minutes)",
    },
    "gui.msg.update_done": {"ja": "WSL の更新が完了しました。", "en": "WSL has been updated."},
    "gui.msg.update_cancelled": {
        "ja": "WSL の更新をキャンセルしました。",
        "en": "Cancelled the WSL update.",
    },
    "gui.msg.update_failed": {"ja": "WSL の更新に失敗しました。", "en": "Failed to update WSL."},
    "gui.msg.browser_failed": {
        "ja": "ブラウザーを開けませんでした。",
        "en": "Could not open the browser.",
    },
    "gui.msg.windows_only": {
        "ja": "WSL Manager は Windows 環境でのみ動作します。\nWindows 10/11 上で実行してください。",
        "en": "WSL Manager runs on Windows only.\nPlease run it on Windows 10/11.",
    },
    # ── 入力フォーム (エクスポート・インポート・複製) ──
    "gui.form.distro": {"ja": "ディストリビューション:", "en": "Distribution:"},
    "gui.form.browse": {"ja": "参照...", "en": "Browse..."},
    "gui.form.browse_dir": {"ja": "フォルダーを選択", "en": "Choose a folder"},
    "gui.form.install_dir": {"ja": "インストール先:", "en": "Install location:"},
    "gui.form.install_dir_hint": {
        "ja": "仮想ディスク (ext4.vhdx) がこのフォルダーに作られます。無ければ作成します。",
        "en": "The virtual disk (ext4.vhdx) is created in this folder. "
        "It is created if it does not exist.",
    },
    "gui.export.title": {"ja": "エクスポート - {name}", "en": "Export - {name}"},
    "gui.export.ok": {"ja": "エクスポート", "en": "Export"},
    "gui.export.format": {"ja": "形式:", "en": "Format:"},
    "gui.export.format_tar": {
        "ja": "tar (標準。ほかの PC・WSL1 にもインポートできます)",
        "en": "tar (standard; can be imported on other PCs and WSL1)",
    },
    "gui.export.format_vhd": {
        "ja": "VHDX (仮想ディスクのまま。WSL2 専用)",
        "en": "VHDX (keeps the virtual disk; WSL2 only)",
    },
    "gui.export.destination": {"ja": "保存先:", "en": "Save to:"},
    "gui.export.browse_title": {"ja": "エクスポート先を選択", "en": "Choose where to export"},
    "gui.export.hint": {
        "ja": "途中で中断しても既存のファイルは壊れません (完了後に置き換えます)。",
        "en": "An existing file is not damaged if the export is interrupted "
        "(it is replaced only when the export finishes).",
    },
    "gui.import.title": {"ja": "インポート", "en": "Import"},
    "gui.import.ok": {"ja": "インポート", "en": "Import"},
    "gui.import.image": {"ja": "イメージ:", "en": "Image:"},
    "gui.import.image_types": {"ja": "WSL イメージ", "en": "WSL images"},
    "gui.import.browse_image": {
        "ja": "インポートするイメージを選択",
        "en": "Choose an image to import",
    },
    "gui.import.version": {"ja": "WSL バージョン:", "en": "WSL version:"},
    "gui.import.wsl2": {"ja": "WSL 2 (推奨)", "en": "WSL 2 (recommended)"},
    "gui.import.vhd_hint": {
        "ja": "VHDX イメージは WSL 2 としてインポートされます。",
        "en": "VHDX images are imported as WSL 2.",
    },
    "gui.clone.title": {"ja": "複製 - {name}", "en": "Clone - {name}"},
    "gui.clone.ok": {"ja": "複製", "en": "Clone"},
    "gui.clone.source": {"ja": "複製元:", "en": "Source:"},
    "gui.clone.new_name": {"ja": "新しい名前:", "en": "New name:"},
    "gui.clone.hint": {
        "ja": "エクスポートとインポートを順に行います。"
        "大きなディストリビューションは時間がかかります。",
        "en": "Exports and then imports the distribution. Large distributions take a while.",
    },
    "form.error.name_invalid": {"ja": "名前: {reason}", "en": "Name: {reason}"},
    "form.error.name_exists": {
        "ja": "「{name}」という名前のディストリビューションは既にあります。",
        "en": "A distribution named '{name}' already exists.",
    },
    "form.error.image_required": {
        "ja": "インポートするイメージを選択してください。",
        "en": "Choose an image to import.",
    },
    "form.error.image_missing": {
        "ja": "イメージが見つかりません: {path}",
        "en": "The image was not found: {path}",
    },
    "form.error.folder_required": {
        "ja": "インストール先フォルダーを指定してください。",
        "en": "Choose an install location.",
    },
    "form.error.folder_not_dir": {
        "ja": "インストール先がフォルダーではありません: {path}",
        "en": "The install location is not a folder: {path}",
    },
    "form.error.folder_has_vhdx": {
        "ja": "インストール先には既に仮想ディスク (ext4.vhdx) があります。"
        "別のフォルダーを選んでください: {path}",
        "en": "The install location already contains a virtual disk (ext4.vhdx). "
        "Choose another folder: {path}",
    },
    "form.error.path_not_absolute": {
        "ja": "ドライブから始まるフルパスで指定してください (例: C:\\WSL): {path}",
        "en": "Enter a full path that starts with a drive (for example C:\\WSL): {path}",
    },
    "form.error.destination_folder_missing": {
        "ja": "保存先のフォルダーがありません: {path}",
        "en": "The destination folder does not exist: {path}",
    },
    "form.error.destination_required": {
        "ja": "保存先を指定してください。",
        "en": "Choose where to save the export.",
    },
    "validation.distro_name.empty": {
        "ja": "ディストリビューション名を入力してください",
        "en": "Enter a distribution name",
    },
    "validation.distro_name.invalid_chars": {
        "ja": "使用できない文字が含まれています: {chars}",
        "en": "Contains characters that cannot be used: {chars}",
    },
    "validation.distro_name.too_long": {
        "ja": "ディストリビューション名は64文字以内にしてください",
        "en": "Use 64 characters or fewer",
    },
    "validation.distro_name.reserved": {
        "ja": "Windows の予約デバイス名は使用できません",
        "en": "Windows reserved device names cannot be used",
    },
    "validation.distro_name.trailing": {
        "ja": "名前の末尾にドットや空白は使用できません",
        "en": "The name cannot end with a dot or a space",
    },
    "validation.distro_name.leading_space": {
        "ja": "名前の先頭に空白は使用できません",
        "en": "The name cannot start with a space",
    },
    "validation.distro_name.control": {
        "ja": "制御文字は使用できません",
        "en": "Control characters cannot be used",
    },
    "validation.distro_name.duplicate": {
        "ja": "同名のディストリビューションが既に存在します。",
        "en": "A distribution with the same name already exists.",
    },
    # ── 進捗ダイアログ ──
    "gui.transfer.starting": {"ja": "開始しています…", "en": "Starting…"},
    "gui.transfer.cancelling": {"ja": "キャンセルしています…", "en": "Cancelling…"},
    "gui.transfer.elapsed": {"ja": "経過 {time}", "en": "Elapsed {time}"},
    "gui.transfer.written": {"ja": "{size} 書き込み済み", "en": "{size} written"},
    "gui.transfer.remaining": {"ja": "残り約 {time}", "en": "About {time} left"},
    "gui.transfer.cancel_prompt": {
        "ja": "処理をキャンセルしますか？",
        "en": "Cancel the operation?",
    },
    "gui.transfer.export_title": {"ja": "エクスポート", "en": "Export"},
    "gui.transfer.export_message": {
        "ja": "「{name}」をエクスポートしています…",
        "en": "Exporting '{name}'…",
    },
    "gui.transfer.import_title": {"ja": "インポート", "en": "Import"},
    "gui.transfer.import_message": {
        "ja": "「{name}」をインポートしています…",
        "en": "Importing '{name}'…",
    },
    "gui.transfer.snapshot_title": {"ja": "スナップショット作成", "en": "Create snapshot"},
    "gui.transfer.snapshot_message": {
        "ja": "「{name}」のスナップショットを作成しています…",
        "en": "Creating a snapshot of '{name}'…",
    },
    "gui.transfer.clone_title": {"ja": "複製", "en": "Clone"},
    "gui.transfer.clone_export": {
        "ja": "「{name}」をエクスポートしています… (1/2)",
        "en": "Exporting '{name}'… (1/2)",
    },
    "gui.transfer.clone_import": {
        "ja": "「{name}」としてインポートしています… (2/2)",
        "en": "Importing as '{name}'… (2/2)",
    },
    "gui.transfer.install_title": {"ja": "インストール", "en": "Install"},
    "gui.transfer.install_message": {
        "ja": "「{name}」をダウンロードしてインストールしています…",
        "en": "Downloading and installing '{name}'…",
    },
    "gui.transfer.install_cancel": {
        "ja": "インストールをキャンセルしますか？",
        "en": "Cancel the installation?",
    },
    "gui.transfer.convert_title": {"ja": "WSL バージョン変換", "en": "WSL version conversion"},
    "gui.transfer.convert_message": {
        "ja": "「{name}」を WSL{version} に変換しています…",
        "en": "Converting '{name}' to WSL{version}…",
    },
    "gui.transfer.convert_cancel": {
        "ja": "変換をキャンセルしますか？\n変換の中断はディストリビューションが不完全な状態で"
        "残る可能性があります。",
        "en": "Cancel the conversion?\nInterrupting it may leave the distribution "
        "in an incomplete state.",
    },
    "gui.transfer.update_cancel": {
        "ja": "WSL の更新をキャンセルしますか？",
        "en": "Cancel the WSL update?",
    },
    # ── スナップショット作成 ──
    "gui.snapshot.create_title": {"ja": "スナップショット作成", "en": "Create snapshot"},
    "gui.snapshot.create_prompt": {
        "ja": "「{name}」のスナップショットを作成します。\n保存先: {folder}\n\nコメント (任意):",
        "en": "Create a snapshot of '{name}'.\nSaved to: {folder}\n\nComment (optional):",
    },
    # ── ヘルプ ──
    "gui.help.shortcuts": {
        "ja": "Enter / ダブルクリック\tターミナルを開く\n"
        "Ctrl+Shift+S\t起動 (バックグラウンド)\n"
        "Delete\t停止\n"
        "F5 / Ctrl+R\t最新の情報に更新\n"
        "Ctrl+F\t検索\n"
        "Ctrl+N\tインストール\n"
        "Ctrl+I\tインポート\n"
        "Ctrl+E\tエクスポート\n"
        "Ctrl+S\tスナップショットを作成\n"
        "Ctrl+D\t詳細情報\n"
        "Ctrl+P\tプロセス一覧\n"
        "Ctrl+,\tWSL 全体の設定\n"
        "Ctrl+L\t操作ログ\n"
        "Ctrl+Shift+Q\tWSL を全停止\n"
        "Shift+F10\t右クリックメニュー",
        "en": "Enter / double-click\tOpen terminal\n"
        "Ctrl+Shift+S\tStart in background\n"
        "Delete\tStop\n"
        "F5 / Ctrl+R\tRefresh\n"
        "Ctrl+F\tSearch\n"
        "Ctrl+N\tInstall\n"
        "Ctrl+I\tImport\n"
        "Ctrl+E\tExport\n"
        "Ctrl+S\tCreate snapshot\n"
        "Ctrl+D\tDetails\n"
        "Ctrl+P\tProcesses\n"
        "Ctrl+,\tGlobal WSL settings\n"
        "Ctrl+L\tOperation log\n"
        "Ctrl+Shift+Q\tShut down WSL\n"
        "Shift+F10\tContext menu",
    },
    "gui.help.cli": {
        "ja": "コマンドライン版 wslmgr.exe を使うと、同じ操作をスクリプトや"
        "タスク スケジューラから実行できます。\n\n"
        "場所: {location}\n\n例:\n  wslmgr list\n  wslmgr snapshot create Ubuntu\n"
        "  wslmgr --help\n\nインストーラで「PATH に追加」を選ぶと、どのフォルダーからでも"
        "「wslmgr」で実行できます。",
        "en": "The command-line tool wslmgr.exe runs the same operations from scripts "
        "and Task Scheduler.\n\nLocation: {location}\n\nExamples:\n  wslmgr list\n"
        "  wslmgr snapshot create Ubuntu\n  wslmgr --help\n\nChoose 'Add to PATH' in the "
        "installer to run 'wslmgr' from any folder.",
    },
    "gui.help.cli_not_found": {
        "ja": "(このフォルダーには見つかりません。"
        "インストーラ版またはポータブル版の ZIP に含まれています)",
        "en": "(not found next to this app; it is included in the installer and the portable ZIP)",
    },
    "gui.about.title": {"ja": "WSL Manager について", "en": "About WSL Manager"},
    "gui.about.body": {
        "ja": "WSL Manager v{version}\n\nWSL ディストリビューション管理ツール\n"
        "Windows 10/11 + WSL\n\n{url}",
        "en": "WSL Manager v{version}\n\nA manager for WSL distributions\n"
        "Windows 10/11 + WSL\n\n{url}",
    },
    # ── WSL バージョン情報 ──
    "gui.version.wsl": {"ja": "WSL バージョン", "en": "WSL version"},
    "gui.version.kernel": {"ja": "カーネル バージョン", "en": "Kernel version"},
    "gui.version.wslg": {"ja": "WSLg バージョン", "en": "WSLg version"},
    "gui.version.msrdc": {"ja": "MSRDC バージョン", "en": "MSRDC version"},
    "gui.version.direct3d": {"ja": "Direct3D バージョン", "en": "Direct3D version"},
    "gui.version.dxcore": {"ja": "DXCore バージョン", "en": "DXCore version"},
    "gui.version.windows": {"ja": "Windows バージョン", "en": "Windows version"},
    "gui.version.other": {"ja": "【その他の情報】", "en": "[Other information]"},
    "gui.version.unavailable": {
        "ja": "WSL のバージョン情報を取得できませんでした。",
        "en": "Could not get WSL version information.",
    },
    # ── プロセスウィンドウ ──
    "gui.process.title": {"ja": "プロセス一覧 - {name}", "en": "Process List - {name}"},
    "gui.process.auto_refresh": {"ja": "自動更新 (3秒)", "en": "Auto refresh (3s)"},
    "gui.process.count": {"ja": "プロセス数: {count}", "en": "Processes: {count}"},
    "gui.process.count_filtered": {
        "ja": "プロセス数: {displayed} / {total}",
        "en": "Processes: {displayed} / {total}",
    },
    "gui.process.col_pid": {"ja": "PID", "en": "PID"},
    "gui.process.col_user": {"ja": "ユーザー", "en": "User"},
    "gui.process.col_cpu": {"ja": "CPU(%)", "en": "CPU(%)"},
    "gui.process.col_memory": {"ja": "メモリ(MB)", "en": "Memory (MB)"},
    "gui.process.col_command": {"ja": "コマンド", "en": "Command"},
    "gui.process.loading": {"ja": "読み込み中…", "en": "Loading..."},
    "gui.process.refreshing": {"ja": "更新中…", "en": "Refreshing..."},
    "gui.process.refreshed": {"ja": "更新完了", "en": "Updated"},
    "gui.process.error": {"ja": "エラー: {error}", "en": "Error: {error}"},
    "gui.process.kill_term": {
        "ja": "プロセスを終了 (SIGTERM)",
        "en": "Terminate process (SIGTERM)",
    },
    "gui.process.kill_kill": {"ja": "強制終了 (SIGKILL)", "en": "Force kill (SIGKILL)"},
    "gui.process.kill_confirm_term": {
        "ja": "PID {pid} ({command}) にシグナルを送信しますか？",
        "en": "Send signal to PID {pid} ({command})?",
    },
    "gui.process.kill_confirm_kill": {
        "ja": "PID {pid} ({command}) にシグナルを送信しますか？\n(SIGKILL: 強制終了します)",
        "en": "Send signal to PID {pid} ({command})?\n(SIGKILL: Force kill)",
    },
    "gui.process.timeout": {"ja": "タイムアウトしました。", "en": "Timed out."},
    "gui.process.fetch_failed": {
        "ja": "プロセス一覧の取得に失敗しました。",
        "en": "Failed to get process list.",
    },
    # ── インストールダイアログ ──
    "gui.install.title": {
        "ja": "ディストリビューションのインストール",
        "en": "Install Distribution",
    },
    "gui.install.label": {
        "ja": "インストールするディストリビューションを選択または入力してください:",
        "en": "Select or enter the distribution to install:",
    },
    "gui.install.empty_list": {
        "ja": "（一覧を取得できませんでした。名前を直接入力してください）",
        "en": "(Failed to get list. Please enter the name directly)",
    },
    "gui.install.btn_install": {"ja": "インストール", "en": "Install"},
    # ── 設定ダイアログ ──
    "gui.wslconfig.title": {"ja": "WSL 設定 (.wslconfig)", "en": "WSL Settings (.wslconfig)"},
    "gui.wslconfig.restore_defaults": {"ja": "デフォルトに戻す", "en": "Restore Defaults"},
    "gui.distroconf.title": {
        "ja": "ディストリビューション設定 - {name}",
        "en": "Distribution Settings - {name}",
    },
    # ── ディスク最適化ダイアログ ──
    "gui.optimize.title": {"ja": "ディスク最適化 - {name}", "en": "Disk Optimization - {name}"},
    "gui.optimize.btn_sparse": {"ja": "スパース化を有効にする", "en": "Enable Sparse Mode"},
    "gui.optimize.btn_compact": {"ja": "ディスクを圧縮する", "en": "Compact Disk"},
    # ── 詳細情報ダイアログ ──
    "gui.detail.title": {"ja": "詳細情報 - {name}", "en": "Details - {name}"},
    # ── ログビューア ──
    "gui.log.title": {"ja": "操作ログビューア", "en": "Operation Log Viewer"},
    "gui.log.clear": {"ja": "ログ消去", "en": "Clear Log"},
    "gui.log.export": {"ja": "エクスポート...", "en": "Export..."},
    # ── バージョン・更新 ──
    "gui.version.title": {"ja": "WSL バージョン情報", "en": "WSL Version Information"},
    "gui.update.title": {"ja": "WSL の更新", "en": "Update WSL"},
    "gui.update.confirm": {
        "ja": "WSL を最新バージョンに更新しますか？",
        "en": "Update WSL to the latest version?",
    },
    "gui.update.running_warning": {
        "ja": "実行中のディストリビューションがあります:\n{distros}\n更新を続行しますか？",
        "en": "Running distributions detected:\n{distros}\nContinue update?",
    },
    # ── マウント/アンマウント ──
    "gui.mount.title": {"ja": "ディスクのマウント", "en": "Mount Disk"},
    "gui.mount.btn_mount": {"ja": "マウント", "en": "Mount"},
    "gui.unmount.title": {"ja": "ディスクのアンマウント", "en": "Unmount Disk"},
    "gui.unmount.btn_unmount": {"ja": "アンマウント", "en": "Unmount"},
    # ── スナップショット管理 ──
    "gui.snapshot.title": {"ja": "スナップショット管理", "en": "Snapshot Management"},
    # ── 右クリックコンテキストメニュー ──
    "gui.context.terminal": {"ja": "ターミナルを開く", "en": "Open terminal"},
    "gui.context.start": {"ja": "起動 (バックグラウンド)", "en": "Start (in background)"},
    "gui.context.details": {"ja": "詳細情報...", "en": "Details..."},
    "gui.context.processes": {"ja": "プロセス一覧...", "en": "Processes..."},
    "gui.context.explorer": {"ja": "エクスプローラーで開く", "en": "Open in Explorer"},
    "gui.context.copy_ip": {"ja": "IP アドレスをコピー", "en": "Copy IP address"},
    "gui.context.stop": {"ja": "停止", "en": "Stop"},
    "gui.context.set_default": {"ja": "既定に設定", "en": "Set as default"},
    "gui.context.convert": {"ja": "WSL1/WSL2 変換...", "en": "Convert WSL1/WSL2..."},
    "gui.context.optimize": {"ja": "ディスク最適化...", "en": "Optimize disk..."},
    "gui.context.distro_conf": {"ja": "wsl.conf を編集...", "en": "Edit wsl.conf..."},
    "gui.context.clone": {"ja": "複製...", "en": "Clone..."},
    "gui.context.snapshot": {"ja": "スナップショットを作成...", "en": "Create snapshot..."},
    "gui.context.export": {"ja": "エクスポート...", "en": "Export..."},
    "gui.context.unregister": {"ja": "登録解除 (削除)...", "en": "Unregister (delete)..."},
    # ── CLI メッセージ ──
    "cli.description": {
        "ja": "WSL Manager - コマンドラインインターフェース",
        "en": "WSL Manager command-line interface",
    },
    "cli.language": {
        "ja": "表示言語 (auto, ja, en。既定: 保存済み設定またはシステム設定)",
        "en": "Display language (auto, ja, en; default: saved preference or system default)",
    },
    "cli.quiet": {
        "ja": "成功時のメッセージ出力を抑制します",
        "en": "Suppress success messages",
    },
    "cli.list": {
        "ja": "WSL ディストリビューションの一覧を表示します",
        "en": "List WSL distributions",
    },
    "cli.start": {
        "ja": "ディストリビューションを起動します",
        "en": "Start distribution",
    },
    "cli.stop": {
        "ja": "ディストリビューションを停止します",
        "en": "Stop distribution",
    },
    "cli.shutdown": {
        "ja": "すべてのディストリビューションを停止します",
        "en": "Shut down all distributions",
    },
    "cli.status": {
        "ja": "実行中ディストリビューションのリソース使用状況を表示します",
        "en": "Show resource usage of running distributions",
    },
    "cli.export": {
        "ja": "ディストリビューションをエクスポートします",
        "en": "Export distribution",
    },
    "cli.import": {
        "ja": "ディストリビューションをインポートします",
        "en": "Import distribution",
    },
    "cli.config": {
        "ja": "現在の .wslconfig または /etc/wsl.conf 設定を表示します",
        "en": "Show current .wslconfig or /etc/wsl.conf settings",
    },
    "cli.set_default": {
        "ja": "ディストリビューションを既定 (デフォルト) に設定します",
        "en": "Set distribution as default",
    },
    "cli.unregister": {
        "ja": "ディストリビューションをアンインストール (登録解除) します",
        "en": "Unregister (uninstall) distribution",
    },
    "cli.install": {
        "ja": "ディストリビューションをインストールします",
        "en": "Install distribution",
    },
    "cli.optimize": {
        "ja": "ディストリビューションの仮想ディスクを最適化します",
        "en": "Optimize virtual disk of distribution",
    },
    "cli.set_version": {
        "ja": "ディストリビューションを WSL1 / WSL2 間で変換します",
        "en": "Convert distribution between WSL1 and WSL2",
    },
    "cli.processes": {
        "ja": "ディストリビューション内で実行中のプロセス一覧を表示します",
        "en": "Show running processes in distribution",
    },
    "cli.log": {
        "ja": "保存されている操作ログを表示・消去します",
        "en": "View or clear operation logs",
    },
    "cli.portproxy": {
        "ja": "ポートフォワーディングルールを管理します",
        "en": "Manage port forwarding rules",
    },
    "cli.snapshot": {
        "ja": "ディストリビューションのスナップショットを管理します",
        "en": "Manage distribution snapshots",
    },
    "cli.clone": {
        "ja": "ディストリビューションを複製します（エクスポート→インポートを自動実行）",
        "en": "Clone distribution (auto export and import)",
    },
    "cli.mount": {
        "ja": "物理ディスクまたは VHD を WSL2 にマウントします",
        "en": "Mount physical disk or VHD to WSL2",
    },
    "cli.unmount": {
        "ja": "WSL2 にマウントされているディスクをアンマウントします",
        "en": "Unmount disk from WSL2",
    },
    "cli.format": {
        "ja": "出力フォーマット (既定: table)",
        "en": "Output format (default: table)",
    },
    "cli.with_ip": {
        "ja": "実行中ディストリビューションの IP アドレスも取得します",
        "en": "Include IP addresses for running distributions",
    },
    "cli.with_disk": {
        "ja": "実行中ディストリビューションのディスク使用量も取得します",
        "en": "Include disk usage for running distributions",
    },
    "cli.all_info": {
        "ja": "IP アドレスおよびディスク使用量を含めて表示します",
        "en": "Include IP addresses and disk usage",
    },
    "cli.list_error": {
        "ja": "ディストリビューション一覧の取得に失敗しました。",
        "en": "Failed to get the distribution list.",
    },
    "cli.error": {"ja": "エラー", "en": "Error"},
    "cli.header.name": {"ja": "名前", "en": "Name"},
    "cli.header.state": {"ja": "状態", "en": "State"},
    "cli.header.version": {"ja": "バージョン", "en": "Version"},
    "cli.header.default": {"ja": "既定", "en": "Default"},
    "cli.header.cpu": {"ja": "CPU(%)", "en": "CPU(%)"},
    "cli.header.memory": {"ja": "メモリ(MB)", "en": "Memory (MB)"},
    "cli.header.disk": {"ja": "ディスク(GB)", "en": "Disk (GB)"},
    "cli.header.ip": {"ja": "IPアドレス", "en": "IP address"},
    "cli.header.pid": {"ja": "PID", "en": "PID"},
    "cli.header.user": {"ja": "ユーザー", "en": "User"},
    "cli.header.command": {"ja": "コマンド", "en": "Command"},
    # ── CLI サブコマンド引数 ──
    "cli.arg.name": {"ja": "ディストリビューション名", "en": "Distribution name"},
    "cli.arg.path": {"ja": "エクスポート先のファイルパス", "en": "Export destination file path"},
    "cli.arg.install_path": {
        "ja": "インストール先ディレクトリ",
        "en": "Install destination directory",
    },
    "cli.arg.image_path": {
        "ja": "インポートするイメージ (tar) のパス",
        "en": "Path to image (tar) to import",
    },
    "cli.arg.yes": {
        "ja": "確認プロンプトを表示せずに実行します",
        "en": "Execute without confirmation prompt",
    },
    "cli.arg.distro_conf": {
        "ja": "指定したディストリビューションの /etc/wsl.conf を参照します",
        "en": "View /etc/wsl.conf of specified distribution",
    },
    "cli.arg.version_choice": {
        "ja": "変換先の WSL バージョン (1 または 2)",
        "en": "Target WSL version (1 or 2)",
    },
    "cli.arg.optimize_sparse": {
        "ja": "仮想ディスクのスパース化を有効にします",
        "en": "Enable sparse mode for virtual disk",
    },
    "cli.arg.optimize_compact": {
        "ja": "仮想ディスクを圧縮します",
        "en": "Compact virtual disk",
    },
    "cli.arg.log_tail": {
        "ja": "表示する末尾のエントリ数 (既定: 50)",
        "en": "Number of recent log entries to show (default: 50)",
    },
    "cli.arg.log_clear": {"ja": "操作ログをすべて消去します", "en": "Clear all operation logs"},
    "cli.arg.portproxy_listen_port": {
        "ja": "リッスンするポート番号",
        "en": "Port number to listen on",
    },
    "cli.arg.portproxy_connect_port": {
        "ja": "接続先のポート番号",
        "en": "Port number to connect to",
    },
    "cli.arg.portproxy_connect_address": {
        "ja": "接続先の IP アドレス",
        "en": "IP address to connect to",
    },
    "cli.arg.portproxy_listen_address": {
        "ja": "リッスンする IP アドレス (既定: 0.0.0.0)",
        "en": "IP address to listen on (default: 0.0.0.0)",
    },
    "cli.arg.snapshot_comment": {
        "ja": "スナップショットのコメント (任意)",
        "en": "Snapshot comment (optional)",
    },
    "cli.arg.snapshot_keep": {
        "ja": "作成後にディストリビューションごとに保持する世代数",
        "en": "Number of generations to retain per distribution",
    },
    "cli.arg.snapshot_dir": {
        "ja": "スナップショット保存先ディレクトリ (既定: 設定値)",
        "en": "Snapshot storage directory (default: setting)",
    },
    "cli.arg.snapshot_tar_file": {
        "ja": "復元または削除するスナップショットの tar ファイル名",
        "en": "Snapshot tar filename to restore or delete",
    },
    "cli.arg.snapshot_restore_name": {
        "ja": "復元先のディストリビューション名 (既定: 自動生成)",
        "en": "Restore target distribution name (default: auto)",
    },
    "cli.arg.clone_new_name": {
        "ja": "複製先の新しいディストリビューション名",
        "en": "New distribution name for clone",
    },
    "cli.arg.mount_disk": {
        "ja": "マウントするディスク（物理ドライブパスまたは VHDX ファイルパス）",
        "en": "Disk to mount (physical drive or VHDX path)",
    },
    "cli.arg.mount_bare": {
        "ja": "ディスクを WSL にアタッチするのみでファイルシステムのマウントを行いません",
        "en": "Attach disk to WSL without mounting filesystem",
    },
    "cli.arg.mount_vhd": {
        "ja": "指定したディスクが VHD/VHDX であることを明示します",
        "en": "Specify disk is VHD/VHDX",
    },
    "cli.arg.mount_type": {
        "ja": "ファイルシステムの種類 (例: ext4)",
        "en": "Filesystem type (e.g. ext4)",
    },
    "cli.arg.mount_partition": {
        "ja": "マウントするパーティション番号",
        "en": "Partition number to mount",
    },
    "cli.arg.mount_name": {"ja": "カスタムマウント名", "en": "Custom mount name"},
    "cli.arg.unmount_disk": {
        "ja": "アンマウントするディスクパス（省略時は全マウントディスク）",
        "en": "Disk path to unmount (all if omitted)",
    },
    # ── CLI 実行メッセージ ──
    "cli.cancelled": {"ja": "中止しました。", "en": "Cancelled."},
    "cli.need_yes": {
        "ja": "エラー: 非対話環境で実行するには --yes を指定してください。",
        "en": "Error: Specify --yes to run in non-interactive environment.",
    },
    "cli.start_failed": {
        "ja": "エラー: 「{name}」の起動に失敗しました: {msg}",
        "en": "Error: Failed to start '{name}': {msg}",
    },
    "cli.stop_failed": {
        "ja": "エラー: 「{name}」の停止に失敗しました: {msg}",
        "en": "Error: Failed to stop '{name}': {msg}",
    },
    "cli.shutdown_failed": {
        "ja": "エラー: WSL の全停止に失敗しました: {msg}",
        "en": "Error: Failed to shut down all distributions: {msg}",
    },
    "cli.export_progress": {
        "ja": "「{name}」を「{path}」にエクスポート中…",
        "en": "Exporting '{name}' to '{path}'...",
    },
    "cli.export_failed": {
        "ja": "エラー: 「{name}」のエクスポートに失敗しました: {msg}",
        "en": "Error: Failed to export '{name}': {msg}",
    },
    "cli.import_progress": {
        "ja": "「{name}」を「{install_path}」にインポート中…",
        "en": "Importing '{name}' to '{install_path}'...",
    },
    "cli.import_failed": {
        "ja": "エラー: 「{name}」のインポートに失敗しました: {msg}",
        "en": "Error: Failed to import '{name}': {msg}",
    },
    "cli.set_default_failed": {
        "ja": "エラー: 「{name}」のデフォルト設定に失敗しました: {msg}",
        "en": "Error: Failed to set '{name}' as default: {msg}",
    },
    "cli.unregister_failed": {
        "ja": "エラー: 「{name}」のアンインストールに失敗しました: {msg}",
        "en": "Error: Failed to unregister '{name}': {msg}",
    },
    "cli.install_progress": {
        "ja": "「{name}」をインストール中…",
        "en": "Installing '{name}'...",
    },
    "cli.install_failed": {
        "ja": "エラー: 「{name}」のインストールに失敗しました: {msg}",
        "en": "Error: Failed to install '{name}': {msg}",
    },
    "cli.convert_failed": {
        "ja": "エラー: 「{name}」の変換に失敗しました: {msg}",
        "en": "Error: Failed to convert '{name}': {msg}",
    },
    "gui.process.kill_success": {
        "ja": "PID {pid} にシグナルを送信しました。",
        "en": "Sent signal to PID {pid}.",
    },
    "cli.arg.status_strict": {
        "ja": "全ディストリで情報取得失敗時にエラー終了します",
        "en": "Exit with an error if information cannot be retrieved for any distribution",
    },
    "cli.portproxy.list": {
        "ja": "ポートフォワーディングルールの一覧を表示します",
        "en": "List port forwarding rules",
    },
    "cli.portproxy.add": {
        "ja": "ポートフォワーディングルールを追加します",
        "en": "Add a port forwarding rule",
    },
    "cli.portproxy.delete": {
        "ja": "ポートフォワーディングルールを削除します",
        "en": "Delete a port forwarding rule",
    },
    "cli.snapshot.create": {
        "ja": "ディストリビューションのスナップショットを作成します",
        "en": "Create a distribution snapshot",
    },
    "cli.snapshot.list": {"ja": "スナップショットの一覧を表示します", "en": "List snapshots"},
    "cli.snapshot.restore": {
        "ja": "スナップショットを新しいディストリビューションとして復元します",
        "en": "Restore a snapshot as a new distribution",
    },
    "cli.snapshot.delete": {"ja": "スナップショットを削除します", "en": "Delete a snapshot"},
    "cli.snapshot.prune": {
        "ja": "保持数を超えたスナップショットを確認・削除します",
        "en": "Review and delete snapshots exceeding the retention count",
    },
    "cli.snapshot.schedule": {
        "ja": "Windows Task Scheduler に定期スナップショットを登録します",
        "en": "Manage scheduled snapshots in Windows Task Scheduler",
    },
    "cli.snapshot.schedule_create": {
        "ja": "毎日の定期スナップショットを登録します",
        "en": "Create a daily scheduled snapshot",
    },
    "cli.snapshot.schedule_list": {
        "ja": "登録済みの定期スナップショットを表示します",
        "en": "List scheduled snapshots",
    },
    "cli.snapshot.schedule_delete": {
        "ja": "定期スナップショットを削除します",
        "en": "Delete a scheduled snapshot",
    },
    "cli.snapshot.set_dir": {
        "ja": "スナップショットの保存先ディレクトリを設定します",
        "en": "Set the snapshot storage directory",
    },
    "cli.arg.schedule_time": {
        "ja": "実行時刻 HH:MM (既定: 03:00)",
        "en": "Run time in HH:MM format (default: 03:00)",
    },
    "cli.arg.schedule_keep": {
        "ja": "保持する世代数 (既定: 7)",
        "en": "Number of generations to retain (default: 7)",
    },
}


def normalize_language(value: object) -> str:
    """Return a supported stored language value, falling back to ``auto``."""
    if isinstance(value, str) and value in (LANGUAGE_AUTO, *SUPPORTED_LANGUAGES):
        return value
    return LANGUAGE_AUTO


def detect_system_language(locale_name: str | None = None) -> str:
    """Detect Japanese systems; use English as the safe fallback for all others."""
    if locale_name is None:
        try:
            locale_name = locale.getlocale()[0]
        except (ValueError, locale.Error):
            locale_name = None
        locale_name = locale_name or os.environ.get("LANG") or os.environ.get("LC_ALL")
    return "ja" if locale_name and locale_name.lower().startswith("ja") else "en"


def resolve_language(preference: object, locale_name: str | None = None) -> str:
    """Resolve an explicit preference or the current system language."""
    preference = normalize_language(preference)
    return detect_system_language(locale_name) if preference == LANGUAGE_AUTO else preference


def translate(key: str, language: object = LANGUAGE_AUTO, **values: object) -> str:
    """Translate ``key`` and interpolate named values; return the key if unknown."""
    message = _MESSAGES.get(key, {}).get(resolve_language(language), key)
    return message.format(**values)
