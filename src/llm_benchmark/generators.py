"""Pure, versioned generators. No network, subprocess or model dependencies."""

import heapq
import itertools
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from llm_benchmark.domain import AnswerSpec, Problem, canonical, digest

CATEGORIES = {
    "01": "数学・数理",
    "02": "論理的推論",
    "03": "アルゴリズム的思考",
    "04": "プログラミング",
    "05": "コンピューター科学",
    "06": "構造化データ処理",
    "07": "指示追従",
    "08": "言語能力",
    "09": "文章理解",
    "10": "長文・コンテキスト",
    "11": "時間・空間・常識的推論",
    "12": "一般知識・専門知識",
    "13": "計画立案・問題解決",
    "14": "ツール利用・エージェント能力",
    "15": "複数ターンの対話理解",
    "16": "頑健性・不確実性",
}

Builder = Callable[[random.Random, float], tuple[dict[str, Any], Any, str, dict[str, Any]]]


@dataclass(frozen=True)
class Generator:
    id: str
    category_id: str
    subcategory_id: str
    name: str
    template: str
    answer_type: str
    build: Builder
    version: str = "1.0.0"
    status: Literal["verified", "experimental", "unavailable"] = "verified"
    tags: tuple[str, ...] = ("日本語理解", "決定的生成")

    def metadata(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "category_id": self.category_id,
            "subcategory_id": self.subcategory_id,
            "name": self.name,
            "template": self.template,
            "version": self.version,
            "status": self.status,
            "difficulty_range": [0, 100],
            "answer_type": self.answer_type,
            "tags": list(self.tags),
        }

    def generate(
        self, seed: int, difficulty: float, origin: Literal["fixed", "dynamic"] = "dynamic"
    ) -> Problem:
        if self.status == "unavailable":
            raise ValueError("この生成器は利用できません")
        if not 0 <= difficulty <= 100 or origin not in ("fixed", "dynamic"):
            raise ValueError("生成パラメーターが範囲外です")
        difficulty = float(difficulty)
        payload, expected, instruction, features = self.build(random.Random(seed), difficulty)
        prompt = (
            f"課題: {self.id}\n{instruction}\n入力(JSON):\n{canonical(payload)}\n"
            "回答だけを出力してください。説明やMarkdownの囲みは不要です。"
        )
        spec = AnswerSpec(expected=expected, type=self.answer_type)  # type: ignore[arg-type]
        content = {
            "prompt": prompt,
            "answer_spec": spec.model_dump(),
            "generator_id": self.id,
            "generator_version": self.version,
            "seed": seed,
            "difficulty": difficulty,
        }
        content_hash = digest(content)
        return Problem(
            problem_id=f"p-{content_hash[:24]}",
            generator_id=self.id,
            generator_version=self.version,
            category_id=self.category_id,
            subcategory_id=self.subcategory_id,
            tags=list(self.tags),
            seed=seed,
            target_difficulty=difficulty,
            prompt=prompt,
            answer_spec=spec,
            grading_type=self.answer_type,
            verification=self.status,
            origin=origin,
            template=self.template,
            features=features,
            content_hash=content_hash,
        )  # type: ignore[arg-type]


REGISTRY: dict[str, Generator] = {}


def register(
    id: str,
    category: str,
    subcategory: str,
    name: str,
    template: str,
    type: str,
    *,
    version: str = "1.0.0",
):
    def decorator(fn: Builder) -> Builder:
        if id in REGISTRY:
            raise ValueError(f"Duplicate generator: {id}")
        REGISTRY[id] = Generator(
            id, category, subcategory, name, template, type, fn, version=version
        )
        return fn

    return decorator


def size(d: float, low: int = 3, high: int = 20) -> int:
    return low + int((high - low) * d / 100)


