# Windows 11 ネイティブ運用

通常のアプリ・問題生成・採点・保存・Ollama・TransformersはWindowsで実行する構成です。通常評価にはWSL2もDockerも不要です。生成コードを実行する評価だけ、Docker DesktopのLinuxコンテナを使います。Ubuntuを手動起動する必要はありません。

この手順はWindows実機での確認用です。CloudでのLinux実行、Mockによる通信契約検証、Windows CIの設定を、Windows実機・CUDA・Docker Desktopでの検証と混同しません。最新の確認状況は[STATUS](STATUS.md)を参照してください。

## 必要環境と管理方針

- Windows 11 x64、PowerShell 5.1以上、Git、uv、Node.js 24系、npm。
- ご提示のuv 0.12.13 / Node.js 24.21.0 / npm 11.19.0をそのまま使用する想定です。miseやpnpmの導入・更新は不要です。npmと`apps/web/package-lock.json`を使用し、pnpm用ロックは作りません。
- Pythonはuv管理の3.12、プロジェクト専用`.venv`。既存の3.11/3.14を削除せず、miseのPython設定も変更しません。`.python-version`は3.12系を指定します。uvは不足時に管理対象Pythonを取得します。
- 3.12を選ぶ根拠は既存のプロジェクト・テスト対象と、ロック済みPyTorch 2.14.1のWindows CPython 3.12向けCPU/CUDA wheelが存在することです。wheelの存在はGPU動作保証ではありません。
- Node.js 24系を維持し、グローバルnpmパッケージは追加しません。依存関係は`uv sync --locked`と`npm ci`で再現します。
- 作業フォルダーは通常ユーザーが書き込めるローカルディスクを使用してください。SQLiteの稼働中DBをネットワーク共有や同期フォルダーに置かないでください。WindowsとWSLで同じ`.venv` / `node_modules`を共有しません。Windows/WSLをまたぐ同じDBへの同時アクセスも避け、OSごとに保存先を分けてください。異なるOS間のロック連携は保証しません。

## 初回セットアップと起動

PowerShellでリポジトリを開きます。管理者権限は不要です。

```powershell
Set-Location C:\dev\benchmark-forge
uv --version
node --version
npm.cmd --version
.\scripts\setup.ps1
.\scripts\start.ps1
```

`setup.ps1`はuvでPython 3.12と依存を準備し、npmでUIをビルドします。通常セットアップにTorch・CUDA・Dockerは含まれません。`start.ps1`はビルド済みUIとAPIを127.0.0.1:8000で配信します。ブラウザーで`http://localhost:8000`を開き、停止は起動したターミナルでCtrl+Cです。別ポートは`start.ps1 -Port 8001`で指定できます。

PowerShellのポリシーがスクリプトを拒否する場合は`Get-ExecutionPolicy -List`で確認し、組織の署名・許可手順に従ってください。これらのスクリプトはExecutionPolicy、証明書検証、レジストリ、ファイアウォールを変更しません。未許可のスクリプトを動かすためのBypassは使用しません。

初回は「クイック診断」でMockモデルのセットを確定し、開始→完了→問題ログ→JSONL出力まで確認してください。Mockはアプリ動作検証専用で、実モデルの性能ではありません。実行中の一時停止・再開・中止も確認してください。

保存先は既定でリポジトリ内の`.benchmark-forge`です。変更は起動前に次を設定します。

```powershell
$env:FORGE_DATA_DIR = 'C:\Users\YOUR_NAME\benchmark-forge-data'
.\scripts\start.ps1
```

APIとCLIによる評価を同じ保存先で同時起動しないでください。WindowsのOSファイルロックで拒否します。DBをバックアップするときはアプリを停止し、保存ディレクトリ全体をコピーします。Windowsのアクセス権は保存先のACLに従います。

## Windows版Ollama

Windows版Ollamaを公式手順で導入・起動し、利用条件を確認したモデルを自身で用意してください。WSL側で動かす必要はありません。

```powershell
ollama list
Invoke-RestMethod http://127.0.0.1:11434/api/tags
```

UIの「モデル」でOllama・一覧にあるモデル名・`http://127.0.0.1:11434`を登録して接続確認します。接続先設定はIPv4/IPv6のループバックIPに限定し、DNS名`localhost`は登録欄では受け付けません。ブラウザーのlocalhostアクセスは可能です。

