# 私有holdout

「プロファイル・設定」でJSONLを選択するか、`uv run forge import-holdout /path/to/private.jsonl` で取り込みます。APIは `POST /api/holdouts` に `{"jsonl":"..."}`。先頭行が次のメタデータ、以降が1〜1000問、UTF-8で900KB以下です。

```jsonl
{"schema":"forge-holdout-v1","name":"私有検証セット","source":"自作","license":"private-use","visibility":"private"}
{"prompt":"2+3を整数だけで答えてください。","category_id":"01","target_difficulty":10,"answer_spec":{"type":"number","expected":5,"tolerance":0}}
{"prompt":"okとだけ出力してください。","category_id":"07","target_difficulty":5,"answer_spec":{"type":"text","expected":"ok"}}
```

`type`はnumber / text / json。未定義キー、重複JSONキー、非有限値、同一問題文、無効なカテゴリ、解答型の不整合は拒否します。URL・パス・コード・圧縮ファイルを解釈しません。カテゴリ均等に重み付けし、固定100%の独立セットとしてfreezeします。同じデータと順序なら同じハッシュです。既存セットは上書きしません。

データは通常の生成器へ登録せず、private / experimentalと出典・利用条件を保存します。取り込みは問題文や正解の正しさ、著作権・利用許諾を自動検証するものではありません。取り込み元で確認してください。

参照解答はアダプターに渡しません。評価時の問題本文は選んだモデルへ送信されます。現在有効な実接続はローカルOllama/Transformersです。結果画面・CSV/JSONL/Markdownには私有問題の回答や情報が含まれ得るため、外部へ共有する前に内容を確認してください。自動アップロードはありません。
