# WSL Manager

[![CI](https://github.com/kumakumapon/WSLManager/actions/workflows/ci.yml/badge.svg)](https://github.com/kumakumapon/WSLManager/actions/workflows/ci.yml)

[English](README.md) | 日本語

## 免責事項

**重要:** WSL Manager は、停止、全停止、登録解除、インポート、エクスポート、WSL バージョン変換、VHDX 圧縮、スナップショット削除など、データや環境に影響する操作を実行します。操作を確定する前に、対象ディストリビューション名とファイルパスを必ず確認してください。重要なデータは事前にバックアップしてください。本プロジェクトは現状有姿で提供され、データ損失、設定破損、サービス停止を防ぐ保証はありません。

## 概要

WSL Manager は、WSL ディストリビューションを管理する Windows 用のデスクトップアプリです。インストール済みのディストリビューションを 1 つの一覧で確認し、起動・停止、ターミナルやエクスプローラーで開く、バックアップと復元、設定の編集を、`wsl.exe` のコマンドを打たずに行えます。Python が無くてもそのまま動く実行ファイルとして配布しており、スクリプトやタスク スケジューラ向けのコマンドライン版 (`wslmgr.exe`) も含みます。

主な機能:

- WSL ディストリビューションの状態、WSL バージョン、既定の印、リソース使用量、IP アドレス、ディスクサイズ、インストール先を一覧表示
- CPU・メモリ使用量の直近30分の履歴グラフを表示し、ホバーで系列名・時刻・正確な値を確認
- バックグラウンドでの起動、ターミナル (Windows Terminal があればそれ、無ければ `cmd.exe`) での起動、個別停止、WSL の全停止
- 既定のディストリビューション設定、WSL1/WSL2 変換
- インストール、登録解除、インポート (tar / VHDX)、エクスポート (tar / VHDX)、複製、スナップショット作成、復元、削除。時間のかかる処理は進捗表示とキャンセルに対応
- 実行中ディストリビューション内のプロセス確認と `SIGTERM` / `SIGKILL`
- `\\wsl.localhost\<name>` を Explorer で開く
- グローバル `%USERPROFILE%\.wslconfig` と各ディストリビューションの `/etc/wsl.conf` 編集
- スパース VHD 化または `diskpart compact vdisk` による WSL2 VHDX 最適化
- WSL バージョン、更新情報の表示と `wsl --update`
- WSL 3.0.1 / WSL Containers の利用可否診断と、読み取り専用のコンテナ表示（GUI / CLI）
- CLI からの `netsh interface portproxy` ルール管理
- 日本語・英語の画面 (**表示 → 言語** でいつでも切り替え、その場で反映)

## ダウンロード

[最新のリリース](https://github.com/kumakumapon/WSLManager/releases/latest) から、次のどれか 1 つを選んでください。

| ファイル | こんなときに |
|----------|--------------|
| `WSLManager-Setup-X.Y.Z.exe` | **おすすめ。** アプリ (GUI と `wslmgr.exe`) をインストールし、スタートメニューのショートカットとアンインストーラを作ります。管理者権限は不要です。コマンドライン版を `PATH` に追加することもできます。 |
| `WSLManager-X.Y.Z-portable.zip` | インストールしたくないとき。好きな場所に展開して `WSLManager.exe` を実行します。`wslmgr.exe`、README、LICENSE も入っています。 |
| `WSLManager.exe` | GUI だけを 1 ファイルで使いたいとき。 |
| `wslmgr.exe` | コマンドライン版だけを 1 ファイルで使いたいとき。 |
| `SHA256SUMS.txt` | 上のファイルのチェックサム。 |

どの実行ファイルも Python は不要です。コード署名はしていないため、初回は Windows SmartScreen の警告が出ることがあります (「詳細情報」→「実行」)。どのファイルを使っても、設定とログは `%APPDATA%\WSLManager`、スナップショットは `%USERPROFILE%\WSLSnapshots` に保存されます。

## 動作環境

- Windows 10 または Windows 11 と WSL (管理者の PowerShell で `wsl --install`)
- ソースから実行・exe をビルドする場合のみ: Python 3.10 以上 (標準ライブラリのみ)

## 使い方

### GUI

スタートメニューの **WSL Manager** (インストーラ版) から起動するか、`WSLManager.exe` を実行します。

```text
+---------------------------------------------------------------------------+
| ファイル  ディストリビューション  WSL  表示  ヘルプ                         |
| [> 起動] [# 停止] [ターミナル] [エクスプローラー] | [+ 追加 v] [スナップショット]  検索: [___] [更新] |
+--------------------------------------------------+------------------------+
| 既定  ディストリビューション  状態      WSL  CPU  | Ubuntu-24.04           |
|  *    Ubuntu-24.04           * 実行中  WSL2 3.2  | (実行中) (WSL 2) (既定) |
|       Debian                 o 停止中  WSL2 -    | CPU / メモリ / ディスク |
|                                                  | IP [コピー]  場所       |
|                                                  | [ターミナルを開く]      |
|                                                  | [起動] [停止] ...       |
|                                                  | バックアップ / 設定・管理 / 削除 |
+--------------------------------------------------+------------------------+
| 準備完了                                  2 件 (実行中 1)   最終更新 12:34 |
+---------------------------------------------------------------------------+
```

- **一覧 (左):** インストール済みのディストリビューション。列見出しのクリックで並べ替え、**検索** (Ctrl+F) で絞り込みます。行のダブルクリックまたは Enter でターミナルを開き、Delete で停止します。右クリック (または Shift+F10) ですべての操作を選べます。
- **詳細パネル (右):** 選択中のディストリビューションの状態、リソース、IP アドレス (コピーボタン付き)、インストール先と、すべての操作ボタンを「バックアップ」「設定・管理」「削除」に分けて表示します。**表示 → 詳細パネル** で隠せます。
- **ボタンは状態に合わせて変わります:** 使えない操作は灰色になります (例: 実行中の「起動」、停止中の「プロセス」、既定のディストリビューションの「既定に設定」)。
- **ツールバー:** 「起動」はウィンドウを開かずにバックグラウンドで起動します。「ターミナル」はシェルを開きます。**＋ 追加** から公式ディストリビューションのインストールとバックアップのインポートができます。
- **質問を何度も続けずに 1 画面のフォームで入力:** エクスポート・インポート・複製は、それぞれ 1 つのフォームに既定値 (今日の日付入りのファイル名、インストール先 `%USERPROFILE%\WSL\<名前>`) が入った状態で開き、tar / VHDX はラジオボタンで選び、入力の誤りはフォームの中に表示されます。`.vhdx` のインポートには自動で `--vhd` を付けます。
- **結果の知らせ方:** WSL の処理中はステータスバーに処理中の表示が出ます。件数と最終更新時刻も表示します。失敗したときは `wsl.exe` のメッセージ付きのエラーダイアログでも知らせるので、見落としません。
- **一覧が空のとき:** 何もインストールされていなければ「インストール」「インポート」を、WSL が無ければその入れ方と「再試行」を表示します。
- **表示メニュー:** 詳細パネル、リソース履歴グラフ、自動更新とその間隔 (5/10/30/60 秒)、テーマ、言語 (その場で反映)、操作ログ。
- 破壊的な操作 (停止、全停止、登録解除、インポート、エクスポートの上書き、バージョン変換、VHDX 圧縮、スナップショット削除) は従来どおり確認を経由します。登録解除はディストリビューション名の再入力も必要です。

キーボード ショートカット (**ヘルプ → キーボード ショートカット**、F1 でも表示):

| キー | 操作 |
|------|------|
| Enter / ダブルクリック | ターミナルを開く |
| Ctrl+Shift+S | バックグラウンドで起動 |
| Delete | 停止 |
| F5 / Ctrl+R | 最新の情報に更新 |
| Ctrl+F | 検索 |
| Ctrl+N / Ctrl+I / Ctrl+E | インストール / インポート / エクスポート |
| Ctrl+S | スナップショットを作成 |
| Ctrl+D / Ctrl+P | 詳細情報 / プロセス一覧 |
| Ctrl+, | WSL 全体の設定 (`.wslconfig`) |
| Ctrl+L | 操作ログ |
| Ctrl+Shift+Q | WSL を全停止 |

### ソースから実行

```powershell
python wslmgr.py
```

Windows では `start_wslmanager.bat` をダブルクリックして起動することもできます。
`dist\WSLManager.exe` があればそれを優先し、無い場合はローカルの `.venv` または
Python Launcher を使用します。

### CLI を使う

インストーラ版とポータブル版の ZIP には、Python なしで動くコンソール用の `wslmgr.exe` が入っています (インストーラで「コマンドライン用ツールを PATH に追加」を選ぶと、どのフォルダからでも `wslmgr` で実行できます)。GUI の **ヘルプ → コマンドライン版** で場所を確認できます。

```powershell
wslmgr list --format json
wslmgr snapshot create Ubuntu --comment "アップグレード前"
```

ソースから使う場合は、リポジトリ直下の `wslmgr.bat` が CLI ランチャーです。Python を `.venv`、Python Launcher (`py -3`)、`python` の順に探して `wslmgr_cli.py` を実行し、渡した引数をすべてそのまま渡して、終了コードも変えずに返します (0 成功、1 エラー、2 引数エラー、3 取消、4 WSL の失敗、5 一部失敗)。スクリプトからも安全に使えます。リポジトリのフォルダを `PATH` に追加すれば、どこからでも `wslmgr` として実行できます。`dist\WSLManager.exe` はウィンドウ専用の GUI ビルドなので、コマンドラインツールとしては使えません。代わりに `dist\wslmgr.exe` をビルドしてください (後述の「コマンドライン用 exe」)。
`&`、`|`、`^` を含む引数は二重引用符で囲んでください。Python 3 が未導入で `py -3` が失敗する場合は、リポジトリのフォルダに `.venv` を作成してください。

```powershell
.\wslmgr.bat list --format json
```

ランチャーを使わず、スクリプトを直接実行することもできます。

```powershell
python wslmgr_cli.py --help
python wslmgr_cli.py --language en --help
python wslmgr_cli.py --version
python wslmgr_cli.py list --with-ip --with-disk
python wslmgr_cli.py list --format json
python wslmgr_cli.py doctor --format json
python wslmgr_cli.py container system-info
python wslmgr_cli.py container list --session "<session-name>" --all --format json
python wslmgr_cli.py container inspect --session "<session-name>" <name-or-id>
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
python wslmgr_cli.py snapshot prune --keep 7 --name Ubuntu       # dry-run
python wslmgr_cli.py snapshot prune --keep 7 --name Ubuntu --yes # 古い世代を削除
python wslmgr_cli.py snapshot schedule create Ubuntu --time 03:00 --keep 7
python wslmgr_cli.py clone Ubuntu UbuntuClone --install-path C:\WSL\UbuntuClone
python wslmgr_cli.py mount C:\disks\data.vhdx --vhd
python wslmgr_cli.py unmount C:\disks\data.vhdx
python wslmgr_cli.py log clear --yes
```

CLI サブコマンドには `list`、`doctor`、`container` (`system-info`/`list`/`inspect`)、`start`、`stop`、`shutdown`、`status`、`export`、`import`、`config`、`set-default`、`unregister`、`install`、`optimize`、`set-version`、`processes`、`log` (`clear`)、`portproxy` (`list`/`add`/`delete`)、`snapshot` (`create`/`list`/`restore`/`delete`/`prune`/`set-dir`/`schedule`)、`clone`、`mount`、`unmount` があります。

### WSL Containers（WSLc）

この連携は公式 **WSL 3.0.1** の CLI 仕様を基準とし、安定版 3.0.1 以降を受け付けます。
WSL パッケージのバージョンとディストリビューションの種別（WSL1/WSL2）は別物であり、種別 3 への変換はありません。

`doctor --format json` でバージョン条件と WSLc サービスを確認します。バージョン条件を
満たすだけでは利用可能と判定しません。実行ファイル不在・ポリシー制限・サービス障害・
タイムアウト・不正な応答を報告し、診断失敗時の終了コードは 4 です。更新は自動実行しません。

最初に `container system-info --format json` を実行し、`Server.Sessions` に表示される
既存セッションの **Name** を `list` / `inspect` の必須オプション `--session` に渡してください。
セッション ID ではなく名前を指定します。GUI では既存セッションを選択します（1 件なら自動選択）。
0 件なら一覧取得を実行せず、複数件なら選択を求めます。これにより WSLc の既定セッション自動作成を
防ぎます。選択したセッションが消えた場合も、新規・既定セッションに切り替えずエラーを表示します。

一覧は実行中のみで、`--all`（GUI:「停止中も表示」）で停止中も含めます。WSLc の行単位 JSON を
CLI では `id` / `name` / `image` / `status` / `health` / `created` の配列へ正規化します。
詳細取得には省略していない ID を使用します。system-info は公式の **オブジェクト** を保持します
（以前の 1 要素配列から変更）。inspect は入れ子を含む配列を保持します。

これらの照会は WSLc サービスに接続・起動する場合がありますが、セッション作成、コンテナの
作成・停止・削除・prune・ネットワーク変更は行いません。従来の WSL2 ディストリビューション管理は
WSLc がなくても使用できます。[仕様の参照先と Windows 実機確認項目](docs/wsl-3.0.1-compatibility.md)
も参照してください。

CLI は保存済みの GUI 言語設定（未指定ならシステム言語）を使ってトップレベルと
`list` のヘルプ、および標準の一覧出力を表示します。サブコマンドの前に `--language auto`、`--language ja`、
`--language en` を指定すると、その実行だけ上書きできます。

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

配布物はすべて 1 コマンドで作れます (Windows、Python 3.10 以上)。

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

`.venv` を作成 (既存なら再利用) して固定版の PyInstaller を入れ、単体テストを実行してから、`dist\` に次を出力します。

```text
dist\WSLManager.exe                          GUI (1 ファイル、Python 不要)
dist\wslmgr.exe                              コマンドライン版
dist\installer\WSLManager-Setup-X.Y.Z.exe     インストーラ (Inno Setup 6.3 以降がある場合)
dist\WSLManager-X.Y.Z-portable.zip           2 つの exe + README + LICENSE
dist\SHA256SUMS.txt                          チェックサム
```

オプション: `-SkipTests`、`-SkipInstaller`、`-RequireInstaller` (Inno Setup が無いときに省略せず失敗させる。Inno Setup は `winget install JRSoftware.InnoSetup` で入ります)、`-Python <python.exe>`、`-Iscc <ISCC.exe>`。CI も同じスクリプトでビルドするので、手元のビルドとリリースのビルドは同じ手順です。

どちらの exe にもアプリのアイコン (`assets/wslmanager.ico`) と Windows のバージョン情報 (エクスプローラーのファイルのプロパティに表示される製品名・バージョン) を埋め込みます。バージョンは `wsl_core.__version__` から取ります。ウイルス対策ソフトの誤検知を減らすため UPX は使いません。

`WSLManager.spec` と `pyinstaller_hooks/` は意図的に同梱しています。conda / miniforge 環境では、無関係なパッケージの PyInstaller hook や Tcl/Tk 検出の問題で解析が失敗することがあるため、これらを使ってビルドを安定させています。PyInstaller を直接使う場合は `python -m PyInstaller --clean WSLManager.spec` (GUI) と `python -m PyInstaller --clean WSLManagerCLI.spec` (CLI) です。

#### コマンドライン用 exe

`dist\WSLManager.exe` はウィンドウ専用の GUI ビルドなので、ターミナルには何も出力しません。コマンドラインツール `dist\wslmgr.exe` は `WSLManagerCLI.spec` から別にビルドします。Python なしで動くコンソール用の exe なので、出力・リダイレクト・終了コード (0 成功、1 エラー、2 引数エラー、3 取消、4 WSL の失敗、5 一部失敗) が通常のコマンドラインツールと同じように動きます。tkinter は含まれず、`pyinstaller_hooks/` も使いません。

- onefile の exe は実行のたびに展開されるため、起動に約 0.6 秒かかります (`python wslmgr_cli.py` を直接実行すると約 0.15 秒です)。
- 出力をファイルやパイプへリダイレクトすると、Windows の ANSI コードページ (日本語 Windows では cp932) でエンコードされます。日本語を表現できないコードページの環境では、日本語を含むメッセージのエンコードに失敗することがあります。onefile の exe は `PYTHONIOENCODING` を無視します。Python スクリプトと同じ制約で、別の Issue として扱います。
- `snapshot schedule create` は、インストールされた `wslmgr.exe` 自身を絶対パスで Task Scheduler に登録します。exe を移動・アンインストールする場合は、先に `snapshot schedule delete` でタスクを削除してください。
- このビルドの `wslmgr.exe` と、リポジトリ直下の `wslmgr.bat` (Python スクリプトを実行するランチャーで、Python が必要) を混同しないでください。

#### Windows インストーラ

`installer/WSLManager.iss` は、`WSLManager-Setup-<version>.exe` をビルドする [Inno Setup](https://jrsoftware.org/isinfo.php) 6.3 以降のスクリプトです (`build.ps1` が実行します)。手動でコンパイルする場合は、先に `dist\WSLManager.exe` と `dist\wslmgr.exe` をビルドしてから、`pyproject.toml` のバージョン (数値の `X.Y.Z` だけ) を渡します。

```powershell
iscc /DAppVersion=1.0.0 installer\WSLManager.iss
```

```text
dist\installer\WSLManager-Setup-1.0.0.exe
```

CI は push と pull request のたびにインストーラをコンパイルし、`WSLManager-installer` という artifact として保存します。インストーラの動作:

- **既定はユーザー単位**です。管理者権限は不要で、`%LOCALAPPDATA%\Programs\WSL Manager` に入ります。インストール時のダイアログで、全ユーザー向け (`Program Files`、管理者権限が必要) に切り替えられます。
- `WSLManager.exe` (GUI) と `wslmgr.exe` (コマンドライン) を入れ、スタートメニューにショートカットを作ります。デスクトップのショートカットと**コマンドライン用ツールを PATH に追加**する選択肢は任意で、**既定はオフ**です。PATH への追加先はユーザーの `PATH` (全ユーザー向けのときはシステムの `PATH`) で、アンインストール時に除去されるのは、インストール先のエントリだけです。すでに開いているターミナルには反映されません。
- WSL Manager が起動している間は、上書きインストールもアンインストールもできません。先に終了してください。実行中の `wslmgr.exe` は、エクスポートや定期スナップショットの最中かもしれないため、インストーラが勝手に閉じることはしません。ファイルが使用中のときは、数回再試行してから中止し (インストーラの終了コード 5。`wslmgr.exe` の終了コードとは無関係です)、インストール済みのファイルには手を付けません。コマンドが終わるのを待って、もう一度実行してください。
- **アンインストールしてもデータは残ります。** 設定とログ (`%APPDATA%\WSLManager`)、スナップショット (`%USERPROFILE%\WSLSnapshots`) は、スナップショットが WSL ディストリビューションのバックアップなので、決して削除しません。
- 定期スナップショットのタスクも削除しません。タスクはインストールされた `wslmgr.exe` をフルパスで指しているので、WSL Manager を移動またはアンインストールする前に、インストール先で `wslmgr.exe snapshot schedule delete` を実行して削除してください。
- インストーラは英語と日本語に対応しています。コード署名はしていないため、実行時に Windows SmartScreen の警告が出ることがあります。

サイレントインストール (スクリプト向け):

```powershell
.\WSLManager-Setup-1.0.0.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /DIR="C:\Tools\WSLManager" /TASKS=addtopath_user
```

全ユーザー向けにするときは、`/CURRENTUSER` の代わりに `/ALLUSERS` (と `/TASKS=addtopath_system`) を使います。全ユーザー向けでは、既定の `Program Files` のままにしてください。一般のユーザーが書き込めるフォルダを `/DIR` に指定して `addtopath_system` と組み合わせると、そのフォルダがすべてのユーザーのシステム `PATH` に入ってしまいます。サイレントのアンインストールは、インストール先の `unins000.exe /VERYSILENT /SUPPRESSMSGBOXES` です (インストーラと同じく、WSL Manager の起動中は止まります)。

リリースとダウンロード: `pyproject.toml` (と `wsl_core.__version__`) のバージョンに一致するタグ `vX.Y.Z` をプッシュすると、CI が `WSLManager-Setup-X.Y.Z.exe`、`WSLManager-X.Y.Z-portable.zip`、単体の `WSLManager.exe` (GUI) と `wslmgr.exe` (コマンドライン)、`SHA256SUMS.txt` を添付した GitHub Release を公開します。ファイルにコード署名はしていないため、チェックサムが役に立つのは、ダウンロードの破損や差し替えに気づくときだけです。ダウンロードしたファイルと見比べてください。

```powershell
Get-FileHash .\WSLManager-Setup-1.0.0.exe -Algorithm SHA256
Get-Content .\SHA256SUMS.txt
```

CI は毎回、インストーラを実際にインストールして検証します (`installer\verify-installer.ps1`: サイレントインストール、上書き、アンインストール、PATH とデスクトップのショートカットの任意タスク、使用中のファイル)。手元でも `pwsh -File installer\verify-installer.ps1 -Setup <Setup.exe> -InstallDir <一時フォルダ>` で実行できます。WSL Manager がすでにインストールされているマシンでは実行を拒否します (同じ AppId なので、その環境を上書きしてしまうため)。また `-InstallDir` を削除するので、`-Force` を付けない限り、一時フォルダの下の空のフォルダしか受け付けません。WSL Manager を起動することも、WSL やデータに触れることもありません。ユーザーの `PATH` は、PATH の検証中だけ変更し、元の値と型を完全に復元します。

## 実装仕様

### モジュール構成

| ファイル | 役割 |
|----------|------|
| `wslmgr.py` | tkinter のメイン画面 (`WSLManager`): ツールバー、一覧、詳細パネル、ステータスバー、メニュー、各操作と確認処理 |
| `wslmgr_gui/` | GUI 部品: `detail_panel.py`、`style.py` (共通のスタイルと色)、`ui_queue.py` (ワーカースレッドの結果を Tk のメインスレッドへ渡す)、`resources.py` (同梱アイコン、`wslmgr.exe` の検索)、`dialogs/` (フォームと各ダイアログ)、`app/` (メイン画面の Mixin)、Windows 定数とレジストリヘルパー |
| `wslmgr_cli.py` | argparse ベースの CLI |
| `wsl_core/` | 解析、整形、バリデーション、設定、ログ、スナップショット、進捗計算、翻訳、ディストリビューションごとの操作の可否を判定する純粋ロジック |
| `tests/` | `wsl_core`、CLI、GUI (モックを使い、実際のウィンドウは作らない) の unittest |
| `WSLManager.spec` / `WSLManagerCLI.spec` | PyInstaller ビルド定義 (GUI / CLI) |
| `pyinstaller_hooks/` | tkinter / Tcl/Tk パッケージング用のローカル PyInstaller hook |
| `tools/pyinstaller_support.py` | 2 つの spec が共有する、exe のバージョン情報 |
| `assets/` | アプリのアイコン (exe とインストーラ用の `.ico`、ウィンドウ用の `.png`) |
| `build.ps1` | exe・インストーラ・ポータブル版 ZIP・チェックサムを 1 コマンドで作るスクリプト |
| `installer/` | Inno Setup のスクリプトと、その検証スクリプト |

### アーキテクチャ

- GUI は Windows 向けで、`tkinter`、`ttk`、`subprocess`、`winreg` を使用します。
- コアロジックは可能な限り GUI、レジストリ、subprocess に依存しない形に分離し、Windows 以外の CI でもテストできるようにしています。
- WSL コマンド出力は `wsl_core.decode_wsl_output()` で UTF-16 LE、UTF-8、CP932、フォールバックエンコーディングに対応します。
- 時間のかかる処理はバックグラウンドで実行し、GUI のフリーズを避けます。ワーカーは Tk のウィジェットに触れず、結果をキューに積み、メインスレッドが取り出して画面を更新します (`wslmgr_gui/ui_queue.py`)。
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
- `snapshot prune --keep N` は既定で削除候補だけを表示します。`--yes` を明示した場合のみ、ディストリビューションごとに新しい N 世代を残して、古い tar/メタデータ組を削除します。
- Windows では `snapshot schedule create <name> --time HH:MM --keep N` により毎日実行するタスクを登録できます。登録・削除には確認が必要です。登録したタスクには、登録時に承認した世代整理のための `--yes` が明示的に含まれます。`snapshot schedule list` / `delete <name>` で管理できます。
- 操作ログは構造化レコードとしてシリアライズし、`wsl_core/logging.py` のヘルパーでローテーションします。

### パッケージング

生の `pyinstaller wslmgr.py` ではなく `build.ps1` (または spec ファイル) を使います。GUI の spec は conda / miniforge の DLL を存在する場合に収集し、ウィンドウ用のアイコンを同梱します。ローカル hook は PyInstaller の runtime hook が参照する `_tcl_data` と `_tk_data` を用意します。

### テスト

```powershell
python -m py_compile wslmgr.py wslmgr_cli.py
python -m compileall -q wsl_core wslmgr_gui tools
python -m unittest discover -s tests -v
```

Linux / macOS では、GUI 以外の大部分を `python3` で検証できます。

### CI

GitHub Actions では、Ubuntu と Windows の複数 Python バージョンでコンパイルチェックと単体テスト、ruff と mypy を実行します。Windows では `build.ps1` で配布物をすべてビルドし、exe のバージョン情報を確認し、インストーラを実際にインストール・アンインストールして検証し、ポータブル版 ZIP の中身を確認します。

## ライセンス

MIT License。詳細は [LICENSE](LICENSE) を参照してください。
