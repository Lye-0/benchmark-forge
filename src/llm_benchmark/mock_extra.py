"""Test-only rule solvers independent of generator reference implementations."""

import itertools
import re


def solve(task, data):
    if task == "math.crt":
        return next(
            x
            for x in range(data["upper_exclusive"])
            if all(x % m == v for m, v in data["conditions"])
        )
    if task == "algorithm.knapsack":
        return max(
            sum(v for (w, v), used in zip(data["items"], bits, strict=True) if used)
            for bits in itertools.product([False, True], repeat=len(data["items"]))
            if sum(w for (w, v), used in zip(data["items"], bits, strict=True) if used)
            <= data["capacity"]
        )
    if task == "cs.lru":
        cache: list[int] = []
        count = 0
        for key in data["accesses"]:
            if key in cache:
                cache.remove(key)
            else:
                count += 1
            cache.append(key)
            cache = cache[-data["capacity"] :]
        return count
    if task == "cs.transactions":
        state, staged = data["initial"].copy(), {}
        for action in data["events"]:
            if action[0] == "begin":
                staged = state.copy()
            elif action[0] == "set":
                staged[action[1]] = action[2]
            elif action[0] == "commit":
                state = staged.copy()
        return state
    if task == "language.scope":
        return sorted(s.split("は")[0] for s in data["sentences"] if "しないわけではない" in s)
    if task == "reading.evidence":
        first = next(d for d in data["documents"] if d["text"].startswith(data["person"] + "の"))
        item = first["text"].split("は")[1].rstrip("。")
        second = next(d for d in data["documents"] if d["text"].startswith(item + "の"))
        return {
            "place": second["text"].split("は")[1].rstrip("。"),
            "evidence": [first["id"], second["id"]],
        }
    if task == "context.ledger":
        return sum(
            int(m[2])
            for m in re.finditer(r"(口座\d+)の残高を([+-]\d+)変更", data["passage"])
            if m[1] == data["target"]
        )
    if task == "planning.schedule":
        remaining = set(range(len(data["durations"])))
        completed: dict[int, int] = {}
        while remaining:
            for node in sorted(remaining):
                parents = [a for a, b in data["dependencies"] if b == node]
                if all(p in completed for p in parents):
                    completed[node] = (
                        max([completed[p] for p in parents], default=0) + data["durations"][node]
                    )
                    remaining.remove(node)
        return max(completed.values())
    if task == "robust.consistency":
        possible = set(range(data["upper_inclusive"] + 1))
        for m, v in data["observations"]:
            possible &= set(range(v, data["upper_inclusive"] + 1, m))
        return {
            "status": "unique"
            if len(possible) == 1
            else "insufficient"
            if possible
            else "inconsistent",
            "value": next(iter(possible)) if len(possible) == 1 else None,
        }
    if task == "spatial.rotation":
        point = data["start"][:]
        for action in data["operations"]:
            if action[0] == "rotate_ccw":
                point = [
                    sum(a * b for a, b in zip(row, point, strict=True)) for row in [[0, -1], [1, 0]]
                ]
            else:
                point = [a + b for a, b in zip(point, action[1:], strict=True)]
        return point
    raise ValueError("Unsupported test solver")