モデル一覧・`/api/show`の申告情報の取得と、実際の推論成功は別です。少数の通常評価を実行し、正答率、エラー、出力、量子化・コンテキスト条件を確認してください。初回テキスト受信時間を測る場合は登録時のストリーミングを有効化します。ネイティブツールは対応モデルでのみ申告し、独立評価で確認してください。

## Transformers / PyTorch（任意）

Windows CPU版を使う場合:

```powershell
uv sync --locked --python 3.12 --extra transformers
.\scripts\diagnose.ps1 -Torch
.\scripts\start.ps1
```

Windows CUDA版を使う場合:

```powershell
uv sync --locked --python 3.12 --extra transformers-cuda
.\scripts\diagnose.ps1 -Torch
.\scripts\start.ps1
```

`setup.ps1 -Backend transformers`または`-Backend transformers-cuda`でもUIを含めて準備できます。2つのextraは同時選択不可です。CUDA版は公式`download.pytorch.org/whl/cu130`の2.14.1+cu130をハッシュ付きでロックしています。対応するNVIDIA GPUとCUDA 13.0対応ドライバーが必要です。アプリはドライバーやCUDA Toolkitをインストール・更新しません。既存GPUが対応しない場合はCPU版を使用できます。

既存の`transformers` extraはPyPI配布版を維持するため、WindowsではCPU版、LinuxではCUDA依存を含む版になります。`transformers-cuda`はWindows/Linux向けの明示的なCUDA 13.0版です。通常セットアップにはどちらも入りません。

起動には`--no-sync`を使用し、選択した任意依存を維持します。別途`uv sync`をextraなしで実行すると任意依存は除去されるので、再度必要なextraを指定してください。

診断はモデルをロードせず、Torch版・CUDA build・CUDA利用可否・GPU名/総VRAMを調べます。UI「プロファイル・設定」の「PyTorch / CUDAを確認」からも実行可能です。`cuda_available: false`でも通常評価やCPU推論は利用できます。GPU構成の取得とCUDA利用可否は別です。

モデル登録でTransformers、取得済みsafetensorsモデルのWindowsパス（例`C:\models\your-model`）、CPUまたはCUDAを指定します。remote codeは禁止し、モデルを自動取得しません。推論は問題ごとに別プロセスでロードし、Windows Job Objectで子プロセスも終了管理します。Jobの割り当てに失敗した場合は推論を拒否します。この仕組みは信頼できないコードを動かすsandboxではありません。

## コード評価用Docker Desktop（任意）

通常の数学・論理・文章・仮想ツール評価には不要です。生成コードを実行する場合だけ、Docker Desktopを公式手順で導入し、Linuxコンテナを有効化します。内部WSL2基盤はDocker Desktopに任せます。Windowsコンテナモードは非対応です。

```powershell
docker info --format '{{.OSType}}'
docker pull python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
.\scripts\diagnose.ps1 -Sandbox
```

API起動後はUIの「隔離環境を診断」で、そのAPIプロセス内の実検証を行います。別CLIプロセスの診断結果はAPIへ引き継ぎません。コード評価の開始時にも検証します。Docker未導入・daemon接続不可・Windowsコンテナ・検証失敗ではコード評価だけを無効化します。ホスト実行への代替はありません。

マウントなし、ソケット/秘密の受け渡しなし、network=none、非root、capabilities削除、read-only root、限定tmpfs、seccomp、CPU/メモリ/PID/時間/出力量を制限します。診断は実際の書込み・通信失敗、cgroup、OOM、CPU時間制限を検査します。cgroup v2等の条件を満たさないDocker環境は拒否します。Docker/VM/カーネルを信頼する境界があり、完全隔離の保証ではありません。

詳細な実機テストは次で実行できます（固定のソフトウェアfixtureのみ）。

```powershell
$env:FORGE_TEST_DOCKER = '1'
uv run --no-sync pytest -q tests/test_sandbox.py
Remove-Item Env:FORGE_TEST_DOCKER
```

## Codex

公式App Serverイベント・JSONL/RPCのMock検証と接続設計を維持しています。Windowsを含め実認証・transport隔離は未検証で、live実行は無効のままです。Dockerの診断成功によってCodexを自動有効化しません。認証キャッシュのコピーや有料APIへの置換は不要です。

## 開発と自動テスト

