"""ディストリビューション一覧と、実行中ディストロの CPU・メモリ・IP の取得。"""

from __future__ import annotations

import concurrent.futures
import logging
import subprocess

import wsl_core
from wslmgr_gui.winutil import CREATE_NO_WINDOW, _get_distro_vhdx_sizes

logger = logging.getLogger(__name__)

# リソース使用量(CPU/メモリ)取得のタイムアウト秒数。
# VM 初期化直後や、ログインシェルの起動が重い/プロセス数が多い
# ディストリビューションでは 2 秒では応答が返らないことがあるため、
# 余裕を持たせた値にしている。
RESOURCE_QUERY_TIMEOUT = 8.0

# IP アドレス取得のタイムアウト秒数。理由は RESOURCE_QUERY_TIMEOUT と同様
# (VM 初期化直後 / ログインシェルが重い / プロセス数が多い場合に備える)。
IP_QUERY_TIMEOUT = 8.0


def get_distro_resource_usage(
    name: str, timeout: float = RESOURCE_QUERY_TIMEOUT
) -> tuple[str, str]:
    """指定ディストリビューションのCPU使用率(%)とメモリ使用量(MB)を返します。"""
    try:
        result = subprocess.run(
            [
                "wsl",
                "-d",
                name,
                "--",
                "sh",
                "-lc",
                (
                    "ps -eo pcpu=,rss= | "
                    "awk '{cpu+=$1; mem+=$2} END {printf \"%.1f %.1f\", cpu, mem/1024}'"
                ),
            ],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "-", "-"

    if result.returncode != 0:
        return "-", "-"

    output = wsl_core.decode_wsl_output(result.stdout).strip()
    return wsl_core.parse_resource_usage(output)


def get_distro_ip(name: str, timeout: float = IP_QUERY_TIMEOUT) -> str:
    """指定ディストリビューションの IP アドレスを返します。"""
    try:
        result = subprocess.run(
            ["wsl", "-d", name, "--", "hostname", "-I"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "-"
    if result.returncode != 0:
        return "-"
    output = wsl_core.decode_wsl_output(result.stdout).strip()
    ips = wsl_core.parse_ip_addresses(output)
    return ips[0] if ips else "-"


def get_distros() -> tuple[list[dict], str | None]:
    """``wsl --list --verbose`` を解析し、必要に応じてリソース情報も取得します。

    Returns:
        (distros, error_message) のタプル。
        成功時は distros にリストが入り error_message は None。
        失敗時は distros は空リストで error_message にメッセージが入ります。
    """
    try:
        result = subprocess.run(
            ["wsl", "--list", "--verbose"],
            capture_output=True,
            creationflags=CREATE_NO_WINDOW,
            timeout=15.0,
        )
    except subprocess.TimeoutExpired:
        return [], "WSL の応答がタイムアウトしました。"
    except FileNotFoundError:
        return [], "wsl.exe が見つかりません。WSL2 がインストールされているか確認してください。"
    except OSError as e:
        return [], f"WSL の実行に失敗しました: {e}"

    if result.returncode != 0:
        stderr = wsl_core.decode_wsl_output(result.stderr).strip()
        return [], stderr or "ディストリビューション一覧の取得に失敗しました。"

    output = wsl_core.decode_wsl_output(result.stdout)
    distros: list[dict] = wsl_core.parse_distro_list(output)

    # レジストリから仮想ディスク (ext4.vhdx) のサイズを取得する
    disk_sizes = _get_distro_vhdx_sizes()
    for d in distros:
        size = disk_sizes.get(d["name"])
        if size is not None:
            d["disk"] = f"{size:.1f}"

    # Running のディストロのリソース使用量を並列取得する
    running_distros = [d for d in distros if d["state"] == "Running"]
    if running_distros:
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            future_to_distro = {
                executor.submit(get_distro_resource_usage, d["name"]): d for d in running_distros
            }
            for future in concurrent.futures.as_completed(future_to_distro):
                distro = future_to_distro[future]
                try:
                    cpu, memory = future.result()
                except Exception:
                    # 1 ディストロの取得失敗で一覧更新全体を止めない。原因はデバッグログに残す。
                    logger.debug("リソース使用量の取得に失敗: %s", distro["name"], exc_info=True)
                    cpu, memory = "-", "-"
                distro["cpu"] = cpu
                distro["memory"] = memory

            ip_future_to_distro = {
                executor.submit(get_distro_ip, d["name"]): d for d in running_distros
            }
            for ip_future in concurrent.futures.as_completed(ip_future_to_distro):
                distro = ip_future_to_distro[ip_future]
                try:
                    distro["ip"] = ip_future.result()
                except Exception:
                    logger.debug("IP アドレスの取得に失敗: %s", distro["name"], exc_info=True)
                    distro["ip"] = "-"

    return distros, None
