# 実装・検証状況

最終確認: 2026-10-12。対象: `Lye-0/benchmark-forge` / `main`。

## 今回の到達点

**Phase 0〜2を実働するPreviewとして完成。Phase 3〜6は下表の範囲だけを実装しました。指示書の全フェーズ完了ではありません。** CPU/GPUなし・認証なしで、Web/CLIから生成→freeze→順次評価→採点→保存→分析→エクスポートを実行できます。

| Phase | 状態 | 実装と検証 |
|---|---|---|
| 0 | 完了（Cloud CPU） | Python/uvロック、React/TS/npmロック、SQLite migration、CLI、API、テスト、CI定義、セットアップスクリプト |
| 1 | 完了 | 14生成器、再現性、論理一意解、固定280件＋動的生成、表面重複除去、セットハッシュ、重み付き採点、保存、Mock実行 |
| 2 | 完了 | 日本語ダークUI、三層/中間状態/検索/一括選択、5プリセット/ユーザー保存、freeze確認、複数モデル、SSE、履歴/概要/詳細/比較/設定 |
| 3 | 一部 | Ollamaアダプター・接続確認・HTTP Mock契約、context_length送信、E2E/P50/P95、Codex protocol-only Mock。Transformers別プロセス推論・局所計測の経路を追加（実モデル/GPUは未検証）。Codex liveは未完了 |
| 4 | 一部 | 問題境界の一時停止/再開・in-flight中止、プロセス再起動の復元、一意結果キー、逐次評価、timeout/error、失敗のみ再試行。隔離ワーカーは未実装で無効 |
| 5 | 一部 | 16カテゴリ管理 / 9カテゴリで14独立構造、テキスト型ツール選択、sub-agent診断。20〜30構造目標、native/agent模擬世界は未完了 |
| 6 | 一部 | 内訳・10難易度帯とWilson区間、CSV/JSONL/Markdown、比較条件警告、方法論/WSL2/安全性文書。校正・私有holdout import・専用速度測定は未完了 |

## 実際に実行した検証

| 検証 | 結果 | 内容 |
|---|---|---|
| pytest | **86 passed** | 生成器を5難易度×8seedで検証、280固定問題の再現/参照照合、真偽全探索一意解、難易度特徴量、freeze/比率/不足拒否、採点と型、重み、再開/重複防止、API/CLI、Origin/Host/SSRF、Codex Mock |
| Ruff lint / format | **PASS** | src / tests / scripts |
| mypy | **PASS** | バックエンド15ファイル |
| Vitest | **6 passed** | 三層選択/indeterminate、検索/折りたたみ/一括、N/A、APIエラー/JSON送信、設定変更時の古いfreeze応答破棄、Transformers登録条件 |
| TypeScript / Vite | **PASS** | 型チェックと本番ビルド |
| Playwright / system Chromium | **2 passed** | 100問の設定→freeze→実行→一時停止/再開→ログ→リロード→同一セット比較、および390px幅のナビ/検索/横overflowなし |
| setup.sh 再実行 | **PASS** | frozen uv/npm依存とUIビルドを再実行し、保護されたロックを変更しない |
| start.sh / HTTP機能確認 | **PASS** | 実API/ビルド済みUI/16カテゴリ/確定/2モデルを確認。同一4問でMock参照4/4、Mock誤答0/4 |
| 既知credential/artifact guard | **PASS** | ローカル履歴・重み・認証キャッシュは追跡外。既知トークン形式なし。万能な秘密検出の保証ではない |
| 開発回答診断 | **5問採点一致** | 新規sub-agentに公開問題だけを渡した診断。`dev_reports/`へ分離し正式ランへ含めない |

pytestの警告はStarlette/httpxの将来的なTestClient API変更と、httpxのテスト用raw dataの非推奨通知です。現行の失敗ではありません。GitHub Actionsは定義済みですが、この記録時点のリモート実行結果は未確認です。

