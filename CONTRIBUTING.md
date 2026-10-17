# Contributing to WSL Manager

WSL Manager への貢献ありがとうございます。このファイルは開発を始めるにあたって最低限必要な手順をまとめたものです。プロジェクトの目的・アーキテクチャ・変更禁止領域などの詳細は [`AGENTS.md`](AGENTS.md) を、利用方法は [`README.md`](README.md) / [`README.ja.md`](README.ja.md) を参照してください。

## セットアップ

WSL Manager はランタイム依存を持たず、Python 3.10 以降の標準ライブラリのみで動作します。

```powershell
# ソースから直接実行する場合、追加インストールは不要です
python wslmgr_cli.py --help
```

lint (`ruff`) と型チェック (`mypy`) を実行する場合のみ、開発用に別途インストールしてください（バージョンは CI と同じく `ruff==0.15.8` / `mypy==2.3.1` に固定）。

```powershell
pip install ruff==0.15.8 mypy==2.3.1
```

## テストの実行

```powershell
# コンパイルチェック (GUI を起動せずバイトコードのみ確認、tkinter 不要)
python -m py_compile wslmgr.py wsl_core.py wslmgr_cli.py
python -m compileall -q wsl_core wslmgr_gui

# unit test (wsl_core / CLI の純粋ロジックが対象、OS を問わず実行可能)
python -m unittest discover -s tests -v

# import スモークテスト (Windows のみ。tkinter / winreg が必要)
python -c "import wslmgr; print('import OK')"

# lint
ruff check .

# 型チェック (対象は wsl_core / wslmgr_gui / wslmgr.py / wslmgr_cli.py。設定は pyproject.toml の [tool.mypy])
mypy
```

ロジックを変更した場合は `tests/` に対応するテストを追加・更新してください。GUI (`wslmgr.py`) の表示文言のみの変更などはテスト追加不要です。

## ruff の方針

- バージョンは `pyproject.toml` に固定されています。ローカルの `ruff` バージョンが異なると結果がずれる可能性があるため、CI の結果を優先してください。
- lint エラーを `# noqa` で抑制するのは、日本語の説明文が一行に収まらない docstring など、行分割すると可読性が下がる場合に限定してください。

## モジュールの責務分担

| モジュール | 役割 |
| --- | --- |
| `wsl_core.py` | パース・検証・設定・ログ・スナップショットなどのコアロジック。GUI/CLI から独立しており、テスト対象の中心。 |
| `wslmgr.py` | tkinter による GUI 本体 (`WSLManager` と `main()`)。`wsl_core` のロジックを呼び出す。`WSLManager` は `wslmgr_gui/app/` の Mixin を継承する。`import` 時に副作用が起きないよう `__name__` ガードを維持する。 |
| `wslmgr_gui/` | `wslmgr.py` から分割した GUI 部品。`winutil.py` (Windows 定数・レジストリ)、`widgets.py` (共通ウィジェット)、`distro_data.py` (ディストロ一覧・CPU・メモリ・IP の取得関数)、`dialogs/` (各ダイアログ)、`app/` (`WSLManager` の Mixin と型チェック用の基底 `AppBase`)。実行時に `wslmgr` を import しない (`python wslmgr.py` 実行時に二重ロードされるため。型注釈用の `if TYPE_CHECKING:` 内のみ可)。 |
| `wslmgr_cli.py` | argparse ベースの CLI。`wsl_core` のロジックを呼び出す。破壊的操作 (terminate/unregister/import/export 等) は確認プロンプトを維持する。 |

新しいロジックを追加する際は、可能な限り `wsl_core.py` に副作用の少ない関数として実装し、GUI/CLI 側は呼び出しに徹してください。詳細な設計制約は [`AGENTS.md`](AGENTS.md) の「アーキテクチャ」「変更禁止領域」を参照してください。

GUI のメソッドを `wslmgr_gui/` へ移すときの注意:

- Mixin (`wslmgr_gui/app/`) は `__init__` を持たず、メソッド名を `WSLManager` や他の Mixin と重複させないでください。同名のメソッドは継承順で後勝ちになり、片方が黙って無効になります (`tests/test_wslmgr_structure.py` が検査します)。
- `messagebox` などを使うメソッドを別モジュールへ移したら、テストの `patch("wslmgr.messagebox")` を移動先モジュール (例: `patch("wslmgr_gui.app.operation_log.messagebox")`) に更新してください。`wslmgr` 側に名前が残っていると、パッチが空振りしても例外にならず、「確認なしで実行される退行」を見逃す偽陽性になります。拒否側のテストには `askyesno.assert_called_once()` のような到達確認も入れてください。
- 移動は、メソッド本体を変えないコピー移動にし、`ast.dump` が移動前後で一致することを確認してください。

## PyInstaller ビルド手順の概要

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean WSLManager.spec
```

生成される実行ファイルは `dist\WSLManager.exe` です。`WSLManager.spec` と `pyinstaller_hooks/` はビルドの信頼性を保つための調整を含んでいるため、変更する場合はビルド検証を必ず行ってください。詳細は [`README.md`](README.md) の "Build An Executable" セクションを参照してください。

## Issue / Pull Request

- 不具合報告には Bug Report テンプレート、機能要望には Feature Request テンプレートを使用してください。
- Pull Request を作成する際は `.github/pull_request_template.md` の各項目を埋めてください。
- 破壊的操作 (terminate/shutdown/unregister/import/export/バージョン変換/VHDX 圧縮/スナップショット削除) の確認プロンプトは、根拠なく省略・弱体化しないでください。

## コーディング規約

TypeScript/Python 共通のコーディング規約に従ってください。プロジェクト固有の詳細は [`AGENTS.md`](AGENTS.md) を参照してください。
