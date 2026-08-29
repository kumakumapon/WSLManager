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


# ── 終了コード体系 ────────────────────────────────────────────────────────
class ExitCode:
    """CLI の終了コード規約。"""

    SUCCESS = 0
    GENERAL_ERROR = 1
    ARGUMENT_ERROR = 2
    USER_CANCELLED = 3
    WSL_ERROR = 4
    PARTIAL_FAILURE = 5


# モジュールレベルの定数エイリアス
EXIT_OK = ExitCode.SUCCESS
EXIT_ERROR = ExitCode.GENERAL_ERROR
EXIT_DENIED = ExitCode.USER_CANCELLED
EXIT_WSL_FAILURE = ExitCode.WSL_ERROR
EXIT_PARTIAL = ExitCode.PARTIAL_FAILURE


# ── Windows 専用フラグ ──────────────────────────────────────────────────────
CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def _language_for_args(args: argparse.Namespace) -> str:
    """Resolve the CLI language selected by the parser or a lightweight test arg."""
    return wsl_core.resolve_language(getattr(args, "language", wsl_core.LANGUAGE_AUTO))


def _t(args: argparse.Namespace, key: str, **values: object) -> str:
    return wsl_core.translate(key, _language_for_args(args), **values)


# ---------------------------------------------------------------------------
# subprocess ヘルパー
# ---------------------------------------------------------------------------

def _run_wsl_command(args: list[str], timeout: float = 10.0) -> tuple[int, str, str]:
    """WSL コマンドを実行して (returncode, stdout, stderr) を返します。

    wsl_core.run_wsl() を使用してコマンドを実行し、
    (returncode, stdout, stderr) のタプル形式で返します。
    """
    res = wsl_core.run_wsl(args, timeout=timeout, creationflags=CREATE_NO_WINDOW)
    return res.returncode, res.stdout, res.stderr