@register("math.expression", "01", "算術", "括弧と積の計算", "sum-of-products", "number")
def expression(r: random.Random, d: float):
    pairs = [
        [r.randint(-size(d, 5, 99), size(d, 5, 99)) for _ in range(2)]
        for _ in range(size(d, 2, 12))
    ]
    return (
        {"pairs": pairs},
        sum(a * b for a, b in pairs),
        "各ペアの2数の積を求め、その総和を整数で答えてください。",
        {"operations": len(pairs) * 2 - 1},
    )


@register("math.linear", "01", "方程式", "一次方程式", "linear-equation", "number")
def linear(r: random.Random, d: float):
    a, b, x = r.randint(1, size(d, 3, 99)), r.randint(-100, 100), r.randint(-size(d), size(d))
    return (
        {"a": a, "b": b, "c": a * x + b},
        x,
        "a*x + b = c を満たす x を求めてください。",
        {"coefficient_magnitude": size(d, 3, 99)},
    )


@register("math.median", "01", "統計", "中央値", "order-statistic", "number")
def median(r: random.Random, d: float):
    values = [r.randint(-100, 100) for _ in range(size(d))]
    return (
        {"values": values},
        statistics.median(values),
        "values の中央値を数値で答えてください。偶数個の場合は中央2数の平均です。",
        {"elements": len(values)},
    )


@register("logic.order", "02", "順序", "前後関係の復元", "unique-chain", "json")
def order(r: random.Random, d: float):
    names = [f"item-{i}" for i in range(size(d, 3, 16))]
    r.shuffle(names)
    edges = list(zip(names[:-1], names[1:], strict=True))
    r.shuffle(edges)
    return (
        {"before": edges},
        names,
        "before の [A,B] は A が B より前を意味します。すべての項目を一意な順序のJSON配列で答えてください。",
        {"constraints": len(edges)},
    )


@register("logic.boolean", "02", "真偽", "真偽制約の一意解", "xor-chain-anchor", "json")
def boolean(r: random.Random, d: float):
    n = size(d, 3, 10)
    solution = [bool(r.getrandbits(1)) for _ in range(n)]
    payload: dict[str, Any] = {
        "count": n,
        "first": solution[0],
        "xor": [solution[i] != solution[i + 1] for i in range(n - 1)],
    }
    # Exhaustive independent uniqueness check, bounded at 2**10 assignments.
    matches = [
        list(bits)
        for bits in itertools.product([False, True], repeat=n)
        if bits[0] == payload["first"]
        and all((bits[i] != bits[i + 1]) == payload["xor"][i] for i in range(n - 1))
    ]
    if matches != [solution]:
        raise ValueError("真偽問題の一意性検証に失敗しました")
    return (
        payload,
        solution,
        "count 個の真偽値をJSON配列で答えてください。先頭は first、隣接する値の排他的論理和は xor と一致します。",
        {"variables": n, "constraints": n},
    )


