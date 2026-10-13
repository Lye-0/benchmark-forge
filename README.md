# Benchmark Forge

ローカルで動く、再現可能なLLM評価ラボ。問題生成にLLMを使わず、固定問題とシード付きの動的問題を確定してから、同じセットを各モデルへ配布します。日本語のダークテーマWeb UIとCLIから同じエンジンを利用できます。

**現在は Preview v1。正式な Standard、実測で校正された難易度、実モデルの性能測定結果はまだ提供していません。** Mockの参照ソルバーはソフトウェア診断専用です。

## 起動

対象：Windows 11ネイティブ / Linux / WSL2 Ubuntu。前提はPython 3.12（uv管理）、Node.js 24系、npm。開発で確認した環境はPython 3.12.14 / uv 0.12.23 / Node 24.19.0です。GPU・Docker・APIキー・有料契約は不要です。


### Windows（PowerShell）

```powershell
.\scripts\setup.ps1
.\scripts\start.ps1
```

Windows版アプリはWSL2を経由しません。Pythonはuvの専用`.venv`、Node.jsは既存24系、npmを使用します。一般利用にmise・Dockerは不要です。詳しい環境準備、任意のCUDA、Docker Desktop、実機チェックは[Windows手順](docs/WINDOWS.md)を参照してください。

### Linux / WSL2（Bash）

```bash
cd benchmark-forge
bash scripts/setup.sh
bash scripts/start.sh
```

ブラウザで `http://127.0.0.1:8000` を開きます。ビルド済みUIとAPIを同じプロセスで配信します。ポートが使用中なら `FORGE_API_PORT=8001 bash scripts/start.sh` とし、ブラウザ側のポートも変えてください。Ctrl+Cで終了します。

1. 「新しいベンチマーク」でプリセット・モデル・生成器・難易度・比率を選択。
2. 「問題セットを確定する」で件数・ハッシュ・警告・設問を確認。この操作ではモデルを呼びません。
3. 「このセットで実行する」で順次評価。進捗、一時停止・再開、保存された結果、問題別ログを確認。
4. 同じセットで評価したランを比較し、CSV / JSONL / Markdownをダウンロード。

初回は **Mock / 参照ソルバー** と **Mock / 誤答テスト** が登録されています。Mockは生成器が保存した正解を読まず、公開問題文を独立した規則で解きます。結果はすべて診断と明示され、正式ランキングに使えません。

## 開発

```bash
# ターミナル1
uv run --no-sync forge serve --port 8000
# ターミナル2
cd apps/web
npm run dev
```

Viteは `127.0.0.1:5173` で起動し、`/api` をバックエンドへプロキシします。ポートを変更する場合、バックエンドの `FORGE_WEB_ORIGIN` とViteの `FORGE_WEB_PORT` / `FORGE_API_PORT` を揃えます。例えばAPIを8001、Webを5174で動かす場合：

```bash
FORGE_WEB_ORIGIN=http://127.0.0.1:5174 uv run --no-sync forge serve --port 8001
# 別ターミナル / apps/web
FORGE_WEB_PORT=5174 FORGE_API_PORT=8001 npm run dev
```

## CLI

```bash
uv run --no-sync forge generators
uv run --no-sync forge generate --count 24 --seed 42
# generate が表示したset_idを使用
uv run --no-sync forge run SET_ID --models mock-reference,mock-wrong
uv run --no-sync forge report RUN_ID --format markdown
uv run --no-sync forge report RUN_ID --format csv --output report.csv
```

`--generators math.linear,data.aggregate` 等で範囲を限定できます。`generate --output` は参照解答付きのセットを保存します。**そのファイルをモデル入力に渡さないでください。** 出力コマンドは既存ファイルを上書きしません。APIとCLIの評価プロセスを同じデータ領域で同時に起動すると、ファイルロックにより拒否します。

## ローカルモデル

Windows版またはLinux/WSL2版Ollamaをローカル起動し、ユーザー自身がモデルを用意します。「モデル」でバックエンド `Ollama`、モデル名、`http://127.0.0.1:11434`、リビジョン・量子化・推論条件を登録し、接続確認します。推論時には問題本文のみ送信します。リダイレクト、認証情報付きURL、外部ホスト、DNSによる接続先は拒否します。Ollamaの実モデル推論はこのクラウドでは未検証です。

