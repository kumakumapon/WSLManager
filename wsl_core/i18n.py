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
    # ── 言語名 ──
    "language.system": {"ja": "システム設定", "en": "System default"},
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
    "gui.common.filter": {"ja": "🔍 フィルタ:", "en": "🔍 Filter:"},
    "gui.common.filter_clear": {"ja": "✕", "en": "✕"},
    "gui.common.refresh": {"ja": "🔄  更新", "en": "🔄  Refresh"},
    "gui.common.name": {"ja": "名前:", "en": "Name:"},
    "gui.common.success": {"ja": "成功", "en": "Success"},
    # ── メインメニュー ──
    "gui.menu.file": {"ja": "ファイル", "en": "File"},
    "gui.menu.distribution": {"ja": "ディストリビューション", "en": "Distribution"},
    "gui.menu.tools": {"ja": "ツール", "en": "Tools"},
    "gui.menu.help": {"ja": "ヘルプ", "en": "Help"},
    "gui.menu.language": {"ja": "言語", "en": "Language"},
    # ── アクション ──
    "gui.action.import": {"ja": "インポート...", "en": "Import..."},
    "gui.action.export": {"ja": "エクスポート...", "en": "Export..."},
    "gui.action.exit": {"ja": "終了", "en": "Exit"},
    "gui.action.start_terminal": {"ja": "起動 / ターミナル", "en": "Start / Terminal"},
    "gui.action.stop": {"ja": "停止", "en": "Stop"},
    "gui.action.shutdown": {"ja": "全停止", "en": "Shut down all"},
    "gui.action.set_default": {"ja": "デフォルトに設定", "en": "Set as default"},
    "gui.action.convert": {"ja": "WSL1/WSL2 変換", "en": "Convert WSL1/WSL2"},
    "gui.action.install": {"ja": "インストール...", "en": "Install..."},
    "gui.action.unregister": {"ja": "アンインストール...", "en": "Unregister..."},
    "gui.action.details": {"ja": "詳細情報...", "en": "Details..."},
    "gui.action.processes": {"ja": "プロセス一覧", "en": "Processes"},
    "gui.action.explorer": {"ja": "エクスプローラーで開く", "en": "Open in Explorer"},
    "gui.action.optimize": {"ja": "ディスク最適化...", "en": "Optimize disk..."},
    "gui.action.snapshots": {"ja": "スナップショット管理...", "en": "Manage snapshots..."},
    "gui.action.mount": {"ja": "ディスクのマウント...", "en": "Mount disk..."},
    "gui.action.unmount": {"ja": "ディスクのアンマウント...", "en": "Unmount disk..."},
    "gui.action.wsl_config": {"ja": "WSL 設定 (.wslconfig)", "en": "WSL settings (.wslconfig)"},
    "gui.action.distro_conf": {
        "ja": "ディストリビューション設定 (wsl.conf)...",
        "en": "Distribution settings (wsl.conf)...",
    },
    "gui.action.clone": {"ja": "クローン (複製)...", "en": "Clone..."},
    "gui.action.log": {"ja": "操作ログ...", "en": "Operation log..."},
    "gui.action.theme": {"ja": "テーマ", "en": "Theme"},
    "gui.action.wsl_version": {"ja": "WSL バージョン情報...", "en": "WSL version..."},
    "gui.action.update_wsl": {"ja": "WSL を更新", "en": "Update WSL"},
    "gui.action.about": {"ja": "このアプリについて...", "en": "About..."},
    # ── ツールバー ──
    "gui.toolbar.start": {"ja": "▶  起動", "en": "▶  Start"},
    "gui.toolbar.stop": {"ja": "■  停止", "en": "■  Stop"},
    "gui.toolbar.shutdown": {"ja": "⬛  全停止", "en": "⬛  Shut down"},
    "gui.toolbar.terminal": {"ja": "🖥  ターミナル", "en": "🖥  Terminal"},
    "gui.toolbar.processes": {"ja": "📋  プロセス", "en": "📋  Processes"},
    "gui.toolbar.refresh": {"ja": "🔄  更新", "en": "🔄  Refresh"},
    "gui.toolbar.install": {"ja": "📦  インストール", "en": "📦  Install"},
    "gui.toolbar.import": {"ja": "📥  インポート", "en": "📥  Import"},
    "gui.toolbar.export": {"ja": "📤  エクスポート", "en": "📤  Export"},
    "gui.toolbar.wsl_config": {"ja": "⚙  WSL設定", "en": "⚙  WSL settings"},
    "gui.auto_refresh": {"ja": "自動更新", "en": "Auto refresh"},
    "gui.history.show": {"ja": "📈 履歴を表示", "en": "📈 Show history"},
    "gui.history.hide": {"ja": "📈 履歴を隠す", "en": "📈 Hide history"},
    # ── リソース履歴パネル ──
    "gui.history.title": {
        "ja": "リソース履歴（直近30分）",
        "en": "Resource history (last 30 min)",
    },
    "gui.history.cpu": {"ja": "CPU 使用率", "en": "CPU usage"},
    "gui.history.memory": {"ja": "メモリ使用量", "en": "Memory usage"},
    # ── テーブル列ヘッダー ──
    "gui.column.name": {"ja": "ディストリビューション名", "en": "Distribution"},
    "gui.column.state": {"ja": "状態", "en": "State"},
    "gui.column.version": {"ja": "バージョン", "en": "Version"},
    "gui.column.cpu": {"ja": "CPU(%)", "en": "CPU(%)"},
    "gui.column.memory": {"ja": "メモリ(MB)", "en": "Memory (MB)"},
    "gui.column.disk": {"ja": "ディスク(GB)", "en": "Disk (GB)"},
    "gui.column.ip": {"ja": "IPアドレス", "en": "IP address"},
    # ── 状態 ──
    "gui.state.running": {"ja": "実行中", "en": "Running"},
    "gui.state.stopped": {"ja": "停止中", "en": "Stopped"},
    # ── ステータス・メッセージ ──
    "gui.status.ready": {"ja": "準備完了", "en": "Ready"},
    "gui.status.refreshing": {
        "ja": "ディストリビューション情報を更新中...",
        "en": "Refreshing distribution list...",
    },
    "gui.status.refreshed": {
        "ja": "ディストリビューション情報を更新しました。",
        "en": "Distribution list refreshed.",
    },
    "gui.status.refresh_failed": {
        "ja": "ディストリビューション情報の更新に失敗しました。",
        "en": "Failed to refresh distribution list.",
    },
    "gui.status.theme_changed": {
        "ja": "テーマを「{theme}」に変更しました。",
        "en": "Theme changed to '{theme}'.",
    },
    "gui.status.theme_failed": {
        "ja": "テーマ「{theme}」の適用に失敗しました。",
        "en": "Failed to apply theme '{theme}'.",
    },
    "gui.language_changed": {
        "ja": "言語設定を保存しました。変更は次回の起動時に反映されます。",
        "en": "Language preference saved. It will be applied next time the app starts.",
    },
    # ── 確認ダイアログ・メッセージ ──
    "gui.confirm.stop": {
        "ja": "「{name}」を停止しますか？\n（未保存の作業内容は失われる可能性があります）",
        "en": "Stop '{name}'?\n(Unsaved work may be lost)",
    },
    "gui.confirm.shutdown": {
        "ja": "実行中のすべての WSL2 ディストリビューションを停止しますか？\n"
        "（未保存の作業内容は失われる可能性があります）",
        "en": "Shut down all running WSL2 distributions?\n(Unsaved work may be lost)",
    },
    "gui.confirm.unregister": {
        "ja": "ディストリビューション「{name}」をアンインストール（登録解除）しますか？\n\n"
        "警告: ディストリビューション内のすべてのデータが完全に削除されます。\n"
        "この操作は取り消せません。",
        "en": "Unregister distribution '{name}'?\n\n"
        "WARNING: All data in this distribution will be permanently deleted.\n"
        "This operation cannot be undone.",
    },
    "gui.confirm.convert": {
        "ja": "ディストリビューション「{name}」を WSL{target} に変換しますか？\n"
        "（変換には数分かかる場合があります）",
        "en": "Convert distribution '{name}' to WSL{target}?\n"
        "(This conversion may take several minutes)",
    },
    "gui.msg.select_distro": {
        "ja": "ディストリビューションを選択してください。",
        "en": "Please select a distribution.",
    },
    "gui.msg.already_version": {
        "ja": "「{name}」は既に WSL{version} です。",
        "en": "'{name}' is already WSL{version}.",
    },
    "gui.msg.start_failed": {
        "ja": "「{name}」の起動に失敗しました:\n{error}",
        "en": "Failed to start '{name}':\n{error}",
    },
    "gui.msg.stop_failed": {
        "ja": "「{name}」の停止に失敗しました:\n{error}",
        "en": "Failed to stop '{name}':\n{error}",
    },
    "gui.msg.shutdown_failed": {
        "ja": "WSL の全停止に失敗しました:\n{error}",
        "en": "Failed to shut down all distributions:\n{error}",
    },
    "gui.msg.set_default_success": {
        "ja": "「{name}」をデフォルトのディストリビューションに設定しました。",
        "en": "Set '{name}' as the default distribution.",
    },
    "gui.msg.set_default_failed": {
        "ja": "デフォルト設定に失敗しました:\n{error}",
        "en": "Failed to set default:\n{error}",
    },
    "gui.msg.convert_success": {
        "ja": "「{name}」を WSL{version} に変換しました。",
        "en": "Converted '{name}' to WSL{version}.",
    },
    "gui.msg.convert_failed": {
        "ja": "変換に失敗しました:\n{error}",
        "en": "Conversion failed:\n{error}",
    },
    "gui.msg.unregister_success": {
        "ja": "「{name}」をアンインストールしました。",
        "en": "Unregistered '{name}'.",
    },
    "gui.msg.unregister_failed": {
        "ja": "アンインストールに失敗しました:\n{error}",
        "en": "Failed to unregister:\n{error}",
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
    "gui.optimize.btn_compact": {"ja": "今すぐ圧縮する", "en": "Compact Now"},
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
    "gui.context.terminal": {"ja": "🖥 ターミナルを開く", "en": "🖥 Open Terminal"},
    "gui.context.details": {"ja": "ℹ  詳細情報", "en": "ℹ  Details"},
    "gui.context.processes": {"ja": "📋 プロセス一覧", "en": "📋 Process List"},
    "gui.context.explorer": {"ja": "📂 エクスプローラーで開く", "en": "📂 Open in Explorer"},
    "gui.context.copy_ip": {"ja": "📋 IPアドレスをコピー", "en": "📋 Copy IP Address"},
    "gui.context.stop": {"ja": "■ 停止", "en": "■ Stop"},
    "gui.context.set_default": {"ja": "★ デフォルトに設定", "en": "★ Set as Default"},
    "gui.context.convert": {"ja": "🔁 WSL1/WSL2 に変換", "en": "🔁 Convert WSL1/WSL2"},
    "gui.context.optimize": {"ja": "🗜 ディスク最適化", "en": "🗜 Disk Optimization"},
    "gui.context.distro_conf": {
        "ja": "⚙ ディストロ設定 (wsl.conf)",
        "en": "⚙ Distro Settings (wsl.conf)",
    },
    "gui.context.clone": {"ja": "📑 複製", "en": "📑 Clone"},
    "gui.context.snapshot": {"ja": "📸 スナップショットを作成", "en": "📸 Create Snapshot"},
    "gui.context.export": {"ja": "📤 エクスポート", "en": "📤 Export"},
    "gui.context.unregister": {"ja": "🗑 アンインストール", "en": "🗑 Unregister"},
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