def shortest_distance(nodes: int, edges: list[list[int]]) -> int:
    adjacency: dict[int, list[tuple[int, int]]] = {i: [] for i in range(nodes)}
    for a, b, weight in edges:
        adjacency[a].append((b, weight))
    distance = {0: 0}
    queue = [(0, 0)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != distance[node]:
            continue
        for target, weight in adjacency[node]:
            candidate = cost + weight
            if candidate < distance.get(target, 10**12):
                distance[target] = candidate
                heapq.heappush(queue, (candidate, target))
    return distance[nodes - 1]


@register("algorithm.path", "03", "グラフ", "重み付き最短経路", "directed-weighted-path", "number")
def path(r: random.Random, d: float):
    n = size(d, 3, 18)
    edges = [[i, i + 1, r.randint(1, 20)] for i in range(n - 1)]
    edges += [
        [i, j, r.randint(1, 30)] for i in range(n) for j in range(i + 2, n) if r.random() < 0.3
    ]
    return (
        {"nodes": n, "edges": edges},
        shortest_distance(n, edges),
        "有向辺 [始点,終点,正の重み] のグラフで、頂点0から頂点 nodes-1 への最短距離を整数で答えてください。",
        {"nodes": n, "edges": len(edges)},
    )


@register(
    "code.trace", "04", "コード読解", "ループと条件分岐の出力", "conditional-reduction", "number"
)
def trace(r: random.Random, d: float):
    values = [r.randint(-20, 30) for _ in range(size(d))]
    modulus = r.randint(2, 7)
    expected = sum(v * 2 if v % modulus == 0 else v - 1 for v in values)
    return (
        {"values": values, "modulus": modulus},
        expected,
        "次のPythonコードが出力する整数を答えてください（実行は不要）。\n total = 0\n for v in values:\n     total += v * 2 if v % modulus == 0 else v - 1\n print(total)",
        {"iterations": len(values), "branches": 2},
    )


@register(
    "code.debug",
    "04",
    "デバッグ",
    "複数条件のループ修正",
    "finite-domain-loop-repair",
    "text",
    version="1.1.0",
)
def debug(r: random.Random, d: float):
    filter_count = size(d, 0, 3)
    step = r.randint(1, size(d, 2, 6))
    exclusions = [[m, r.randrange(m)] for m in r.sample([3, 5, 7, 11, 13], filter_count)]
    lower_inclusive, upper_inclusive = r.choice([True, False]), r.choice([True, False])
    cases = [[r.randint(-30, 30), r.randint(35, 65)] for _ in range(size(d, 3, 10))]
    correct: dict[str, Any] = {
        "start_offset": 0 if lower_inclusive else 1,
        "stop_offset": 1 if upper_inclusive else 0,
        "step": step,
        "exclude": exclusions,
    }

    def output(option, case):
        a, b = case
        return [
            x
            for x in range(a + option["start_offset"], b + option["stop_offset"], option["step"])
            if all(x % modulus != residue for modulus, residue in option["exclude"])
        ]

    desired = [
        [
            x
            for x in range(a - 2, b + 3)
            if (x >= a if lower_inclusive else x > a)
            and (x <= b if upper_inclusive else x < b)
            and (x - a - correct["start_offset"]) % step == 0
            and all(x % m != v for m, v in exclusions)
        ]
        for a, b in cases
    ]
    candidates = []
    mutations: list[tuple[str, list[Any]]] = [
        ("start_offset", [-2, -1, 0, 1, 2]),
        ("stop_offset", [-2, -1, 0, 1, 2]),
        ("step", list(range(1, 9))),
        ("exclude", [exclusions[:i] + exclusions[i + 1 :] for i in range(filter_count)]),
    ]
    for field, values in mutations:
        for value in values:
            candidate = {**correct, field: value}
            if [output(candidate, case) for case in cases] != desired:
                candidates.append(candidate)
    count = size(d, 3, 8)
    selected = [correct, *r.sample(candidates, count - 1)]
    r.shuffle(selected)
    options = dict(zip("ABCDEFGH"[:count], selected, strict=True))
    valid = [
        label
        for label, option in options.items()
        if [output(option, case) for case in cases] == desired
    ]
    assert len(valid) == 1
    return (
        {
            "contract": {
                "lower_inclusive": lower_inclusive,
                "upper_inclusive": upper_inclusive,
                "step": step,
                "exclude": exclusions,
            },
            "cases": cases,
            "options": options,
        },
        valid[0],
        "各case=[a,b]に対しcontractが指定する下端/上端の包含条件で整数を選び、許可された最初の整数a（下端を含む場合）またはa+1を起点にstep刻みで昇順に列挙します。ただしexcludeの[法,余り]のどれかに一致する整数は除外。負数の剰余も0以上法未満です。修正候補optionを次の制限コードに当てはめ、全casesで仕様どおりのリストを返す唯一の記号1文字を答えてください。実行は不要です。\n result=[]\n for x in range(a+option.start_offset, b+option.stop_offset, option.step):\n     if all(x % m != v for [m,v] in option.exclude): result.append(x)\nrangeは開始を含み終了を含みません。空のexcludeなら全て通過。",
        {
            "cases": len(cases),
            "options": count,
            "conditions": 3 + filter_count,
            "exclusion_rules": filter_count,
        },
    )


@register("data.aggregate", "06", "表操作", "条件抽出と集計", "filter-group-sum", "json")
def aggregate(r: random.Random, d: float):
    rows: list[dict[str, Any]] = [
        {"group": r.choice(["alpha", "beta", "gamma"]), "value": r.randint(0, 50)}
        for _ in range(size(d, 4, 35))
    ]
    threshold = r.randint(5, 30)
    answer = {
        g: sum(row["value"] for row in rows if row["group"] == g and row["value"] >= threshold)
        for g in ["alpha", "beta", "gamma"]
    }
    return (
        {"rows": rows, "threshold": threshold},
        answer,
        "value >= threshold の行だけを対象に、group 別の value の合計をJSONオブジェクトで答えてください。alpha,beta,gammaを必ず含め、該当行がない場合は0です。",
        {"rows": len(rows), "operations": 2},
    )


@register(
    "data.join", "06", "結合", "キー結合と売上集計", "join-and-reduce", "json", version="1.1.0"
)
def join(r: random.Random, d: float):
    products: list[dict[str, Any]] = [
        {"id": f"sku-{i}", "price": r.randint(1, 50)} for i in range(size(d, 2, 8))
    ]
    orders: list[dict[str, Any]] = [
        {"id": r.choice(products)["id"], "quantity": r.randint(1, 10)}
        for _ in range(size(d, 3, 25))
    ]
    answer = {
        p["id"]: p["price"] * sum(o["quantity"] for o in orders if o["id"] == p["id"])
        for p in products
    }
    return (
        {"products": products, "orders": orders},
        answer,
        "products と orders を id で結合し、商品ごとの price*quantity の売上合計を答えてください。回答は商品idをキー、売上合計の数値を値とする単一のJSONオブジェクトです。配列やproductsなどの外側のキーは付けません。全商品を含め、注文がない商品は0です。",
        {"products": len(products), "orders": len(orders)},
    )


@register("instruction.format", "07", "書式", "選別・整列・厳密書式", "filter-sort-render", "text")
def formatting(r: random.Random, d: float):
    values = r.sample(range(-80, 120), size(d, 3, 22))
    return (
        {"values": values},
        "|".join(map(str, sorted(v for v in values if v >= 0 and v % 2 == 0))),
        "非負の偶数だけを昇順に並べ、縦棒 | で区切って答えてください。空白、末尾の区切り、説明は禁止。対象がなければ空文字です。",
        {"elements": len(values), "constraints": 4},
    )


@register("temporal.offset", "11", "日時計算", "UTC日時の加減算", "utc-minute-offset", "text")
def temporal(r: random.Random, d: float):
    start = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(minutes=r.randint(0, 500_000))
    offsets = [r.randint(-7200, 7200) for _ in range(size(d, 2, 12))]
    expected = (start + timedelta(minutes=sum(offsets))).strftime("%Y-%m-%d %H:%M")
    return (
        {"start_utc": start.strftime("%Y-%m-%d %H:%M"), "offsets_minutes": offsets},
        expected,
        "UTCの start_utc に offsets_minutes の全オフセットを順に加算し、最終日時を YYYY-MM-DD HH:MM で答えてください。",
        {"updates": len(offsets)},
    )


@register("dialogue.state", "15", "情報更新", "会話内の訂正追跡", "last-update-wins", "json")
def state(r: random.Random, d: float):
    events = [
        {"field": r.choice(["place", "time", "owner"]), "value": f"value-{r.randrange(100)}"}
        for _ in range(size(d, 4, 30))
    ]
    answer: dict[str, str] = {}
    for event in events:
        answer[event["field"]] = event["value"]
    return (
        {"events": events},
        answer,
        "会話の訂正を古い順に events に記録しています。各 field の最後の value をJSONで答えてください。一度も現れないfieldは省略します。",
        {"turns": len(events)},
    )


@register(
    "tool.select",
    "14",
    "テキスト型",
    "API制約照合と必須引数",
    "text-api-constraint-matching",
    "json",
    version="1.1.0",
)
def tool(r: random.Random, d: float):
    attribute_count, argument_count = size(d, 2, 6), size(d, 1, 5)
    domains = {
        "operation": ["read", "delete"],
        "resource": ["inventory", "orders"],
        "region": ["east", "west", "central"],
        "consistency": ["strong", "eventual"],
        "format": ["json", "csv"],
        "history": ["supported", "unsupported"],
    }
    constraints = {key: r.choice(values) for key, values in list(domains.items())[:attribute_count]}
    constraints["operation"] = "read"
    arguments = {
        "item_id": f"item-{r.randrange(1000000)}",
        "warehouse": f"W{r.randrange(100)}",
        "as_of": f"2026-10-{r.randint(1, 28):02}",
        "locale": r.choice(["ja-JP", "en-US"]),
        "request_id": f"R{r.randrange(1000000)}",
    }
    required = r.sample(list(arguments), argument_count)
    definitions: list[dict[str, Any]] = [{"attributes": constraints.copy(), "required": required}]
    for key, value in constraints.items():
        definitions.append(
            {
                "attributes": {
                    **constraints,
                    key: r.choice([v for v in domains[key] if v != value]),
                },
                "required": required[:],
            }
        )
    definitions.append(
        {"attributes": constraints.copy(), "required": required + ["unavailable_token"]}
    )
    r.shuffle(definitions)
    tools = {
        f"api_{r.randrange(1000000):06}_{i}": definition for i, definition in enumerate(definitions)
    }
    suitable = [
        name
        for name, definition in tools.items()
        if all(definition["attributes"].get(key) == value for key, value in constraints.items())
        and all(key in arguments for key in definition["required"])
    ]
    assert len(suitable) == 1
    return (
        {"constraints": constraints, "available_arguments": arguments, "tools": tools},
        {
            "name": suitable[0],
            "arguments": {key: arguments[key] for key in tools[suitable[0]]["required"]},
        },
        'これはテキストだけのAPI選択問題で、実際には呼び出しません。constraintsの全属性に厳密に一致し、requiredの全引数をavailable_argumentsから供給できる唯一のAPIを選択してください。全引数の型はstring。引数の推測・変換・補完は禁止です。API名自体に意味はありません。{"name":API名,"arguments":必須引数だけを値とともに含むオブジェクト}で答えてください。余分な引数は出力しません。',
        {
            "tool_count": len(tools),
            "argument_count": argument_count,
            "constraints": attribute_count,
        },
    )


def registry_tree() -> list[dict[str, Any]]:
    tree = []
    for id, name in CATEGORIES.items():
        generators = [g for g in REGISTRY.values() if g.category_id == id]
        subs = sorted({g.subcategory_id for g in generators})
        tree.append(
            {
                "id": id,
                "name": name,
                "status": "verified"
                if any(g.status == "verified" for g in generators)
                else "experimental"
                if any(g.status == "experimental" for g in generators)
                else "unavailable",
                "subcategories": [
                    {
                        "id": sub,
                        "name": sub,
                        "generators": [g.metadata() for g in generators if g.subcategory_id == sub],
                    }
                    for sub in subs
                ],
            }
        )
    return tree


from llm_benchmark.generators_extra import register_extra  # noqa: E402

register_extra(register, size)

from llm_benchmark.generators_language import register_language  # noqa: E402
from llm_benchmark.generators_reasoning import register_reasoning  # noqa: E402
from llm_benchmark.generators_systems import register_systems  # noqa: E402

register_language(register, size)
register_reasoning(register, size)
register_systems(register, size)
