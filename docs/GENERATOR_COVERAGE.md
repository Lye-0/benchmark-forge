# 生成器のカバレッジ（2026-10-14）

通常のテキスト評価は50独立構造、15/16大カテゴリ、固定1,000問（各20問）。大カテゴリに問題が存在することは、小カテゴリや能力全体の網羅を意味しません。全件の生成難易度は未校正で、正式Standardは無効です。

| 大カテゴリ | 構造数 | 実装済みの通常テキスト問題 | 指示書に対して残る範囲の例 |
|---|---:|---|---|
| 01 数学・数理 | 7 | 括弧と積の計算、一次方程式、中央値、合同条件の一意解、非復元抽出の厳密確率、整数係数連立方程式、格子多角形の面積 | 数列、関数、微積分、一般の線形代数・最適化 |
| 02 論理的推論 | 4 | 前後関係の復元、真偽制約の一意解、複数前提規則の閉包、集合演算の合成 | 一般的な反例構成・矛盾説明、複雑な制約充足 |
| 03 アルゴリズム的思考 | 5 | 重み付き最短経路、容量制約下の最大価値、有向グラフの到達可能性、交互手番の最適値、文字列の最小編集距離 | 一般ゲーム木・探索戦略、計算量の比較 |
| 04 プログラミング | 4 | ループと条件分岐の出力、複数条件のループ修正、制限式の静的型判定、境界バグを検出する入力 | 汎用コード生成、構文修正、リファクタリング、複数ファイル（隔離コード評価は別モード） |
| 05 コンピューター科学 | 5 | LRUキャッシュミス、トランザクションの確定と取消、ラウンドロビンの完了時刻、最長プレフィックス経路選択、所有者とグループの権限判定 | ファイルシステム、コンパイラ、並列実行の競合、一般的なセキュリティ知識 |
| 06 構造化データ処理 | 4 | 条件抽出と集計、キー結合と売上集計、限定JSONスキーマの検証、複合キーの反結合 | CSV/XMLの変換、汎用SQL、一般のJSON Schema |
| 07 指示追従 | 2 | 選別・整列・厳密書式、条件成立規則の優先順位 | 長さ・禁止語・順序を横断する複合指示 |
| 08 言語能力 | 3 | 否定の作用域と対象抽出、限定英語の否定量化、明示文法の照応連鎖 | 自由翻訳、自由作文、省略・語用論、多言語全般 |
| 09 文章理解 | 2 | 二つの記録を結ぶ根拠、構成事実と単一値属性の含意 | 自由記述要約、一般文章の比較・要旨 |
| 10 長文・コンテキスト | 2 | 長文台帳の差分統合、長文内の有効版ポリシー検索 | 自然な長文の意味統合、実測コンテキスト限界 |
| 11 時間・空間・常識的推論 | 3 | UTC日時の加減算、回転と移動の合成、全員の空き時間の共通部分 | タイムゾーン、基礎物理、一般的な常識・因果 |
| 12 一般知識・専門知識 | 0 | 未対応 | 物理・化学・生物・地理・歴史・経済・文化等すべて（出典/利用条件の確認前） |
| 13 計画立案・問題解決 | 3 | 並列作業の最短完了時刻、一対一割当の最小費用、重複しない予約の最大報酬 | 一般的な資源制約計画、途中の条件変更に伴う再計画 |
| 14 ツール利用・エージェント能力 | 1 | API制約照合と必須引数 | 多様な実API連携・実モデルの失敗復旧（native/agentは別モード） |
| 15 複数ターンの対話理解 | 2 | 会話内の訂正追跡、話者に限定した発言訂正 | 長い自然会話の一貫性、曖昧な指示対象の確認 |
| 16 頑健性・不確実性 | 3 | 観測制約の解の有無、命令を含む文書の限定抽出、質問の前提と欠落情報の区別 | 自由文での不確実性説明、実ツール権限への攻撃耐性 |

## 採用条件と解釈

- 問題生成は乱数・厳密計算・構成事実のみ。LLMによる問題生成なし。
- verifiedは再現性、参照計算、採点のソフトウェア検証を意味します。人間の難易度やモデル識別力の実証ではありません。
- 入力表現は現在、説明文＋JSON、文中の構成文章・疑似コード。回答は数値・短答・JSON。文章/表/CSV/XML等の全形式をカバーしたとは扱いません。
- 新規生成器は独立参照ソルバー、複数seed・難易度、境界ケースを確認。名称や数値の差し替えは独立構造に数えません。
- language.quantifiers/reference等は明示された限定文法、reading.entailmentは構成事実の分類です。自然言語理解全般の測定ではありません。
- robust.injectionは非信頼文書の限定行抽出であり、実際のツール権限やOSの安全性を実証しません。
- code.typesは限定式の静的型規則、code.bug_testsは定義済み述語の識別。提出コードをホストで実行しません。
- 難易度は依存深さ、制約、集合・グラフ・入力サイズ等の生成特徴です。個々のseedで難化を保証せず、分野間の同難易度を主張しません。code.debug/tool.selectもv1.1.0で条件数・相互作用を増やす構造へ更新しました。
- 重複除外は対応済み生成器の順序不変入力と完全一致に限定。新規生成器の一般的な意味同値や名前置換の除外は未実装です。
- 固定銀行は0/25/50/75/100の各4問。生成器の難易度入力は連続0–100ですが、固定問題は離散標本です。狭い範囲・大量指定で不足すると明示的に拒否し、動的問題へ代替しません。

