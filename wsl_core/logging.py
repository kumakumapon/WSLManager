"""
wsl_core.logging - 操作ログの永続化・ローテーション・非同期書き込みモジュール
"""

from __future__ import annotations

import json
import os
import queue
import sys
import threading
from datetime import datetime
from typing import Any

from .types import CURRENT_SCHEMA_VERSION


def _get_open():
    """wsl_core.open がモックされている場合はそれを優先して取得するヘルパー。"""
    mod = sys.modules.get("wsl_core")
    if mod and hasattr(mod, "open"):
        return mod.open
    return open


def get_default_log_dir() -> str:
    """操作ログを保存するデフォルトディレクトリのパスを返します。

    Windows (``sys.platform == "win32"``) では環境変数 ``APPDATA`` 配下の
    ``WSLManager/logs`` を、それ以外では ``~/.wslmgr/logs`` を返します。
    ディレクトリの作成などの I/O は一切行いません。
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA", "")
        return os.path.join(appdata, "WSLManager", "logs")
    return os.path.expanduser("~/.wslmgr/logs")


def serialize_log_entry(
    operation: str,
    target: str,
    result: str,
    timestamp: str | None = None,
    source: str | None = None,
    schema_version: int = CURRENT_SCHEMA_VERSION,
) -> str:
    """操作ログ1件を JSON Lines 形式の1行 (改行なし) にシリアライズして返します。

    キーは "timestamp", "operation", "target", "result", "schema_version" です。
    timestamp が None の場合は現在時刻を ISO 8601 形式で設定します。
    source を指定すると "source" キー (例: "gui" / "cli") も出力します。
    日本語をエスケープしないように ``json.dumps(ensure_ascii=False)`` を使用します。
    """
    ts = timestamp if timestamp is not None else datetime.now().isoformat()
    entry: dict[str, Any] = {
        "schema_version": schema_version,
        "timestamp": ts,
        "operation": operation,
        "target": target,
        "result": result,
    }
    if source is not None:
        entry["source"] = source
    return json.dumps(entry, ensure_ascii=False)


def deserialize_log_entries(text: str) -> list[dict]:
    """JSON Lines 形式の操作ログテキストを解析して dict のリストを返します。

    1行につき1つの JSON オブジェクトを想定します。空行や JSON として
    パースできない行はスキップします。
    ``text`` が空文字または None の場合は空リストを返します。
    """
    if not text:
        return []
    entries: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(entry, dict):
            if "schema_version" not in entry:
                entry["schema_version"] = 1
            entries.append(entry)
    return entries


def format_log_entry_from_dict(entry: dict) -> str:
    """操作ログの dict を人間が読みやすい1行の文字列にして返します。

    フォーマット:
        [{timestamp}] {operation} | {target} | {result}

    キーが欠けている場合はそれぞれ "-" をデフォルト値として使用します。
    """
    timestamp = entry.get("timestamp", "-")
    operation = entry.get("operation", "-")
    target = entry.get("target", "-")
    result = entry.get("result", "-")
    return f"[{timestamp}] {operation} | {target} | {result}"


def format_operation_log_entry(
    operation: str,
    target: str,
    result: str,
    timestamp: str | None = None,
) -> str:
    """操作ログの1行を生成して返します。

    フォーマット:
        [{timestamp}] {operation} | {target} | {result}

    timestamp が None の場合は現在時刻を ISO 8601 形式で設定します。
    operation の例: "起動", "停止", "インストール", "エクスポート"
    """
    ts = timestamp if timestamp is not None else datetime.now().isoformat()
    return f"[{ts}] {operation} | {target} | {result}"


def rotate_log_files(
    log_dir: str,
    base_name: str = "operations.jsonl",
    max_size: int = 1_048_576,
    max_backups: int = 10,
) -> None:
    """ログファイルが最大サイズを超えた場合にローテーションを行います。

    ``log_dir/base_name`` が ``max_size`` バイトを超えていれば、
    ``operations.jsonl`` → ``operations.1.jsonl`` → ``operations.2.jsonl`` ...
    のように番号を1つずつ繰り上げてリネームします。
    ``max_backups`` を超える番号のバックアップファイルは削除します。
    対象ファイルが存在しない場合は何もしません。
    """
    base_path = os.path.join(log_dir, base_name)
    if not os.path.exists(base_path):
        return
    if os.path.getsize(base_path) <= max_size:
        return

    stem, ext = os.path.splitext(base_name)

    def backup_path(n: int) -> str:
        return os.path.join(log_dir, f"{stem}.{n}{ext}")

    # max_backups を超える古いバックアップを削除する
    oldest = backup_path(max_backups)
    if os.path.exists(oldest):
        os.remove(oldest)

    # 既存バックアップを番号の大きい方から繰り上げる (衝突を避けるため降順)
    for n in range(max_backups - 1, 0, -1):
        src = backup_path(n)
        if os.path.exists(src):
            os.rename(src, backup_path(n + 1))

    # 現在のログファイルを .1 にリネームする
    os.rename(base_path, backup_path(1))


def log_file_paths(
    log_dir: str,
    base_name: str = "operations.jsonl",
    max_backups: int = 10,
) -> list[str]:
    """操作ログ本体と回転済みバックアップの候補パスを列挙します。

    実際にファイルが存在するかは確認しません。``rotate_log_files`` が生成する
    ``operations.jsonl`` / ``operations.1.jsonl`` … と同じ命名規則を使います。
    """
    stem, ext = os.path.splitext(base_name)
    paths = [os.path.join(log_dir, base_name)]
    paths.extend(
        os.path.join(log_dir, f"{stem}.{n}{ext}") for n in range(1, max_backups + 1)
    )
    return paths


def delete_log_files(
    log_dir: str,
    base_name: str = "operations.jsonl",
    max_backups: int = 10,
) -> tuple[int, list[str]]:
    """操作ログ本体と回転済みバックアップをすべて削除します。

    存在しないファイルは黙ってスキップします。

    Returns:
        (削除できた件数, 削除に失敗したパスのリスト) のタプル。
    """
    deleted = 0
    failed: list[str] = []
    for path in log_file_paths(log_dir, base_name, max_backups):
        if not os.path.exists(path):
            continue
        try:
            os.remove(path)
        except OSError:
            failed.append(path)
        else:
            deleted += 1
    return deleted, failed


class AsyncLogWriter:
    """操作ログを専用のデーモンスレッドで非同期に追記するライタ。

    ``open`` / ``write`` / :func:`rotate_log_files` の同期 I/O を Tk の
    イベントループから切り離すためのクラスです。:meth:`submit` は
    ``queue.Queue`` に積むだけで呼び出し元をブロックしないため、
    ``%APPDATA%`` がネットワークドライブ上にある環境などで書き込みが
    遅くても GUI がカクつきません。

    I/O エラーは元の同期実装と同様に握りつぶします (ログの永続化に失敗しても
    アプリの操作自体は継続させるため)。ただしキューには上限 (``maxsize``) を
    設け、溢れた場合は :attr:`dropped_count` を、書き込み失敗時は
    :attr:`write_error_count` をそれぞれインクリメントして呼び出し元が
    後から検知できるようにします。
    """

    _SENTINEL = object()

    def __init__(
        self,
        log_dir: str,
        base_name: str = "operations.jsonl",
        max_size: int = 1_048_576,
        max_backups: int = 10,
        maxsize: int = 1000,
    ) -> None:
        self._log_dir = log_dir
        self._base_name = base_name
        self._max_size = max_size
        self._max_backups = max_backups
        self._queue: queue.Queue = queue.Queue(maxsize=maxsize)
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._stopped = False
        self._dropped_count = 0
        self._write_error_count = 0

    @property
    def log_path(self) -> str:
        """ログ本体のフルパス。"""
        return os.path.join(self._log_dir, self._base_name)

    @property
    def dropped_count(self) -> int:
        """キュー溢れにより破棄されたログエントリ数。"""
        with self._lock:
            return self._dropped_count

    @property
    def write_error_count(self) -> int:
        """書き込み時に ``OSError`` が発生した回数。"""
        with self._lock:
            return self._write_error_count

    def submit(
        self,
        operation: str,
        target: str,
        result: str,
        timestamp: str | None = None,
        source: str | None = None,
    ) -> None:
        """操作ログ1件を書き込みキューに積みます。ブロックしません。

        :meth:`stop` 済みの場合は何もしません。キューが満杯の場合は
        :attr:`dropped_count` をインクリメントして破棄します (ブロックしません)。
        """
        if self._stopped:
            return
        line = serialize_log_entry(operation, target, result, timestamp, source)
        if not self._ensure_thread():
            return
        try:
            self._queue.put_nowait(line)
        except queue.Full:
            with self._lock:
                self._dropped_count += 1

    def flush(self, timeout: float = 2.0) -> bool:
        """キューに積まれた全エントリが書き込まれるまで待ちます。

        キュー末尾にバリア (``threading.Event``) を積み、ライタスレッドが
        そこまで処理し終えるのを待ちます。

        Returns:
            時間内に書き込みが完了すれば True、タイムアウトすれば False。
        """
        with self._lock:
            thread = self._thread
        if thread is None or not thread.is_alive():
            return self._queue.empty()
        barrier = threading.Event()
        try:
            self._queue.put(barrier, timeout=timeout)
        except queue.Full:
            return False
        return barrier.wait(timeout)

    def stop(self, timeout: float = 2.0) -> bool:
        """残りのエントリを書き込んでからライタスレッドを終了させます。

        以降の :meth:`submit` は無視されます。冪等です。

        Returns:
            時間内にスレッドが終了すれば True、しなければ False。
        """
        with self._lock:
            self._stopped = True
            thread = self._thread
        if thread is None or not thread.is_alive():
            return True
        try:
            self._queue.put(self._SENTINEL, timeout=timeout)
        except queue.Full:
            pass
        thread.join(timeout)
        return not thread.is_alive()

    # ── 内部実装 ──────────────────────────────────────────────────────

    def _ensure_thread(self) -> bool:
        """ライタスレッドが動いていなければ起動します。

        Returns:
            スレッドが利用可能なら True、:meth:`stop` 済みなら False。
        """
        with self._lock:
            if self._stopped:
                return False
            if self._thread is not None and self._thread.is_alive():
                return True
            self._thread = threading.Thread(
                target=self._run, name="wslmgr-log-writer", daemon=True
            )
            self._thread.start()
            return True

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            if item is self._SENTINEL:
                return
            if isinstance(item, threading.Event):
                item.set()
                continue
            self._write(item)

    def _write(self, line: str) -> None:
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            op = _get_open()
            with op(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            rotate_log_files(
                self._log_dir, self._base_name, self._max_size, self._max_backups
            )
        except OSError:
            with self._lock:
                self._write_error_count += 1


def append_log_entry(
    log_dir: str,
    operation: str,
    target: str,
    result: str,
    source: str | None = None,
    base_name: str = "operations.jsonl",
    max_size: int = 1_048_576,
    max_backups: int = 10,
) -> None:
    """操作ログ1件を同期的に (呼び出し元スレッドをブロックして) 追記します。

    ``AsyncLogWriter`` は専用スレッドでの非同期書き込みを前提としており、
    終了前に :meth:`AsyncLogWriter.stop` を呼び忘れるとエントリを失う
    リスクがあります。CLI のような単発・短命プロセスでは、その心配がない
    この同期版ヘルパーの方が適しています。書き込み内容・ローテーション
    ロジックは :meth:`AsyncLogWriter._write` と同じです。
    I/O エラーは握りつぶします (ログの永続化に失敗してもコマンド自体の
    成否には影響させないため)。
    """
    line = serialize_log_entry(operation, target, result, source=source)
    try:
        os.makedirs(log_dir, exist_ok=True)
        op = _get_open()
        with op(os.path.join(log_dir, base_name), "a", encoding="utf-8") as f:
            f.write(line + "\n")
        rotate_log_files(log_dir, base_name, max_size, max_backups)
    except OSError:
        pass


def tail_entries(entries: list, n: int) -> list:
    """リストの末尾 n 件を返します。

    ``n <= 0`` の場合は空リストを返します。``n >= len(entries)`` の場合は
    全件のコピーを返します。副作用はなく、引数の entries 自体は変更しません。
    """
    if n <= 0:
        return []
    if n >= len(entries):
        return list(entries)
    return entries[-n:]
