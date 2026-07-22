"""
wslmgr_cli - WSL Manager のコマンドラインインターフェース

GUI (wslmgr.py) を使わずに、コマンドラインから WSL2 ディストリビューションの
一覧表示・起動・停止・エクスポート/インポート・設定確認などを行うためのツールです。
標準ライブラリのみに依存し、テキスト解析には wsl_core.py の純粋関数を再利用します。
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime

import wsl_core

# ── Windows 専用フラグ ──────────────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


# ---------------------------------------------------------------------------
# subprocess ヘルパー
# ---------------------------------------------------------------------------

def _run_wsl_command(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """WSL コマンドを実行して (returncode, stdout, stderr) を返します。

    Windows では CREATE_NO_WINDOW フラグを使ってコンソールウィンドウの表示を抑制します。
    出力は wsl_core.decode_wsl_output() でデコードします。
    タイムアウトや OSError が発生した場合は returncode=-1 とし、
    stderr にエラーメッセージを設定します。
    """
    try:
        result = subprocess.run(
            ["wsl"] + args,
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, "", "タイムアウトしました。"
    except OSError as e:
        return -1, "", str(e)

    stdout = wsl_core.decode_wsl_output(result.stdout)
    stderr = wsl_core.decode_wsl_output(result.stderr)
    return result.returncode, stdout, stderr


def _run_netsh_portproxy(args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    """``netsh interface portproxy`` コマンドを実行して (returncode, stdout, stderr) を返します。

    netsh の出力は UTF-16 ではないため wsl_core.decode_wsl_output は使わず、
    ``text=True`` でそのままテキストとして受け取ります。
    タイムアウトや OSError が発生した場合は returncode=-1 とし、
    stderr にエラーメッセージを設定します（_run_wsl_command と同形式）。
    """
    try:
        result = subprocess.run(
            ["netsh", "interface", "portproxy"] + args,
            capture_output=True,
            text=True,
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return -1, "", "タイムアウトしました。"
    except OSError as e:
        return -1, "", str(e)

    return result.returncode, result.stdout, result.stderr


# ---------------------------------------------------------------------------
# フォーマットヘルパー
# ---------------------------------------------------------------------------

def _format_table(headers: list[str], rows: list[list[str]], min_width: int = 8) -> str:
    """データを整列されたテキストテーブルとしてフォーマットします。

    各列幅は max(ヘッダ長, データ最大長, min_width) です。
    行がない場合はヘッダのみのテーブルを返します。
    """
    str_headers = [str(h) for h in headers]
    str_rows = [[str(cell) for cell in row] for row in rows]

    widths: list[int] = []
    for col_idx, header in enumerate(str_headers):
        col_values = [row[col_idx] for row in str_rows if col_idx < len(row)]
        max_data_len = max((len(v) for v in col_values), default=0)
        widths.append(max(len(header), max_data_len, min_width))

    lines: list[str] = []
    header_line = "  ".join(h.ljust(w) for h, w in zip(str_headers, widths))
    lines.append(header_line)
    lines.append("  ".join("-" * w for w in widths))
    for row in str_rows:
        line = "  ".join(
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(widths))
        )
        lines.append(line)

    return "\n".join(lines)


def _format_csv(headers: list[str], rows: list[list[str]]) -> str:
    """データを csv モジュールを使って CSV テキストとしてフォーマットします。"""
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue().rstrip("\n")


# ---------------------------------------------------------------------------
# list サブコマンド
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> None:
    """``wsl --list --verbose`` の結果を表示します。"""
    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    distros = wsl_core.parse_distro_list(stdout)

    if args.format == "json":
        print(json.dumps(distros, ensure_ascii=False, indent=2))
        return

    headers = ["Name", "State", "Version", "Default"]
    rows = [
        [d["name"], d["state"], d["version"], "*" if d["default"] else ""]
        for d in distros
    ]

    if args.format == "csv":
        print(_format_csv(headers, rows))
    else:
        print(_format_table(headers, rows))


# ---------------------------------------------------------------------------
# start サブコマンド
# ---------------------------------------------------------------------------

def cmd_start(args: argparse.Namespace) -> None:
    """指定したディストリビューションを起動します。"""
    name = args.name
    returncode, _stdout, stderr = _run_wsl_command(
        ["-d", name, "--", "echo", "started"], timeout=30.0
    )
    if returncode == 0:
        print(f"「{name}」を起動しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」の起動に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# stop サブコマンド
# ---------------------------------------------------------------------------

def cmd_stop(args: argparse.Namespace) -> None:
    """指定したディストリビューションを停止します。"""
    name = args.name
    returncode, _stdout, stderr = _run_wsl_command(["--terminate", name], timeout=30.0)
    if returncode == 0:
        print(f"「{name}」を停止しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」の停止に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# shutdown サブコマンド
# ---------------------------------------------------------------------------

def cmd_shutdown(args: argparse.Namespace) -> None:
    """すべてのディストリビューションを停止します。"""
    returncode, _stdout, stderr = _run_wsl_command(["--shutdown"], timeout=30.0)
    if returncode == 0:
        print("WSL を全停止しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: WSL の全停止に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# status サブコマンド
# ---------------------------------------------------------------------------

_RESOURCE_USAGE_CMD = (
    "ps -eo pcpu,rss --no-headers | "
    "awk '{cpu+=$1; mem+=$2} END {printf \"%.1f %.1f\", cpu, mem/1024}'"
)


def cmd_status(args: argparse.Namespace) -> None:
    """実行中ディストリビューションのリソース使用状況を表示します。"""
    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    distros = wsl_core.parse_distro_list(stdout)
    running = [d for d in distros if d["state"] == "Running"]

    results: list[dict] = []
    for d in running:
        rc, out, _err = _run_wsl_command(
            ["-d", d["name"], "--", "sh", "-lc", _RESOURCE_USAGE_CMD], timeout=10.0
        )
        if rc == 0:
            cpu, memory = wsl_core.parse_resource_usage(out.strip())
        else:
            cpu, memory = "-", "-"
        results.append({"name": d["name"], "cpu": cpu, "memory": memory})

    if args.format == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    headers = ["Name", "CPU(%)", "Memory(MB)"]
    rows = [[r["name"], r["cpu"], r["memory"]] for r in results]
    print(_format_table(headers, rows))


# ---------------------------------------------------------------------------
# export サブコマンド
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> None:
    """指定したディストリビューションをエクスポートします。"""
    name = args.name
    path = args.path
    print(f"「{name}」を「{path}」にエクスポート中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--export", name, path], timeout=600.0
    )
    if returncode == 0:
        print(f"「{name}」のエクスポートが完了しました: {path}")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のエクスポートに失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# import サブコマンド
# ---------------------------------------------------------------------------

def cmd_import(args: argparse.Namespace) -> None:
    """ディストリビューションをインポートします。"""
    name = args.name
    install_path = args.install_path
    image_path = args.image_path

    valid, reason = wsl_core.validate_distro_name(name)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(1)

    print(f"「{name}」を「{install_path}」にインポート中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--import", name, install_path, image_path], timeout=600.0
    )
    if returncode == 0:
        print(f"「{name}」のインポートが完了しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のインポートに失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# config サブコマンド
# ---------------------------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> None:
    """現在の .wslconfig 設定を表示します。"""
    path = os.path.expanduser("~/.wslconfig")
    if not os.path.exists(path):
        print(f"エラー: {path} が見つかりません。", file=sys.stderr)
        sys.exit(1)

    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"エラー: .wslconfig の読み込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    try:
        sections = wsl_core.parse_wslconfig(text)
    except wsl_core.WslConfigParseError as e:
        print(f"エラー: .wslconfig のパースに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    if args.format == "json":
        print(json.dumps(sections, ensure_ascii=False, indent=2))
        return

    if not sections:
        print("設定項目がありません。")
        return

    for section_name, items in sections.items():
        print(f"[{section_name}]")
        for key, value in items.items():
            print(f"  {key} = {value}")


# ---------------------------------------------------------------------------
# 破壊的操作・レジストリ参照ヘルパー
# ---------------------------------------------------------------------------

def _confirm_or_exit(prompt: str, assume_yes: bool) -> None:
    """破壊的操作の実行前に確認を行います。

    assume_yes が True の場合は確認せずに即座に戻ります。
    非対話環境 (標準入力が TTY でない) の場合は、確認できないため
    ``--yes`` の指定を促すメッセージを表示して終了します。
    TTY の場合は ``[y/N]`` 形式で入力を求め、``y`` / ``yes`` (大小文字不問)
    以外が入力された場合は操作を中止して終了します。
    """
    if assume_yes:
        return
    if not sys.stdin.isatty():
        print("エラー: 非対話環境で実行するには --yes を指定してください。", file=sys.stderr)
        sys.exit(1)
    try:
        answer = input(f"{prompt} [y/N]: ")
    except EOFError:
        # Ctrl-D などで入力が閉じられた場合は「いいえ」として扱う
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("中止しました。")
        sys.exit(1)


def _get_distro_vhdx_path(name: str) -> str | None:
    """指定ディストリビューションの仮想ディスク (ext4.vhdx) の絶対パスを返します。

    ``HKEY_CURRENT_USER\\Software\\Microsoft\\Windows\\CurrentVersion\\Lxss`` 配下を
    走査し、``DistributionName`` が一致するサブキーの ``BasePath`` を
    wsl_core.normalize_base_path で正規化した上でファイルの存在を確認します。
    winreg が利用できない環境 (Windows 以外) やレジストリアクセスに失敗した場合、
    または一致するディストロが見つからない・vhdx が存在しない場合は None を返します。
    """
    try:
        import winreg
    except ImportError:
        return None

    try:
        lxss = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Lxss",
        )
    except OSError:
        return None

    with lxss:
        index = 0
        while True:
            try:
                subkey_name = winreg.EnumKey(lxss, index)
            except OSError:
                break
            index += 1
            try:
                with winreg.OpenKey(lxss, subkey_name) as sub:
                    dname, _ = winreg.QueryValueEx(sub, "DistributionName")
                    base_path, _ = winreg.QueryValueEx(sub, "BasePath")
            except OSError:
                continue
            if str(dname) != name:
                continue
            normalized = wsl_core.normalize_base_path(str(base_path))
            vhdx_path = os.path.join(normalized, "ext4.vhdx")
            return vhdx_path if os.path.exists(vhdx_path) else None

    return None


# ---------------------------------------------------------------------------
# set-default サブコマンド
# ---------------------------------------------------------------------------

def cmd_set_default(args: argparse.Namespace) -> None:
    """指定したディストリビューションを既定 (デフォルト) に設定します。"""
    name = args.name
    returncode, _stdout, stderr = _run_wsl_command(["--set-default", name], timeout=30.0)
    if returncode == 0:
        print(f"「{name}」をデフォルトに設定しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のデフォルト設定に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# unregister サブコマンド
# ---------------------------------------------------------------------------

def cmd_unregister(args: argparse.Namespace) -> None:
    """指定したディストリビューションをアンインストール (登録解除) します。"""
    name = args.name
    _confirm_or_exit(
        f"「{name}」を完全に削除（アンインストール）します。この操作は取り消せません。続行しますか?",
        args.yes,
    )
    returncode, _stdout, stderr = _run_wsl_command(["--unregister", name], timeout=120.0)
    if returncode == 0:
        print(f"「{name}」をアンインストールしました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のアンインストールに失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# install サブコマンド
# ---------------------------------------------------------------------------

def cmd_install(args: argparse.Namespace) -> None:
    """指定したディストリビューションをインストールします。"""
    name = args.name
    print(f"「{name}」をインストール中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--install", "-d", name, "--no-launch"], timeout=1800.0
    )
    if returncode == 0:
        print(f"「{name}」のインストールが完了しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のインストールに失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# optimize サブコマンド
# ---------------------------------------------------------------------------

def cmd_optimize(args: argparse.Namespace) -> None:
    """指定したディストリビューションの仮想ディスクを最適化します（スパース化 / 圧縮）。"""
    name = args.name

    # 圧縮・スパース化のどちらでも、まず対象ディストロを終了しておく (失敗は無視する)
    _run_wsl_command(["--terminate", name], timeout=30.0)

    if args.sparse:
        returncode, _stdout, stderr = _run_wsl_command(
            ["--manage", name, "--set-sparse", "true"], timeout=120.0
        )
        if returncode == 0:
            print(f"「{name}」のスパース化を有効にしました。")
        else:
            msg = stderr.strip() or "不明なエラー"
            print(f"エラー: 「{name}」のスパース化に失敗しました: {msg}", file=sys.stderr)
            sys.exit(1)
        return

    # --compact
    vhdx_path = _get_distro_vhdx_path(name)
    if vhdx_path is None:
        print(f"エラー: 「{name}」の仮想ディスク (ext4.vhdx) が見つかりません。", file=sys.stderr)
        sys.exit(1)

    print("管理者権限が必要な場合があります。")

    script_text = wsl_core.build_diskpart_compact_script(vhdx_path)
    script_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".txt", delete=False, encoding="ascii", errors="replace"
        ) as f:
            f.write(script_text)
            script_path = f.name

        result = subprocess.run(
            ["diskpart", "/s", script_path],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=600.0,
        )
    except subprocess.TimeoutExpired:
        print(f"エラー: 「{name}」の仮想ディスクの圧縮がタイムアウトしました。", file=sys.stderr)
        sys.exit(1)
    except OSError as e:
        print(f"エラー: 「{name}」の仮想ディスクの圧縮に失敗しました: {e}", file=sys.stderr)
        sys.exit(1)
    finally:
        if script_path is not None:
            try:
                os.remove(script_path)
            except OSError:
                pass

    if result.returncode == 0:
        print(f"「{name}」の仮想ディスクを圧縮しました。")
    else:
        print(f"エラー: 「{name}」の仮想ディスクの圧縮に失敗しました。", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# set-version サブコマンド
# ---------------------------------------------------------------------------

def cmd_set_version(args: argparse.Namespace) -> None:
    """指定したディストリビューションを WSL1 / WSL2 間で変換します。"""
    name = args.name
    version = args.version
    _confirm_or_exit(
        f"「{name}」を WSL{version} に変換します。変換には時間がかかることがあります。続行しますか?",
        args.yes,
    )
    returncode, _stdout, stderr = _run_wsl_command(
        ["--set-version", name, version], timeout=1800.0
    )
    if returncode == 0:
        print(f"「{name}」を WSL{version} に変換しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」の変換に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


# ---------------------------------------------------------------------------
# processes サブコマンド
# ---------------------------------------------------------------------------

_PROCESS_LIST_CMD = (
    "ps -eo pid,user,pcpu,rss,comm --sort=-pcpu 2>/dev/null || "
    "ps -eo pid,user,pcpu,rss,comm"
)


def cmd_processes(args: argparse.Namespace) -> None:
    """指定したディストリビューション内で実行中のプロセス一覧を表示します。"""
    name = args.name
    returncode, stdout, stderr = _run_wsl_command(
        ["-d", name, "--", "sh", "-lc", _PROCESS_LIST_CMD], timeout=15.0
    )
    if returncode != 0:
        msg = stderr.strip() or "プロセス一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    processes = wsl_core.parse_process_list(stdout)

    if args.format == "json":
        print(json.dumps(processes, ensure_ascii=False, indent=2))
        return

    headers = ["PID", "User", "CPU(%)", "Memory(MB)", "Command"]
    rows = [[p["pid"], p["user"], p["cpu"], p["memory"], p["command"]] for p in processes]

    if args.format == "csv":
        print(_format_csv(headers, rows))
    else:
        print(_format_table(headers, rows))


# ---------------------------------------------------------------------------
# log サブコマンド
# ---------------------------------------------------------------------------

def cmd_log(args: argparse.Namespace) -> None:
    """保存されている操作ログを表示します。"""
    log_path = os.path.join(wsl_core.get_default_log_dir(), "operations.jsonl")
    if not os.path.exists(log_path):
        print("操作ログはまだありません。")
        return

    try:
        with open(log_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"エラー: 操作ログの読み込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(1)

    entries = wsl_core.deserialize_log_entries(text)
    entries = wsl_core.tail_entries(entries, args.tail)

    if args.format == "json":
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return

    for entry in entries:
        print(wsl_core.format_log_entry_from_dict(entry))


# ---------------------------------------------------------------------------
# portproxy サブコマンド
# ---------------------------------------------------------------------------

def cmd_portproxy_list(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールの一覧を表示します。"""
    returncode, stdout, stderr = _run_netsh_portproxy(["show", "all"])
    if returncode != 0:
        msg = stderr.strip() or "ポートフォワーディング一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    rules = wsl_core.parse_portproxy_output(stdout)

    if args.format == "json":
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return

    headers = ["ListenAddress", "ListenPort", "ConnectAddress", "ConnectPort"]
    rows = [
        [r["listen_address"], r["listen_port"], r["connect_address"], r["connect_port"]]
        for r in rules
    ]

    if args.format == "csv":
        print(_format_csv(headers, rows))
    else:
        print(_format_table(headers, rows))


