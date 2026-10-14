"""Deterministic systems, structured data, and static programming tasks."""

from collections import deque
from ipaddress import IPv4Address, IPv4Network


def round_robin(processes, quantum):
    pending = sorted(processes, key=lambda p: (p["arrival"], p["id"]))
    remaining = {p["id"]: p["burst"] for p in pending}
    ready: deque[str] = deque()
    result = {}
    now = 0
    while pending or ready:
        if not ready:
            now = max(now, pending[0]["arrival"])
        while pending and pending[0]["arrival"] <= now:
            ready.append(pending.pop(0)["id"])
        current = ready.popleft()
        elapsed = min(quantum, remaining[current])
        now += elapsed
        remaining[current] -= elapsed
        while pending and pending[0]["arrival"] <= now:
            ready.append(pending.pop(0)["id"])
        if remaining[current]:
            ready.append(current)
        else:
            result[current] = now
    return result


def schema_valid(value, schema):
    kind = schema["type"]
    if kind == "integer":
        return type(value) is int and schema["minimum"] <= value <= schema["maximum"]
    if kind == "string":
        return isinstance(value, str) and value in schema["enum"]
    if kind == "boolean":
        return type(value) is bool
    if kind == "array":
        return (
            isinstance(value, list)
            and schema["minItems"] <= len(value) <= schema["maxItems"]
            and all(schema_valid(v, schema["items"]) for v in value)
        )
    return (
        isinstance(value, dict)
        and set(schema["required"]) <= value.keys()
        and value.keys() <= schema["properties"].keys()
        and all(schema_valid(v, schema["properties"][k]) for k, v in value.items())
    )


def infer(expression, environment):
    if isinstance(expression, str):
        return environment[expression]
    operator, *args = expression
    types = [infer(arg, environment) for arg in args]
    if "error" in types:
        return "error"
    if operator == "add":
        return "int" if types == ["int", "int"] else "error"
    if operator == "and":
        return "bool" if types == ["bool", "bool"] else "error"
    if operator == "eq":
        return "bool" if types[0] == types[1] else "error"
    return types[1] if types[0] == "bool" and types[1] == types[2] else "error"


