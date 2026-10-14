"""Independent finite-domain reference solvers; never execute submitted programs."""


def solve(task, data):
    if task == "cs.round_robin":
        jobs = {p["id"]: p.copy() for p in data["processes"]}
        queue = []
        result: dict[str, int] = {}
        time, used, active = 0, 0, None
        while len(result) < len(jobs):
            for key in sorted(jobs):
                if jobs[key]["arrival"] == time:
                    queue.append(key)
            if active is not None:
                if jobs[active]["burst"] == 0:
                    result[active] = time
                    active = None
                elif used == data["quantum"]:
                    queue.append(active)
                    active = None
            if active is None and queue:
                active, used = queue.pop(0), 0
            if active is not None:
                jobs[active]["burst"] -= 1
                used += 1
            time += 1
        return result
    if task == "cs.routing":

        def bits(address):
            return "".join(f"{int(octet):08b}" for octet in address.split("."))

        answer = []
        for destination in data["destinations"]:
            best_length, hop = -1, None
            for route in data["routes"]:
                address, prefix = route["cidr"].split("/")
                length = int(prefix)
                if bits(destination)[:length] == bits(address)[:length] and length > best_length:
                    best_length, hop = length, route["next_hop"]
            answer.append(hop)
        return answer
    if task == "cs.permissions":
        output = []
        for request in data["requests"]:
            file = data["files"][request["file"]]
            grant = file["mode"][2]
            if file["group"] in request["groups"]:
                grant = file["mode"][1]
            if file["owner"] == request["user"]:
                grant = file["mode"][0]
            output.append(
                all(not request["need"] // bit % 2 or grant // bit % 2 for bit in [1, 2, 4])
            )
        return output
    if task == "data.schema":
        valid_indices = []
        for index, value in enumerate(data["records"]):
            pending = [(value, data["schema"])]
            valid = True
            while pending and valid:
                value, rule = pending.pop()
                kind = rule["type"]
                if kind == "object":
                    valid = isinstance(value, dict)
                    if valid:
                        valid = all(k in value for k in rule["required"]) and all(
                            k in rule["properties"] for k in value
                        )
                    if valid:
                        pending.extend((v, rule["properties"][k]) for k, v in value.items())
                elif kind == "array":
                    valid = (
                        isinstance(value, list)
                        and rule["minItems"] <= len(value) <= rule["maxItems"]
                    )
                    if valid:
                        pending.extend((v, rule["items"]) for v in value)
                elif kind == "integer":
                    valid = (
                        type(value) is int and value >= rule["minimum"] and value <= rule["maximum"]
                    )
                elif kind == "string":
                    valid = type(value) is str and value in rule["enum"]
                else:
                    valid = type(value) is bool
            if valid:
                valid_indices.append(index)
        return valid_indices
    if task == "data.antijoin":
        return [
            row["id"]
            for row in data["left"]
            if not any(
                other["enabled"]
                and all(
                    row[k] is not None and other[k] is not None and row[k] == other[k]
                    for k in ["a", "b"]
                )
                for other in data["right"]
            )
        ]
    if task == "code.types":

        def infer(expr):
            if type(expr) is str:
                return data["environment"][expr]
            children = tuple(infer(e) for e in expr[1:])
            allowed: dict[str, dict[tuple[str, ...], str]] = {
                "add": {("int", "int"): "int"},
                "and": {("bool", "bool"): "bool"},
                "eq": {("int", "int"): "bool", ("bool", "bool"): "bool"},
                "if": {("bool", "int", "int"): "int", ("bool", "bool", "bool"): "bool"},
            }
            return allowed[expr[0]].get(children, "error")

        return [infer(expr) for expr in data["expressions"]]
    if task == "code.bug_tests":
        lo, hi = data["lower"], data["upper"]
        detections: dict[str, list[int]] = {name: [] for name in data["variants"]}
        for i, value in enumerate(data["cases"]):
            correct = value in range(lo, hi)
            actual = {
                "lower_strict": value in range(lo + 1, hi),
                "upper_inclusive": value in range(lo, hi + 1),
                "disjunction": not (value < lo and value >= hi),
                "reversed": value in range(hi, lo),
            }
            for name in detections:
                if actual[name] != correct:
                    detections[name].append(i)
        return detections
    if task == "temporal.intersections":
        occupied = [
            set().union(*(set(range(a, b)) for a, b in schedule)) for schedule in data["schedules"]
        ]
        common = sorted(set.intersection(*occupied))
        intervals: list[list[int]] = []
        for minute in common:
            if intervals and intervals[-1][1] == minute:
                intervals[-1][1] += 1
            else:
                intervals.append([minute, minute + 1])
        return intervals
    raise ValueError("Unsupported test solver")
