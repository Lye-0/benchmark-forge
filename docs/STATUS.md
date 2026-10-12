# 実装・検証状況

最終確認: 2026-10-12 / `Lye-0/benchmark-forge` / `main`。

フェーズの境界で停止せず、Phase 4〜6のCPU環境で検証できる縦方向の経路まで続行しました。実モデル/GPU・Codex認証・正式Standard・長期の生成器目標を完成したとは扱いません。

| Phase | 到達点 | 残る条件 |
|---|---|---|
| 0 | ロック付きPython/React環境、API/CLI、DB、CI、起動手順 | リモートCI実行結果は未確認 |
| 1 | 24生成器、固定480件、freeze、重み、再現性、独立参照ソルバー | 意味的な構造同値検出は未実装 |
| 2 | 日本語UI、三層選択、進捗、履歴、比較、独立評価・holdout入力 | 長期の大規模画面最適化は未検証 |
| 3 | Ollamaストリーミング/初回テキスト計測・モデル申告情報、Transformers別プロセス、局所計測、Codex protocol Mock | 実モデル/CPU・GPU・WSL・CodexアカウントはNOT_VERIFIED |
| 4 | DB v2試行履歴、即時中止、実プロセスクラッシュ復元、1000件保存、Docker使い捨て隔離採点 | ユーザーのWindows Docker Desktop / WSLで同じ検証を通す必要あり。数日規模の負荷試験は未実施 |
| 5 | 24独立生成構造・15カテゴリ、テキスト型/ネイティブ型/複数ターン仮想世界の独立モード、開発用回答診断 | 一般知識の検証済み生成器なし。50〜80/100種類は長期目標。実モデルのtool能力未検証 |
| 6 | 私有holdout、校正用観測JSONL、80%維持の保守的補助指標、専用速度試験、リソース表示、圧縮/逐次アーカイブ・CPU/GPU構成記録、運用文書 | 統計的な実測校正・正式Standard・tokenizer間で同一トークン長の比較は未達 |

## 今回実行した検証

- 今回のpytest: **153 passed / 2 skipped**。別途`FORGE_TEST_DOCKER=1 pytest tests/test_sandbox.py`は**9 passed**（通常skipする実Docker2件を含む）。
- 新規検証: UTF-8分割NDJSON、可視chunkの時刻、終端欠落・過大応答・中止時のclose、モデル申告情報、GPU情報の欠落/異常、別スレッドでの逐次出力、出力中の更新に対するスナップショット整合、gzip既存ファイル保護。HTTP/機器応答はfixtureであり実モデル・GPU検証ではありません。
- Ruff lint / format、mypy: PASS。
- Vitest: **6 passed**。TypeScript / Vite: PASS。
- Playwright / system Chromium: **4 passed**。100問2モデルのfreeze・中断再開・比較、390px画面、私有holdout取込、複数ターン評価、専用速度表示。
- 全24生成器を5難易度×8seedで再生成し、独立したルールソルバーと採点を照合。固定480件を参照照合。整数/浮動小数の等しい難易度でIDが同じになるよう正規化。
- 1000件の動的セットと1000件の評価結果/試行の一意性。別Pythonプロセスを`os._exit`で異常終了させ、確定済み結果を保持して未終了試行をinterruptedに復元。
- DB v1→v2: 既存結果を履歴へ移行、再実行しても重複せず、過去に未記録の時刻はnull。
- 作成途中キャンセルで未起動コンテナが残る競合を再現し、作成の完了を待って削除するよう修正。遅延を注入した回帰試験と実Docker削除試験を追加。
- Docker: non-root / seccomp / no-new-privileges / capabilities削除 / network=none / read-only root / cgroup制限を検査。ホストsentinel不可視、外部通信不可、書込先・ファイル量・PID制限、実OOM、CPU時間/タイムアウト、過大出力、キャンセル後の削除を確認。
- 同じDocker経路でMockの生成コードを実行し、参照モデル2/2、誤答モデル0/2を確認。実LLMへの回答要求はしていません。
- 新規astra / medium・履歴なし・ツールなしで公開問題5問を回答診断し、5問で採点一致。`dev_reports/2026-10-12-expanded-generators.json`へ分離。同じworkspaceへのアクセスを機械的に遮断したとは主張しません。

