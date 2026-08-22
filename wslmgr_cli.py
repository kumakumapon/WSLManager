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
        msg = stderr.strip() or "ディストリビューション一覧の取得に失敗しました。"
        print(f"エラー: {msg}", file=sys.stderr)
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

    headers = ["Name", "State", "Version", "Default"]
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
        _log_cli_operation(
            "スナップショット削除", snap.get("tar_file", args.tar_file), "; ".join(errors)
        )
        print("エラー: 削除に失敗しました: " + "; ".join(errors), file=sys.stderr)
        sys.exit(ExitCode.GENERAL_ERROR)

    _log_cli_operation("スナップショット削除", snap.get("tar_file", args.tar_file), "成功")
    _print_action_result(args, "削除しました。", target=snap.get("tar_file", args.tar_file))


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

def build_parser() -> argparse.ArgumentParser:
    """argparse のパーサーとサブコマンドを構築して返します。"""
    parser = argparse.ArgumentParser(
        prog="wslmgr",
        description="WSL Manager - コマンドラインインターフェース",
    )
    parser.add_argument(
        "--version", action="version", version=f"WSL Manager {wsl_core.__version__}"
    )
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="成功時のメッセージ出力を抑制します"
    )

    subparsers = parser.add_subparsers(dest="command")

    # list
    p_list = subparsers.add_parser("list", help="WSL ディストリビューションの一覧を表示します")
    p_list.add_argument(
        "--format", choices=["table", "json", "csv"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_list.add_argument(
        "--with-ip", action="store_true",
        help="実行中ディストリビューションの IP アドレスも取得します",
    )
    p_list.add_argument(
        "--with-disk", action="store_true",
        help="実行中ディストリビューションのディスク使用量も取得します",
    )
    p_list.add_argument(
        "--all-info", "-a", action="store_true",
        help="IP アドレスおよびディスク使用量を含めて表示します",
    )
    p_list.set_defaults(func=cmd_list)

    # start
    p_start = subparsers.add_parser("start", help="ディストリビューションを起動します")
    p_start.add_argument("name", help="ディストリビューション名")
    p_start.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_start.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_start.set_defaults(func=cmd_start)

    # stop
    p_stop = subparsers.add_parser("stop", help="ディストリビューションを停止します")
    p_stop.add_argument("name", help="ディストリビューション名")
    p_stop.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_stop.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_stop.set_defaults(func=cmd_stop)

    # shutdown
    p_shutdown = subparsers.add_parser(
        "shutdown", help="すべてのディストリビューションを停止します"
    )
    p_shutdown.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_shutdown.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_shutdown.set_defaults(func=cmd_shutdown)

    # status
    p_status = subparsers.add_parser(
        "status", help="実行中ディストリビューションのリソース使用状況を表示します"
    )
    p_status.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_status.add_argument(
        "--with-disk", action="store_true", help="ディスク使用量も取得します"
    )
    p_status.add_argument(
        "--all-info", "-a", action="store_true", help="すべてのリソース情報を取得します"
    )
    p_status.add_argument(
        "--strict", action="store_true", help="全ディストリで情報取得失敗時にエラー終了します"
    )
    p_status.set_defaults(func=cmd_status)

    # export
    p_export = subparsers.add_parser("export", help="ディストリビューションをエクスポートします")
    p_export.add_argument("name", help="ディストリビューション名")
    p_export.add_argument("path", help="エクスポート先のファイルパス")
    p_export.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_export.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_export.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_export.set_defaults(func=cmd_export)

    # import
    p_import = subparsers.add_parser("import", help="ディストリビューションをインポートします")
    p_import.add_argument("name", help="ディストリビューション名")
    p_import.add_argument("install_path", help="インストール先ディレクトリ")
    p_import.add_argument("image_path", help="インポートするイメージ (tar) のパス")
    p_import.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_import.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_import.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_import.set_defaults(func=cmd_import)

    # config
    p_config = subparsers.add_parser(
        "config", help="現在の .wslconfig または /etc/wsl.conf 設定を表示します"
    )
    p_config.add_argument(
        "--distro", "-d", help="指定したディストリビューションの /etc/wsl.conf を参照します"
    )
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
    p_set_default.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_set_default.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_set_default.set_defaults(func=cmd_set_default)

    # unregister
    p_unregister = subparsers.add_parser(
        "unregister", help="ディストリビューションをアンインストール (登録解除) します"
    )
    p_unregister.add_argument("name", help="ディストリビューション名")
    p_unregister.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_unregister.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_unregister.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_unregister.set_defaults(func=cmd_unregister)

    # install
    p_install = subparsers.add_parser("install", help="ディストリビューションをインストールします")
    p_install.add_argument("name", help="ディストリビューション名")
    p_install.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_install.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
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
    p_optimize.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_optimize.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_optimize.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
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
    p_set_version.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_set_version.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
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
    p_log = subparsers.add_parser("log", help="保存されている操作ログを表示・消去します")
    p_log_subparsers = p_log.add_subparsers(dest="log_command")

    # log show (default)
    p_log.add_argument(
        "--tail", type=int, default=50, help="表示する末尾のエントリ数 (既定: 50)"
    )
    p_log.add_argument(
        "--format", choices=["table", "json"], default="table",
        help="出力フォーマット (既定: table)",
    )
    p_log.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_log.set_defaults(func=cmd_log)

    p_log_clear = p_log_subparsers.add_parser("clear", help="操作ログをすべて消去します")
    p_log_clear.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_log_clear.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_log_clear.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_log_clear.set_defaults(func=cmd_log_clear)

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
    p_portproxy_add.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_portproxy_add.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_portproxy_add.set_defaults(func=cmd_portproxy_add)

    p_portproxy_delete = portproxy_subparsers.add_parser(
        "delete", help="ポートフォワーディングルールを削除します"
    )
    p_portproxy_delete.add_argument("listen_port", help="リッスンするポート番号")
    p_portproxy_delete.add_argument(
        "--listen-address", default="0.0.0.0", help="リッスンする IP アドレス (既定: 0.0.0.0)"
    )
    p_portproxy_delete.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_portproxy_delete.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
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
    p_snapshot_create.add_argument(
        "--comment", default="", help="スナップショットのコメント (任意)"
    )
    p_snapshot_create.add_argument(
        "--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)"
    )
    p_snapshot_create.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_snapshot_create.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
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
    p_snapshot_restore.add_argument(
        "--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)"
    )
    p_snapshot_restore.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_snapshot_restore.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_snapshot_restore.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_snapshot_restore.set_defaults(func=cmd_snapshot_restore)

    p_snapshot_delete = snapshot_subparsers.add_parser(
        "delete", help="スナップショットを削除します"
    )
    p_snapshot_delete.add_argument(
        "tar_file", help="削除するスナップショットの tar ファイル名"
    )
    p_snapshot_delete.add_argument(
        "--dir", help="スナップショット保存先ディレクトリ (既定: 設定値)"
    )
    p_snapshot_delete.add_argument(
        "--yes", "-y", action="store_true", help="確認プロンプトを表示せずに実行します"
    )
    p_snapshot_delete.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_snapshot_delete.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_snapshot_delete.set_defaults(func=cmd_snapshot_delete)

    p_snapshot_set_dir = snapshot_subparsers.add_parser(
        "set-dir", help="スナップショットの保存先ディレクトリを設定します"
    )
    p_snapshot_set_dir.add_argument("path", help="保存先ディレクトリのパス")
    p_snapshot_set_dir.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_snapshot_set_dir.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_snapshot_set_dir.set_defaults(func=cmd_snapshot_set_dir)

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
    p_clone.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_clone.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_clone.set_defaults(func=cmd_clone)

    # mount
    p_mount = subparsers.add_parser("mount", help="物理ディスクまたは VHD を WSL2 にマウントします")
    p_mount.add_argument(
        "disk", help="マウントするディスク（物理ドライブパスまたは VHDX ファイルパス）"
    )
    p_mount.add_argument(
        "--bare", action="store_true",
        help="ディスクを WSL にアタッチするのみでファイルシステムのマウントを行いません",
    )
    p_mount.add_argument(
        "--vhd", action="store_true", help="指定したディスクが VHD/VHDX であることを明示します"
    )
    p_mount.add_argument("--type", "-t", help="ファイルシステムの種類 (例: ext4)")
    p_mount.add_argument("--partition", "-p", type=int, help="マウントするパーティション番号")
    p_mount.add_argument("--name", help="カスタムマウント名")
    p_mount.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_mount.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_mount.set_defaults(func=cmd_mount)

    # unmount
    p_unmount = subparsers.add_parser(
        "unmount", help="WSL2 にマウントされているディスクをアンマウントします"
    )
    p_unmount.add_argument(
        "disk", nargs="?", default=None,
        help="アンマウントするディスクパス（省略時は全マウントディスク）",
    )
    p_unmount.add_argument(
        "--format", choices=["table", "json"], default="table", help="出力フォーマット"
    )
    p_unmount.add_argument("--quiet", "-q", action="store_true", help="出力を抑制します")
    p_unmount.set_defaults(func=cmd_unmount)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if not hasattr(args, "func"):
        parser.print_help()
        sys.exit(ExitCode.SUCCESS)
    args.func(args)


if __name__ == "__main__":
    main()
