# ADR 0003: 独立評価・履歴・使い捨て実行

日付: 2026-10-12 / 採用。

- 既存のfreeze→scheduler→SQLite→reportを共通化し、text / native-tools / agent / codeを独立モードで保存する。速度試験は独立プロファイルとし、通常の能力点と混合しない。
- 再試行前の結果を破棄しない。DB v2のattemptsへ各開始・終了・中断・応答を保存し、resultsは採点用の現行結果だけ保持する。v1は履歴の最初の試行として移行し、当時未記録の時刻を捏造しない。
- コードの実行先は固定digestのPython Dockerイメージのみ。自動pullなし、ホストmountなし。実行プロセスごとに検証してから有効化する。カーネル・Docker daemonは信頼境界に残り、完全隔離とは主張しない。Cloud daemonはrootlessではなく、WSLではrootlessを推奨する。
- Transformersの別プロセスはtrusted local inference用であり、生成コードの隔離には使わない。
- 仮想在庫は純粋なメモリ内の許可リスト処理。任意の関数解決・eval・OS操作・ネットワーク呼出は行わない。許可外の品目、操作、型を変更前に拒否する。
- Ollama native toolsはモデル設定の明示的な申告が必要。アダプターの対応とモデルの実能力は別。MockとHTTP契約テストを完了しても実モデルをverified扱いしない。
- holdoutはdata-only JSONL、ローカル保存のみ。スキーマと参照値の型は検査できるが、出典の権利と設問・正解の意味的正しさは取り込み元が確認する。

## 確認した公式資料

2026-10-12に公式GitHubの現行ファイルを取得して確認。

- https://github.com/ollama/ollama/blob/main/docs/api.md : `/api/chat`のtools、message.tool_calls.function.name/arguments、tool_name付きtool応答、stream=false。
- https://github.com/docker/docs/blob/main/content/manuals/engine/containers/resource_constraints.md : memoryと同値のmemory-swapでswap禁止、cpus quota。

コード・ツール・速度試験のソフトウェア検証はMock回答で実施。実LLMで問題を解く開発テストは新規astra / mediumサブエージェントによる公開問題文だけの診断に限定した。
