# AGENTS.md — WSL Manager

> このファイルにはプロジェクト固有の指示だけを記載します。共通の詳細ルールは AI Platform Repository の `prompts/coding-agent-typescript-python.md` を参照してください。参照できない環境では「重要な共通ルールの要約」を適用します。

## プロジェクト概要

- 目的: Windows 上で WSL ディストリビューションを GUI (tkinter) および CLI から管理するデスクトップユーティリティを提供する。
- 所有チーム・連絡先: リポジトリ Issue で対応。
- 対象環境: ローカル Windows 10/11 実行環境（開発・CI は Linux/Windows 両方で一部検証）。

## 使用技術

- 言語・バージョン: Python 3.10 以降（CI は 3.10 / 3.12 で検証）。
- フレームワーク・主要ライブラリ: 標準ライブラリのみ（GUI は `tkinter`）。ビルド時のみ `PyInstaller` を使用。
- 実行環境: Windows（GUI・WSL 操作の実行環境）。CI は `ubuntu-latest` と `windows-latest` の両方で実行。

## パッケージマネージャー

- Python: `pip`。ランタイム依存はなし（標準ライブラリのみ）。ビルド用に `PyInstaller` を任意導入。
- ロックファイル・依存定義ファイルはなし。
- 依存更新のルール: ランタイム依存の追加は既存方針（標準ライブラリのみ）から外れるため、明確な理由なく行わない。

## ディレクトリ構成

| パス | 役割 | 変更時の注意 |
| --- | --- | --- |
| `wsl_core.py` | パース・検証・設定・ログ・スナップショットなどのコアロジック（テスト対象） | GUI/CLI から独立したロジックを維持し、副作用は最小限にする |
| `wslmgr.py` | tkinter による GUI 本体 | `import` 時に副作用が起きないよう `__name__` ガードを維持する |
| `wslmgr_cli.py` | コマンドラインインターフェース | 破壊的操作（terminate/unregister/import/export 等）は確認プロンプトを維持する |
| `tests/` | `wsl_core` / CLI の単体テスト | ロジック変更時は対応するテストを追加・更新する |
| `pyinstaller_hooks/` | PyInstaller ビルド用フック | exe ビルド手順に影響するため変更は慎重に |
| `docs/` | ドキュメント（レビュー記録等） | 実装と乖離しないよう更新する |

## アーキテクチャ

- エントリーポイント: GUI は `wslmgr.py`、CLI は `wslmgr_cli.py`。
- レイヤー・責務: `wsl_core.py`（パース・検証・設定・ログ・スナップショットのコアロジック）→ `wslmgr.py` / `wslmgr_cli.py`（GUI/CLI からコアロジックを呼び出す）。
- 状態管理・非同期処理: 操作ログは非同期化・スレッドセーフを考慮して実装されている（既存実装を踏襲する）。
- 重要な設計制約: WSL ディストリビューションに対する破壊的操作（terminate/shutdown/unregister/import/export/VHDX 圧縮/スナップショット削除）は、実行前に確認プロンプトを経由させる。

## 検証コマンド

| 目的 | コマンド | 実行条件・補足 |
| --- | --- | --- |
| コンパイルチェック | `python -m py_compile wslmgr.py wsl_core.py` | GUI を起動せずバイトコードのみ確認（tkinter 不要） |
| unit test | `python -m unittest discover -s tests -v` | `wsl_core` の純粋ロジックが対象。OS を問わず実行可能 |
| import スモークテスト | `python -c "import wslmgr; print('import OK')"` | Windows ランナーのみ（`tkinter`/`winreg` が必要） |
| lint | `ruff check .` | `ruff==0.15.8` に固定（`pyproject.toml` 参照） |

## 変更禁止領域

- `pyinstaller_hooks/`: `PyInstaller` によるビルド (`WSLManager.exe`) に直結するため、ビルド検証なしに変更しない。
- 破壊的 WSL 操作（terminate/shutdown/unregister/import/export/バージョン変換/VHDX 圧縮/スナップショット削除）の確認プロンプト: ユーザーの意図しないデータ損失を防ぐため、根拠なく省略・弱体化しない。

## DB・API 固有ルール

- DB: 該当なし（外部データベースは使用しない）。
- API: 該当なし（外部公開 API は提供しない。WSL コマンド (`wsl.exe`) 呼び出しが中心）。
- 外部サービス: なし。Windows の `wsl.exe` / `netsh` / `diskpart` 等の OS コマンドに依存する。

## デプロイ上の注意

- 環境変数・Secret を必要とする外部サービス連携はない。
- 配布物は `PyInstaller` でビルドした `dist/WSLManager.exe`。ビルド手順を変更する場合は `WSLManager.spec` と `pyinstaller_hooks/` を確認する。
- 本番相当の WSL 環境に対して破壊的操作を伴うコマンドを検証目的で実行しない。

## プロジェクト固有の完了条件

- ロジック変更時は `tests/` に対応するテストを追加・更新し、`python -m unittest discover -s tests -v` と `ruff check .` を実行する。
- README（`README.md` / `README.ja.md`）に記載の挙動を変更した場合は両方を更新する。
- 破壊的操作に関わる変更は、確認プロンプトの挙動を明示的に確認する。

<!-- AI-PLATFORM:START -->
## AI Platform 共通ルール（同期管理）

- 変更前に関連実装・設定・テストを確認し、既存の設計と命名を尊重する。
- 必要最小限の差分を選び、外部入力を検証する。TypeScript は型安全性、Python は型ヒントと明確な例外処理を優先する。
- 不具合修正には回帰テストを追加し、lint・型チェック・テスト・ビルドを実行する。テスト削除やチェック無効化で問題を回避しない。
- Secret・個人情報を出力しない。認証、認可、DB、公開 API は根拠なく変更しない。
- 実行していない検証を成功と報告せず、PR には変更内容、テスト結果、リスク・未検証事項を記載する。

詳細: `kumakumapon/ai-platform` の `prompts/coding-agent-typescript-python.md`
<!-- AI-PLATFORM:END -->