Transformersは任意依存と専用推論ワーカーに対応しています（実モデル未検証、利用条件は下記）。Codex CLI / App Serverは公式のイベント契約とMock試験まで実装し、実行可能な隔離を検証できていないため実接続を無効にしています。認証キャッシュの解析・転用や有料APIへの代替は行いません。

## 検証

```bash
bash scripts/check.sh
cd apps/web
npx playwright install chromium
npm run e2e
# Cloudなど、システムChromiumを使用する場合
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run e2e
```

E2Eは通常のデータ領域と別の一時DB・専用ポートを使用します。生成器・固定コーパスの整合、再現性、一意解、重みと分母、中断・再開、API/CLI、外部Origin拒否、Codex通信の失敗、安全側での実行停止をテストしています。実Dockerの権限・ネットワーク・資源制限・削除試験は実行済みです。GPU試験・Codex実接続は未実施です。GitHub Actionsの実行結果はリポジトリへpush後に確認してください。

## データと制限

- SQLiteは既定で `.benchmark-forge/forge.sqlite3` に保存。`FORGE_DATA_DIR` で変更可能。マイグレーションは自動適用。バックアップはサービス停止後にデータ領域全体をコピーします。
- 24生成器 / 15大カテゴリ / 480件の小規模な固定コーパス。固定問題が足りない条件は失敗し、動的問題へ無断で置換しません。狭い難易度範囲には固定問題がないことがあります。
- 総合値はカテゴリ均等の重み付き正答率。全割当問題を分母とし、タイムアウト・エラー・無回答も保持します。単純正答率と固定/動的の寄与も表示します。
- コード生成・ネイティブツール・複数ターン仮想在庫は独立評価です。コードは実行プロセスでDocker隔離の検証が通った場合のみ有効。Ollamaツール対応はモデルごとの申告と実検証が必要です。
- 難易度は構造パラメーターの暫定値。固定コーパスの難易度は5つの保管点ですが、動的生成と設定は連続値です。カテゴリ間の同じ値が同じ難しさを意味するとは限りません。
- RAM/VRAM/TTFTなど未測定の値はN/A。能力・速度・リソースを単一スコアに合成しません。
- 外部データは含めていません。コードライセンスはユーザー未決定で、無断でMIT等を適用していません。

詳しい進捗は [docs/STATUS.md](docs/STATUS.md)、次の開発は [docs/ROADMAP.md](docs/ROADMAP.md)、安全性は [docs/SECURITY.md](docs/SECURITY.md)、Windowsネイティブの手順は [docs/WINDOWS.md](docs/WINDOWS.md)、Linux/WSL2は [docs/WSL2.md](docs/WSL2.md) を参照してください。

### ローカルTransformers（Windows / Linux / WSL2、実モデル未検証）

任意依存は `uv sync --locked --extra transformers` で導入できます（Torchを含み大容量）。通常のMock/Ollama開発には不要です。Webのモデル登録でTransformersを選び、取得済みモデルのローカルディレクトリとCPU/CUDAを指定します。safetensors形式のみ対応し、ダウンロードやremote code実行はしません。量子化指定は現時点でN/Aまたはnoneに限定しています。

問題ごとにモデルをロードするため、タイムアウトにはロード時間も含まれます。実行中の中止はワーカーを終了します。ロード・生成時間とメモリは問題ログ/JSONLに記録します。生成時間はprefill込みでありdecode速度ではありません。詳細な検証範囲は [STATUS](docs/STATUS.md) を参照してください。

## 独立評価と履歴

「プロファイル・設定」に私有holdout、速度試験、ツール/コード評価があります。通常の能力評価と合算しません。試行履歴は再試行後も保持し、旧DBはv2へ自動移行します。更新前のバックアップはサービスを停止してデータ領域をコピーしてください。

