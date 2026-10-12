"""ディストリビューション詳細情報ダイアログ。"""

from __future__ import annotations

import concurrent.futures
import os
import subprocess
import threading
import tkinter as tk
from tkinter import ttk

import wsl_core
from wslmgr_gui.winutil import CREATE_NO_WINDOW, _get_distro_vhdx_path


class DistroDetailDialog(tk.Toplevel):
    """ディストリビューションの詳細情報を表示するダイアログ。

    OS 情報 (/etc/os-release)、稼働時間 (uptime)、IP アドレス一覧、
    ディスク使用状況 (df) をバックグラウンドで取得して表示します。
    """

    def __init__(self, parent: tk.Tk, distro_name: str) -> None:
        super().__init__(parent)
        self._distro = distro_name
        self.title(
            wsl_core.translate(
                "gui.detail.title",
                getattr(parent, "_language", wsl_core.LANGUAGE_AUTO),
                name=distro_name,
            )
        )
        self.geometry("560x520")
        self.minsize(450, 400)
        self._build_ui()
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)
        self._fetch_all()

    def _build_ui(self) -> None:
        main = ttk.Frame(self, padding=12)
        main.pack(fill=tk.BOTH, expand=True)

        ttk.Label(main, text=self._distro, font=("", 13, "bold")).pack(anchor=tk.W, pady=(0, 8))

        # OS 情報セクション
        self._os_frame = self._section(main, "OS 情報")
        self._os_labels: dict[str, tk.StringVar] = {}
        for key, label in [
            ("PRETTY_NAME", "OS"),
            ("VERSION_ID", "バージョン"),
            ("ID", "ID"),
        ]:
            var = tk.StringVar(value="取得中…")
            self._os_labels[key] = var
            self._info_row(self._os_frame, label, var)

        self._uptime_var = tk.StringVar(value="取得中…")
        self._info_row(self._os_frame, "稼働時間", self._uptime_var)

        # ネットワークセクション
        net_frame = self._section(main, "ネットワーク")
        self._ip_var = tk.StringVar(value="取得中…")
        self._info_row(net_frame, "IPアドレス", self._ip_var)

        # ディスクセクション
        disk_frame = self._section(main, "ディスク使用量")
        self._vhdx_var = tk.StringVar(value="取得中…")
        self._info_row(disk_frame, "仮想ディスク", self._vhdx_var)

        # df テーブル
        df_tree_frame = ttk.Frame(disk_frame)
        df_tree_frame.pack(fill=tk.BOTH, expand=True, pady=(4, 0))

        cols = ("filesystem", "size", "used", "avail", "use_pct", "mount")
        self._df_tree = ttk.Treeview(
            df_tree_frame,
            columns=cols,
            show="headings",
            selectmode="none",
            height=5,
        )
        for cid, text, w in [
            ("filesystem", "ファイルシステム", 130),
            ("size", "サイズ", 80),
            ("used", "使用", 80),
            ("avail", "空き", 80),
            ("use_pct", "使用率", 60),
            ("mount", "マウント先", 100),
        ]:
            self._df_tree.heading(cid, text=text)
            self._df_tree.column(
                cid,
                width=w,
                minwidth=50,
                anchor=tk.CENTER if cid != "filesystem" and cid != "mount" else tk.W,
            )
        vsb = ttk.Scrollbar(df_tree_frame, orient=tk.VERTICAL, command=self._df_tree.yview)
        self._df_tree.configure(yscrollcommand=vsb.set)
        self._df_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)

        # ステータス
        self._status_var = tk.StringVar(value="情報を取得中…")
        ttk.Label(
            main,
            textvariable=self._status_var,
            relief=tk.SUNKEN,
            anchor=tk.W,
            padding=(4, 2),
        ).pack(fill=tk.X, pady=(8, 0))

        btn_frame = ttk.Frame(main)
        btn_frame.pack(fill=tk.X, pady=(6, 0))
        ttk.Button(btn_frame, text="更新", command=self._fetch_all, width=8).pack(
            side=tk.RIGHT, padx=(4, 0)
        )
        ttk.Button(btn_frame, text="閉じる", command=self.destroy, width=8).pack(side=tk.RIGHT)

    @staticmethod
    def _section(parent: ttk.Frame, title: str) -> ttk.Frame:
        ttk.Separator(parent, orient=tk.HORIZONTAL).pack(fill=tk.X, pady=(6, 4))
        ttk.Label(parent, text=title, font=("", 10, "bold")).pack(anchor=tk.W, pady=(0, 2))
        frame = ttk.Frame(parent)
        frame.pack(fill=tk.BOTH, expand=True, padx=(8, 0))
        return frame

    @staticmethod
    def _info_row(parent: ttk.Frame, label: str, var: tk.StringVar) -> None:
        row = ttk.Frame(parent)
        row.pack(fill=tk.X, pady=1)
        ttk.Label(row, text=f"{label}:", width=14, anchor=tk.W).pack(side=tk.LEFT)
        ttk.Label(row, textvariable=var, anchor=tk.W).pack(side=tk.LEFT, fill=tk.X, expand=True)

    def _fetch_all(self) -> None:
        self._status_var.set("情報を取得中…")
        distro = self._distro

        def _run() -> dict:
            data: dict = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                fut_os = pool.submit(self._cmd, distro, "cat /etc/os-release 2>/dev/null")
                fut_up = pool.submit(self._cmd, distro, "uptime -p 2>/dev/null || uptime")
                fut_ip = pool.submit(self._cmd, distro, "hostname -I 2>/dev/null")
                fut_df = pool.submit(self._cmd, distro, "df -B1 2>/dev/null || df -k")

                data["os"] = wsl_core.parse_os_release(fut_os.result())
                data["uptime"] = wsl_core.parse_uptime(fut_up.result())
                data["ips"] = wsl_core.parse_ip_addresses(fut_ip.result())
                data["df"] = wsl_core.parse_disk_usage(fut_df.result())

            vhdx = _get_distro_vhdx_path(distro)
            if vhdx:
                try:
                    size = os.path.getsize(vhdx) / (1024**3)
                    data["vhdx"] = f"{size:.2f} GB ({os.path.basename(vhdx)})"
                except OSError:
                    data["vhdx"] = f"サイズ取得不可 ({vhdx})"
            else:
                data["vhdx"] = "VHD なし (WSL1 の可能性)"
            return data

        def _run_and_apply() -> None:
            try:
                data = _run()
            except Exception as exc:
                err_text = str(exc)
                self.after(0, lambda: self._on_error(err_text))
                return
            self.after(0, lambda: self._apply(data))

        threading.Thread(target=_run_and_apply, daemon=True).start()

    @staticmethod
    def _cmd(distro: str, cmd: str) -> str:
        try:
            result = subprocess.run(
                ["wsl", "-d", distro, "--", "sh", "-lc", cmd],
                capture_output=True,
                creationflags=CREATE_NO_WINDOW,
                timeout=5.0,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        return wsl_core.decode_wsl_output(result.stdout).strip()

    def _apply(self, data: dict) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return

        os_info = data.get("os", {})
        for key, var in self._os_labels.items():
            var.set(os_info.get(key, "-"))

        self._uptime_var.set(data.get("uptime", "-"))

        ips = data.get("ips", [])
        self._ip_var.set(", ".join(ips) if ips else "-")

        self._vhdx_var.set(data.get("vhdx", "-"))

        for item in self._df_tree.get_children():
            self._df_tree.delete(item)
        for entry in data.get("df", []):
            self._df_tree.insert(
                "",
                tk.END,
                values=(
                    entry["filesystem"],
                    wsl_core.format_bytes(entry["total"]),
                    wsl_core.format_bytes(entry["used"]),
                    wsl_core.format_bytes(entry["available"]),
                    entry["use_percent"],
                    entry["mount_point"],
                ),
            )

        self._status_var.set("取得完了")

    def _on_error(self, msg: str) -> None:
        try:
            if self.winfo_exists():
                self._status_var.set(f"エラー: {msg}")
        except tk.TclError:
            pass