def cmd_portproxy_add(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールを追加します。"""
    valid, reason = wsl_core.validate_port_number(args.listen_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(1)
    valid, reason = wsl_core.validate_port_number(args.connect_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(1)

    listen_port = args.listen_port
    connect_port = args.connect_port
    listen_address = args.listen_address
    connect_address = args.connect_address

    returncode, _stdout, stderr = _run_netsh_portproxy(
        [
            "add", "v4tov4",
            f"listenport={listen_port}",
            f"listenaddress={listen_address}",
            f"connectport={connect_port}",
            f"connectaddress={connect_address}",
        ]
    )
    if returncode == 0:
        print(
            f"ポートフォワーディングを追加しました: "
            f"{listen_address}:{listen_port} -> {connect_address}:{connect_port}"
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        print(
            f"エラー: ポートフォワーディングの追加に失敗しました: {msg}"
            "（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(1)


def cmd_portproxy_delete(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールを削除します。"""
    valid, reason = wsl_core.validate_port_number(args.listen_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(1)

    listen_port = args.listen_port
    listen_address = args.listen_address

    returncode, _stdout, stderr = _run_netsh_portproxy(
        ["delete", "v4tov4", f"listenport={listen_port}", f"listenaddress={listen_address}"]
    )
    if returncode == 0:
        print(f"ポートフォワーディングを削除しました: {listen_address}:{listen_port}")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(
            f"エラー: ポートフォワーディングの削除に失敗しました: {msg}"
            "（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(1)


def _make_portproxy_help_func(parser: argparse.ArgumentParser):
    """``wslmgr portproxy`` (サブサブコマンドなし) 実行時にヘルプを表示する関数を返します。"""
    def _cmd_portproxy_help(_args: argparse.Namespace) -> None:
        parser.print_help()
        sys.exit(0)
    return _cmd_portproxy_help


# ---------------------------------------------------------------------------
# snapshot サブコマンド
# ---------------------------------------------------------------------------

def _resolve_snapshot_dir(args: argparse.Namespace) -> str:
    """スナップショット保存先ディレクトリを解決します。

    ``--dir`` が指定されていればそれを優先し、指定がなければ GUI と同様に
    設定ファイル (``wsl_core.load_settings``) の ``snapshot_dir``、
    それも未設定であれば ``wsl_core.get_default_snapshot_dir()`` を使います。
    """
    if getattr(args, "dir", None):
        return args.dir
    settings = wsl_core.load_settings(wsl_core.get_default_settings_path())
    return settings.get("snapshot_dir") or wsl_core.get_default_snapshot_dir()


def _find_snapshot_by_tar_file(snapshots: list[dict], tar_file: str) -> dict | None:
    """スナップショット一覧から tar ファイル名 (ベース名) が一致するエントリを探します。"""
    return next((s for s in snapshots if s.get("tar_file") == tar_file), None)


def cmd_snapshot_create(args: argparse.Namespace) -> None:
    """指定したディストリビューションのスナップショット (tar + メタデータ) を作成します。"""
    name = args.name
    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    distros = wsl_core.parse_distro_list(stdout)
    matched = next((d for d in distros if d["name"] == name), None)
    if matched is None:
        print(f"エラー: 「{name}」というディストリビューションが見つかりません。", file=sys.stderr)
        sys.exit(1)
    wsl_version = str(matched.get("version") or "") or "2"

    snap_dir = _resolve_snapshot_dir(args)
    try:
        os.makedirs(snap_dir, exist_ok=True)
    except OSError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(1)

    timestamp = time.strftime(wsl_core.SNAPSHOT_TIMESTAMP_FORMAT)
    basename = wsl_core.build_snapshot_basename(name, timestamp)
    tar_name = basename + ".tar"
    tar_path = os.path.join(snap_dir, tar_name)
    json_path = os.path.join(snap_dir, basename + ".json")

    print(f"「{name}」のスナップショットをエクスポート中…")
    returncode, _stdout, stderr = _run_wsl_command(["--export", name, tar_path], timeout=600.0)
    if returncode != 0:
        try:
            os.remove(tar_path)
        except OSError:
            pass
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{name}」のスナップショット作成に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)

    try:
        size_bytes = os.path.getsize(tar_path)
    except OSError:
        size_bytes = 0

    created_at = datetime.now().isoformat(timespec="seconds")
    metadata = wsl_core.build_snapshot_metadata(
        name, wsl_version, args.comment or "", size_bytes, created_at, tar_name
    )
    if not wsl_core.write_snapshot_metadata(json_path, metadata):
        print("警告: メタデータの保存に失敗しました。", file=sys.stderr)

    print(f"「{name}」のスナップショットを作成しました: {tar_path}")


def cmd_snapshot_list(args: argparse.Namespace) -> None:
    """保存されているスナップショットの一覧を表示します。"""
    snap_dir = _resolve_snapshot_dir(args)
    snapshots = wsl_core.load_snapshots(snap_dir)

    if args.format == "json":
        print(json.dumps(snapshots, ensure_ascii=False, indent=2))
        return

    if not snapshots:
        print("スナップショットがありません。")
        return

    headers = ["Distro", "Created", "Size", "Comment", "File", "Exists"]
    rows = [
        [
            s.get("distro_name", ""),
            s.get("created_at", ""),
            wsl_core.format_bytes(s.get("size_bytes", 0)),
            s.get("comment", ""),
            s.get("tar_file", ""),
            "yes" if s.get("tar_exists", True) else "MISSING",
        ]
        for s in snapshots
    ]

    if args.format == "csv":
        print(_format_csv(headers, rows))
    else:
        print(_format_table(headers, rows))
        total = wsl_core.total_snapshots_size(snapshots)
        print(f"合計: {wsl_core.format_bytes(total)} ({len(snapshots)} 件)")


def cmd_snapshot_restore(args: argparse.Namespace) -> None:
    """指定したスナップショットを新しいディストリビューションとして復元します。"""
    snap_dir = _resolve_snapshot_dir(args)
    snapshots = wsl_core.load_snapshots(snap_dir)
    snap = _find_snapshot_by_tar_file(snapshots, args.tar_file)
    if snap is None:
        print(f"エラー: 「{args.tar_file}」というスナップショットが見つかりません。", file=sys.stderr)
        sys.exit(1)
    if not snap.get("tar_exists", True):
        print(f"エラー: tar ファイルが見つかりません: {snap.get('tar_path', '')}", file=sys.stderr)
        sys.exit(1)

    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)
    distros = wsl_core.parse_distro_list(stdout)
    existing = [d["name"] for d in distros]

    distro_name = snap.get("distro_name", "")
    if args.name:
        new_name = args.name
        valid, reason = wsl_core.validate_distro_name(new_name)
        if not valid:
            print(f"エラー: {reason}", file=sys.stderr)
            sys.exit(1)
        existing_casefold = {n.casefold() for n in existing}
        if new_name.casefold() in existing_casefold:
            print("エラー: 同名のディストリビューションが既に存在します。", file=sys.stderr)
            sys.exit(1)
    else:
        new_name = wsl_core.default_clone_name(distro_name, existing)

    install_path = args.install_path
    version = snap.get("wsl_version") or "2"
    tar_path = snap.get("tar_path", "")

    if not args.yes:
        print("次の内容で復元します。")
        print(f"  名前: {new_name}")
        print(f"  スナップショット: {os.path.basename(tar_path)}")
        print(f"  保存先: {install_path}")
        print(f"  バージョン: WSL{version}")
        try:
            answer = input("よろしいですか? [y/N]: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    print(f"「{new_name}」へ復元中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--import", new_name, install_path, tar_path, "--version", version], timeout=1800.0
    )
    if returncode == 0:
        print(f"「{new_name}」に復元しました。")
    else:
        msg = stderr.strip() or "不明なエラー"
        print(f"エラー: 「{new_name}」への復元に失敗しました: {msg}", file=sys.stderr)
        sys.exit(1)


def cmd_snapshot_delete(args: argparse.Namespace) -> None:
    """指定したスナップショットの tar / JSON ファイルを削除します。"""
    snap_dir = _resolve_snapshot_dir(args)
    snapshots = wsl_core.load_snapshots(snap_dir)
    snap = _find_snapshot_by_tar_file(snapshots, args.tar_file)
    if snap is None:
        print(f"エラー: 「{args.tar_file}」というスナップショットが見つかりません。", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        print("次のスナップショットを削除します。この操作は取り消せません。")
        print(f"  ディストリビューション: {snap.get('distro_name', '')}")
        print(f"  作成日時: {snap.get('created_at', '')}")
        print(f"  ファイル: {snap.get('tar_file', '')}")
        try:
            answer = input("よろしいですか? [y/N]: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    errors: list[str] = []
    tar_path = snap.get("tar_path", "")
    json_path = snap.get("json_path", "")
    if snap.get("tar_exists", True) and tar_path:
        try:
            os.remove(tar_path)
        except OSError as e:
            errors.append(str(e))
    if json_path:
        try:
            os.remove(json_path)
        except OSError as e:
            errors.append(str(e))

    if errors:
        print("エラー: 削除に失敗しました: " + "; ".join(errors), file=sys.stderr)
        sys.exit(1)

    print("削除しました。")


def _make_snapshot_help_func(parser: argparse.ArgumentParser):
    """``wslmgr snapshot`` (サブサブコマンドなし) 実行時にヘルプを表示する関数を返します。"""
    def _cmd_snapshot_help(_args: argparse.Namespace) -> None:
        parser.print_help()
        sys.exit(0)
    return _cmd_snapshot_help


# ---------------------------------------------------------------------------
# clone サブコマンド
# ---------------------------------------------------------------------------

def cmd_clone(args: argparse.Namespace) -> None:
    """指定したディストリビューションを複製します（エクスポート→インポートを自動実行）。"""
    name = args.name
    new_name = args.new_name
    install_path = args.install_path

    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(1)

    distros = wsl_core.parse_distro_list(stdout)
    matched = next((d for d in distros if d["name"] == name), None)
    if matched is None:
        print(f"エラー: 「{name}」というディストリビューションが見つかりません。", file=sys.stderr)
        sys.exit(1)
    version = str(matched.get("version") or "") or "2"

    existing = [d["name"] for d in distros]
    valid, reason = wsl_core.validate_clone_name(new_name, existing)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(1)

    if not args.yes:
        print("次の内容で複製します。")
        print(f"  複製元: {name}")
        print(f"  複製先の名前: {new_name}")
        print(f"  複製先フォルダ: {install_path}")
        try:
            answer = input("よろしいですか? [y/N]: ")
        except EOFError:
            answer = ""
        if answer.strip().lower() not in ("y", "yes"):
            print("中止しました。")
            sys.exit(0)

    tmp_dir = tempfile.mkdtemp(prefix="wslmgr_clone_")
    tmp_tar = os.path.join(tmp_dir, wsl_core.sanitize_snapshot_name(new_name) + ".tar")
    try:
        print(f"「{name}」を複製中… (1/2 エクスポート)")
        returncode, _stdout, stderr = _run_wsl_command(["--export", name, tmp_tar], timeout=1800.0)
        if returncode != 0:
            msg = stderr.strip() or "不明なエラー"
            print(f"エラー: 「{name}」のエクスポートに失敗しました: {msg}", file=sys.stderr)
            sys.exit(1)

        print(f"「{name}」を複製中… (2/2 インポート)")
        returncode, _stdout, stderr = _run_wsl_command(
            ["--import", new_name, install_path, tmp_tar, "--version", version], timeout=1800.0
        )
        if returncode != 0:
            msg = stderr.strip() or "不明なエラー"
            print(f"エラー: 「{new_name}」のインポートに失敗しました: {msg}", file=sys.stderr)
            sys.exit(1)

        print(f"「{name}」を「{new_name}」として複製しました。")
    finally:
        try:
            os.remove(tmp_tar)
        except OSError:
            pass
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    """argparse のパーサーとサブコマンドを構築して返します。"""
    parser = argparse.ArgumentParser(
        prog="wslmgr",
        description="WSL Manager - コマンドラインインターフェース",
    )
    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="WSL ディストリビューションの一覧を表示します")
    p_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_list.set_defaults(func=cmd_list)

    # start
    p_start = subparsers.add_parser("start", help="ディストリビューションを起動します")
    p_start.add_argument("name", help="ディストリビューション名")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = subparsers.add_parser("stop", help="ディストリビューションを停止します")
    p_stop.add_argument("name", help="ディストリビューション名")
    p_stop.set_defaults(func=cmd_stop)

    # shutdown
    p_shutdown = subparsers.add_parser("shutdown", help="すべてのディストリビューションを停止します")
    p_shutdown.set_defaults(func=cmd_shutdown)

    # status
    p_status = subparsers.add_parser("status", help="実行中ディストリビューションのリソース使用状況を表示します")
    p_status.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_status.set_defaults(func=cmd_status)

    # export
    p_export = subparsers.add_parser("export", help="ディストリビューションをエクスポートします")
    p_export.add_argument("name", help="ディストリビューション名")
    p_export.add_argument("path", help="エクスポート先のファイルパス")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help="ディストリビューションをインポートします")
    p_import.add_argument("name", help="ディストリビューション名")
    p_import.add_argument("install_path", help="インストール先ディレクトリ")
    p_import.add_argument("image_path", help="インポートするイメージ (tar) のパス")
    p_import.set_defaults(func=cmd_import)

    # config
    p_config = subparsers.add_parser("config", help="現在の .wslconfig 設定を表示します")
    p_config.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_config.set_defaults(func=cmd_config)

    # set-default
    p_set_default = subparsers.add_parser(
        "set-default", help="ディストリビューションを既定 (デフォルト) に設定します"
    )
    p_set_default.add_argument("name", help="ディストリビューション名")
    p_set_default.set_defaults(func=cmd_set_default)

    # unregister
    p_unregister = subparsers.add_parser(
        "unregister", help="ディストリビューションをアンインストール (登録解除) します"
    )
    p_unregister.add_argument("name", help="ディストリビューション名")
    p_unregister.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_unregister.set_defaults(func=cmd_unregister)

    # install
    p_install = subparsers.add_parser("install", help="ディストリビューションをインストールします")
    p_install.add_argument("name", help="ディストリビューション名")
    p_install.set_defaults(func=cmd_install)

    # optimize
    p_optimize = subparsers.add_parser(
        "optimize", help="ディストリビューションの仮想ディスクを最適化します"
    )
    p_optimize.add_argument("name", help="ディストリビューション名")
    optimize_group = p_optimize.add_mutually_exclusive_group(required=True)
    optimize_group.add_argument(
        "--sparse", action="store_true", help="仮想ディスクのスパース化を有効にします"
    )
    optimize_group.add_argument(
        "--compact", action="store_true", help="仮想ディスクを圧縮します"
    )
    p_optimize.set_defaults(func=cmd_optimize)

    # set-version
    p_set_version = subparsers.add_parser(
        "set-version", help="ディストリビューションを WSL1 / WSL2 間で変換します"
    )
    p_set_version.add_argument("name", help="ディストリビューション名")
    p_set_version.add_argument(
        "version", choices=["1", "2"], help="変換先の WSL バージョン (1 または 2)"
    )
    p_set_version.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_set_version.set_defaults(func=cmd_set_version)

    # processes
    p_processes = subparsers.add_parser(
        "processes", help="ディストリビューション内で実行中のプロセス一覧を表示します"
    )
    p_processes.add_argument("name", help="ディストリビューション名")
    p_processes.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_processes.set_defaults(func=cmd_processes)

    # log
    p_log = subparsers.add_parser("log", help="保存されている操作ログを表示します")
    p_log.add_argument(
        "--tail", type=int, default=50, help="表示する末尾のエントリ数 (既定: 50)"
    )
    p_log.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_log.set_defaults(func=cmd_log)

    # portproxy
    p_portproxy = subparsers.add_parser(
        "portproxy", help="ポートフォワーディングルールを管理します"
    )
    p_portproxy.set_defaults(func=_make_portproxy_help_func(p_portproxy))
    portproxy_subparsers = p_portproxy.add_subparsers(dest="portproxy_command")

    p_portproxy_list = portproxy_subparsers.add_parser(
        "list", help="ポートフォワーディングルールの一覧を表示します"
    )
    p_portproxy_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_portproxy_list.set_defaults(func=cmd_portproxy_list)

    p_portproxy_add = portproxy_subparsers.add_parser(
        "add", help="ポートフォワーディングルールを追加します"
    )
    p_portproxy_add.add_argument("listen_port", help="リッスンするポート番号")
    p_portproxy_add.add_argument("connect_port", help="接続先のポート番号")
    p_portproxy_add.add_argument(
        "--connect-address", required=True, help="接続先の IP アドレス"
    )
    p_portproxy_add.add_argument(
        "--listen-address", default="0.0.0.0", help="リッスンする IP アドレス (既定: 0.0.0.0)"
    )
    p_portproxy_add.set_defaults(func=cmd_portproxy_add)

    p_portproxy_delete = portproxy_subparsers.add_parser(
        "delete", help="ポートフォワーディングルールを削除します"
    )
    p_portproxy_delete.add_argument("listen_port", help="リッスンするポート番号")
    p_portproxy_delete.add_argument(
        "--listen-address", default="0.0.0.0", help="リッスンする IP アドレス (既定: 0.0.0.0)"
    )
    p_portproxy_delete.set_defaults(func=cmd_portproxy_delete)

    # snapshot
    p_snapshot = subparsers.add_parser(
        "snapshot", help="ディストリビューションのスナップショットを管理します"
    )
    p_snapshot.set_defaults(func=_make_snapshot_help_func(p_snapshot))
    snapshot_subparsers = p_snapshot.add_subparsers(dest="snapshot_command")

    p_snapshot_create = snapshot_subparsers.add_parser(
        "create", help="ディストリビューションのスナップショットを作成します"
    )
    p_snapshot_create.add_argument("name", help="ディストリビューション名")
    p_snapshot_create.add_argument("--comment", default="", help="スナップショットのコメント (任意)")
    p_snapshot_create.add_argument("--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)")
    p_snapshot_create.set_defaults(func=cmd_snapshot_create)

    p_snapshot_list = snapshot_subparsers.add_parser(
        "list", help="スナップショットの一覧を表示します"
    )
    p_snapshot_list.add_argument("--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)")
    p_snapshot_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_snapshot_list.set_defaults(func=cmd_snapshot_list)

    p_snapshot_restore = snapshot_subparsers.add_parser(
        "restore", help="スナップショットを新しいディストリビューションとして復元します"
    )
    p_snapshot_restore.add_argument("tar_file", help="復元するスナップショットの tar ファイル名")
    p_snapshot_restore.add_argument(
        "--install-path", required=True, help="復元先のインストールディレクトリ"
    )
    p_snapshot_restore.add_argument(
        "--name", help="復元先のディストリビューション名 (既定: 自動生成)"
    )
    p_snapshot_restore.add_argument("--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)")
    p_snapshot_restore.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_snapshot_restore.set_defaults(func=cmd_snapshot_restore)

    p_snapshot_delete = snapshot_subparsers.add_parser(
        "delete", help="スナップショットを削除します"
    )
    p_snapshot_delete.add_argument("tar_file", help="削除するスナップショットの tar ファイル名")
    p_snapshot_delete.add_argument("--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)")
    p_snapshot_delete.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_snapshot_delete.set_defaults(func=cmd_snapshot_delete)

    # clone
    p_clone = subparsers.add_parser(
        "clone", help="ディストリビューションを複製します（エクスポート→インポートを自動実行）"
    )
    p_clone.add_argument("name", help="複製元のディストリビューション名")
    p_clone.add_argument("new_name", help="複製先の新しいディストリビューション名")
    p_clone.add_argument("--install-path", required=True, help="複製先のインストールディレクトリ")
    p_clone.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_clone.set_defaults(func=cmd_clone)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(0)
    args.func(args)


if __name__ == "__main__":
    main()