def _run_netsh_portproxy(args: list[str], timeout: float = 15.0) -> tuple[int, str, str]:
    """``netsh interface portproxy`` コマンドを実行して (returncode, stdout, stderr) を返します。

    netsh の出力は UTF-16 ではないため wsl_core.decode_wsl_output は使わず、
    ``text=True`` でそのままテキストとして受け取ります。
    タイムアウトや OSError が発生した場合は returncode=-1 とし、
    stderr にエラーメッセージを設定します（_run_wsl_command と同形式）。
    """
    try:
        result = subprocess.run(
            ["netsh", "interface", "portproxy", *args],
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
    # widths は str_headers を enumerate して構築するため常に同じ長さになる。
    # strict=True で万一の長さ不一致 (バグ) を検出する。
    header_line = "  ".join(h.ljust(w) for h, w in zip(str_headers, widths, strict=True))
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
# ---------------------------------------------------------------------------
# list サブコマンド
# ---------------------------------------------------------------------------

def cmd_list(args: argparse.Namespace) -> None:
    """``wsl --list --verbose`` の結果を表示します。"""
    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or _t(args, "cli.list_error")
        print(f"{_t(args, 'cli.error')}: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)

    distros = wsl_core.parse_distro_list(stdout)

    fetch_ip = getattr(args, "with_ip", False) or getattr(args, "all_info", False)
    fetch_disk = getattr(args, "with_disk", False) or getattr(args, "all_info", False)

    for d in distros:
        if d["state"] == "Running":
            if fetch_ip:
                rc, out, _err = _run_wsl_command(
                    ["-d", d["name"], "--", "hostname", "-I"], timeout=5.0
                )
                if rc == 0:
                    ips = wsl_core.parse_ip_addresses(out)
                    d["ip"] = ", ".join(ips) if ips else "-"
            if fetch_disk:
                rc, out, _err = _run_wsl_command(
                    ["-d", d["name"], "--", "df", "-h", "/"], timeout=5.0
                )
                if rc == 0:
                    disks = wsl_core.parse_disk_usage(out)
                    if disks:
                        d["disk"] = f"{disks[0].get('used', '-')}/{disks[0].get('size', '-')}"

    if getattr(args, "format", "table") == "json":
        print(json.dumps(distros, ensure_ascii=False, indent=2))
        return

    headers = [
        _t(args, "cli.header.name"),
        _t(args, "cli.header.state"),
        _t(args, "cli.header.version"),
        _t(args, "cli.header.default"),
    ]
    if fetch_ip:
        headers.append("IP")
    if fetch_disk:
        headers.append("Disk")

    rows = []
    for d in distros:
        row = [d["name"], d["state"], d["version"], "*" if d["default"] else ""]
        if fetch_ip:
            row.append(d.get("ip", "-"))
        if fetch_disk:
            row.append(d.get("disk", "-"))
        rows.append(row)

    if getattr(args, "format", "table") == "csv":
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
        _log_cli_operation("起動", name, "成功")
        _print_action_result(args, f"「{name}」を起動しました。", target=name)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("起動", name, msg)
        print(f"エラー: 「{name}」の起動に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# stop サブコマンド
# ---------------------------------------------------------------------------

def cmd_stop(args: argparse.Namespace) -> None:
    """指定したディストリビューションを停止します。"""
    name = args.name
    returncode, _stdout, stderr = _run_wsl_command(["--terminate", name], timeout=30.0)
    if returncode == 0:
        _log_cli_operation("停止", name, "成功")
        _print_action_result(args, f"「{name}」を停止しました。", target=name)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("停止", name, msg)
        print(f"エラー: 「{name}」の停止に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# shutdown サブコマンド
# ---------------------------------------------------------------------------

def cmd_shutdown(args: argparse.Namespace) -> None:
    """すべてのディストリビューションを停止します。"""
    returncode, _stdout, stderr = _run_wsl_command(["--shutdown"], timeout=30.0)
    if returncode == 0:
        _log_cli_operation("全停止", "全ディストリビューション", "成功")
        _print_action_result(args, "WSL を全停止しました。", target="all")
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("全停止", "全ディストリビューション", msg)
        print(f"エラー: WSL の全停止に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


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
        sys.exit(ExitCode.WSL_ERROR)

    distros = wsl_core.parse_distro_list(stdout)
    running = [d for d in distros if d["state"] == "Running"]

    fetch_disk = getattr(args, "with_disk", False) or getattr(args, "all_info", False)

    results: list[dict] = []
    failed_count = 0
    for d in running:
        rc, out, _err = _run_wsl_command(
            ["-d", d["name"], "--", "sh", "-lc", _RESOURCE_USAGE_CMD], timeout=10.0
        )
        if rc == 0:
            cpu, memory = wsl_core.parse_resource_usage(out.strip())
        else:
            cpu, memory = "-", "-"
            failed_count += 1
        entry = {"name": d["name"], "cpu": cpu, "memory": memory}

        if fetch_disk:
            rc_d, out_d, _err_d = _run_wsl_command(
                ["-d", d["name"], "--", "df", "-h", "/"], timeout=10.0
            )
            if rc_d == 0:
                disks = wsl_core.parse_disk_usage(out_d)
                disk_str = (
                    f"{disks[0].get('used', '-')}/{disks[0].get('size', '-')}"
                    if disks
                    else "-"
                )
                entry["disk"] = disk_str
            else:
                entry["disk"] = "-"

        results.append(entry)

    if getattr(args, "strict", False) and running and failed_count == len(running):
        print(
            "エラー: 全ディストリビューションでリソース情報の取得に失敗しました。",
            file=sys.stderr,
        )
        sys.exit(ExitCode.PARTIAL_FAILURE)

    if getattr(args, "format", "table") == "json":
        print(json.dumps(results, ensure_ascii=False, indent=2))
        return

    headers = ["Name", "CPU(%)", "Memory(MB)"]
    if fetch_disk:
        headers.append("Disk")
    rows = []
    for r in results:
        row = [r["name"], r["cpu"], r["memory"]]
        if fetch_disk:
            row.append(r.get("disk", "-"))
        rows.append(row)
    print(_format_table(headers, rows))


# ---------------------------------------------------------------------------
# export サブコマンド
# ---------------------------------------------------------------------------

def cmd_export(args: argparse.Namespace) -> None:
    """指定したディストリビューションをエクスポートします。"""
    name = args.name
    path = args.path

    if os.path.exists(path):
        _confirm_or_exit(
            f"「{path}」は既に存在します。上書きします。続行しますか?", args.yes
        )

    if not getattr(args, "quiet", False):
        print(f"「{name}」を「{path}」にエクスポート中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--export", name, path], timeout=600.0
    )
    if returncode == 0:
        _log_cli_operation("エクスポート", name, path)
        _print_action_result(
            args,
            f"「{name}」のエクスポートが完了しました: {path}",
            target=name,
            detail={"path": path},
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("エクスポート", name, msg)
        print(f"エラー: 「{name}」のエクスポートに失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


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
        sys.exit(ExitCode.GENERAL_ERROR)

    if os.path.exists(os.path.join(install_path, "ext4.vhdx")):
        _confirm_or_exit(
            f"「{install_path}」には既に仮想ディスク (ext4.vhdx) が存在します。"
            "上書きします。続行しますか?",
            args.yes,
        )

    if not getattr(args, "quiet", False):
        print(f"「{name}」を「{install_path}」にインポート中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--import", name, install_path, image_path], timeout=600.0
    )
    if returncode == 0:
        _log_cli_operation("インポート", name, image_path)
        _print_action_result(
            args,
            f"「{name}」のインポートが完了しました。",
            target=name,
            detail={"install_path": install_path, "image_path": image_path},
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("インポート", name, msg)
        print(f"エラー: 「{name}」のインポートに失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# config サブコマンド
# ---------------------------------------------------------------------------

def cmd_config(args: argparse.Namespace) -> None:
    """現在の .wslconfig またはディストリビューションの wsl.conf 設定を表示します。"""
    distro_name = getattr(args, "distro", None)
    if distro_name:
        # /etc/wsl.conf を取得
        returncode, stdout, stderr = _run_wsl_command(
            ["-d", distro_name, "--", "cat", "/etc/wsl.conf"], timeout=10.0
        )
        if returncode != 0:
            msg = stderr.strip() or "wsl.conf の取得に失敗しました。"
            print(
                f"エラー: 「{distro_name}」の /etc/wsl.conf を読み込めませんでした: {msg}",
                file=sys.stderr,
            )
            sys.exit(ExitCode.WSL_ERROR)
        text = stdout
    else:
        path = os.path.expanduser("~/.wslconfig")
        if not os.path.exists(path):
            print(f"エラー: {path} が見つかりません。", file=sys.stderr)
            sys.exit(ExitCode.GENERAL_ERROR)

        try:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            print(f"エラー: .wslconfig の読み込みに失敗しました: {e}", file=sys.stderr)
            sys.exit(ExitCode.GENERAL_ERROR)

    try:
        sections = wsl_core.parse_wslconfig(text)
    except wsl_core.WslConfigParseError as e:
        print(f"エラー: 設定のパースに失敗しました: {e}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    if getattr(args, "format", "table") == "json":
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

def _log_cli_operation(operation: str, target: str, result: str) -> None:
    """CLI から実行した状態変更操作を GUI と同じ operations.jsonl に記録します。

    実際に wsl.exe / netsh / diskpart 等のコマンド実行を試みた場合のみ呼び出します。
    確認拒否・非対話中断 (:func:`_confirm_or_exit` による ``sys.exit``) や、
    実コマンド実行に到達しない事前検証の失敗 (引数バリデーション等) は対象外です。
    """
    wsl_core.append_log_entry(
        wsl_core.get_default_log_dir(), operation, target, result, source="cli"
    )


def _print_action_result(
    args: argparse.Namespace,
    human_msg: str,
    status: str = "ok",
    target: str | None = None,
    detail: dict | None = None,
) -> None:
    """変更系サブコマンドの結果を --format json や --quiet に応じて出力します。"""
    if getattr(args, "format", "table") == "json":
        res = {
            "status": status,
            "command": getattr(args, "command", ""),
            "target": target or getattr(args, "name", ""),
            "message": human_msg,
        }
        if detail:
            res.update(detail)
        print(json.dumps(res, ensure_ascii=False, indent=2))
    elif not getattr(args, "quiet", False):
        print(human_msg)


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
        sys.exit(ExitCode.USER_CANCELLED)
    try:
        answer = input(f"{prompt} [y/N]: ")
    except EOFError:
        # Ctrl-D などで入力が閉じられた場合は「いいえ」として扱う
        answer = ""
    if answer.strip().lower() not in ("y", "yes"):
        print("中止しました。")
        sys.exit(ExitCode.USER_CANCELLED)


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
        _log_cli_operation("デフォルト設定", name, "成功")
        _print_action_result(args, f"「{name}」をデフォルトに設定しました。", target=name)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("デフォルト設定", name, msg)
        print(f"エラー: 「{name}」のデフォルト設定に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


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
        _log_cli_operation("アンインストール", name, "成功")
        _print_action_result(args, f"「{name}」をアンインストールしました。", target=name)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("アンインストール", name, msg)
        print(f"エラー: 「{name}」のアンインストールに失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# install サブコマンド
# ---------------------------------------------------------------------------

def cmd_install(args: argparse.Namespace) -> None:
    """指定したディストリビューションをインストールします。"""
    name = args.name
    if not getattr(args, "quiet", False):
        print(f"「{name}」をインストール中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--install", "-d", name, "--no-launch"], timeout=1800.0
    )
    if returncode == 0:
        _log_cli_operation("インストール", name, "成功")
        _print_action_result(args, f"「{name}」のインストールが完了しました。", target=name)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("インストール", name, msg)
        print(f"エラー: 「{name}」のインストールに失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


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
            _log_cli_operation("スパース化", name, "成功")
            _print_action_result(args, f"「{name}」のスパース化を有効にしました。", target=name)
        else:
            msg = stderr.strip() or "不明なエラー"
            _log_cli_operation("スパース化", name, msg)
            print(f"エラー: 「{name}」のスパース化に失敗しました: {msg}", file=sys.stderr)
            sys.exit(ExitCode.WSL_ERROR)
        return

    # --compact
    vhdx_path = _get_distro_vhdx_path(name)
    if vhdx_path is None:
        print(f"エラー: 「{name}」の仮想ディスク (ext4.vhdx) が見つかりません。", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    _confirm_or_exit(
        f"「{name}」の仮想ディスクを圧縮します。この操作は取り消せません。続行しますか?",
        args.yes,
    )

    if not getattr(args, "quiet", False):
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
        _log_cli_operation("圧縮", name, "タイムアウト")
        print(f"エラー: 「{name}」の仮想ディスクの圧縮がタイムアウトしました。", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)
    except OSError as e:
        _log_cli_operation("圧縮", name, str(e))
        print(f"エラー: 「{name}」の仮想ディスクの圧縮に失敗しました: {e}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)
    finally:
        if script_path is not None:
            try:
                os.remove(script_path)
            except OSError:
                pass

    if result.returncode == 0:
        _log_cli_operation("圧縮", name, "成功")
        _print_action_result(args, f"「{name}」の仮想ディスクを圧縮しました。", target=name)
    else:
        _log_cli_operation("圧縮", name, f"終了コード {result.returncode}")
        print(f"エラー: 「{name}」の仮想ディスクの圧縮に失敗しました。", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# set-version サブコマンド
# ---------------------------------------------------------------------------

def cmd_set_version(args: argparse.Namespace) -> None:
    """指定したディストリビューションを WSL1 / WSL2 間で変換します。"""
    name = args.name
    version = args.version
    _confirm_or_exit(
        f"「{name}」を WSL{version} に変換します。"
        "変換には時間がかかることがあります。続行しますか?",
        args.yes,
    )
    returncode, _stdout, stderr = _run_wsl_command(
        ["--set-version", name, version], timeout=1800.0
    )
    if returncode == 0:
        _log_cli_operation("バージョン変換", name, f"WSL{version}")
        _print_action_result(
            args,
            f"「{name}」を WSL{version} に変換しました。",
            target=name,
            detail={"version": version},
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("バージョン変換", name, msg)
        print(f"エラー: 「{name}」の変換に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


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
        sys.exit(ExitCode.WSL_ERROR)

    processes = wsl_core.parse_process_list(stdout)

    if getattr(args, "format", "table") == "json":
        print(json.dumps(processes, ensure_ascii=False, indent=2))
        return

    headers = ["PID", "User", "CPU(%)", "Memory(MB)", "Command"]
    rows = [[p["pid"], p["user"], p["cpu"], p["memory"], p["command"]] for p in processes]

    if getattr(args, "format", "table") == "csv":
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
        if getattr(args, "format", "table") == "json":
            print("[]")
        elif not getattr(args, "quiet", False):
            print("操作ログはまだありません。")
        return

    try:
        with open(log_path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"エラー: 操作ログの読み込みに失敗しました: {e}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    entries = wsl_core.deserialize_log_entries(text)
    entries = wsl_core.tail_entries(entries, args.tail)

    if getattr(args, "format", "table") == "json":
        print(json.dumps(entries, ensure_ascii=False, indent=2))
        return

    for entry in entries:
        print(wsl_core.format_log_entry_from_dict(entry))


def cmd_log_clear(args: argparse.Namespace) -> None:
    """保存されている操作ログを消去します。"""
    _confirm_or_exit("すべての操作ログを消去します。続行しますか?", getattr(args, "yes", False))
    deleted, failed = wsl_core.delete_log_files(wsl_core.get_default_log_dir())
    if failed:
        print(f"エラー: 一部ログファイルの削除に失敗しました: {', '.join(failed)}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    _print_action_result(
        args,
        f"操作ログを消去しました ({deleted} ファイル削除)。",
        target="logs",
        detail={"deleted_count": deleted},
    )


# ---------------------------------------------------------------------------
# portproxy サブコマンド
# ---------------------------------------------------------------------------

def cmd_portproxy_list(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールの一覧を表示します。"""
    returncode, stdout, stderr = _run_netsh_portproxy(["show", "all"])
    if returncode != 0:
        msg = stderr.strip() or "ポートフォワーディング一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)

    rules = wsl_core.parse_portproxy_output(stdout)

    if getattr(args, "format", "table") == "json":
        print(json.dumps(rules, ensure_ascii=False, indent=2))
        return

    headers = ["ListenAddress", "ListenPort", "ConnectAddress", "ConnectPort"]
    rows = [
        [r["listen_address"], r["listen_port"], r["connect_address"], r["connect_port"]]
        for r in rules
    ]

    if getattr(args, "format", "table") == "csv":
        print(_format_csv(headers, rows))
    else:
        print(_format_table(headers, rows))


def cmd_portproxy_add(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールを追加します。"""
    valid, reason = wsl_core.validate_port_number(args.listen_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)
    valid, reason = wsl_core.validate_port_number(args.connect_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)

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
    target = f"{listen_address}:{listen_port} -> {connect_address}:{connect_port}"
    if returncode == 0:
        _log_cli_operation("ポートフォワード追加", target, "成功")
        _print_action_result(
            args,
            f"ポートフォワーディングを追加しました: {target}",
            target=target,
            detail={
                "listen_address": listen_address,
                "listen_port": listen_port,
                "connect_address": connect_address,
                "connect_port": connect_port,
            },
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("ポートフォワード追加", target, msg)
        print(
            f"エラー: ポートフォワーディングの追加に失敗しました: {msg}"
            "（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(ExitCode.WSL_ERROR)


def cmd_portproxy_delete(args: argparse.Namespace) -> None:
    """ポートフォワーディングルールを削除します。"""
    valid, reason = wsl_core.validate_port_number(args.listen_port)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)

    listen_port = args.listen_port
    listen_address = args.listen_address

    returncode, _stdout, stderr = _run_netsh_portproxy(
        ["delete", "v4tov4", f"listenport={listen_port}", f"listenaddress={listen_address}"]
    )
    target = f"{listen_address}:{listen_port}"
    if returncode == 0:
        _log_cli_operation("ポートフォワード削除", target, "成功")
        _print_action_result(
            args,
            f"ポートフォワーディングを削除しました: {target}",
            target=target,
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("ポートフォワード削除", target, msg)
        print(
            f"エラー: ポートフォワーディングの削除に失敗しました: {msg}"
            "（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(ExitCode.WSL_ERROR)


def _make_portproxy_help_func(parser: argparse.ArgumentParser):
    """``wslmgr portproxy`` (サブサブコマンドなし) 実行時にヘルプを表示する関数を返します。"""
    def _cmd_portproxy_help(_args: argparse.Namespace) -> None:
        parser.print_help()
        sys.exit(ExitCode.SUCCESS)
    return _cmd_portproxy_help


# ---------------------------------------------------------------------------
# snapshot サブコマンド
# ---------------------------------------------------------------------------

def _resolve_snapshot_dir(args: argparse.Namespace) -> str:
    """スナップショット保存先ディレクトリを解決します。"""
    if getattr(args, "dir", None):
        return args.dir
    settings = wsl_core.load_settings(wsl_core.get_default_settings_path())
    return settings.get("snapshot_dir") or wsl_core.get_default_snapshot_dir()


def _find_snapshot_by_tar_file(snapshots: list[dict], tar_file: str) -> dict | None:
    """スナップショット一覧から tar ファイル名 (ベース名) が一致するエントリを探します。"""
    return next((s for s in snapshots if s.get("tar_file") == tar_file), None)


def _delete_snapshot_files(snapshot: dict, snapshot_dir: str) -> list[str]:
    """スナップショット配下の tar / JSON を削除し、失敗メッセージを返します。

    ``load_snapshots`` が生成した同一ディレクトリ直下のファイルだけを対象にする。
    メタデータが改ざんされていても保存先外を削除しないための最終防衛線である。
    """
    directory = os.path.abspath(snapshot_dir)
    errors: list[str] = []
    for key, exists in (("tar_path", snapshot.get("tar_exists", True)), ("json_path", True)):
        path = snapshot.get(key, "")
        if not exists or not isinstance(path, str) or not path:
            continue
        absolute = os.path.abspath(path)
        if os.path.dirname(absolute) != directory:
            errors.append(f"安全でない削除対象を拒否しました: {path}")
            continue
        try:
            os.remove(absolute)
        except OSError as e:
            errors.append(str(e))
    return errors


def _prune_snapshots(
    snapshot_dir: str, keep: int, distro_name: str | None, dry_run: bool, assume_yes: bool
) -> list[dict]:
    """保持数を超えたスナップショットを表示または削除して候補を返します。"""
    snapshots = wsl_core.load_snapshots(snapshot_dir)
    try:
        candidates = wsl_core.snapshots_to_prune(snapshots, keep, distro_name)
    except ValueError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)

    if not candidates:
        print("削除対象のスナップショットはありません。")
        return []

    print(f"保持数 {keep} を超える {len(candidates)} 件のスナップショット:")
    for snapshot in candidates:
        print(f"  {snapshot.get('distro_name', '')}: {snapshot.get('tar_file', '')}")
    if dry_run:
        print("dry-run: 削除は実行していません。実行するには --yes を指定してください。")
        return candidates

    _confirm_or_exit("上記のスナップショットを完全に削除します。よろしいですか?", assume_yes)
    errors: list[str] = []
    for snapshot in candidates:
        errors.extend(_delete_snapshot_files(snapshot, snapshot_dir))
    if errors:
        print("エラー: 削除に失敗しました: " + "; ".join(errors), file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    return candidates


def cmd_snapshot_create(args: argparse.Namespace) -> None:
    """指定したディストリビューションのスナップショット (tar + メタデータ) を作成します。"""
    name = args.name
    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)

    distros = wsl_core.parse_distro_list(stdout)
    matched = next((d for d in distros if d["name"] == name), None)
    if matched is None:
        print(f"エラー: 「{name}」というディストリビューションが見つかりません。", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    wsl_version = str(matched.get("version") or "") or "2"

    snap_dir = _resolve_snapshot_dir(args)
    try:
        os.makedirs(snap_dir, exist_ok=True)
    except OSError as e:
        print(f"エラー: {e}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    timestamp = time.strftime(wsl_core.SNAPSHOT_TIMESTAMP_FORMAT)
    basename = wsl_core.build_snapshot_basename(name, timestamp)
    tar_name = basename + ".tar"
    tar_path = os.path.join(snap_dir, tar_name)
    json_path = os.path.join(snap_dir, basename + ".json")

    if not getattr(args, "quiet", False):
        print(f"「{name}」のスナップショットをエクスポート中…")
    returncode, _stdout, stderr = _run_wsl_command(["--export", name, tar_path], timeout=600.0)
    if returncode != 0:
        try:
            os.remove(tar_path)
        except OSError:
            pass
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("スナップショット作成", name, msg)
        print(f"エラー: 「{name}」のスナップショット作成に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)

    try:
        size_bytes = os.path.getsize(tar_path)
    except OSError:
        size_bytes = 0

    created_at = datetime.now().isoformat(timespec="seconds")
    metadata = wsl_core.build_snapshot_metadata(
        name, wsl_version, args.comment or "", size_bytes, created_at, tar_name
    )
    meta_ok = wsl_core.write_snapshot_metadata(json_path, metadata)
    if not meta_ok:
        print("警告: メタデータの保存に失敗しました。", file=sys.stderr)

    _log_cli_operation("スナップショット作成", name, tar_path)
    _print_action_result(
        args,
        f"「{name}」のスナップショットを作成しました: {tar_path}",
        target=name,
        detail={"tar_path": tar_path, "json_path": json_path, "size_bytes": size_bytes},
    )

    keep = getattr(args, "keep", None)
    if keep is not None:
        # 新規スナップショットのメタデータ保存後に評価し、失敗時でも最新世代を保持する。
        _prune_snapshots(
            snap_dir,
            keep,
            name,
            dry_run=False,
            assume_yes=getattr(args, "yes", False),
        )

    if not meta_ok:
        sys.exit(ExitCode.PARTIAL_FAILURE)


def cmd_snapshot_list(args: argparse.Namespace) -> None:
    """保存されているスナップショットの一覧を表示します。"""
    snap_dir = _resolve_snapshot_dir(args)
    snapshots = wsl_core.load_snapshots(snap_dir)

    if getattr(args, "format", "table") == "json":
        print(json.dumps(snapshots, ensure_ascii=False, indent=2))
        return

    if not snapshots:
        if not getattr(args, "quiet", False):
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

    if getattr(args, "format", "table") == "csv":
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
        print(
            f"エラー: 「{args.tar_file}」というスナップショットが見つかりません。", file=sys.stderr
        )
        sys.exit(ExitCode.GENERAL_ERROR)
    if not snap.get("tar_exists", True):
        print(f"エラー: tar ファイルが見つかりません: {snap.get('tar_path', '')}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    returncode, stdout, stderr = _run_wsl_command(["--list", "--verbose"], timeout=15.0)
    if returncode != 0:
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)
    distros = wsl_core.parse_distro_list(stdout)
    existing = [d["name"] for d in distros]

    distro_name = snap.get("distro_name", "")
    if args.name:
        new_name = args.name
        valid, reason = wsl_core.validate_distro_name(new_name)
        if not valid:
            print(f"エラー: {reason}", file=sys.stderr)
            sys.exit(ExitCode.GENERAL_ERROR)
        existing_casefold = {n.casefold() for n in existing}
        if new_name.casefold() in existing_casefold:
            print("エラー: 同名のディストリビューションが既に存在します。", file=sys.stderr)
            sys.exit(ExitCode.GENERAL_ERROR)
    else:
        new_name = wsl_core.default_clone_name(distro_name, existing)

    install_path = args.install_path
    version = snap.get("wsl_version") or "2"
    tar_path = snap.get("tar_path", "")

    if not getattr(args, "quiet", False):
        print("次の内容で復元します。")
        print(f"  名前: {new_name}")
        print(f"  スナップショット: {os.path.basename(tar_path)}")
        print(f"  保存先: {install_path}")
        print(f"  バージョン: WSL{version}")
        if os.path.exists(os.path.join(install_path, "ext4.vhdx")):
            print(
                f"警告: 「{install_path}」には既に仮想ディスク (ext4.vhdx) が存在します。"
                "上書きされます。"
            )
    _confirm_or_exit("よろしいですか?", args.yes)

    if not getattr(args, "quiet", False):
        print(f"「{new_name}」へ復元中…")
    returncode, _stdout, stderr = _run_wsl_command(
        ["--import", new_name, install_path, tar_path, "--version", version], timeout=1800.0
    )
    if returncode == 0:
        _log_cli_operation("スナップショット復元", new_name, tar_path)
        _print_action_result(
            args,
            f"「{new_name}」に復元しました。",
            target=new_name,
            detail={"install_path": install_path, "tar_path": tar_path},
        )
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("スナップショット復元", new_name, msg)
        print(f"エラー: 「{new_name}」への復元に失敗しました: {msg}", file=sys.stderr)
        sys.exit(ExitCode.WSL_ERROR)


def cmd_snapshot_delete(args: argparse.Namespace) -> None:
    """指定したスナップショットの tar / JSON ファイルを削除します。"""
    snap_dir = _resolve_snapshot_dir(args)
    snapshots = wsl_core.load_snapshots(snap_dir)
    snap = _find_snapshot_by_tar_file(snapshots, args.tar_file)
    if snap is None:
        print(
            f"エラー: 「{args.tar_file}」というスナップショットが見つかりません。", file=sys.stderr
        )
        sys.exit(ExitCode.GENERAL_ERROR)

    if not getattr(args, "quiet", False):
        print("次のスナップショットを削除します。この操作は取り消せません。")
        print(f"  ディストリビューション: {snap.get('distro_name', '')}")
        print(f"  作成日時: {snap.get('created_at', '')}")
        print(f"  ファイル: {snap.get('tar_file', '')}")
    _confirm_or_exit("よろしいですか?", args.yes)

    errors = _delete_snapshot_files(snap, snap_dir)

    if errors:
        _log_cli_operation(
            "スナップショット削除", snap.get("tar_file", args.tar_file), "; ".join(errors)
        )
        print("エラー: 削除に失敗しました: " + "; ".join(errors), file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    _log_cli_operation("スナップショット削除", snap.get("tar_file", args.tar_file), "成功")
    _print_action_result(args, "削除しました。", target=snap.get("tar_file", args.tar_file))


def cmd_snapshot_prune(args: argparse.Namespace) -> None:
    """保持数を超えたスナップショットを dry-run または削除します。"""
    snap_dir = _resolve_snapshot_dir(args)
    candidates = _prune_snapshots(
        snap_dir, args.keep, args.name, dry_run=not args.yes, assume_yes=args.yes
    )
    _print_action_result(
        args,
        (
            f"{len(candidates)} 件のスナップショットを"
            f"{'削除しました' if args.yes else '削除候補として表示しました'}。"
        ),
        target=args.name or snap_dir,
        detail={"count": len(candidates), "dry_run": not args.yes},
    )


def _scheduled_task_name(distro_name: str) -> str:
    """ディストロごとに安定した Windows タスク名を返します。"""
    return "WSLManager-Snapshot-" + wsl_core.sanitize_snapshot_name(distro_name)


def _build_scheduled_snapshot_command(args: argparse.Namespace) -> str:
    """Task Scheduler に登録する、自己完結したスナップショットコマンドを構築します。"""
    command = [sys.executable, os.path.abspath(__file__), "snapshot", "create", args.name]
    command.extend(
        ["--dir", os.path.abspath(args.dir), "--keep", str(args.keep), "--yes", "--quiet"]
    )
    return subprocess.list2cmdline(command)


def _run_schtasks(command: list[str]) -> tuple[int, str, str]:
    """Windows Task Scheduler コマンドを実行する。"""
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, errors="replace", timeout=30.0
        )
    except subprocess.TimeoutExpired:
        return -1, "", "タスク スケジューラの操作がタイムアウトしました。"
    except OSError as e:
        return -1, "", str(e)
    return result.returncode, result.stdout, result.stderr


def _require_windows_task_scheduler() -> None:
    if sys.platform != "win32":
        print("エラー: スケジュール機能は Windows でのみ利用できます。", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)


def cmd_snapshot_schedule_create(args: argparse.Namespace) -> None:
    """毎日実行する安全なスナップショットタスクを Windows に登録します。"""
    _require_windows_task_scheduler()
    snap_dir = _resolve_snapshot_dir(args)
    try:
        datetime.strptime(args.time, "%H:%M")
    except ValueError:
        print("エラー: --time は HH:MM (24時間形式) で指定してください。", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)
    if args.keep < 1:
        print("エラー: --keep は 1 以上にしてください。", file=sys.stderr)
        sys.exit(ExitCode.ARGUMENT_ERROR)
    args.dir = snap_dir
    task_name = _scheduled_task_name(args.name)
    if not getattr(args, "quiet", False):
        print(f"毎日 {args.time} に「{args.name}」をバックアップし、{args.keep} 世代を保持します。")
        print(f"  タスク名: {task_name}")
        print(f"  保存先: {snap_dir}")
    _confirm_or_exit("既存の同名タスクがあれば置き換えます。よろしいですか?", args.yes)
    rc, _out, err = _run_schtasks([
        "schtasks", "/create", "/tn", task_name, "/tr", _build_scheduled_snapshot_command(args),
        "/sc", "DAILY", "/st", args.time, "/f",
    ])
    if rc != 0:
        print(f"エラー: タスクの登録に失敗しました: {err.strip()}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    _print_action_result(args, "定期スナップショットを登録しました。", target=task_name)


def cmd_snapshot_schedule_list(args: argparse.Namespace) -> None:
    """WSLManager が登録した定期スナップショットタスクを表示します。"""
    _require_windows_task_scheduler()
    rc, out, err = _run_schtasks(["schtasks", "/query", "/fo", "LIST", "/v"])
    if rc != 0:
        print(f"エラー: タスク一覧の取得に失敗しました: {err.strip()}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    blocks = [block for block in out.split("\n\n") if "WSLManager-Snapshot-" in block]
    print("\n\n".join(blocks) if blocks else "定期スナップショットは登録されていません。")


def cmd_snapshot_schedule_delete(args: argparse.Namespace) -> None:
    """定期スナップショットタスクを削除します（バックアップデータは削除しない）。"""
    _require_windows_task_scheduler()
    task_name = _scheduled_task_name(args.name)
    if not getattr(args, "quiet", False):
        print(f"タスク「{task_name}」を削除します。バックアップデータは削除しません。")
    _confirm_or_exit("よろしいですか?", args.yes)
    rc, _out, err = _run_schtasks(["schtasks", "/delete", "/tn", task_name, "/f"])
    if rc != 0:
        print(f"エラー: タスクの削除に失敗しました: {err.strip()}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    _print_action_result(args, "定期スナップショットを削除しました。", target=task_name)


def cmd_snapshot_set_dir(args: argparse.Namespace) -> None:
    """スナップショットの保存先ディレクトリを設定します。"""
    path = args.path
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        print(f"エラー: ディレクトリを作成できませんでした: {e}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    settings_path = wsl_core.get_default_settings_path()
    settings = wsl_core.load_settings(settings_path)
    settings["snapshot_dir"] = os.path.abspath(path)
    ok = wsl_core.save_settings(settings_path, settings)
    if ok:
        _print_action_result(
            args,
            f"スナップショット保存先を「{settings['snapshot_dir']}」に設定しました。",
            target=settings["snapshot_dir"],
        )
    else:
        print("エラー: 設定の保存に失敗しました。", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)


def _make_snapshot_help_func(parser: argparse.ArgumentParser):
    """``wslmgr snapshot`` (サブサブコマンドなし) 実行時にヘルプを表示する関数を返します。"""
    def _cmd_snapshot_help(_args: argparse.Namespace) -> None:
        parser.print_help()
        sys.exit(ExitCode.SUCCESS)
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
        sys.exit(ExitCode.WSL_ERROR)

    distros = wsl_core.parse_distro_list(stdout)
    matched = next((d for d in distros if d["name"] == name), None)
    if matched is None:
        print(f"エラー: 「{name}」というディストリビューションが見つかりません。", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)
    version = str(matched.get("version") or "") or "2"

    existing = [d["name"] for d in distros]
    valid, reason = wsl_core.validate_clone_name(new_name, existing)
    if not valid:
        print(f"エラー: {reason}", file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    if not getattr(args, "quiet", False):
        print("次の内容で複製します。")
        print(f"  複製元: {name}")
        print(f"  複製先の名前: {new_name}")
        print(f"  複製先フォルダ: {install_path}")
        if os.path.exists(os.path.join(install_path, "ext4.vhdx")):
            print(
                f"警告: 「{install_path}」には既に仮想ディスク (ext4.vhdx) が存在します。"
                "上書きされます。"
            )
    _confirm_or_exit("よろしいですか?", args.yes)

    tmp_dir = tempfile.mkdtemp(prefix="wslmgr_clone_")
    tmp_tar = os.path.join(tmp_dir, wsl_core.sanitize_snapshot_name(new_name) + ".tar")
    try:
        if not getattr(args, "quiet", False):
            print(f"「{name}」を複製中… (1/2 エクスポート)")
        returncode, _stdout, stderr = _run_wsl_command(["--export", name, tmp_tar], timeout=1800.0)
        if returncode != 0:
            msg = stderr.strip() or "不明なエラー"
            _log_cli_operation("複製", f"{name} → {new_name}", msg)
            print(f"エラー: 「{name}」のエクスポートに失敗しました: {msg}", file=sys.stderr)
            sys.exit(ExitCode.WSL_ERROR)

        if not getattr(args, "quiet", False):
            print(f"「{name}」を複製中… (2/2 インポート)")
        returncode, _stdout, stderr = _run_wsl_command(
            ["--import", new_name, install_path, tmp_tar, "--version", version], timeout=1800.0
        )
        if returncode != 0:
            msg = stderr.strip() or "不明なエラー"
            _log_cli_operation("複製", f"{name} → {new_name}", msg)
            print(f"エラー: 「{new_name}」のインポートに失敗しました: {msg}", file=sys.stderr)
            sys.exit(ExitCode.WSL_ERROR)

        _log_cli_operation("複製", f"{name} → {new_name}", "成功")
        _print_action_result(
            args,
            f"「{name}」を「{new_name}」として複製しました。",
            target=f"{name} -> {new_name}",
            detail={"source": name, "target_distro": new_name, "install_path": install_path},
        )
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
# mount / unmount サブコマンド
# ---------------------------------------------------------------------------

def cmd_mount(args: argparse.Namespace) -> None:
    """物理ディスクまたは VHD を WSL2 にマウントします。"""
    mount_args = wsl_core.build_wsl_mount_args(
        disk=args.disk,
        bare=args.bare,
        fs_type=args.type,
        partition=args.partition,
        vhd=args.vhd,
        name=args.name,
    )
    returncode, _stdout, stderr = _run_wsl_command(mount_args, timeout=60.0)
    if returncode == 0:
        _log_cli_operation("マウント", args.disk, "成功")
        _print_action_result(args, f"「{args.disk}」をマウントしました。", target=args.disk)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("マウント", args.disk, msg)
        print(
            f"エラー: マウントに失敗しました: {msg}（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(ExitCode.WSL_ERROR)


def cmd_unmount(args: argparse.Namespace) -> None:
    """WSL2 にマウントされているディスクをアンマウントします。"""
    unmount_args = wsl_core.build_wsl_unmount_args(disk=args.disk)
    returncode, _stdout, stderr = _run_wsl_command(unmount_args, timeout=30.0)
    target = args.disk or "全マウントディスク"
    if returncode == 0:
        _log_cli_operation("アンマウント", target, "成功")
        _print_action_result(args, f"「{target}」をアンマウントしました。", target=target)
    else:
        msg = stderr.strip() or "不明なエラー"
        _log_cli_operation("アンマウント", target, msg)
        print(
            f"エラー: アンマウントに失敗しました: {msg}（管理者権限が必要な場合があります）",
            file=sys.stderr,
        )
        sys.exit(ExitCode.WSL_ERROR)


# ---------------------------------------------------------------------------
# エントリーポイント
# ---------------------------------------------------------------------------

def build_parser(language: str | None = None) -> argparse.ArgumentParser:
    """argparse のパーサーとサブコマンドを構築して返します。"""
    active_language = wsl_core.resolve_language(language)
    def t(key: str) -> str:
        return wsl_core.translate(key, active_language)
    parser = argparse.ArgumentParser(
        prog="wslmgr",
        description=t("cli.description"),
    )
    parser.add_argument(
        "--version", action="version", version=f"WSL Manager {wsl_core.__version__}"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help=t("cli.quiet")
    )
    parser.add_argument(
        "--language", choices=(wsl_core.LANGUAGE_AUTO, *wsl_core.SUPPORTED_LANGUAGES),
        default=language if language is not None else wsl_core.LANGUAGE_AUTO,
        help=t("cli.language"),
    )

    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help=t("cli.list"))
    p_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help=t("cli.format"),
    )
    p_list.add_argument(
        "--with-ip", action="store_true",
        help=t("cli.with_ip"),
    )
    p_list.add_argument(
        "--with-disk", action="store_true",
        help=t("cli.with_disk"),
    )
    p_list.add_argument(
        "--all-info", "-a", action="store_true",
        help=t("cli.all_info"),
    )
    p_list.set_defaults(func=cmd_list)

    # start
    p_start = subparsers.add_parser("start", help=t("cli.start"))
    p_start.add_argument("name", help=t("cli.arg.name"))
    p_start.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_start.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = subparsers.add_parser("stop", help=t("cli.stop"))
    p_stop.add_argument("name", help=t("cli.arg.name"))
    p_stop.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_stop.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_stop.set_defaults(func=cmd_stop)

    # shutdown
    p_shutdown = subparsers.add_parser(
        "shutdown", help=t("cli.shutdown")
    )
    p_shutdown.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_shutdown.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_shutdown.set_defaults(func=cmd_shutdown)

    # status
    p_status = subparsers.add_parser(
        "status", help=t("cli.status")
    )
    p_status.add_argument(
        "--format", choices=["table", "json"], default="table",
        help=t("cli.format"),
    )
    p_status.add_argument(
        "--with-disk", action="store_true", help=t("cli.with_disk"),
    )
    p_status.add_argument(
        "--all-info", "-a", action="store_true", help=t("cli.all_info"),
    )
    p_status.add_argument(
        "--strict", action="store_true", help="全ディストリで情報取得失敗時にエラー終了します"
    )
    p_status.set_defaults(func=cmd_status)

    # export
    p_export = subparsers.add_parser("export", help=t("cli.export"))
    p_export.add_argument("name", help=t("cli.arg.name"))
    p_export.add_argument("path", help=t("cli.arg.path"))
    p_export.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_export.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_export.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help=t("cli.import"))
    p_import.add_argument("name", help=t("cli.arg.name"))
    p_import.add_argument("install_path", help=t("cli.arg.install_path"))
    p_import.add_argument("image_path", help=t("cli.arg.image_path"))
    p_import.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_import.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_import.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_import.set_defaults(func=cmd_import)

    # config
    p_config = subparsers.add_parser(
        "config", help=t("cli.config")
    )
    p_config.add_argument(
        "--distro", "-d", help=t("cli.arg.distro_conf")
    )
    p_config.add_argument(
        "--format", choices=["table", "json"], default="table",
        help=t("cli.format"),
    )
    p_config.set_defaults(func=cmd_config)

    # set-default
    p_set_default = subparsers.add_parser(
        "set-default", help=t("cli.set_default")
    )
    p_set_default.add_argument("name", help=t("cli.arg.name"))
    p_set_default.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_set_default.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_set_default.set_defaults(func=cmd_set_default)

    # unregister
    p_unregister = subparsers.add_parser(
        "unregister", help=t("cli.unregister")
    )
    p_unregister.add_argument("name", help=t("cli.arg.name"))
    p_unregister.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_unregister.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_unregister.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_unregister.set_defaults(func=cmd_unregister)

    # install
    p_install = subparsers.add_parser("install", help=t("cli.install"))
    p_install.add_argument("name", help=t("cli.arg.name"))
    p_install.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_install.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_install.set_defaults(func=cmd_install)

    # optimize
    p_optimize = subparsers.add_parser(
        "optimize", help=t("cli.optimize")
    )
    p_optimize.add_argument("name", help=t("cli.arg.name"))
    optimize_group = p_optimize.add_mutually_exclusive_group(required=True)
    optimize_group.add_argument(
        "--sparse", action="store_true", help=t("cli.arg.optimize_sparse")
    )
    optimize_group.add_argument(
        "--compact", action="store_true", help=t("cli.arg.optimize_compact")
    )
    p_optimize.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_optimize.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_optimize.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_optimize.set_defaults(func=cmd_optimize)

    # set-version
    p_set_version = subparsers.add_parser(
        "set-version", help=t("cli.set_version")
    )
    p_set_version.add_argument("name", help=t("cli.arg.name"))
    p_set_version.add_argument(
        "version", choices=["1", "2"], help=t("cli.arg.version_choice")
    )
    p_set_version.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_set_version.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_set_version.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_set_version.set_defaults(func=cmd_set_version)

    # processes
    p_processes = subparsers.add_parser(
        "processes", help=t("cli.processes")
    )
    p_processes.add_argument("name", help=t("cli.arg.name"))
    p_processes.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help=t("cli.format"),
    )
    p_processes.set_defaults(func=cmd_processes)

    # log
    p_log = subparsers.add_parser("log", help=t("cli.log"))
    p_log_subparsers = p_log.add_subparsers(dest="log_command")

    # log show (default)
    p_log.add_argument(
        "--tail", type=int, default=50, help=t("cli.arg.log_tail")
    )
    p_log.add_argument(
        "--format", choices=["table", "json"], default="table",
        help=t("cli.format"),
    )
    p_log.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_log.set_defaults(func=cmd_log)

    p_log_clear = p_log_subparsers.add_parser("clear", help=t("cli.arg.log_clear"))
    p_log_clear.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_log_clear.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_log_clear.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_log_clear.set_defaults(func=cmd_log_clear)

    # portproxy
    p_portproxy = subparsers.add_parser(
        "portproxy", help=t("cli.portproxy")
    )
    p_portproxy.set_defaults(func=_make_portproxy_help_func(p_portproxy))
    portproxy_subparsers = p_portproxy.add_subparsers(dest="portproxy_command")

    p_portproxy_list = portproxy_subparsers.add_parser(
        "list", help="ポートフォワーディングルールの一覧を表示します"
    )
    p_portproxy_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help=t("cli.format"),
    )
    p_portproxy_list.set_defaults(func=cmd_portproxy_list)

    p_portproxy_add = portproxy_subparsers.add_parser(
        "add", help="ポートフォワーディングルールを追加します"
    )
    p_portproxy_add.add_argument("listen_port", help=t("cli.arg.portproxy_listen_port"))
    p_portproxy_add.add_argument("connect_port", help=t("cli.arg.portproxy_connect_port"))
    p_portproxy_add.add_argument(
        "--connect-address", required=True, help=t("cli.arg.portproxy_connect_address")
    )
    p_portproxy_add.add_argument(
        "--listen-address", default="0.0.0.0", help=t("cli.arg.portproxy_listen_address")
    )
    p_portproxy_add.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_portproxy_add.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_portproxy_add.set_defaults(func=cmd_portproxy_add)

    p_portproxy_delete = portproxy_subparsers.add_parser(
        "delete", help="ポートフォワーディングルールを削除します"
    )
    p_portproxy_delete.add_argument("listen_port", help=t("cli.arg.portproxy_listen_port"))
    p_portproxy_delete.add_argument(
        "--listen-address", default="0.0.0.0", help=t("cli.arg.portproxy_listen_address")
    )
    p_portproxy_delete.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_portproxy_delete.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_portproxy_delete.set_defaults(func=cmd_portproxy_delete)

    # snapshot
    p_snapshot = subparsers.add_parser(
        "snapshot", help=t("cli.snapshot")
    )
    p_snapshot.set_defaults(func=_make_snapshot_help_func(p_snapshot))
    snapshot_subparsers = p_snapshot.add_subparsers(dest="snapshot_command")

    p_snapshot_create = snapshot_subparsers.add_parser(
        "create", help="ディストリビューションのスナップショットを作成します"
    )
    p_snapshot_create.add_argument("name", help=t("cli.arg.name"))
    p_snapshot_create.add_argument(
        "--comment", default="", help=t("cli.arg.snapshot_comment")
    )
    p_snapshot_create.add_argument(
        "--keep", type=int, help=t("cli.arg.snapshot_keep")
    )
    p_snapshot_create.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_snapshot_create.add_argument(
        "--dir", help=t("cli.arg.snapshot_dir")
    )
    p_snapshot_create.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_snapshot_create.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_snapshot_create.set_defaults(func=cmd_snapshot_create)

    p_snapshot_list = snapshot_subparsers.add_parser(
        "list", help="スナップショットの一覧を表示します"
    )
    p_snapshot_list.add_argument("--dir", help=t("cli.arg.snapshot_dir"))
    p_snapshot_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help=t("cli.format"),
    )
    p_snapshot_list.set_defaults(func=cmd_snapshot_list)

    p_snapshot_restore = snapshot_subparsers.add_parser(
        "restore", help="スナップショットを新しいディストリビューションとして復元します"
    )
    p_snapshot_restore.add_argument("tar_file", help=t("cli.arg.snapshot_tar_file"))
    p_snapshot_restore.add_argument(
        "--install-path", required=True, help=t("cli.arg.install_path")
    )
    p_snapshot_restore.add_argument(
        "--name", help=t("cli.arg.snapshot_restore_name")
    )
    p_snapshot_restore.add_argument(
        "--dir", help=t("cli.arg.snapshot_dir")
    )
    p_snapshot_restore.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_snapshot_restore.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_snapshot_restore.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_snapshot_restore.set_defaults(func=cmd_snapshot_restore)

    p_snapshot_delete = snapshot_subparsers.add_parser(
        "delete", help="スナップショットを削除します"
    )
    p_snapshot_delete.add_argument(
        "tar_file", help=t("cli.arg.snapshot_tar_file")
    )
    p_snapshot_delete.add_argument(
        "--dir", help=t("cli.arg.snapshot_dir")
    )
    p_snapshot_delete.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_snapshot_delete.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_snapshot_delete.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_snapshot_delete.set_defaults(func=cmd_snapshot_delete)

    p_snapshot_prune = snapshot_subparsers.add_parser(
        "prune", help="保持数を超えたスナップショットを確認・削除します"
    )
    p_snapshot_prune.add_argument(
        "--keep", type=int, required=True, help=t("cli.arg.snapshot_keep")
    )
    p_snapshot_prune.add_argument("--name", help=t("cli.arg.name"))
    p_snapshot_prune.add_argument("--dir", help=t("cli.arg.snapshot_dir"))
    p_snapshot_prune.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_snapshot_prune.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_snapshot_prune.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_snapshot_prune.set_defaults(func=cmd_snapshot_prune)

    p_snapshot_schedule = snapshot_subparsers.add_parser(
        "schedule", help="Windows Task Scheduler に定期スナップショットを登録します"
    )
    p_snapshot_schedule.set_defaults(func=_make_snapshot_help_func(p_snapshot_schedule))
    schedule_subparsers = p_snapshot_schedule.add_subparsers(dest="schedule_command")
    p_schedule_create = schedule_subparsers.add_parser(
        "create", help="毎日の定期スナップショットを登録します"
    )
    p_schedule_create.add_argument("name", help=t("cli.arg.name"))
    p_schedule_create.add_argument("--time", default="03:00", help="実行時刻 HH:MM (既定: 03:00)")
    p_schedule_create.add_argument("--keep", type=int, default=7, help="保持する世代数 (既定: 7)")
    p_schedule_create.add_argument(
        "--dir", help=t("cli.arg.snapshot_dir")
    )
    p_schedule_create.add_argument("--yes", "-y", action="store_true", help=t("cli.arg.yes"))
    p_schedule_create.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_schedule_create.set_defaults(func=cmd_snapshot_schedule_create)
    p_schedule_list = schedule_subparsers.add_parser(
        "list", help="登録済みの定期スナップショットを表示します"
    )
    p_schedule_list.set_defaults(func=cmd_snapshot_schedule_list)
    p_schedule_delete = schedule_subparsers.add_parser(
        "delete", help="定期スナップショットを削除します"
    )
    p_schedule_delete.add_argument("name", help=t("cli.arg.name"))
    p_schedule_delete.add_argument("--yes", "-y", action="store_true", help=t("cli.arg.yes"))
    p_schedule_delete.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_schedule_delete.set_defaults(func=cmd_snapshot_schedule_delete)

    p_snapshot_set_dir = snapshot_subparsers.add_parser(
        "set-dir", help="スナップショットの保存先ディレクトリを設定します"
    )
    p_snapshot_set_dir.add_argument("path", help=t("cli.arg.path"))
    p_snapshot_set_dir.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_snapshot_set_dir.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_snapshot_set_dir.set_defaults(func=cmd_snapshot_set_dir)

    # clone
    p_clone = subparsers.add_parser(
        "clone", help=t("cli.clone")
    )
    p_clone.add_argument("name", help=t("cli.arg.name"))
    p_clone.add_argument("new_name", help=t("cli.arg.clone_new_name"))
    p_clone.add_argument("--install-path", required=True, help=t("cli.arg.install_path"))
    p_clone.add_argument(
        "--yes", "-y", action="store_true", help=t("cli.arg.yes")
    )
    p_clone.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_clone.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_clone.set_defaults(func=cmd_clone)

    # mount
    p_mount = subparsers.add_parser("mount", help=t("cli.mount"))
    p_mount.add_argument(
        "disk", help=t("cli.arg.mount_disk")
    )
    p_mount.add_argument(
        "--bare", action="store_true",
        help=t("cli.arg.mount_bare"),
    )
    p_mount.add_argument(
        "--vhd", action="store_true", help=t("cli.arg.mount_vhd")
    )
    p_mount.add_argument("--type", "-t", help=t("cli.arg.mount_type"))
    p_mount.add_argument("--partition", "-p", type=int, help=t("cli.arg.mount_partition"))
    p_mount.add_argument("--name", help=t("cli.arg.mount_name"))
    p_mount.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_mount.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_mount.set_defaults(func=cmd_mount)

    # unmount
    p_unmount = subparsers.add_parser(
        "unmount", help=t("cli.unmount")
    )
    p_unmount.add_argument(
        "disk", nargs="?", default=None,
        help=t("cli.arg.unmount_disk"),
    )
    p_unmount.add_argument(
        "--format", choices=["table", "json"], default="table", help=t("cli.format")
    )
    p_unmount.add_argument("--quiet", "-q", action="store_true", help=t("cli.quiet"))
    p_unmount.set_defaults(func=cmd_unmount)

    return parser


def _language_preference_from_argv(argv: list[str]) -> str:
    """Read a global ``--language`` override before building localized help text."""
    for index, value in enumerate(argv):
        if value.startswith("--language="):
            return value.partition("=")[2]
        if value == "--language" and index + 1 < len(argv):
            return argv[index + 1]
    settings = wsl_core.load_settings(wsl_core.get_default_settings_path())
    return str(settings.get("language", wsl_core.LANGUAGE_AUTO))


def main() -> None:
    preference = _language_preference_from_argv(sys.argv[1:])
    parser = build_parser(preference)
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(ExitCode.SUCCESS)
    args.func(args)


if __name__ == "__main__":
    main()