## 独立レビューと修正

ユーザー指定のgpt-6-astra / mediumで読み取りレビューを実施。同期APIハンドラーが別スレッドからasyncio.Queueを操作する問題をdebug-mode TestClientで再現し、run作成/controlをasyncハンドラーへ変更しました。API試験はdebug event loopを有効にしています。

Ollamaの保存済みcontext_lengthがリクエストに反映されない問題を修正し、Mock HTTPでnum_ctx=4096を確認。設定編集中に古いfreeze応答を受け取れる競合は設定revisionで解決し、通信を遅延させるUI試験を追加しました。修正後にbackend/UI/ブラウザの該当経路を再実行して合格しています。

## Gitの変更単位

- `611b0c8` — `feat: 再現可能な問題生成と評価エンジンを追加`
- `f395818` — `feat: 日本語のベンチマーク設定と結果分析UIを追加`
- セットアップ/CI/ドキュメント/開発診断は別の日本語Conventional Commitとして保存。最新の実SHAは `git log` で確認してください。

## 未実施・無効・制約

- **NOT_VERIFIED**: Ollama実モデル、Codex CLI/App Server実アカウント、ChatGPT公式preview条件/登録/サインイン、WSL2/GPU/ドライバー。
- **未実装・無効**: モデル生成コード/ホストコマンド実行、Docker隔離ワーカー、native tools、複数ターンagent、Codex live transport。
- **実侵入試験は未実施**: ホスト秘密の読取禁止、ネットワーク禁止、non-root、CPU/RAM/PID制限等。現在確認したのは隔離不能時に機能が停止することであり、Docker安全性の実証ではありません。
- **未完成**: 正式Standard、実測難易度/80%維持点推定、意味的重複判定、private holdout import、大量artifact管理、完全な試行履歴、長時間の負荷試験、GPU実機/TTFT/統一長速度試験。
- Cloudの公式資料サイトとPlaywright CDNはproxyから403。公式Codex資料はGitHubの公式ソースと認証不要のCLI schemaで確認。ブラウザ検証は既存system Chromiumを使用し、TLS検証等を無効化していません。
- コードライセンスはユーザー未確定。外部データセット・モデル重み・認証情報を含めていません。

次の具体的な実装順はROADMAP.mdに記録しています。既存のCloud taskは隔離されたcheckoutなので、ユーザー指定がない限りworktreeを追加しません。

## 続行実装: Transformersと即時中止

Linux / WSL2向けに、取得済みローカルモデルを別プロセスでロードする経路を追加。safetensors限定・remote code禁止・オフライン設定・環境変数の許可リストを使用します。CPU/CUDAを明示選択し、量子化指定は未対応として拒否します。コンテキスト超過は切り捨てず失敗します。

問題ごとにプロセスを作成し、モデルロード時間、prefill込み生成時間、プロセス生涯のPeak RSS、CUDA時のPyTorch割当Peak、ライブラリ版を成功結果に保存し、UIログとJSONLに表示。decode速度/TTFTは欠測。cold起動のE2Eをwarm推論速度と比較しないでください。失敗・中止時のリソース値は未取得です。

中止は実行中のawaitをキャンセルし、Transformersのプロセスグループを終了・回収して次のランへ進みます。OllamaはHTTP待機を停止しますがサーバー内推論の停止保証はありません。pauseは問題境界のままです。

追加検証は実OSプロセスの正常終了/timeout/cancel/異常応答/出力過大時の回収、公開問題だけの転送、ライブラリMockでのロード/生成契約、結果計測の保存、実行中止後のキュー継続です。実モデルのロード・回答、CUDA計測は **NOT_VERIFIED**。このCloudに大容量の任意依存やモデル重みは追加していません。

このプロセス境界は推論のライフサイクル管理用です。ファイルシステムやネットワークを隔離するsandboxではなく、生成コードやCodex live実行を許可する根拠にはしません。
