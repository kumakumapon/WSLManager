"""
wsl_core.actions - GUI の操作可否判定と、インポート/エクスポート引数の組み立て

GUI (tkinter) に依存しない純粋関数だけを置きます。メイン画面のボタン・メニューの
有効/無効、フォームダイアログの既定値と入力検証、``wsl.exe`` に渡す引数の組み立てを
ここに集め、Windows 以外の CI でもテストできるようにしています。
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Mapping
from datetime import date

from .validation import validate_distro_name

# 選択中のディストリビューションに対する操作の ID。
# GUI はこの ID でボタン・メニュー項目を登録し、``action_availability`` の結果で
# 有効/無効を切り替える。
DISTRO_ACTIONS: tuple[str, ...] = (
    "start",
    "stop",
    "terminal",
    "explorer",
    "copy_ip",
    "details",
    "processes",
    "set_default",
    "convert",
    "distro_conf",
    "optimize",
    "snapshot",
    "export",
    "clone",
    "unregister",
)

# ``wsl --import --vhd`` / ``wsl --export --vhd`` が扱う仮想ディスクの拡張子
VHD_EXTENSIONS: tuple[str, ...] = (".vhd", ".vhdx")

# ``wsl --import`` が受け付ける tar 形式の拡張子 (ファイル選択ダイアログの絞り込み用)
TAR_EXTENSIONS: tuple[str, ...] = (".tar", ".tar.gz", ".tgz", ".tar.xz")


def _is_running(distro: Mapping[str, object]) -> bool:
    return distro.get("state") == "Running"


def _has_ip(distro: Mapping[str, object]) -> bool:
    ip = distro.get("ip")
    return isinstance(ip, str) and ip not in ("", "-")


def action_availability(distro: Mapping[str, object] | None) -> dict[str, bool]:
    """選択中のディストリビューションに対して、各操作を実行できるかを返します。

    Args:
        distro: ``parse_distro_list`` の 1 要素 (``name`` / ``state`` / ``version`` /
            ``default`` / ``ip`` を参照)。未選択なら ``None``。

    Returns:
        ``DISTRO_ACTIONS`` の全 ID をキーに持つ dict。未選択ならすべて ``False``。

    判定の方針:
        - 起動は停止中のときだけ、停止とプロセス一覧は実行中のときだけ有効。
        - 既定に設定は、既定ではないときだけ有効。
        - バージョン変換は WSL1/WSL2 が判明しているときだけ有効。
        - ディスク最適化は仮想ディスクを持つ WSL2 (または不明) のときだけ有効。
        - IP のコピーは IP アドレスを取得できているときだけ有効。
        - それ以外 (ターミナル、エクスプローラー、バックアップ系、登録解除など) は
          選択していれば有効。停止中でも WSL が自動で起動するため。
    """
    if distro is None:
        return dict.fromkeys(DISTRO_ACTIONS, False)
    running = _is_running(distro)
    version = str(distro.get("version") or "")
    availability = dict.fromkeys(DISTRO_ACTIONS, True)
    availability.update(
        {
            "start": not running,
            "stop": running,
            "processes": running,
            "copy_ip": _has_ip(distro),
            "set_default": not bool(distro.get("default")),
            "convert": version in ("1", "2"),
            "optimize": version != "1",
        }
    )
    return availability


def conversion_target(version: object) -> str | None:
    """WSL バージョン変換の変換先 (``"1"`` / ``"2"``) を返します。不明なら ``None``。"""
    text = str(version or "")
    if text == "1":
        return "2"
    if text == "2":
        return "1"
    return None


def is_vhd_image(path: str) -> bool:
    """パスが仮想ディスク (``.vhd`` / ``.vhdx``) なら True を返します (大文字小文字は無視)。"""
    return path.lower().endswith(VHD_EXTENSIONS)


def build_export_args(name: str, destination: str, vhd: bool) -> list[str]:
    """``wsl`` に渡すエクスポート引数を組み立てます (``wsl`` 自体は含みません)。"""
    args = ["--export", name, destination]
    if vhd:
        args.append("--vhd")
    return args


def build_import_args(name: str, install_dir: str, image_path: str, version: str) -> list[str]:
    """``wsl`` に渡すインポート引数を組み立てます (``wsl`` 自体は含みません)。

    仮想ディスク (``.vhd`` / ``.vhdx``) は ``--vhd`` を付けないと ``wsl --import`` が
    tar として読もうとして失敗する。VHD のインポートは WSL2 専用なので、その場合は
    ``--version`` を付けない (``--vhd`` と WSL1 の組み合わせは受け付けられない)。
    """
    args = ["--import", name, install_dir, image_path]
    if is_vhd_image(image_path):
        args.append("--vhd")
    elif version in ("1", "2"):
        args += ["--version", version]
    return args


def default_install_base(environ: Mapping[str, str] | None = None) -> str:
    """インポート・複製先フォルダの既定の親フォルダ (``%USERPROFILE%\\WSL``) を返します。

    ``USERPROFILE`` が無い環境 (Windows 以外) ではホームディレクトリ配下を返します。
    I/O は行いません (フォルダの作成もしません)。
    """
    env = os.environ if environ is None else environ
    profile = env.get("USERPROFILE") or os.path.expanduser("~")
    return os.path.join(profile, "WSL")


def suggest_install_dir(name: str, base_dir: str | None = None) -> str:
    """ディストリビューション名から、インポート・複製先フォルダの候補を返します。"""
    base = base_dir if base_dir is not None else default_install_base()
    return os.path.join(base, name.strip()) if name.strip() else base


def suggest_export_filename(name: str, vhd: bool, today: date | None = None) -> str:
    """エクスポートファイル名の候補 (例: ``Ubuntu-20260101.tar``) を返します。"""
    stamp = (today or date.today()).strftime("%Y%m%d")
    return f"{name}-{stamp}{'.vhdx' if vhd else '.tar'}"


def replace_export_extension(path: str, vhd: bool) -> str:
    """形式の切り替えに合わせて、エクスポート先の拡張子を ``.tar`` / ``.vhdx`` に揃えます。

    利用者が拡張子を独自に付けている場合 (``.tar`` / ``.vhdx`` / ``.vhd`` 以外) は
    変更しません。
    """
    root, ext = os.path.splitext(path)
    if ext.lower() not in (".tar", ".vhdx", ".vhd"):
        return path
    return root + (".vhdx" if vhd else ".tar")


# ── フォームの入力検証 ─────────────────────────────────────────────────────
#
# 戻り値はエラーの (翻訳キー, 埋め込み値) のリスト。空なら入力は妥当。
# GUI 側で ``translate(key, language, **values)`` して表示する。

FormError = tuple[str, dict[str, str]]


def _name_errors(name: str, existing: Iterable[str], language: str) -> list[FormError]:
    valid, reason = validate_distro_name(name, language=language)
    if not valid:
        return [("form.error.name_invalid", {"reason": reason})]
    if name.casefold() in {e.casefold() for e in existing}:
        return [("form.error.name_exists", {"name": name})]
    return []


def validate_import_form(
    name: str,
    image_path: str,
    install_dir: str,
    existing: Iterable[str],
    language: str = "ja",
    *,
    isfile: Callable[[str], bool] = os.path.isfile,
    listdir: Callable[[str], list[str]] = os.listdir,
) -> list[FormError]:
    """インポートフォームの入力を検証します。

    - 名前は ``validate_distro_name`` を満たし、既存のディストリビューションと重複しない
      (WSL は大文字小文字を区別せず重複を拒否するため casefold で比較する)
    - イメージファイルが存在する
    - インストール先が指定されており、既存の仮想ディスク (``ext4.vhdx``) が無い
      (WSL2 はインストール先に ``ext4.vhdx`` を作るため、別のディストリビューションの
      フォルダを選んだ場合の衝突を防ぐ)
    """
    errors = _name_errors(name.strip(), existing, language)
    if not image_path.strip():
        errors.append(("form.error.image_required", {}))
    elif not isfile(image_path):
        errors.append(("form.error.image_missing", {"path": image_path}))
    errors.extend(_install_dir_errors(install_dir, listdir))
    return errors


def validate_clone_form(
    name: str,
    install_dir: str,
    existing: Iterable[str],
    language: str = "ja",
    *,
    listdir: Callable[[str], list[str]] = os.listdir,
) -> list[FormError]:
    """複製フォームの入力を検証します (名前とインストール先はインポートと同じ規則)。"""
    errors = _name_errors(name.strip(), existing, language)
    errors.extend(_install_dir_errors(install_dir, listdir))
    return errors


def _install_dir_errors(install_dir: str, listdir: Callable[[str], list[str]]) -> list[FormError]:
    if not install_dir.strip():
        return [("form.error.folder_required", {})]
    try:
        entries = listdir(install_dir)
    except FileNotFoundError:
        return []  # まだ無いフォルダは実行時に作成する
    except NotADirectoryError:
        return [("form.error.folder_not_dir", {"path": install_dir})]
    except OSError:
        return []  # 権限などは実行時に wsl.exe のエラーとして報告する
    # WSL2 はインストール先に ext4.vhdx を作る。既にあるフォルダ (別のディストリビューションの
    # 置き場所など) を選ぶと衝突するため、ここで止める。
    if any(entry.casefold() == "ext4.vhdx" for entry in entries):
        return [("form.error.folder_has_vhdx", {"path": install_dir})]
    return []


def validate_export_form(destination: str) -> list[FormError]:
    """エクスポートフォームの入力を検証します (保存先の指定だけを確認します)。"""
    if not destination.strip():
        return [("form.error.destination_required", {})]
    return []
