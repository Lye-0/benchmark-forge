# Windows + WSL2 Ubuntuでの利用

以下はローカル向け手順です。このCloudでの検証は通常Linux/CPUのみで、WSL2のGPU・Windowsブラウザ・ドライバーは未検証です。

1. WindowsにWSL2 Ubuntuを用意します。Python 3.12が使えるUbuntu 24.04以降を推奨。
2. Ubuntu内でPython 3.12、uv、Node.js 22/24とnpmを用意します。uvの公式インストール案内: <https://docs.astral.sh/uv/getting-started/installation/>。Nodeは公式配布または既に利用しているバージョン管理ツールを使用。TLS/パッケージ署名を無効化しないでください。
3. Linux側のホーム配下で `git clone https://github.com/Lye-0/benchmark-forge.git`。`/mnt/c` よりWSL側ファイルシステムの利用を推奨。
4. `cd benchmark-forge`、`bash scripts/setup.sh`、`bash scripts/start.sh`。
5. Windowsブラウザで `http://127.0.0.1:8000` を開きます。WSLのlocalhost転送を利用します。ポート変更はREADMEの手順で行ってください。

転送が働かない場合、まずWSL側で `curl http://127.0.0.1:8000/api/health` を確認します。WSL/Windowsの転送・ファイアウォール・ポート競合を確認し、安全性の根拠なく0.0.0.0へバインドして回避しないでください。

## OllamaとGPU

Ollamaは同じWSL環境にローカルサービスとして用意し、必要なモデルをユーザー自身で取得します。NVIDIAのWindowsドライバーとWSL向けCUDA/GPU互換性は公式資料で確認してください。本アプリはドライバーをインストールしません。

Webの「モデル」でOllamaのモデル名・リビジョン・量子化・推論設定を登録し、接続確認後に評価します。APIがWSL内にありOllamaがWindows側にある構成は現在のliteral loopback制限で利用できない場合があります。外部IPを無条件に許可せず、同じWSL側のOllamaを優先してください。

Transformersの追加依存は `uv sync --locked --extra transformers` で用意できます。取得済みのsafetensorsモデルをローカルディレクトリで指定し、CPU/CUDAを選択します。別プロセスの契約テストは完了していますが、実モデル推論は未検証です。GPU用torch/CUDA構成は別途検証が必要で、不要なCloud CPU開発では追加しません。

## オフライン運用

依存導入、UIビルド、ローカルモデル取得を先に済ませれば、生成・採点・保存・Mock診断・ローカルOllama呼出は外部サービスを要求しません。`scripts/start.sh` は `uv run --no-sync` を使用。Vite開発サーバーやsetupを毎回ネットワーク経由で実行する必要はありません。

## よくある問題

- **固定問題不足**：指定した生成器・難易度範囲のコーパス数を超えています。問題数を減らすか、難易度範囲を広げるか、明示的に動的比率を上げて新しいカスタムセットを作ります。
- **別の評価プロセスが動いています**：同じDBでAPIとCLIを同時に動かせません。サービスを終了するか、CLI用に別の `FORGE_DATA_DIR` を指定。
- **Origin拒否**：Webのポート変更時にAPIの `FORGE_WEB_ORIGIN` を合わせていない可能性があります。READMEの2プロセス例を参照。
- **Ollamaの接続確認は成功したが実行失敗**：サービスのモデル名・コンテキスト長・メモリ・timeout設定を確認。接続確認は推論成功を保証しません。
- **Codexを登録しても選択できない**：安全なツール禁止・ファイル隔離を実証するまで実接続を無効にしています。公式の認証済みCLIがあっても、このアプリから認証ファイルを解析して回避しません。
- **クラッシュ後のラン**：保存済み回答は残り、paused状態へ復元します。再開ボタンで未保存の問題から再処理。強制終了直前にバックエンドが答えたがDB未保存だった問題は再リクエストされる可能性があります。
- **ブラウザテストのダウンロード制限**：システムChromiumがあれば `PLAYWRIGHT_CHROMIUM_EXECUTABLE=/usr/bin/chromium npm run e2e`。証明書検証を無効にする回避は不要です。
