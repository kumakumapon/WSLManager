"""
wsl_core.portproxy - ポートフォワーディング・ネットワーク関連ユーティリティモジュール
"""

from __future__ import annotations

import re

_SS_PROCESS_RE = re.compile(r'users:\(\("([^"]+)"')


def parse_portproxy_output(output: str) -> list[dict]:
    """``netsh interface portproxy show all`` のテキスト出力を解析してルール一覧を返します。

    出力には "Listen on ipv4:" のようなヘッダ行、列名行 (Address / Port ...)、
    区切り線 (---- ...)、空行が含まれるため、それらはスキップします。
    実データ行は ``listen_address listen_port connect_address connect_port`` の
    4フィールドで構成されることを想定し、空白区切りで分割します。
    返り値の各 dict のキーは listen_address, listen_port(int),
    connect_address, connect_port(int) です。
    ``output`` が空文字または None の場合は空リストを返します。
    """
    if not output:
        return []
    rules: list[dict] = []
    for raw_line in output.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("Listen on") or line.startswith("Address"):
            continue
        # 区切り線 ("--------------- ----------  --------------- ----------") はスキップ
        if set(line.replace(" ", "")) <= {"-"}:
            continue
        parts = line.split()
        if len(parts) != 4:
            continue
        listen_address, listen_port_str, connect_address, connect_port_str = parts
        try:
            listen_port = int(listen_port_str)
            connect_port = int(connect_port_str)
        except ValueError:
            continue
        rules.append(
            {
                "listen_address": listen_address,
                "listen_port": listen_port,
                "connect_address": connect_address,
                "connect_port": connect_port,
            }
        )
    return rules


def parse_ss_output(output: str) -> list[dict]:
    """``ss -tlnp`` のテキスト出力を解析してリスニングソケット一覧を返します。

    先頭1行はヘッダ行としてスキップします。"Local Address:Port" フィールドは
    IPv4 (``addr:port``) と IPv6 (``[addr]:port``) の両方の形式に対応します。
    プロセス名は ``users:(("name",...))`` 形式から正規表現で抽出し、
    一致しない場合は元の文字列をそのまま使用します。
    返り値の各 dict のキーは state, local_address, local_port(int), process です。
    ``output`` が空文字または None の場合は空リストを返します。
    """
    if not output:
        return []
    results: list[dict] = []
    lines = output.splitlines()
    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("State") or line.startswith("Netid"):
            continue
        parts = line.split(None, 5)
        if len(parts) < 4:
            continue
        state = parts[0]
        local_field = parts[3]

        # IPv6: "[::]:22" 形式
        m = re.match(r"^\[(.+)\]:(\d+)$", local_field)
        if m:
            local_address = m.group(1)
            port_str = m.group(2)
        else:
            # IPv4: "0.0.0.0:22" 形式 (最後の ':' でポートを分離)
            if ":" not in local_field:
                continue
            local_address, _, port_str = local_field.rpartition(":")

        try:
            local_port = int(port_str)
        except ValueError:
            continue

        remainder = " ".join(parts[5:]) if len(parts) > 5 else ""
        proc_match = _SS_PROCESS_RE.search(remainder)
        if proc_match:
            process = proc_match.group(1)
        else:
            process = remainder.strip() if remainder.strip() else "-"

        results.append(
            {
                "state": state,
                "local_address": local_address,
                "local_port": local_port,
                "process": process,
            }
        )
    return results


def detect_network_mode(config: dict[str, dict[str, str]]) -> str:
    """.wslconfig の dict からネットワークモードを判定して返します。

    ``config["wsl2"]["networkingMode"]`` の値 (大小文字を区別しない) を確認します。
    値が "mirrored" であれば "mirrored" を返します。
    値が "nat" または空文字 (未設定) であれば "nat" を返します。
    それ以外の値の場合は、その値を小文字化したものをそのまま返します。
    """
    mode = config.get("wsl2", {}).get("networkingMode", "")
    normalized = mode.strip().lower()
    if normalized == "mirrored":
        return "mirrored"
    if normalized in ("", "nat"):
        return "nat"
    return normalized

