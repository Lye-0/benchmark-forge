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

- 今回のpytest: **161 passed / 2 skipped**。Windowsネイティブ対応時に別途`FORGE_TEST_DOCKER=1 pytest tests/test_sandbox.py`は**9 passed**（通常skipする実Docker2件を含む）。
- 新規検証: UTF-8分割NDJSON、可視chunkの時刻、終端欠落・過大応答・中止時のclose、モデル申告情報、GPU情報の欠落/異常、別スレッドでの逐次出力、出力中の更新に対するスナップショット整合、gzip既存ファイル保護。HTTP/機器応答はfixtureであり実モデル・GPU検証ではありません。
- Ruff lint / format、mypy: PASS。
- Vitest: **12 passed**。TypeScript / Vite: PASS。
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

Cloud内のLinux/CPU・Mock・Docker検証に加え、ユーザーからWindows CI成功とWindows上のOllama評価完了の報告を受けています。GPU利用の詳細・Transformers実推論・Docker Desktopは未確認です。これらを利用する場合は[Windows手順](WINDOWS.md)で確認してください。通常評価にWSL2は不要です。認証値や私有問題をチャットへ貼る必要はありません。

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

### Windows CIの文字コード修正

ユーザー提供のWindows runnerログでは、任意依存のインストール後、Torch診断の`print(r)`が日本語をcp1252へ変換できず失敗しました。CIを既存の`python -m llm_benchmark.torch_probe`へ変更し、ASCIIエスケープ付きJSONで出力します。診断失敗時の終了コード1は維持します。cp1252の標準出力を使った回帰試験を追加しました。修正後のWindows CI結果は未確認です。

### 完了表示の巻き戻り修正

Windows E2Eで完了表示を待つ2件がタイムアウトしたとの報告を受け、HTTP詳細取得とSSE進捗の到着順競合を調査しました。初回取得または再開後の古いHTTP応答が完了イベントより遅れて届くと、画面を実行中/待機中へ戻す不具合を2件の回帰試験で再現しました。修正前は両試験が失敗し、修正後は保存済みrevisionより古い応答を無視して完了表示を維持します。詳細タブの取得にも同じ規則を適用しています。

Cloud/LinuxでPython155件（Docker2件skip）、Web8件、E2E4件、型検査・ビルドが成功しました。E2Eは失敗時にDB側の状態・処理数・revisionをJSON添付し、未終了ランを中止して後続テストへの混入を防ぎます。待機時間は延長していません。報告されたWindows実行のDB状態やtraceは未取得であり、その失敗原因がこの競合だけだったとはまだ断定できません。修正後のWindows CI結果は未確認です。

### Windows E2Eの実行待ち期限の修正

ユーザー提供の`browser-failure-traces-windows-latest.zip`を確認。20秒の待機期限切れ時、画面は参照モデル59/100問、直後のDB記録は同モデルrunning・64/100問（revision69）、他方はcompleted・100/100問（revision102）でした。前回の表示巻き戻りとは別に、今回残った失敗は処理中のランに対する固定20秒の期限不足です。再開したランは逐次キュー末尾に入り、先に別モデル100問を実行するため、2モデル分の実行時間が待機対象になります。

1問0.1秒の追加遅延を入れた一時Mock診断でも、20秒時点で参照モデル59/100問、他方100/100問、30秒時点で両方100/100問となる正常な進行を再現しました。製品の評価順序・問題数・保存の耐久性は変更していません。

E2Eは選択した2ランの進行を確認し、15秒間進展なし・予期しない一時停止/中止・全体120秒超で明示的に失敗します。バックエンド完了後の画面反映は5秒以内を別途検証します。待機キュー、停止検出、総期限の3件の単体テストを追加。失敗時の最小進捗情報はログと独立した`durable-run-progress.json`にも保存し、trace.zipを展開しなくても確認できるようにしました。修正後のWindows CI結果は未確認です。

### 無回答バッジと出力終了理由の表示（2026-10-13）

無回答の状態クラス`empty`と空画面レイアウトのクラス名が衝突し、大きな余白が付いていたため、空画面側を`empty-state`へ分離。実Chromiumで正解・不正解・無回答の高さが同一になることを確認しました。

結果画面・個別ログ・Markdownにバックエンドが明示した`done_reason=length`による終了を表示。上限終了全体と、そのうち無回答の件数を区別します。トークン数だけから原因を推定せず、記録のない過去結果は不明として扱います。集計は現在の問題別結果のみを対象とし、再試行履歴を重複計上しません。採点・正答率は変更しません。Markdownにはモデル・推論条件、状態、正解/誤答/無回答/タイムアウト/エラー/採点不可の内訳も追加しました。

Cloud/LinuxでPython156件（実Docker2件skip）、Web11件、E2E4件、Ruff・型検査・ビルドが成功。今回の変更後のWindows実行は未検証です。以前のWindows CIはユーザーから成功報告を受領済み。提供されたOllama実行ログも実評価の証拠として確認済みで、ユーザーの回答ログはリポジトリへ保存していません。

### 分割アーカイブと分析表示（2026-10-13）

指示書8.1/12の分析・巨大出力要件を継続実装。CLIの`archive-split`は1つのSQLiteスナップショットから未回答問題・結果・全試行を分割JSONL/gzipへ保存します。UTF-8の行境界を保持し、完了時にだけSHA-256・件数・サイズ・セットハッシュ・revisionを持つマニフェストを作成。`archive-verify`は保存ファイルの欠落・サイズ・ハッシュを検証します。真正性・採点の妥当性の検証ではありません。確定セットのメモリ保持は従来どおりです。

形式別・タグ別の既存集計を画面に追加。全割当数を分母として処理済み数も併記し、タグの重複は総合点に加算しません。採点不可も結果内訳とログの絞り込み対象に追加しました。

Cloud/Linuxの検証: Python160件成功・実Docker2件skip、Web12件、E2E4件、Ruff・mypy・TypeScript・Vite成功。分割の往復一致（未回答問題/結果/試行）、圧縮、日本語パス、既存出力保護、破損/欠落、途中失敗、マニフェストの外部パス拒否を検証。Windows固有動作は今回のCI実行待ちです。

### 売上集計問題の回答形式（2026-10-13）

`data.join`の設問に「商品idをキー、売上合計の数値を値とする単一JSONオブジェクト」を明記。配列や外側のproductsキーを付けない契約をモデルへ事前提示します。参照解答と採点器は変更せず、生成器を1.1.0へ更新し、対応する公開固定20問を再生成しました。その他の固定460問は変更していません。

旧版の確定セットを読み込む回帰試験を追加。保存済みの問題文・参照解答・ハッシュを維持し、新規セットとの直接比較はセットハッシュ差で拒否します。過去のユーザー回答を再採点したり、過去スコアを補正したりはしません。

最終検証: Cloud/LinuxでPython161件成功・実Docker2件skip、Web12件、E2E4件、Ruff・mypy・TypeScript・Vite成功。今回のWindows実行結果は未確認。提供済みWindows実行ログではGPU機種情報が未取得だったため、次のGPU計測対応に先立ってGPU名とドライバー版をユーザーへ確認中です。Torch/Transformersの追加インストールやモデル再実行は、この確認のためには不要です。
