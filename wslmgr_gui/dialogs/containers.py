"""WSL Containers (WSLc) 管理ダイアログ。"""

from __future__ import annotations

import json
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import TYPE_CHECKING

import wsl_core

if TYPE_CHECKING:
    from wslmgr import WSLManager


class ContainerManagerDialog(tk.Toplevel):
    """Read-only view of explicitly selected, existing WSLc sessions."""

    def __init__(self, parent: WSLManager) -> None:
        super().__init__(parent)
        self._language = getattr(parent, "_language", wsl_core.LANGUAGE_AUTO)
        self._results = queue.SimpleQueue()
        self._busy = False
        self._closed = False
        self._poll_id = None
        self._row_session = ""
        self.title("WSL Containers")
        self.geometry("900x450")
        self.minsize(600, 300)
        self.transient(parent)
        self.protocol("WM_DELETE_WINDOW", self.destroy)

        frame = ttk.Frame(self, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)
        self._status = tk.StringVar()
        ttk.Label(frame, textvariable=self._status, wraplength=820).pack(anchor=tk.W)
        options = ttk.Frame(frame)
        options.pack(fill=tk.X, pady=8)
        ttk.Label(options, text=self._t("containers.session")).pack(side=tk.LEFT)
        self._session = tk.StringVar()
        self._sessions = ttk.Combobox(
            options, textvariable=self._session, state="readonly", width=36
        )
        self._sessions.pack(side=tk.LEFT, padx=6)
        self._sessions.bind("<<ComboboxSelected>>", lambda _e: self._reload())
        self._all = tk.BooleanVar(value=False)
        self._all_button = ttk.Checkbutton(
            options, text=self._t("containers.all"), variable=self._all, command=self._reload
        )
        self._all_button.pack(side=tk.LEFT)
        columns = ("id", "name", "image", "status", "health", "created")
        table = ttk.Frame(frame)
        table.pack(fill=tk.BOTH, expand=True)
        self._tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse")
        for key in columns:
            self._tree.heading(key, text="ID" if key == "id" else self._t(f"containers.{key}"))
            self._tree.column(key, width=140, anchor=tk.W)
        vertical = ttk.Scrollbar(table, orient=tk.VERTICAL, command=self._tree.yview)
        horizontal = ttk.Scrollbar(table, orient=tk.HORIZONTAL, command=self._tree.xview)
        self._tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vertical.grid(row=0, column=1, sticky="ns")
        horizontal.grid(row=1, column=0, sticky="ew")
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self._tree.bind("<Double-1>", self._show_inspect)
        buttons = ttk.Frame(frame)
        buttons.pack(fill=tk.X, pady=(8, 0))
        self._refresh_button = ttk.Button(
            buttons, text=self._t("gui.common.refresh"), command=self._reload
        )
        self._refresh_button.pack(side=tk.LEFT)
        self._inspect_button = ttk.Button(
            buttons, text=self._t("containers.inspect"), command=self._show_inspect
        )
        self._inspect_button.pack(side=tk.LEFT, padx=6)
        ttk.Button(buttons, text=self._t("gui.common.close"), command=self.destroy).pack(
            side=tk.RIGHT
        )
        self._reload()

    def _t(self, key: str, **values: object) -> str:
        return wsl_core.translate(key, self._language, **values)

    def _start_task(self, work: Callable, done: Callable) -> None:
        if self._busy or self._closed:
            return
        self._busy = True
        for widget in (
            self._refresh_button,
            self._inspect_button,
            self._all_button,
            self._sessions,
        ):
            widget.configure(state="disabled")
        self._status.set(self._t("containers.loading"))
        results = self._results

        def run() -> None:
            try:
                results.put((done, work(), None))
            except Exception as exc:
                results.put((done, None, str(exc)))

        threading.Thread(target=run, daemon=True).start()
        self._poll_id = self.after(50, self._poll_result)

    def _poll_result(self) -> None:
        self._poll_id = None
        if self._closed:
            return
        try:
            done, value, error = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.after(50, self._poll_result)
            return
        self._busy = False
        for widget in (self._refresh_button, self._inspect_button, self._all_button):
            widget.configure(state="normal")
        self._sessions.configure(state="readonly")
        if error is not None:
            self._status.set(self._t("containers.error", error=error))
        else:
            done(value)

    def destroy(self) -> None:
        self._closed = True
        if self._poll_id is not None:
            self.after_cancel(self._poll_id)
            self._poll_id = None
        super().destroy()

    def _reload(self) -> None:
        if self._busy or self._closed:
            return
        session, include_all = self._session.get(), self._all.get()
        self._row_session = ""
        for item in self._tree.get_children():
            self._tree.delete(item)

        def work():
            client = wsl_core.WslcClient()
            info = client.system_info()
            names = [item["Name"] for item in info["Server"]["Sessions"]]
            selected = session if session in names else (names[0] if len(names) == 1 else "")
            records = (
                client.list_containers(selected, all_containers=include_all) if selected else []
            )
            return names, selected, records

        def done(result):
            names, selected, records = result
            self._sessions.configure(values=names)
            self._session.set(selected)
            self._row_session = selected
            for record in records:
                row = wsl_core.container_summary(record)
                self._tree.insert("", tk.END, values=tuple(row.values()))
            key = (
                "containers.count"
                if selected
                else "containers.select"
                if names
                else "containers.none"
            )
            self._status.set(self._t(key, count=len(records)))

        self._start_task(work, done)

    def _show_inspect(self, _event: object | None = None) -> None:
        if self._busy or self._closed:
            return
        selection = self._tree.selection()
        if not selection or not self._row_session:
            return
        values = self._tree.item(selection[0], "values")
        name = next((str(v) for v in (values[0], values[1]) if v and str(v) != "-"), "")
        if not name:
            self._status.set(self._t("containers.missing_id"))
            return
        session = self._row_session

        def work():
            return wsl_core.WslcClient().inspect_container(session, name)

        def done(records):
            dialog = tk.Toplevel(self)
            dialog.title(self._t("containers.inspect"))
            dialog.geometry("760x500")
            text = tk.Text(dialog, wrap=tk.NONE)
            scroll = ttk.Scrollbar(dialog, command=text.yview)
            scroll.pack(side=tk.RIGHT, fill=tk.Y)
            text.configure(yscrollcommand=scroll.set)
            text.pack(fill=tk.BOTH, expand=True)
            text.insert("1.0", json.dumps(records, ensure_ascii=False, indent=2))
            text.configure(state="disabled")
            self._status.set(self._t("containers.inspected"))

        self._start_task(work, done)