## 知識カテゴリの追加条件

一般知識は分類だけ埋めるための架空データを採用しません。資料の原典URL・利用条件・取得日・スナップショットhash・個別事実の照合結果を記録できた時点で追加します。今回、外部知識資料を検証済みとして組み込んでいません。

## 次の拡充

薄い小カテゴリを優先して50〜80構造へ拡充し、長期目標100以上へ進みます。未対応範囲は上表に残し、出典確認・採点契約・難易度特徴・独立検証を満たさないものをverifiedへ昇格させません。

## 生成器一覧

| ID | 版 | 小カテゴリ | 回答形式 | 難易度特徴（seed 42、50） |
|---|---|---|---|---|
| `math.expression` | 1.0.0 | 算術 | number | operations |
| `math.linear` | 1.0.0 | 方程式 | number | coefficient_magnitude |
| `math.median` | 1.0.0 | 統計 | number | elements |
| `logic.order` | 1.0.0 | 順序 | json | constraints |
| `logic.boolean` | 1.0.0 | 真偽 | json | variables, constraints |
| `algorithm.path` | 1.0.0 | グラフ | number | nodes, edges |
| `code.trace` | 1.0.0 | コード読解 | number | iterations, branches |
| `code.debug` | 1.1.0 | デバッグ | text | cases, options, conditions, exclusion_rules |
| `data.aggregate` | 1.0.0 | 表操作 | json | rows, operations |
| `data.join` | 1.1.0 | 結合 | json | products, orders |
| `instruction.format` | 1.0.0 | 書式 | text | elements, constraints |
| `temporal.offset` | 1.0.0 | 日時計算 | text | updates |
| `dialogue.state` | 1.0.0 | 情報更新 | json | turns |
| `tool.select` | 1.1.0 | テキスト型 | json | tool_count, argument_count, constraints |
| `math.crt` | 1.0.0 | 整数論 | number | constraints, search_space |
| `algorithm.knapsack` | 1.0.0 | 動的計画法 | number | items, capacity |
| `cs.lru` | 1.0.0 | メモリ | number | accesses, capacity |
| `cs.transactions` | 1.0.0 | データベース | json | events |
| `language.scope` | 1.0.0 | 否定 | json | sentences, negation_depth |
| `reading.evidence` | 1.1.0 | 根拠特定 | json | documents, joins |
| `context.ledger` | 1.0.0 | 複数箇所統合 | number | records, accounts |
| `planning.schedule` | 1.0.0 | 依存関係 | number | tasks, dependencies |
| `robust.consistency` | 1.0.0 | 情報不足・矛盾 | json | constraints, domain_size |
| `spatial.rotation` | 1.0.0 | 座標 | json | operations |
| `language.quantifiers` | 1.0.0 | 英語の量化 | json | statements, members |
| `language.reference` | 1.0.0 | 照応 | json | paragraphs, reference_depth |
| `reading.entailment` | 1.0.0 | 含意 | json | facts, claims |
| `context.policy` | 1.0.0 | 改訂検索 | json | policies, revisions, characters |
| `instruction.priority` | 1.0.0 | 条件付き指示 | json | flags, rules, max_conditions |
| `dialogue.correction` | 1.0.0 | 訂正と参照 | json | speakers, turns |
| `robust.injection` | 1.0.0 | 非信頼文書 | json | documents, distractor_lines_per_document |
| `robust.premise` | 1.0.0 | 前提検証 | json | records, characters |
| `math.probability` | 1.0.0 | 確率 | json | population, draws, sample_space |
| `math.linear_system` | 1.0.0 | 線形代数 | json | variables, row_operations, max_coefficient |
| `math.polygon_area` | 1.0.0 | 幾何 | number | vertices, coordinate_span |
| `logic.implication` | 1.0.0 | 含意 | json | atoms, rules, max_premises |
| `logic.set_relations` | 1.0.0 | 集合 | json | universe_size, operations, nesting_depth |
| `algorithm.reachability` | 1.0.0 | グラフ | json | nodes, edges, required_hops |
| `algorithm.minimax` | 1.0.0 | ゲーム木 | number | depth, leaves, decision_nodes |
| `planning.assignment` | 1.0.0 | 資源割当 | number | workers, jobs, possible_assignments |
| `algorithm.edit_distance` | 1.0.0 | 動的計画法 | number | source_length, target_length, dp_cells |
| `planning.interval_selection` | 1.0.0 | スケジュール | number | jobs, candidate_subsets |
| `cs.round_robin` | 1.0.0 | OS | json | processes, total_cpu |
| `cs.routing` | 1.0.0 | ネットワーク | json | routes, destinations |
| `cs.permissions` | 1.0.0 | アクセス制御 | json | requests |
| `data.schema` | 1.0.0 | 検証 | json | records, schema_rules |
| `data.antijoin` | 1.0.0 | 関係演算 | json | left_rows, right_rows, join_keys |
| `code.types` | 1.0.0 | 型推論 | json | max_depth, expressions |
| `code.bug_tests` | 1.0.0 | テスト設計 | json | cases, variants |
| `temporal.intersections` | 1.0.0 | 時間区間 | json | people, intervals_per_person |
