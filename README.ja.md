# WSL Manager

[![CI](https://github.com/kumakumapon/WSLMgr/actions/workflows/ci.yml/badge.svg)](https://github.com/kumakumapon/WSLMgr/actions/workflows/ci.yml)

[English](README.md) | 日本語

## 免責事項

**重要:** WSL Manager は、停止、全停止、登録解除、インポート、エクスポート、WSL バージョン変換、VHDX 圧縮、スナップショット削除など、データや環境に影響する操作を実行します。操作を確定する前に、対象ディストリビューション名とファイルパスを必ず確認してください。重要なデータは事前にバックアップしてください。本プロジェクトは現状有姿で提供され、データ損失、設定破損、サービス停止を防ぐ保証はありません。

## 概要

WSL Manager は、WSL ディストリビューションを管理するための Windows 向け Python/tkinter GUI ツールです。よく使う操作をスクリプト化できる CLI も含み、解析、バリデーション、設定、ログ、スナップショットなどのロジックはテストしやすい `wsl_core.py` に分離しています。

主な機能:

- WSL ディストリビューションの状態、WSL バージョン、デフォルト設定、リソース使用量、IP アドレス、ディスクサイズを一覧表示
- ディストリビューションの起動、ターミナル起動、個別停止、全停止
- デフォルトディストリビューション設定、WSL1/WSL2 変換
- インストール、登録解除、インポート、エクスポート、複製、スナップショット作成、復元、削除
- 実行中ディストリビューション内のプロセス確認と `SIGTERM` / `SIGKILL`
- `\\wsl.localhost\<name>` を Explorer で開く
- グローバル `%USERPROFILE%\.wslconfig` と各ディストリビューションの `/etc/wsl.conf` 編集
- スパース VHD 化または `diskpart compact vdisk` による WSL2 VHDX 最適化
- WSL バージョン、更新情報の表示と `wsl --update`
- CLI からの `netsh interface portproxy` ルール管理
- アプリ設定と操作ログの保存

## 動作環境

- Windows 10 または Windows 11
- WSL がインストール済みであること
- Python 3.10 以上
- 実行時の追加依存パッケージなし（標準ライブラリのみ）
- `dist\WSLManager.exe` を作る場合のみ PyInstaller が必要

## 使い方

### GUI を起動

```powershell
python wslmgr.py
```

メイン画面にはインストール済みディストリビューションが表示されます。行を選択し、ツールバー、メニューバー、ダブルクリック、右クリックメニューから操作します。

主な GUI 操作:

- ディストリビューション一覧の更新、自動更新の有効化
- Windows Terminal があればそれを使い、無ければ `cmd.exe` でディストリビューションを起動
- 選択したディストリビューションの停止、または WSL 全体の停止
- 実行中ディストリビューションのプロセス一覧表示と `SIGTERM` / `SIGKILL`
- エクスポート、インポート、複製、スナップショット作成、復元、登録解除
- `.wslconfig` とディストリビューション別 `wsl.conf` の編集
- WSL2 VHDX のスパース化または即時圧縮

### CLI を使う

```powershell
python wslmgr_cli.py --help
python wslmgr_cli.py --version
python wslmgr_cli.py list --with-ip --with-disk
python wslmgr_cli.py list --format json
python wslmgr_cli.py start Ubuntu
python wslmgr_cli.py stop Ubuntu
python wslmgr_cli.py shutdown
python wslmgr_cli.py export Ubuntu C:\backup\Ubuntu.tar
python wslmgr_cli.py import UbuntuClone C:\WSL\UbuntuClone C:\backup\Ubuntu.tar
python wslmgr_cli.py config
python wslmgr_cli.py config --distro Ubuntu
python wslmgr_cli.py portproxy list
python wslmgr_cli.py snapshot create Ubuntu --comment "アップグレード前"
python wslmgr_cli.py snapshot list
python wslmgr_cli.py snapshot restore Ubuntu_20260101-000000.tar --install-path C:\WSL\Restored
python wslmgr_cli.py snapshot set-dir D:\WSLSnapshots
python wslmgr_cli.py clone Ubuntu UbuntuClone --install-path C:\WSL\UbuntuClone
python wslmgr_cli.py mount C:\disks\data.vhdx --vhd
python wslmgr_cli.py unmount C:\disks\data.vhdx
python wslmgr_cli.py log clear --yes
```

CLI サブコマンドには `list`、`start`、`stop`、`shutdown`、`status`、`export`、`import`、`config`、`set-default`、`unregister`、`install`、`optimize`、`set-version`、`processes`、`log` (`clear`)、`portproxy` (`list`/`add`/`delete`)、`snapshot` (`create`/`list`/`restore`/`delete`/`set-dir`)、`clone`、`mount`、`unmount` があります。

### 終了コード

`wslmgr_cli.py` は次の終了コードを使用します。

| コード | 意味 |
|------|---------|
| `0` | 成功 |
| `1` | 一般エラー（distro 名不正、ポート番号不正、ファイル未存在、`.wslconfig` パース失敗などの入力検証エラー） |
| `2` | コマンドライン引数エラー（`argparse` 標準の挙動、変更なし） |
| `3` | 確認拒否（破壊的操作の確認プロンプトでユーザーが拒否した場合、または非対話環境で `--yes` が必要だが指定されなかった場合） |
| `4` | 基盤コマンドの実行失敗（`wsl.exe` / `diskpart` / `netsh` が非0の終了コードを返した、タイムアウトした、または実行ファイルが見つからなかった場合） |
| `5` | 部分失敗（コマンド自体は完了したが結果の一部が失敗した場合。例: `status` で一部ディストロのリソース取得に失敗した、`snapshot create` で tar のエクスポートは成功したが JSON メタデータの書き込みに失敗した、等） |

**破壊的変更:** この体系の導入以前は、すべての失敗が終了コード `1` でした。「終了コードが 0 以外なら失敗」という判定のみを行うスクリプトは影響を受けませんが、失敗の種類を区別するために `終了コード == 1` を特別扱いしているスクリプトは、上記の新しいコードに合わせて更新が必要です。

### exe をビルド

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller --clean WSLManager.spec
```

生成先:

```text
dist\WSLManager.exe
```

`WSLManager.spec` と `pyinstaller_hooks/` は意図的に同梱しています。conda / miniforge 環境では、無関係なパッケージの PyInstaller hook や Tcl/Tk 検出の問題で解析が失敗することがあるため、これらを使ってビルドを安定させています。

## 実装仕様

### モジュール構成

| ファイル | 役割 |
|----------|------|
| `wslmgr.py` | tkinter GUI、各種ダイアログ、バックグラウンド実行、UI 状態、確認処理 |
| `wslmgr_cli.py` | argparse ベースの CLI |
| `wsl_core.py` | 解析、整形、バリデーション、設定、ログ、スナップショット、進捗計算の純粋ロジック |
| `tests/` | `wsl_core.py` と CLI の unittest |
| `WSLManager.spec` | PyInstaller ビルド定義 |
| `pyinstaller_hooks/` | tkinter / Tcl/Tk パッケージング用のローカル PyInstaller hook |

### アーキテクチャ

- GUI は Windows 向けで、`tkinter`、`ttk`、`subprocess`、`winreg` を使用します。
- コアロジックは可能な限り GUI、レジストリ、subprocess に依存しない形に分離し、Windows 以外の CI でもテストできるようにしています。
- WSL コマンド出力は `wsl_core.decode_wsl_output()` で UTF-16 LE、UTF-8、CP932、フォールバックエンコーディングに対応します。
- 時間のかかる処理はバックグラウンドで実行し、GUI のフリーズを避けます。
- 破壊的操作は確認ダイアログ、または CLI の明示的なサブコマンドを通して実行します。
- 設定値は利用前に正規化し、`.wslconfig` / `wsl.conf` エディタでは可能な限り未知のキーを保持します。

### 実行する WSL / Windows コマンド

このアプリは独自サービスや常駐プロセスではなく、既存の Windows コマンドをラップします。

- `wsl --list --verbose`
- `wsl --distribution <name>`
- `wsl --terminate <name>`
- `wsl --shutdown`
- `wsl --set-default <name>`
- `wsl --set-version <name> <1|2>`
- `wsl --install --distribution <name> --no-launch`
- `wsl --unregister <name>`
- `wsl --export <name> <path>`
- `wsl --import <name> <install-path> <image-path>`
- `wsl --manage <name> --set-sparse true`
- 生成した `diskpart` スクリプトによる `compact vdisk`
- CLI のポート転送管理用 `netsh interface portproxy`

### スナップショットとログ

- スナップショットは tar ファイルと JSON メタデータで保存します。
- 既定のスナップショット保存先はユーザープロファイル配下です。
- 復元は元ディストリビューションを上書きせず、新しいディストリビューション名でインポートします。
- 操作ログは構造化レコードとしてシリアライズし、`wsl_core.py` のヘルパーでローテーションします。

### パッケージング

PyInstaller ビルドでは、生の `pyinstaller wslmgr.py` ではなく `WSLManager.spec` を使います。spec は conda / miniforge の DLL を存在する場合に収集し、ローカル hook は PyInstaller の runtime hook が参照する `_tcl_data` と `_tk_data` を用意します。

### テスト

```powershell
python -m py_compile wslmgr.py wslmgr_cli.py wsl_core.py
python -m unittest discover -s tests -v
```

Linux / macOS では、GUI 以外の大部分を `python3` で検証できます。

### CI

GitHub Actions では、Ubuntu と Windows の複数 Python バージョンでコンパイルチェックと単体テストを実行します。Windows ジョブでは GUI モジュールの import スモークテストも実行します。

## ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。