def register_systems(register, size):
    @register(
        "cs.round_robin",
        "05",
        "OS",
        "ラウンドロビンの完了時刻",
        "arrival-aware-round-robin",
        "json",
    )
    def cpu(r, d):
        n, quantum = size(d, 3, 12), r.randint(1, 4)
        processes = [
            {"id": f"P{i:02}", "arrival": r.randrange(n * 2), "burst": r.randint(1, 12)}
            for i in range(n)
        ]
        return (
            {"processes": processes, "quantum": quantum},
            round_robin(processes, quantum),
            "単一CPU、切替コスト0、時刻0開始のラウンドロビン。到着したプロセスはFIFO待ち行列の末尾へ。CPUが空なら次の到着まで進めます。各実行はquantumまたは残り時間の短い方。実行中は割込みなし。実行終了時刻までの到着を(到着時刻,IDの辞書順)で末尾に追加してから、未完了の実行プロセスを末尾に戻します。同時刻の到着も再投入より先です。完了なら再投入しません。IDをキー、完了時刻を値とするJSONオブジェクトで答えてください。",
            {"processes": n, "total_cpu": sum(p["burst"] for p in processes)},
        )

    @register(
        "cs.routing",
        "05",
        "ネットワーク",
        "最長プレフィックス経路選択",
        "ipv4-longest-prefix",
        "json",
    )
    def routing(r, d):
        routes = [{"cidr": "0.0.0.0/0", "next_hop": "H0"}]
        base = r.randrange(256)
        for i in range(size(d, 3, 16)):
            prefix = r.choice([8, 16, 24, 28, 32])
            address = (10 << 24) | (base << 16) | r.randrange(65536)
            network = IPv4Network((address, prefix), strict=False)
            routes.append({"cidr": str(network), "next_hop": f"H{i + 1}"})
        destinations = [str(IPv4Network(route["cidr"]).network_address) for route in routes[1:]]
        destinations += ["192.0.2.1", f"10.{base}.255.255"]
        r.shuffle(routes)
        answer = []
        for destination in destinations:
            matches = [
                (i, IPv4Network(route["cidr"]))
                for i, route in enumerate(routes)
                if IPv4Address(destination) in IPv4Network(route["cidr"])
            ]
            winner = max(matches, key=lambda pair: (pair[1].prefixlen, -pair[0]))[0]
            answer.append(routes[winner]["next_hop"])
        return (
            {"routes": routes, "destinations": destinations},
            answer,
            "IPv4の各宛先に対して、そのアドレスを含むCIDRのうちプレフィックス長が最大の経路を選択。同じ長さならroutesの配列添字が小さい方を優先。/0は全アドレスに一致。destinationsの順でnext_hopをJSON配列にしてください。",
            {"routes": len(routes), "destinations": len(destinations)},
        )

    @register(
        "cs.permissions",
        "05",
        "アクセス制御",
        "所有者とグループの権限判定",
        "posix-permission-class",
        "json",
    )
    def permissions(r, d):
        files = [
            {
                "owner": r.choice(["alice", "bob"]),
                "group": r.choice(["staff", "dev"]),
                "mode": [r.randrange(8) for _ in range(3)],
            }
            for _ in range(size(d, 3, 20))
        ]
        requests = [
            {
                "file": i,
                "user": r.choice(["alice", "bob", "carol"]),
                "groups": r.sample(["staff", "dev"], r.randrange(3)),
                "need": r.randint(1, 7),
            }
            for i in range(len(files))
        ]
        answer = []
        for req in requests:
            file = files[req["file"]]
            index = (
                0 if req["user"] == file["owner"] else 1 if file["group"] in req["groups"] else 2
            )
            answer.append(file["mode"][index] & req["need"] == req["need"])
        return (
            {"files": files, "requests": requests},
            answer,
            "modeは[所有者,所属グループ,その他]の権限値で読=4,書=2,実行=1の和。userがownerなら所有者欄のみ、そうでなくfileのgroupがgroupsにあればグループ欄のみ、それ以外はその他欄のみを使います。他の欄へのフォールバックや権限合成はありません。管理者特例もありません。needの全ビットが許可されるかrequests順にJSON真偽値配列で答えてください。",
            {"requests": len(requests)},
        )

    @register(
        "data.schema", "06", "検証", "限定JSONスキーマの検証", "restricted-json-schema", "json"
    )
    def schema(r, d):
        upper = r.randint(3, 12)
        spec = {
            "type": "object",
            "required": ["count", "tags"],
            "additionalProperties": False,
            "properties": {
                "count": {"type": "integer", "minimum": 0, "maximum": upper},
                "tags": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 3,
                    "items": {"type": "string", "enum": ["red", "blue"]},
                },
                "active": {"type": "boolean"},
            },
        }
        records = []
        for _ in range(size(d, 4, 20)):
            record = {
                "count": r.randint(0, upper),
                "tags": r.choices(["red", "blue"], k=r.randint(1, 3)),
                "active": r.choice([True, False]),
            }
            mutation = r.randrange(8)
            if mutation == 0:
                record["count"] = True
            elif mutation == 1:
                record["count"] = upper + 1
            elif mutation == 2:
                record["tags"] = []
            elif mutation == 3:
                del record["count"]
            elif mutation == 4:
                record["extra"] = 1
            elif mutation == 5:
                record["tags"] = ["green"]
            records.append(record)
        return (
            {"schema": spec, "records": records},
            [i for i, record in enumerate(records) if schema_valid(record, spec)],
            "次の限定JSONスキーマだけを用いてrecordsを検証し、有効なレコードの0始まり添字を昇順JSON配列で答えてください。objectはrequiredの全キー必須、additionalProperties=falseでproperties以外のキー禁止。integerは真偽値を除く整数でminimum以上maximum以下。stringはenumのいずれか。booleanはtrue/falseのみ。arrayはminItems以上maxItems以下の長さで全要素がitemsを満たすこと。任意キーも存在すれば型検証します。型変換なし、nullはどの型にも不適合。",
            {"records": len(records), "schema_rules": 9},
        )

    @register(
        "data.antijoin",
        "06",
        "関係演算",
        "複合キーの反結合",
        "null-aware-relational-antijoin",
        "json",
    )
    def antijoin(r, d):
        n = size(d, 4, 24)
        left = [
            {"id": i, "a": r.choice([None, 0, 1, 2]), "b": r.choice([None, "x", "y"])}
            for i in range(n)
        ]
        right = [
            {
                "a": r.choice([None, 0, 1, 2]),
                "b": r.choice([None, "x", "y"]),
                "enabled": r.choice([True, False]),
            }
            for _ in range(n)
        ]
        excluded = {
            (row["a"], row["b"])
            for row in right
            if row["enabled"] and row["a"] is not None and row["b"] is not None
        }
        answer = [row["id"] for row in left if (row["a"], row["b"]) not in excluded]
        return (
            {"left": left, "right": right},
            answer,
            "leftの各行について、enabled=trueでaとbの両方がその行と等しいright行が1つも存在しない場合だけ採用します。SQLの等値規則と同様、どちらかがnullなら比較は一致しません（null同士も不一致）。rightの重複は結果に影響しません。採用したleftのidを入力順のJSON配列で答えてください。",
            {"left_rows": n, "right_rows": n, "join_keys": 2},
        )

    @register(
        "code.types",
        "04",
        "型推論",
        "制限式の静的型判定",
        "restricted-expression-type-inference",
        "json",
    )
    def types(r, d):
        environment = {"x": "int", "y": "int", "p": "bool", "q": "bool"}
        depth = size(d, 1, 5)

        def expression(level):
            if level == 0 or r.random() < 0.25:
                return r.choice(list(environment))
            op = r.choice(["add", "and", "eq", "if"])
            return [op, *[expression(level - 1) for _ in range(3 if op == "if" else 2)]]

        def typed_expression(level, kind):
            if level == 0:
                return r.choice([name for name, typ in environment.items() if typ == kind])
            op = r.choice(["add", "if"] if kind == "int" else ["and", "eq", "if"])
            if op == "if":
                return [
                    op,
                    typed_expression(level - 1, "bool"),
                    typed_expression(level - 1, kind),
                    typed_expression(level - 1, kind),
                ]
            operand_type = r.choice(["int", "bool"]) if op == "eq" else kind
            return [
                op,
                typed_expression(level - 1, operand_type),
                typed_expression(level - 1, operand_type),
            ]

        expressions = [
            typed_expression(depth, "int"),
            typed_expression(depth, "bool"),
            ["add", typed_expression(depth - 1, "int"), typed_expression(depth - 1, "bool")],
        ] + [expression(depth) for _ in range(size(d, 3, 8) - 3)]
        r.shuffle(expressions)
        return (
            {"environment": environment, "expressions": expressions},
            [infer(expr, environment) for expr in expressions],
            '式の文法は変数名の文字列、または["add",式,式],["and",式,式],["eq",式,式],["if",条件式,真枝,偽枝]のみ。environmentが変数型。addはint2個からint、andはbool2個からbool、eqは同型2個からbool、ifは条件がboolかつ両枝が同型なら枝の型。型変換なし。全部分式を静的に検査し、どれかが不適合なら式全体がerror。各式の型を"int","bool","error"のJSON配列で答えてください。',
            {"max_depth": depth, "expressions": len(expressions)},
        )

    @register(
        "code.bug_tests",
        "04",
        "テスト設計",
        "境界バグを検出する入力",
        "interval-membership-mutant-discrimination",
        "json",
    )
    def bugs(r, d):
        lower, upper = r.randint(-10, 5), r.randint(6, 20)
        cases = [lower - 1, lower, upper - 1, upper, 0] + [
            r.randint(-15, 25) for _ in range(size(d, 1, 15))
        ]
        r.shuffle(cases)
        variants = r.sample(
            ["lower_strict", "upper_inclusive", "disjunction", "reversed"], size(d, 2, 4)
        )
        answer = {}
        for variant in variants:
            wrong = {
                "lower_strict": lambda x: lower < x < upper,
                "upper_inclusive": lambda x: lower <= x <= upper,
                "disjunction": lambda x: x >= lower or x < upper,
                "reversed": lambda x: upper <= x < lower,
            }[variant]
            answer[variant] = [i for i, x in enumerate(cases) if wrong(x) != (lower <= x < upper)]
        return (
            {"lower": lower, "upper": upper, "cases": cases, "variants": variants},
            answer,
            "正しい仕様はlower <= x かつ x < upperの真偽値。各変種の定義はlower_strict: lower < x かつ x < upper、upper_inclusive: lower <= x かつ x <= upper、disjunction: x >= lower または x < upper、reversed: upper <= x かつ x < lower。コード実行は不要です。variantsの各変種について仕様と真偽値が異なるcasesの0始まり添字を昇順で列挙し、変種名をキーとするJSONオブジェクトで答えてください。",
            {"cases": len(cases), "variants": len(variants)},
        )

    @register(
        "temporal.intersections",
        "11",
        "時間区間",
        "全員の空き時間の共通部分",
        "multi-schedule-interval-intersection",
        "json",
    )
    def intervals(r, d):
        schedules = []
        for _ in range(size(d, 2, 5)):
            schedule = []
            for _ in range(size(d, 2, 8)):
                start = r.randrange(60)
                schedule.append([start, start + r.randint(1, 20)])
            schedules.append(schedule)
        boundaries = sorted(
            {t for schedule in schedules for interval in schedule for t in interval}
        )
        answer: list[list[int]] = []
        for start, end in zip(boundaries, boundaries[1:], strict=False):
            if all(any(a <= start and end <= b for a, b in schedule) for schedule in schedules):
                if answer and answer[-1][1] == start:
                    answer[-1][1] = end
                else:
                    answer.append([start, end])
        return (
            {"schedules": schedules},
            answer,
            "schedulesの各要素は1人分の空き時間の集合です。各区間[start,end]は同一日の分単位の半開区間[start,end)で、開始を含み終了を含みません。1人分では重複区間の和集合を取り、全員の共通部分を求めます。隣接する区間も併合した極大の正長区間を開始時刻昇順のJSON配列で答えてください。共通部分なしは[]。",
            {"people": len(schedules), "intervals_per_person": len(schedules[0])},
        )
