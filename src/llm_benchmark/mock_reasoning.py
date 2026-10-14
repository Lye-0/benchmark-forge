"""Test-only solvers using algorithms independent of generation references."""

import itertools
from fractions import Fraction

SUPPORTED_IDS = frozenset(
    {
        "math.probability",
        "math.linear_system",
        "math.polygon_area",
        "logic.implication",
        "logic.set_relations",
        "algorithm.reachability",
        "algorithm.minimax",
        "planning.assignment",
        "algorithm.edit_distance",
        "planning.interval_selection",
    }
)


def solve(task, data):
    if task == "math.probability":
        # Sequential sampling distribution, rather than combinations formula.
        distribution = {0: Fraction(1)}
        for drawn in range(data["draws"]):
            updated: dict[int, Fraction] = {}
            for red_used, probability in distribution.items():
                for increment, remaining in [
                    (1, data["red"] - red_used),
                    (0, data["blue"] - (drawn - red_used)),
                ]:
                    if remaining > 0:
                        k = red_used + increment
                        updated[k] = updated.get(k, Fraction(0)) + probability * Fraction(
                            remaining, data["red"] + data["blue"] - drawn
                        )
            distribution = updated
        value = distribution.get(data["target_red"], Fraction(0))
        return {"numerator": value.numerator, "denominator": value.denominator}
    if task == "math.linear_system":
        rows = [
            [Fraction(x) for x in row] + [Fraction(rhs)]
            for row, rhs in zip(data["matrix"], data["rhs"], strict=True)
        ]
        n = len(rows)
        for column in range(n):
            pivot = next(i for i in range(column, n) if rows[i][column])
            rows[column], rows[pivot] = rows[pivot], rows[column]
            scale = rows[column][column]
            rows[column] = [x / scale for x in rows[column]]
            for i in range(n):
                if i != column:
                    factor = rows[i][column]
                    rows[i] = [a - factor * b for a, b in zip(rows[i], rows[column], strict=True)]
        assert all(row[-1].denominator == 1 for row in rows)
        return [int(row[-1]) for row in rows]
    if task == "math.polygon_area":
        # Signed fan triangles also work for concave simple polygons.
        points = data["vertices"]
        ox, oy = points[0]
        total = 0
        for i in range(1, len(points) - 1):
            ax, ay = points[i][0] - ox, points[i][1] - oy
            bx, by = points[i + 1][0] - ox, points[i + 1][1] - oy
            total += ax * by - ay * bx
        return abs(total)
    if task == "logic.implication":
        # Event driven counters instead of repeated whole-rule fixed points.
        known = set(data["facts"])
        queue = list(known)
        remaining = [len(set(body)) for body, _ in data["rules"]]
        watchers: dict[int, list[int]] = {atom: [] for atom in data["atoms"]}
        for i, (body, _) in enumerate(data["rules"]):
            for atom in set(body):
                watchers[atom].append(i)
        while queue:
            atom = queue.pop()
            for index in watchers[atom]:
                remaining[index] -= 1
                head = data["rules"][index][1]
                if remaining[index] == 0 and head not in known:
                    known.add(head)
                    queue.append(head)
        return sorted(known)
    if task == "logic.set_relations":

        def contains(expression, element):
            if isinstance(expression, str):
                return element in data["sets"][expression]
            op, left, right = expression
            a, b = contains(left, element), contains(right, element)
            return {
                "union": a or b,
                "intersection": a and b,
                "difference": a and not b,
                "xor": a != b,
            }[op]

        domain = sorted({x for values in data["sets"].values() for x in values})
        return [x for x in domain if contains(data["expression"], x)]
    if task == "algorithm.reachability":
        n = data["nodes"]
        paths = [[i == j for j in range(n)] for i in range(n)]
        for a, b in data["edges"]:
            paths[a][b] = True
        for k in range(n):
            for i in range(n):
                for j in range(n):
                    paths[i][j] |= paths[i][k] and paths[k][j]
        return [i for i, connected in enumerate(paths[data["start"]]) if connected]
    if task == "algorithm.minimax":

        def visit(start, width, level):
            if width == 1:
                return data["leaves"][start]
            half = width // 2
            left, right = visit(start, half, level + 1), visit(start + half, half, level + 1)
            return max(left, right) if level % 2 == 0 else min(left, right)

        return visit(0, len(data["leaves"]), 0)
    if task == "planning.assignment":
        return min(
            sum(data["costs"][i][job] for i, job in enumerate(order))
            for order in itertools.permutations(range(len(data["costs"])))
        )
    if task == "algorithm.edit_distance":
        # Shortest path through the edit grid, using unit-cost BFS.
        source, target = data["source"], data["target"]
        from collections import deque

        frontier = deque([(0, 0, 0)])
        visited = set()
        while frontier:
            i, j, cost = frontier.popleft()
            if (i, j) in visited:
                continue
            visited.add((i, j))
            if i == len(source) and j == len(target):
                return cost
            if i < len(source) and j < len(target):
                if source[i] == target[j]:
                    frontier.appendleft((i + 1, j + 1, cost))
                else:
                    frontier.append((i + 1, j + 1, cost + 1))
            if i < len(source):
                frontier.append((i + 1, j, cost + 1))
            if j < len(target):
                frontier.append((i, j + 1, cost + 1))
    if task == "planning.interval_selection":
        best = 0
        jobs = data["jobs"]
        for mask in range(1 << len(jobs)):
            selected = sorted(job for i, job in enumerate(jobs) if mask & (1 << i))
            if all(a[1] <= b[0] for a, b in zip(selected, selected[1:], strict=False)):
                best = max(best, sum(job[2] for job in selected))
        return best
    raise ValueError("Unsupported test solver")