```powershell
.\scripts\check.ps1
Set-Location apps\web
npx.cmd playwright install chromium
npm.cmd run e2e
```

CIはWindows/Linux両方でPythonテスト、型検査、Webテスト・ビルド・E2Eを実行する構成です。Windows E2Eは`start.ps1`を使ってAPIを起動します。Windows jobには任意CPU版Torchのインストールとモデルを使わないランタイム診断も含めます。実DockerテストはLinux jobのみで、Windows GPU/Docker Desktopは実機での確認が必要です。CI設定の追加と実際のCI成功は区別して記録します。

開発中のViteは別ターミナルで`npm.cmd --prefix apps/web run dev`、APIは`start.ps1`で起動できます。通常利用はビルド済みUIのみで十分です。

| 症状 | 確認・対応 |
|---|---|
| `npm.ps1`がポリシーで拒否 | 本手順・スクリプトは`npm.cmd`を使用。ポリシーを無効化しない |
| 8000番が使用中 | `start.ps1 -Port 8001`。他アプリのプロセスを終了しない |
| データ領域ロック失敗 | 同じ保存先のAPI/CLIを閉じる。保存先権限も確認。稼働中にlockファイルを削除しない |
| Ollama接続不可 | Windows版Ollamaの起動、`/api/tags`、モデル名、ループバックIPを確認 |
| Torch/DLL読み込み失敗 | 指定extraと3.12の`.venv`、公式Windowsランタイム要件を確認。通常評価は継続可能 |
| CUDA不可 | CPU版かCUDA版か、GPUとドライバー互換性を確認。CPU登録でも利用可能 |
| Docker診断失敗 | Desktop起動、Linuxコンテナモード、固定イメージ、cgroup/権限条件を確認。制限を緩めて成功扱いにしない |

公式資料: [uvとPyTorch](https://docs.astral.sh/uv/guides/integration/pytorch/)、[PyTorch Windows](https://pytorch.org/get-started/locally/)、[Ollama Windows](https://docs.ollama.com/windows)、[Docker Desktop Windows](https://docs.docker.com/desktop/setup/install/windows-install/)。依存構成は2026-10-12にuv公式GitHub資料と公式wheel indexで確認しました。


## Intel / NVIDIA併用PCのGPU診断

Windowsでは`nvidia-smi`によるNVIDIA構成情報に、CIMのディスプレイアダプター名・ドライバー版を補完します。PATHにない場合はWindows System32とNVIDIA NVSMIの標準配置も確認します。NVIDIA取得失敗とCIM取得失敗を別々に表示し、CIMだけで検出したGPUの専用VRAM容量はN/Aです。GPUが表示されても、OllamaがそのGPUで推論していることを保証するものではありません。

```powershell
git pull
.\scripts\diagnose.ps1 -Gpu
```

または`uv run --no-sync forge doctor --gpu`で同じ診断を実行できます。JSONの日本語はWindowsの文字コードに依存しないエスケープ形式です。追加パッケージ・Torch・CUDA toolkitのインストールやモデルの再実行は不要です。アプリを再起動後、設定画面の「GPUの現在値を確認」からも単発計測できます。

`gpu_devices`は構成情報、`gpu_sample`はNVIDIA GPU全体の使用率・使用メモリ・電力・温度の取得時点の値です。他アプリの使用量を含み、モデル単位やベンチマーク中のPeakではありません。ドライバーが提供しない値はN/A（JSONではnull）と理由を返します。構成情報はアプリ起動後の初回取得をキャッシュし、現在値は診断ボタンを押すたびに取得します。診断失敗でも通常評価を禁止せず、計測値を0で代用しません。

Cloudでは応答fixtureによる検証を実施し、Windows CIにもPowerShell診断を追加しています。実際のRTX 5070 Laptop GPUでの取得値・ドライバー互換性は、上記の実機診断結果で確認してください。ドライバーの自動更新やGPU切り替え設定の変更は行いません。

DockerがないPCで`diagnose.ps1 -Sandbox`を実行すると、`state: not_installed`と`available: false`が返るのが正常です。コード評価以外の通常評価は利用できます。スクリプトはこの診断結果を表示し、一般的な例外スタックを出さずに終了コード1を返します。自動処理では、コード隔離が利用不可であることを引き続き判別できます。診断自体が壊れている場合（不正なJSON等）は例外を隠しません。Docker導入は生成コードの実行評価を使う段階で構いません。
