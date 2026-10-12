"""Independent deterministic structures; no model or external dataset involved."""

import math


def register_extra(register, size):
    @register("math.crt", "01", "整数論", "合同条件の一意解", "bounded-congruences", "number")
    def congruences(r, d):
        moduli = r.sample([3, 5, 7, 11, 13, 17], size(d, 2, 4))
        bound = math.prod(moduli)
        answer = r.randrange(bound)
        return (
            {"conditions": [[m, answer % m] for m in moduli], "upper_exclusive": bound},
            answer,
            "0以上upper_exclusive未満で、各条件 [法,余り] をすべて満たす整数を答えてください。",
            {"constraints": len(moduli), "search_space": bound},
        )

    @register(
        "algorithm.knapsack",
        "03",
        "動的計画法",
        "容量制約下の最大価値",
        "zero-one-knapsack",
        "number",
    )
    def knapsack(r, d):
        items = [[r.randint(1, 12), r.randint(1, 25)] for _ in range(size(d, 3, 12))]
        capacity = size(d, 5, 25)
        table = [0] * (capacity + 1)
        for weight, value in items:
            for cap in range(capacity, weight - 1, -1):
                table[cap] = max(table[cap], table[cap - weight] + value)
        return (
            {"items": items, "capacity": capacity},
            table[-1],
            "itemsは [重さ,価値]。各項目は高々1回選べます。重さ合計がcapacity以下となる最大価値合計を整数で答えてください。",
            {"items": len(items), "capacity": capacity},
        )

    @register("cs.lru", "05", "メモリ", "LRUキャッシュミス", "lru-cache-simulation", "number")
    def lru(r, d):
        capacity = size(d, 2, 5)
        accesses = [r.randrange(capacity + 2) for _ in range(size(d, 6, 40))]
        last: dict[int, int] = {}
        misses = 0
        for t, key in enumerate(accesses):
            if key not in last:
                misses += 1
                if len(last) == capacity:
                    del last[min(last, key=lambda key: last[key])]
            last[key] = t
        return (
            {"capacity": capacity, "accesses": accesses},
            misses,
            "空のLRUキャッシュにaccessesを順に適用。未格納ならミスで追加し、満杯時は最も長く参照されていない要素を追い出します。ミス数を整数で答えてください。",
            {"accesses": len(accesses), "capacity": capacity},
        )

    @register(
        "cs.transactions",
        "05",
        "データベース",
        "トランザクションの確定と取消",
        "transaction-rollback",
        "json",
    )
    def transactions(r, d):
        events, current = [], {"a": r.randint(0, 20), "b": r.randint(0, 20)}
        initial = current.copy()
        for _ in range(size(d, 2, 10)):
            before = current.copy()
            events.append(["begin"])
            for _ in range(r.randint(1, 4)):
                key, value = r.choice(["a", "b"]), r.randint(-50, 50)
                events.append(["set", key, value])
                current[key] = value
            commit = r.choice([True, False])
            events.append(["commit" if commit else "rollback"])
            if not commit:
                current = before
        return (
            {"initial": initial, "events": events},
            current,
            "トランザクションは入れ子なし。begin時点を保存、setは値を置換、commitは確定、rollbackはbegin時点に戻します。最終状態をJSONオブジェクトで答えてください。",
            {"events": len(events)},
        )

    @register(
        "language.scope",
        "08",
        "否定",
        "否定の作用域と対象抽出",
        "controlled-japanese-negation",
        "json",
    )
    def scope(r, d):
        names = [f"人物{i}" for i in range(size(d, 3, 16))]
        sentences, selected = [], []
        for name in names:
            positive = bool(r.getrandbits(1))
            sentences.append(
                f"{name}は参加しないわけではない。"
                if positive
                else f"{name}は参加するわけではない。"
            )
            if positive:
                selected.append(name)
        r.shuffle(sentences)
        return (
            {"sentences": sentences},
            sorted(selected),
            "この形式言語では「参加しないわけではない」は参加、「参加するわけではない」は不参加と厳密に定義します。参加する人物名だけを文字列の辞書順でJSON配列にしてください。現実の語用論上の推測はしません。",
            {"sentences": len(names), "negation_depth": 2},
        )

    @register(
        "reading.evidence",
        "09",
        "根拠特定",
        "二つの記録を結ぶ根拠",
        "relational-evidence-selection",
        "json",
    )
    def evidence(r, d):
        n = size(d, 3, 18)
        people = r.sample(range(100, 999), n)
        places = r.sample(range(100, 999), n)
        docs = []
        for i in range(n):
            docs.extend(
                [
                    {"id": f"A{i}", "text": f"人物{people[i]}の担当品は品物{i}。"},
                    {"id": f"B{i}", "text": f"品物{i}の保管場所は倉庫{places[i]}。"},
                ]
            )
        target = r.randrange(n)
        r.shuffle(docs)
        return (
            {"documents": docs, "person": f"人物{people[target]}"},
            {"place": f"倉庫{places[target]}", "evidence": [f"A{target}", f"B{target}"]},
            'personの担当品の保管場所を記録から特定し、{"place":場所,"evidence":[人物の記録ID,品物の記録ID]}で答えてください。',
            {"documents": len(docs), "joins": 1},
        )

    @register(
        "context.ledger",
        "10",
        "複数箇所統合",
        "長文台帳の差分統合",
        "long-ledger-aggregation",
        "number",
    )
    def ledger(r, d):
        target = f"口座{r.randrange(6)}"
        records = [(f"口座{r.randrange(6)}", r.randint(-50, 50)) for _ in range(size(d, 20, 180))]
        return (
            {
                "passage": "\n".join(
                    f"記録{i}: {key}の残高を{delta:+d}変更。"
                    for i, (key, delta) in enumerate(records)
                ),
                "target": target,
            },
            sum(delta for key, delta in records if key == target),
            "各口座の初期残高は0。passageの記録をすべて適用したtargetの残高を整数で答えてください。",
            {"records": len(records), "accounts": 6},
        )

    @register(
        "planning.schedule",
        "13",
        "依存関係",
        "並列作業の最短完了時刻",
        "dag-critical-path",
        "number",
    )
    def schedule(r, d):
        n = size(d, 3, 16)
        durations = [r.randint(1, 20) for _ in range(n)]
        edges = [[a, b] for a in range(n) for b in range(a + 1, n) if r.random() < 0.3]
        finish: list[int] = []
        for node in range(n):
            finish.append(
                durations[node] + max([finish[a] for a, b in edges if b == node], default=0)
            )
        return (
            {"durations": durations, "dependencies": edges},
            max(finish),
            "作業IDはdurationsの添字。[A,B]はA完了後にB開始可能を意味します。時刻0開始、作業者は無制限、作業は中断不可。全作業の最短完了時刻を整数で答えてください。",
            {"tasks": n, "dependencies": len(edges)},
        )

    @register(
        "robust.consistency",
        "16",
        "情報不足・矛盾",
        "観測制約の解の有無",
        "finite-domain-uncertainty",
        "json",
    )
    def consistency(r, d):
        upper = size(d, 10, 60)
        hidden = r.randint(0, upper)
        observations = [[r.randint(2, 9), 0] for _ in range(size(d, 1, 5))]
        for item in observations:
            item[1] = hidden % item[0]
        if r.random() < 0.35:
            observations.append([observations[0][0], (observations[0][1] + 1) % observations[0][0]])
        matches = [x for x in range(upper + 1) if all(x % m == v for m, v in observations)]
        answer = {
            "status": "inconsistent"
            if not matches
            else "unique"
            if len(matches) == 1
            else "insufficient",
            "value": matches[0] if len(matches) == 1 else None,
        }
        return (
            {"upper_inclusive": upper, "observations": observations},
            answer,
            '未知整数xは0以上upper_inclusive以下。observationsの [法,余り] を全て満たすxについて、解なしはinconsistent、一意ならunique、複数ならinsufficient。{"status":分類,"value":一意解またはnull}で答えてください。',
            {"constraints": len(observations), "domain_size": upper + 1},
        )

    @register(
        "spatial.rotation",
        "11",
        "座標",
        "回転と移動の合成",
        "affine-coordinate-composition",
        "json",
    )
    def rotation(r, d):
        start = [r.randint(-10, 10), r.randint(-10, 10)]
        x, y = start
        operations = []
        for _ in range(size(d, 2, 18)):
            if r.random() < 0.5:
                operations.append(["rotate_ccw"])
                x, y = -y, x
            else:
                dx, dy = r.randint(-10, 10), r.randint(-10, 10)
                operations.append(["translate", dx, dy])
                x, y = x + dx, y + dy
        return (
            {"start": start, "operations": operations},
            [x, y],
            "座標startにoperationsを順に適用。rotate_ccwは原点中心に反時計回り90度回転、translateは[dx,dy]だけ平行移動。最終座標を[x,y]のJSON配列で答えてください。",
            {"operations": len(operations)},
        )
