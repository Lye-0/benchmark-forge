"""Independent parsers for the constructed-language test tasks."""

import re


def solve(task, data):
    if task == "language.quantifiers":
        result = []
        for statement in data["statements"]:
            match = re.search(r"G\d+", statement)
            assert match is not None
            group = match[0]
            ready = sum(data["groups"][group])
            total = len(data["groups"][group])
            if statement.startswith("Every"):
                result.append(ready == total)
            elif statement.startswith("No") and not statement.startswith("Not"):
                result.append(ready == 0)
            else:
                result.append(ready < total)
        return result
    if task == "language.reference":
        result = []
        for paragraph in data["paragraphs"]:
            previous: list[str] = []
            for sentence in paragraph:
                subject, obj = sentence.removesuffix("を訪ねた。").split("は")
                if subject in ("前者", "後者"):
                    subject = previous[subject == "後者"]
                previous = [subject, obj]
            result.append(previous[0])
        return result
    if task == "reading.entailment":
        facts = dict(re.findall(r"(箱\d+)の色は(赤|青|緑)。", data["passage"]))
        result = []
        for statement in data["statements"]:
            match = re.fullmatch(r"(箱\d+)は(赤|青|緑)(である|ではない)。", statement)
            assert match is not None
            box, color, ending = match.groups()
            if box not in facts:
                result.append("unknown")
            else:
                actual = f"{box}は{facts[box]}である。"
                positive = f"{box}は{color}である。"
                truth = actual == positive
                if ending == "ではない":
                    truth = not truth
                result.append("entailed" if truth else "contradicted")
        return result
    if task == "context.policy":
        candidates = {}
        for key, version, days in re.findall(
            r"(規程\d+) / 版(\d+) / 上限(\d+)日。", data["passage"]
        ):
            if key == data["target"] and int(version) <= data["as_of_version"]:
                candidates[int(version)] = int(days)
        version = sorted(candidates)[-1]
        return {"version": version, "days": candidates[version]}
    if task == "instruction.priority":
        for rule in sorted(data["rules"], key=lambda row: row["priority"], reverse=True):
            conditions, outcome = rule["text"].split("なら")
            violations = 0
            for condition in conditions.split("かつ"):
                key, value = condition.split("が")
                violations += data["flags"][key] != (value == "真")
            if not violations:
                return outcome.removesuffix("を選ぶ。")
        return "既定処理"
    if task == "dialogue.correction":
        relevant = [
            turn["text"] for turn in data["turns"] if turn["speaker"] == data["target_speaker"]
        ]
        destination = relevant[-1].split("届け先は")[1].removesuffix("。")
        item = next(
            text.split("の")[0] for text in reversed(relevant) if not text.startswith("訂正:")
        )
        return {"item": item, "destination": destination}
    if task == "robust.injection":
        return [
            {
                "id": doc["id"],
                "code": re.findall(r"^品番: (X[0-9]{4})$", doc["body"], re.MULTILINE)[0],
            }
            for doc in data["documents"]
        ]
    if task == "robust.premise":
        target = data["question"].split("が")[0]
        entry = next(line for line in data["passage"].splitlines() if line.startswith(target + ":"))
        year = re.search(r"年=(\d+)", entry)
        if "未受賞" in entry:
            return {"status": "false_premise", "year": None}
        if year:
            return {"status": "known", "year": int(year[1])}
        return {"status": "insufficient", "year": None}
    raise ValueError("Unsupported test solver")
