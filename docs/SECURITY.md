# 安全性とローカル運用

## ローカルAPIとデータ

127.0.0.1へバインドし、Host / Origin / Fetch Metadataを検証します。変更操作はapplication/json、ストリームを読みながら1MBを上限に拒否します。検証エラーには入力値を返しません。共有ネットワーク・インターネットへの公開は対象外です。

OllamaはHTTPのliteral loopbackのみ。URL資格情報、DNS名、path/query、redirect、環境プロキシを拒否します。公開問題と、ツール評価時の許可された仮想世界の観測だけを送信します。参照解答と採点器は渡しません。

私有holdoutは型検査するJSONLのみ。パス・URL・コードの実行やZIP展開はありません。出典の利用権・問題内容の正しさ・個人情報の有無は取り込み元で確認してください。入力は通常のローカルDBへ保存し、Gitや外部へ自動送信しません。結果とエクスポートは参照解答を含むため非公開データとして扱ってください。

## コードの隔離

コード生成評価は専用DockerSandboxだけを使い、ホスト上では実行しません。固定digestのイメージを事前に用意し、実行プロセスごとの検証が通るまで無効です。コンテナ実設定は実行ごとにinspectします。

- non-root UID/GID 65534、cap-drop ALL、no-new-privileges、seccomp、network=none。
- ホストmountなし。ホーム、認証情報、採点器、Git、Docker socketを渡しません。
- read-only root、/tmpだけ16MiBのnoexec/nosuid/nodev tmpfs。
- メモリ128MiB・swap禁止、CPU 0.5、CPU時間2秒、PID 32、ファイル1MiB、FD 64、応答64KiB、wall time最大10秒。
- 正解を含まないテスト入力と候補コードだけを渡し、出力の正誤はホスト側の参照値で判定します。
- timeout / OOM / 異常終了 / 出力過大を区別。キャンセル時もコンテナを強制削除します。削除失敗は機能を無効化します。

Cloudで、無権限・秘密領域非公開・ホストsentinel不可視・外部通信不可・書込制限・ファイル上限・PID上限・OOM・時間制限・cancel後削除を実検証しました。Docker daemonとカーネルは信頼境界に残ります。現在のCloud daemonはrootlessではありません。WSLではrootlessを推奨し、同じ検証を通す必要があります。コンテナを完全なセキュリティ境界とは断定しません。

Transformersワーカーは終了管理用の別プロセスです。ローカルsafetensors、remote code禁止、オフライン、環境変数許可リストを使用しますが、OS sandboxではありません。

## 仮想ツールとCodex

仮想在庫はメモリ内だけの状態機械です。lookup / adjust以外、対象外品目、不正型、参照前の変更、負の残高を変更前に拒否。1ターン1呼出・最大6ターンで問題ごとにリセットします。実ツール・外部API・ホストコマンドは解決しません。

Codexは公式イベントのprotocol-only Mock検証まで。実認証・ツール禁止・正解や秘密の読取禁止を成立させるlive transportは未検証で無効です。Pythonコンテナの検証をCodex接続の安全性とみなしてはいけません。認証キャッシュの解析・転用、有料APIへの自動切替をしません。

## 公開と保存

SQLite・.env・認証ファイル・モデル重みはGit対象外。SQLはパラメーター化し、Reactは回答をテキスト表示、CSVは数式先頭を無害化します。secret_scan.pyは既知形式の検出であり全個人情報・秘密の除去保証ではありません。コードライセンスは未決定です。

## Windowsホスト

Windowsでも生成コードをホストで実行しません。Docker DesktopのLinuxコンテナで同じ実検証を行い、未導入・接続不可・Windowsコンテナ・検証失敗時はコード評価のみ無効にします。通常評価はDockerへ依存しません。TransformersはJob Objectを入力送信前に割り当て、割り当て失敗時は終了します。CPU/GPUワーカーは信頼済みローカル推論用で、コード隔離の代替ではありません。Windowsのデータ保護は保存先ACLに従い、POSIX modeをACL設定として扱いません。PowerShellスクリプトは実行ポリシー・証明書・全体のツール設定を変更しません。
