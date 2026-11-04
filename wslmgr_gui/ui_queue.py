"""バックグラウンドスレッドから Tk のメインスレッドへ処理を渡すキュー。

tkinter のウィジェットはメインスレッド以外から触ってはいけない。従来は
ワーカースレッドから ``widget.after(0, fn)`` を呼んでいたが、これは Tcl が
スレッド対応でビルドされ、かつ tkinter がそれを検出できる場合にしか動かない
(例: Tcl/Tk 9 と組み合わせた一部の Python では、``after`` が呼び出し元スレッドの
イベントキューに登録されてコールバックが永遠に実行されない。メインループ開始前に
呼ぶと ``RuntimeError`` になることもある)。

ここでは、ワーカーは :func:`post_to_ui` でスレッドセーフなキューに積むだけにし、
メインスレッドが ``after`` で定期的にキューを取り出して実行する。Tk の API を
触るのは常にメインスレッドだけになる。
"""

from __future__ import annotations

import logging
import queue
import sys
import tkinter as tk
from collections.abc import Callable

logger = logging.getLogger(__name__)

# ルートウィンドウにキューを保持させる属性名
_ATTR = "_wslmgr_ui_queue"

# キューを確認する間隔 (ミリ秒)。体感の遅延にならず、アイドル時の負荷も無視できる値。
POLL_INTERVAL_MS = 30

# 1 回の確認で実行する最大件数。大量に積まれても UI を長時間ふさがない。
MAX_CALLBACKS_PER_TICK = 50


class UiQueue:
    """ルートウィンドウ 1 つにつき 1 個。メインスレッドで生成すること。"""

    def __init__(self, root: tk.Misc, interval_ms: int = POLL_INTERVAL_MS) -> None:
        self._root = root
        self._interval_ms = interval_ms
        self._queue: queue.SimpleQueue[tuple[tk.Misc | None, Callable[[], None]]] = (
            queue.SimpleQueue()
        )
        self._job: str | None = None
        self._closed = False
        setattr(root, _ATTR, self)
        self._schedule()

    def post(self, widget: tk.Misc | None, fn: Callable[[], None]) -> None:
        """どのスレッドからでも呼べる。``widget`` が破棄済みなら ``fn`` は実行しない。"""
        if not self._closed:
            self._queue.put((widget, fn))

    def close(self) -> None:
        """以降の投入を捨て、定期確認を止める (ウィンドウを閉じる直前に呼ぶ)。"""
        self._closed = True
        if self._job is not None:
            try:
                self._root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _schedule(self) -> None:
        try:
            self._job = self._root.after(self._interval_ms, self._drain)
        except tk.TclError:  # ルートが破棄済み
            self._closed = True
            self._job = None

    def _drain(self) -> None:
        self._job = None
        for _ in range(MAX_CALLBACKS_PER_TICK):
            try:
                widget, fn = self._queue.get_nowait()
            except queue.Empty:
                break
            self._run(widget, fn)
        if not self._closed:
            self._schedule()

    def _run(self, widget: tk.Misc | None, fn: Callable[[], None]) -> None:
        try:
            if widget is not None and not widget.winfo_exists():
                return
            fn()
        except tk.TclError:
            # 実行中にウィジェットが閉じられた場合など。UI はもう存在しないので捨てる。
            logger.debug("UI callback dropped after the widget was destroyed", exc_info=True)
        except Exception:
            # 1 件の失敗でキューの処理全体 (= 以降のすべての画面更新) を止めない。
            # Tk の after コールバックと同じく、標準の例外報告に回す。
            report = getattr(self._root, "report_callback_exception", None)
            try:
                if callable(report):
                    report(*sys.exc_info())
                else:
                    logger.exception("UI callback failed")
            except Exception:
                logger.exception("UI callback failed")


def install(root: tk.Misc) -> UiQueue:
    """``root`` にキューを用意して返します (既にあればそれを返します)。メインスレッド専用。"""
    existing = getattr(root, _ATTR, None)
    if isinstance(existing, UiQueue):
        return existing
    return UiQueue(root)


def post_to_ui(widget: tk.Misc, fn: Callable[[], None]) -> None:
    """``fn`` を Tk のメインスレッドで実行するよう依頼します。どのスレッドからでも呼べます。

    ``widget`` が実行時点で破棄されていれば ``fn`` は呼ばれません。ルートに
    :class:`UiQueue` が無い場合 (単体で開いたダイアログなど) は、従来どおり
    ``widget.after(0, fn)`` に委ねます。

    ここでは Tcl を呼ばない (``_root()`` は ``master`` をたどるだけの Python 処理)。
    """
    find_root = getattr(widget, "_root", None)
    root = find_root() if callable(find_root) else None
    ui_queue = getattr(root, _ATTR, None) if root is not None else None
    if isinstance(ui_queue, UiQueue):
        ui_queue.post(widget, fn)
        return
    try:
        widget.after(0, fn)
    except (tk.TclError, RuntimeError):
        # 破棄済み、またはメインループの外。表示先がもう無いので捨てる。
        pass