警告はStarlette/httpxの将来API変更とテスト用raw dataの非推奨通知です。

## 比較・安全性の制約

- 通常のPreview、私有holdout、速度、ネイティブツール、agent、codeは独立モード/セット。異なるセット・採点器・モードは直接比較不可。
- 80%維持の補助推定は各帯20件以上・Wilson下限の連続条件で、不足した帯を飛び越えません。校正済み難易度ではなく、Mockや速度/ツール/コード試験は除外します。
- Transformersは問題ごとにcoldロード。成功応答のRSS、CUDA allocator Peak、版、ロード時間、prefill込み生成時間を保存。TTFT/decode時間を捏造しません。実モデルとCUDAは未検証。
- Ollamaのnative対応は登録時の申告。接続確認では/api/showのモデル申告情報も取得します。アダプター実装やモデル一覧は能力の実証ではありません。中止はHTTP待機を停止しますが、サーバー内部推論の即時停止は保証しません。
- Python隔離の成功はCodex liveの安全性を保証しません。Codex実認証・公式preview条件・最小権限transportは未検証で無効。認証キャッシュの解析や有料APIへの切替なし。
- CloudのDocker daemonはrootlessではありません。カーネルとdaemonを信頼する境界が残り、コンテナを完全隔離とは断定しません。ユーザー環境で毎回検証できなければコード採点は無効。
- 私有holdoutはスキーマ/解答型を検証しますが、設問の意味的正しさ・出典の権利は取り込み元で確認してください。
- 正式Standard、実測校正、一般知識の資料整備、同一トークン長の速度測定、モデルファイルハッシュ・GPU電力、Codex実認証は未完成。外部資料・認証値・モデル重み・私有問題はコミットしていません。コードライセンス未決定。

## 利用者側でしか確認できない次の作業

Cloud内のLinux/CPU・Mock・Docker検証を実施しました。次は[Windows手順](WINDOWS.md)でネイティブ起動・OllamaまたはTransformersの実推論・GPU・Docker Desktopを確認してください。通常評価にWSL2は不要です。認証値や私有問題をチャットへ貼る必要はありません。

## Windowsネイティブ対応の追加（2026-10-12）

- `fcntl`をWindowsのbyte-range lock / POSIX flockへ分離。別プロセス競合・終了後の解放・日本語/空白パスをテスト。
- TransformersはWindows/Linuxに対応する実装。WindowsはJob Objectで子プロセスも終了、Linuxはprocess group。作成途中のキャンセルで生成されたプロセスも回収。RAMはWindows peak working set / Linux high-water RSSとして区別。
- PowerShell setup/start/check/diagnoseを追加。Python 3.12をuvの`.venv`で管理、Node 24系・npmを維持。既存Python/グローバル環境・ポリシーを変更しない。
- Windows CPU版 / CUDA 13.0版Torchを選択可能。公式indexとwheel hashesをuv.lockへ保存。Windows x64を指定した`uv sync --locked --dry-run`で両extraの解決を確認（インストール/実機推論ではない）。Windows対象のmypyもPASS。
- Dockerは明示診断時とコード評価時のみ接続。未導入・接続不可・Windowsコンテナ・制限検証失敗を区別し、通常評価を継続。Cloudの実Linuxコンテナで9件PASS。Docker Desktopでは未検証。
- UIに実行OS/CPU/GPU構成とPyTorch/CUDA明示診断を追加。CUDA診断はモデルをロードせず、未導入でもアプリ起動可能。
- CIをubuntu-latest / windows-latestのmatrix化。WindowsではPowerShell 5.1のsetup/checkと、start.ps1を使うE2E、CPU版Torchの実インポート診断を設定。CloudからActions API取得は403で拒否されたため、リモートCI実行結果は未確認。設定追加をWindows成功とは記載しない。
- LinuxでWebテスト6件、E2E4件、型検査・ビルドが成功。PowerShell実行、Windows Job Objectの実動作、Windows CUDA・Docker Desktop・実モデルはWindows側での確認待ち。
- Codexの公式プロトコルMockは維持。live認証/隔離は従来どおり未検証で無効。今回モデル回答診断は不要な変更のため実LLM呼出は行っていない。
