"""Ten bounded, deterministic reasoning families with exact references."""

import math
from fractions import Fraction
from functools import lru_cache
from typing import Any


def register_reasoning(register, size):
    @register(
        "math.probability", "01", "確率", "非復元抽出の厳密確率", "hypergeometric-exact", "json"
    )
    def probability(r, d):
        red, blue = r.randint(3, size(d, 20, 60)), r.randint(3, size(d, 20, 60))
        draws = r.randint(size(d, 2, 5), min(red + blue - 1, size(d, 2, 8)))
        target = r.randint(max(0, draws - blue), min(red, draws))
        value = Fraction(
            math.comb(red, target) * math.comb(blue, draws - target), math.comb(red + blue, draws)
        )
        return (
            {"red": red, "blue": blue, "draws": draws, "target_red": target},
            {"numerator": value.numerator, "denominator": value.denominator},
            '赤red個、青blue個の玉から、各玉が等確率となるようdraws個を戻さず抽出します。赤がちょうどtarget_red個となる確率を既約分数のJSON {"numerator":分子,"denominator":正の分母}で答えてください。',
            {
                "population": red + blue,
                "draws": draws,
                "sample_space": math.comb(red + blue, draws),
            },
        )

    @register(
        "math.linear_system",
        "01",
        "線形代数",
        "整数係数連立方程式",
        "invertible-linear-system",
        "json",
    )
    def linear_system(r, d):
        n = size(d, 2, 5)
        matrix = [[int(i == j) for j in range(n)] for i in range(n)]
        operations = size(d, 3, 18)
        for _ in range(operations):
            a, b = r.sample(range(n), 2)
            factor = r.choice([-2, -1, 1, 2])
            matrix[a] = [x + factor * y for x, y in zip(matrix[a], matrix[b], strict=True)]
        answer = [r.randint(-9, 9) for _ in range(n)]
        rhs = [sum(a * x for a, x in zip(row, answer, strict=True)) for row in matrix]
        return (
            {"matrix": matrix, "rhs": rhs},
            answer,
            "matrixの各行を係数、rhsの同じ添字を右辺とする連立一次方程式matrix・x=rhsを解いてください。一意な整数解が存在します。変数を列の順に並べたJSON配列を答えてください。",
            {
                "variables": n,
                "row_operations": operations,
                "max_coefficient": max(abs(x) for row in matrix for x in row),
            },
        )

    @register(
        "math.polygon_area", "01", "幾何", "格子多角形の面積", "simple-polygon-shoelace", "number"
    )
    def polygon_area(r, d):
        n = size(d, 3, 9)
        xs = sorted(r.sample(range(-30, 31), n))
        points = [[x, r.randint(1, 15)] for x in xs]
        points += [[x, -r.randint(1, 15)] for x in reversed(xs)]
        shift = r.randrange(len(points))
        points = points[shift:] + points[:shift]
        if r.getrandbits(1):
            points.reverse()
        double_area = abs(
            sum(
                a[0] * b[1] - b[0] * a[1]
                for a, b in zip(points, points[1:] + points[:1], strict=True)
            )
        )
        return (
            {"vertices": points},
            double_area,
            "verticesは自己交差しない多角形の頂点を周に沿って並べた[x,y]配列です。最後から最初へも辺があります。面積の2倍を整数で答えてください。",
            {"vertices": len(points), "coordinate_span": xs[-1] - xs[0]},
        )

    @register(
        "logic.implication", "02", "含意", "複数前提規則の閉包", "horn-forward-closure", "json"
    )
    def implication(r, d):
        n = size(d, 5, 16)
        rules: list[list[Any]] = [[[0, 1], 2]]
        facts = [0, 1]
        for node in range(3, n):
            premises = r.sample(range(node), r.randint(1, min(node, 3)))
            rules.append([premises, node])
        for _ in range(size(d, 1, 12)):
            rules.append([r.sample(range(n), r.randint(1, 3)), r.randrange(n)])
        # Remove some links so seeds include both reachable and unsupported atoms.
        rules = [rule for i, rule in enumerate(rules) if i == 0 or r.random() > 0.25]
        r.shuffle(rules)
        known = set(facts)
        while True:
            expanded = known | {head for body, head in rules if set(body) <= known}
            if expanded == known:
                break
            known = expanded
        return (
            {"atoms": list(range(n)), "facts": facts, "rules": rules},
            sorted(known),
            "命題は整数ID。factsは初期に真と確定した命題。rulesの[前提ID配列,結論ID]は、全前提が真と確定した時だけ結論を追加する規則です。逆・対偶は使いません。追加不能になるまで適用し、初期factsを含む全確定IDを昇順のJSON配列で答えてください。",
            {"atoms": n, "rules": len(rules), "max_premises": max(len(body) for body, _ in rules)},
        )

    @register(
        "logic.set_relations", "02", "集合", "集合演算の合成", "finite-set-expression", "json"
    )
    def set_relations(r, d):
        universe = list(range(size(d, 6, 24)))
        sets = {name: [x for x in universe if r.random() < 0.5] for name in ["A", "B", "C", "D"]}
        expression: Any = "A"
        value = set(sets["A"])
        operations = size(d, 2, 7)
        for _ in range(operations):
            op, name = (
                r.choice(["union", "intersection", "difference", "xor"]),
                r.choice(list(sets)),
            )
            expression = [op, expression, name]
            other = set(sets[name])
            value = {
                "union": value | other,
                "intersection": value & other,
                "difference": value - other,
                "xor": value ^ other,
            }[op]
        return (
            {"sets": sets, "expression": expression},
            sorted(value),
            "expressionの文字列はsets内の集合名、[演算,左,右]は再帰的な集合式です。union=和、intersection=共通部分、difference=左から右を除く差、xor=片方だけに属する対称差。結果の要素を昇順のJSON配列で答えてください。",
            {"universe_size": len(universe), "operations": operations, "nesting_depth": operations},
        )

    @register(
        "algorithm.reachability",
        "03",
        "グラフ",
        "有向グラフの到達可能性",
        "directed-reachability",
        "json",
    )
    def reachability(r, d):
        n = size(d, 5, 20)
        labels = r.sample(range(n), n)
        reachable_count = r.randint(size(d, 3, 8), n - 1)
        reachable, blocked = labels[:reachable_count], labels[reachable_count:]
        # A randomly labelled path guarantees multi-hop deductions. Back edges
        # add cycles; no edge exits the reachable component. Incoming edges
        # from blocked vertices make edge direction consequential.
        edge_set = set(zip(reachable, reachable[1:], strict=False))
        for i, a in enumerate(reachable):
            for b in reachable[:i]:
                if r.random() < 0.25:
                    edge_set.add((a, b))
        for a in blocked:
            for b in labels:
                if a != b and r.random() < 0.3:
                    edge_set.add((a, b))
        edge_set.add((r.choice(blocked), r.choice(reachable)))
        edges = [list(edge) for edge in sorted(edge_set)]
        r.shuffle(edges)
        start = reachable[0]
        visited, pending = {start}, [start]
        while pending:
            node = pending.pop()
            for a, b in edges:
                if a == node and b not in visited:
                    visited.add(b)
                    pending.append(b)
        return (
            {"nodes": n, "edges": edges, "start": start},
            sorted(visited),
            "頂点IDは0以上nodes未満。edgesの[a,b]はaからbへの有向辺です。startから0本以上の辺をたどって到達できる全頂点（start自身を含む）を昇順のJSON配列で答えてください。",
            {"nodes": n, "edges": len(edges), "required_hops": reachable_count - 1},
        )

    @register(
        "algorithm.minimax",
        "03",
        "ゲーム木",
        "交互手番の最適値",
        "alternating-minimax-tree",
        "number",
    )
    def minimax(r, d):
        depth = size(d, 2, 6)
        values = [r.randint(-30, 30) for _ in range(2**depth)]
        layer = values[:]
        for level in reversed(range(depth)):
            choose = max if level % 2 == 0 else min
            layer = [choose(layer[i : i + 2]) for i in range(0, len(layer), 2)]
        return (
            {"depth": depth, "leaves": values},
            layer[0],
            "完全二分ゲーム木で根の深さは0、葉の深さはdepthです。leavesは葉を左から右へ並べた利得。偶数深さの手番は利得最大化、奇数深さは最小化し、各手番は左右の子の一方を選びます。両者が最適に選ぶときの根の利得を整数で答えてください。",
            {"depth": depth, "leaves": len(values), "decision_nodes": len(values) - 1},
        )

    @register(
        "planning.assignment",
        "13",
        "資源割当",
        "一対一割当の最小費用",
        "bipartite-minimum-assignment",
        "number",
    )
    def assignment(r, d):
        n = size(d, 3, 7)
        costs = [[r.randint(1, 40) for _ in range(n)] for _ in range(n)]

        @lru_cache(None)
        def best(worker, used):
            if worker == n:
                return 0
            return min(
                costs[worker][job] + best(worker + 1, used | (1 << job))
                for job in range(n)
                if not used & (1 << job)
            )

        return (
            {"costs": costs},
            best(0, 0),
            "costs[i][j]は作業者iに仕事jを割り当てる費用。作業者と仕事は同数で、各作業者にちょうど1仕事、各仕事にちょうど1人を割り当てます。合計費用の最小値だけを整数で答えてください。割当自体が複数通りでも最小費用は一意です。",
            {"workers": n, "jobs": n, "possible_assignments": math.factorial(n)},
        )

    @register(
        "algorithm.edit_distance",
        "03",
        "動的計画法",
        "文字列の最小編集距離",
        "levenshtein-unit-cost",
        "number",
    )
    def edit_distance(r, d):
        n = size(d, 4, 14)
        source = "".join(r.choices("abcde", k=n))
        target = "".join(r.choices("abcde", k=r.randint(max(1, n - 2), n + 2)))
        previous = list(range(len(target) + 1))
        for i, a in enumerate(source, 1):
            current = [i]
            for j, b in enumerate(target, 1):
                current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (a != b)))
            previous = current
        return (
            {"source": source, "target": target},
            previous[-1],
            "sourceをtargetに変える最小費用を整数で答えてください。許される操作は1文字の挿入・削除・別文字への置換で、各費用は1です。文字の入替えは1操作ではできません。",
            {
                "source_length": len(source),
                "target_length": len(target),
                "dp_cells": (len(source) + 1) * (len(target) + 1),
            },
        )

    @register(
        "planning.interval_selection",
        "13",
        "スケジュール",
        "重複しない予約の最大報酬",
        "weighted-interval-selection",
        "number",
    )
    def interval_selection(r, d):
        jobs = []
        for _ in range(size(d, 4, 14)):
            start = r.randrange(size(d, 10, 35))
            jobs.append([start, start + r.randint(1, 10), r.randint(1, 40)])
        ordered = sorted(jobs, key=lambda job: job[1])
        best = [0]
        for i, (start, _, reward) in enumerate(ordered):
            compatible = max((j + 1 for j in range(i) if ordered[j][1] <= start), default=0)
            best.append(max(best[-1], best[compatible] + reward))
        return (
            {"jobs": jobs},
            best[-1],
            "jobsの各項目は[開始時刻,終了時刻,報酬]。1人で、時間区間が重ならない仕事だけを選びます。ある仕事の終了と次の開始が同時刻なら両方可能です。仕事は中断不可・各項目高々1回。得られる報酬合計の最大値を整数で答えてください。",
            {"jobs": len(jobs), "candidate_subsets": 2 ** len(jobs)},
        )
