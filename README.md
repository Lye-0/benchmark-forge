# Benchmark Forge

ローカルで動く、再現可能なLLM評価ラボ。問題生成にLLMを使わず、固定問題とシード付きの動的問題を確定してから、同じセットを各モデルへ配布します。日本語のダークテーマWeb UIとCLIから同じエンジンを利用できます。

**現在は Preview v1。正式な Standard、実測で校正された難易度、実モデルの性能測定結果はまだ提供していません。** Mockの参照ソルバーはソフトウェア診断専用です。

## 起動

前提：LinuxまたはWSL2 Ubuntu、Python 3.12、uv、Node.js 22または24、npm。開発で確認した環境はPython 3.12.14 / uv 0.12.23 / Node 24.19.0です。GPU・Docker・APIキー・有料契約は不要です。

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
uv run forge serve --port 8000
# ターミナル2
cd apps/web
npm run dev
```

Viteは `127.0.0.1:5173` で起動し、`/api` をバックエンドへプロキシします。ポートを変更する場合、バックエンドの `FORGE_WEB_ORIGIN` とViteの `FORGE_WEB_PORT` / `FORGE_API_PORT` を揃えます。例えばAPIを8001、Webを5174で動かす場合：

```bash
FORGE_WEB_ORIGIN=http://127.0.0.1:5174 uv run forge serve --port 8001
# 別ターミナル / apps/web
FORGE_WEB_PORT=5174 FORGE_API_PORT=8001 npm run dev
```

## CLI

```bash
uv run forge generators
uv run forge generate --count 20 --seed 42
# generate が表示したset_idを使用
uv run forge run SET_ID --models mock-reference,mock-wrong
uv run forge report RUN_ID --format markdown
uv run forge report RUN_ID --format csv --output report.csv
```

`--generators math.linear,data.aggregate` 等で範囲を限定できます。`generate --output` は参照解答付きのセットを保存します。**そのファイルをモデル入力に渡さないでください。** 出力コマンドは既存ファイルを上書きしません。APIとCLIの評価プロセスを同じデータ領域で同時に起動すると、ファイルロックにより拒否します。

## ローカルモデル

OllamaをWSL内でローカル起動し、ユーザー自身がモデルを用意します。「モデル」でバックエンド `Ollama`、モデル名、`http://127.0.0.1:11434`、リビジョン・量子化・推論条件を登録し、接続確認します。推論時には問題本文のみ送信します。リダイレクト、認証情報付きURL、外部ホスト、DNSによる接続先は拒否します。Ollamaの実モデル推論はこのクラウドでは未検証です。

Transformersは依存関係をオプション化していますが、専用推論ワーカーは未実装です。Codex CLI / App Serverは公式のイベント契約とMock試験まで実装し、実行可能な隔離を検証できていないため実接続を無効にしています。認証キャッシュの解析・転用や有料APIへの代替は行いません。

## 検証

```bash
bash scripts/check.sh
cd apps/web
npx playwright install chromium
npm run e2e
# Cloudなど、システムChromiumを使用する場合
PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run e2e
```

E2Eは通常のデータ領域と別の一時DB・専用ポートを使用します。生成器・固定コーパスの整合、再現性、一意解、重みと分母、中断・再開、API/CLI、外部Origin拒否、Codex通信の失敗、安全側での実行停止をテストしています。実際のDocker侵入試験・GPU試験・Codex実接続試験は未実施です。GitHub Actionsの実行結果はリポジトリへpush後に確認してください。

## データと制限

- SQLiteは既定で `.benchmark-forge/forge.sqlite3` に保存。`FORGE_DATA_DIR` で変更可能。マイグレーションは自動適用。バックアップはサービス停止後にデータ領域全体をコピーします。
- 14生成器 / 9大カテゴリ / 280件の小規模な固定コーパス。固定問題が足りない条件は失敗し、動的問題へ無断で置換しません。狭い難易度範囲には固定問題がないことがあります。
- 総合値はカテゴリ均等の重み付き正答率。全割当問題を分母とし、タイムアウト・エラー・無回答も保持します。単純正答率と固定/動的の寄与も表示します。
- 生成コードの実行、ネイティブツール、複数ターンエージェントは無効。コード読解・修正選択、テキストでのツール選択は実行を伴わず利用できます。
- 難易度は構造パラメーターの暫定値。固定コーパスの難易度は5つの保管点ですが、動的生成と設定は連続値です。カテゴリ間の同じ値が同じ難しさを意味するとは限りません。
- RAM/VRAM/TTFTなど未測定の値はN/A。能力・速度・リソースを単一スコアに合成しません。
- 外部データは含めていません。コードライセンスはユーザー未決定で、無断でMIT等を適用していません。

詳しい進捗は [docs/STATUS.md](docs/STATUS.md)、次の開発は [docs/ROADMAP.md](docs/ROADMAP.md)、安全性は [docs/SECURITY.md](docs/SECURITY.md)、Windows向けの手順は [docs/WSL2.md](docs/WSL2.md) を参照してください。
