# ADR 0002: Codexは公式契約のMock検証と安全性ゲートを先に作る

- 日付: 2026-10-12
- 状態: 採用 / live integrationは未完了

公式資料サイト `developers.openai.com`、FastAPI/Viteの公式サイトは、このCloudのegress proxyから403で到達できませんでした。TLS検証を無効化せず、GitHubの公式 `openai/codex` リポジトリをHTTPS Git proxyから読み取り、remote HEADの公式ソースを確認しました。

確認したソース: [openai/codex / a9b0815167c27ab13719dd12d13b63e02b70d221](https://github.com/openai/codex/tree/a9b0815167c27ab13719dd12d13b63e02b70d221)。特にapp-server READMEとv2のsuiteを参照。ローカルの公式 `codex-cli 0.159.2` で `exec --help`、`app-server --help`、`app-server generate-json-schema` を実行し、認証を使わず、Initialize / ThreadStart / TurnStart / ItemCompleted / TurnCompleted等のフィールドを確認しました。TurnCompletedはturnIdでなくturn.idから照合します。

実装範囲はCLIのJSONLイベント解析と、注入transportに対するApp Serverのinitialize/initialized/account-read/thread-start/turn-start、thread/turnのイベント照合、完了、失敗、割当枠エラー、ツール拒否、timeout/cancel時のinterruptです。CLI出力のtoken使用量を純粋なdecode速度として扱いません。

Mockはこのサブセットの契約試験で、完全なschema適合性やlive compatibilityを保証しません。CLI実サブプロセス・App Server live transport・サインイン・認証更新は提供していません。read-onlyだけではホストの正解情報が読めるため、実接続を常に無効にします。GitHubのmodel一覧やCodexバイナリの存在からアクセス権を主張しません。

後続では公式Sign in with ChatGPTの現行プレビュー条件・利用規約・登録フローを改めて確認し、model-only adapterとの比較差分を記録し、専用の公開設問だけが読める環境とツール制限を実証してからlive経路を追加します。ユーザーの既存ログインやトークンを解析・転用しません。