```bash
uv run --no-sync forge import-holdout /path/to/private.jsonl
uv run --no-sync forge tool-set --mode agent --count 5
uv run --no-sync forge speed-probe --input-repetitions 100 --output-repetitions 32
uv run --no-sync forge code-set --count 5
# 上記コマンドが返したSET_IDを使用
uv run --no-sync forge run SET_ID --models mock-reference
uv run --no-sync forge resume RUN_ID
uv run --no-sync forge resume RUN_ID --retry
uv run --no-sync forge report RUN_ID --format jsonl --output report.jsonl.gz --compress
uv run --no-sync forge calibration REAL_MODEL_RUN_ID --output observations.jsonl
```

モデルはWebまたは `forge model-register /path/to/model-config.json` で登録します。私有問題の形式は [HOLDOUT.md](docs/HOLDOUT.md)。校正用の出力はMock・未完了・速度/ツール/コードを拒否します。

## Dockerコード採点（任意）

通常のテキスト評価にはDockerは不要です。コード採点を使う環境で、次の固定イメージを一度取得します。アプリは自動pullしません。

```bash
docker pull python@sha256:a6e34c598f2467ed0e9a8d349809fcd8b5c603269512df273a0bb1784edc11b1
uv run --no-sync forge sandbox-check
FORGE_TEST_DOCKER=1 uv run pytest -q tests/test_sandbox.py
```

Webのコード評価は開始時に隔離検証し、CLIのコード評価も同じプロセスで検証します。Docker socketをモデル・コンテナへ渡さず、ネットワークとホストmountを禁止します。検証できない環境では無効です。詳細は [SECURITY.md](docs/SECURITY.md)。

### 初回応答時間と全記録の出力

Ollama登録時に「ストリーミングで初回応答時間を測る」を有効化できます。問題ログの「初回テキスト受信」はHTTP要求開始から最初の可視テキストchunkまでの時間です。内部の最初のtoken時刻とは異なり、非streaming・空回答・ツール評価ではN/Aです。途中切断や終端の欠落を成功扱いしません。

問題ログの「全問題・試行アーカイブ」または次のCLIで、実行条件・未回答を含む全問題・結果・全試行を順次JSONLへ出力できます。

```bash
uv run --no-sync forge archive RUN_ID archive.jsonl
uv run --no-sync forge archive RUN_ID archive.jsonl.gz --compress
```

`forge-stream-v1`形式で、出力開始時のSQLiteスナップショットを保持します。結果・試行は1件ずつ処理しますが、確定問題セットはメモリに保持します。遅いダウンロード中はWALが拡大する可能性があります。**参照解答や私有問題を含むため、モデル入力に渡したり無条件に公開したりしないでください。** 通常のJSONLレポート形式とは異なります。

大きいアーカイブは、存在しない新規フォルダーを指定して分割出力できます。以下はPowerShellでも同じコマンドです。

```bash
uv run --no-sync forge archive-split RUN_ID archive-parts --part-mib 64 --compress
uv run --no-sync forge archive-verify archive-parts
```

各パートは独立したgzipファイルです。`--compress`を省略するとJSONLになります。サイズは圧縮前のUTF-8バイト数で判定し、JSONの1行を途中で切りません。1レコードが指定サイズを超える場合、そのパートのみ上限を超えます。`manifest.json`の順序で各パートを展開・連結すると単一の`forge-stream-v1`アーカイブになります。

検証は各パートの欠落・保存サイズ・SHA-256を確認します。参照先はフォルダー内の連番ファイルに限定し、内容の真正性や採点の妥当性までは保証しません。既存フォルダーへの出力は拒否します。途中失敗したフォルダーには完成を示す`manifest.json`がなく、不完全な出力として検証に失敗します。再試行には別の新規フォルダーを指定してください。

### 実行中の回答時間

結果画面とMarkdownレポートに全確定結果の平均、直近20件以内の平均、残り回答処理時間の推定を表示します。推定は実行中のみ、直近10件以上があり、変動係数が0.35以下で、エラー・タイムアウト・採点不可を含まない場合に限ります。条件を満たさない場合はN/Aと理由を表示します。

この値は直近の平均時間が続くと仮定した参考値です。待機列・一時停止・結果保存の時間を含まず、処理中の1問は全時間を見込みます。完了予定時刻や信頼区間ではありません。再試行した問題は最新の確定結果だけを実際の完了順に集計し、過去の失敗試行を重複加算しません。
