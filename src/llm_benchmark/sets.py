import math
import random
from datetime import UTC, datetime
from importlib.resources import files

from llm_benchmark.domain import FrozenSet, Problem, SetConfig, digest
from llm_benchmark.generators import REGISTRY


class SetUnavailable(ValueError):
    pass


def fixed_catalogue() -> list[Problem]:
    resource = files("llm_benchmark").joinpath("fixed_catalogue.jsonl")
    return [
        Problem.model_validate_json(line)
        for line in resource.read_text(encoding="utf-8").splitlines()
        if line
    ]


def build_set(config: SetConfig) -> FrozenSet:
    if config.evaluation_mode != "text":
        raise SetUnavailable("独立したツール/コード評価の作成画面を使用してください")
    if config.profile.lower().startswith("standard"):
        raise SetUnavailable(
            "16分野の検証条件が未達のため正式Standardは利用できません。Previewを選んでください"
        )
    unknown = set(config.generator_ids) - REGISTRY.keys()
    if unknown:
        raise SetUnavailable(f"未登録の生成器: {', '.join(sorted(unknown))}")
    chosen = [REGISTRY[id] for id in sorted(config.generator_ids)]
    if any(g.status != "verified" for g in chosen):
        raise SetUnavailable("Previewの既定評価はverified生成器のみを使用します")
    rng = random.Random(config.seed)
    allocations = list(chosen)  # Every selected generator receives at least one question.
    category_counts = {
        g.category_id: sum(x.category_id == g.category_id for x in allocations) for g in chosen
    }
    generator_counts = {g.id: 1 for g in chosen}
    while len(allocations) < config.count:
        cat = min(category_counts, key=lambda c: (category_counts[c], c))
        options = [g for g in chosen if g.category_id == cat]
        g = min(options, key=lambda g: (generator_counts[g.id], g.id))
        allocations.append(g)
        category_counts[cat] += 1
        generator_counts[g.id] += 1
    rng.shuffle(allocations)
    fixed_count = math.floor(config.count * config.fixed_ratio + 0.5)
    # Spread fixed origins over the shuffled allocation; never silently replace missing fixed items.
    fixed_indices = set(rng.sample(range(config.count), fixed_count))
    catalogue = fixed_catalogue() if fixed_count else []
    used: set[str] = set()
    problems: list[Problem] = []
    duplicates = 0
    for index, g in enumerate(allocations):
        target = (
            config.difficulty_min
            + (config.difficulty_max - config.difficulty_min) * (index + 0.5) / config.count
        )
        if index in fixed_indices:
            candidates = [
                p
                for p in catalogue
                if p.generator_id == g.id
                and config.difficulty_min <= p.target_difficulty <= config.difficulty_max
                and digest(p.prompt) not in used
            ]
            if not candidates:
                raise SetUnavailable(
                    f"固定問題不足: {g.name} / 難易度{config.difficulty_min}〜{config.difficulty_max}。問題数・範囲・比率を調整してください"
                )
            rng.shuffle(candidates)
            p = min(candidates, key=lambda p: abs(p.target_difficulty - target))
        else:
            for _ in range(100):
                p = g.generate(rng.randrange(2**32), target)
                if digest(p.prompt) not in used:
                    break
                duplicates += 1
            else:
                raise SetUnavailable(f"重複を避けて十分な問題を作れません: {g.name}")
        used.add(digest(p.prompt))
        problems.append(p)
    rng.shuffle(problems)
    categories = sorted({p.category_id for p in problems})
    weights = {p.problem_id: 1 / len(categories) / category_counts[p.category_id] for p in problems}
    warnings = [
        "Preview: 難易度は未校正。正式なStandardスコアではありません。",
        "固定問題は公開されています。学習データ汚染の可能性があります。",
        f"検証済みの選択範囲: {len(categories)}/16大カテゴリ。未選択・未実装分野は評価していません。",
        "総合正答率はカテゴリ均等重み。固定/動的の内訳は実問題数に基づきます。",
    ]
    requested = config.count * config.fixed_ratio
    if fixed_count != requested:
        warnings.append(f"固定問題数を{requested:g}から{fixed_count}へ整数化しました。")
    payload = {
        "config": config.model_dump(),
        "problems": [p.model_dump() for p in problems],
        "weights": weights,
        "profile_version": "Preview v1",
        "grader_version": "1.0.0",
    }
    hash = digest(payload)
    return FrozenSet(
        set_id=f"set-{hash[:24]}",
        set_hash=hash,
        config=config,
        problems=problems,
        weights=weights,
        warnings=warnings,
        duplicate_stats={
            "surface_rejected": duplicates,
            "adopted": len(problems),
            "structures": len({p.template for p in problems}),
            "repeated_structures": len(problems) - len({p.template for p in problems}),
        },
        created_at=datetime.now(UTC).isoformat(),
    )


def presets() -> list[dict]:
    all_ids = list(REGISTRY)
    return [
        {
            "id": "preview-standard-v1",
            "name": "総合・標準（Preview）",
            "description": "正式Standardの前段階。実装済み分野を均等評価。",
            "config": SetConfig(
                generator_ids=all_ids, count=100, profile="preview-standard-v1"
            ).model_dump(),
        },
        {
            "id": "preview-wide-v1",
            "name": "幅広く評価",
            "description": "検証済みの全構造をカバー。",
            "config": SetConfig(
                generator_ids=all_ids, count=56, profile="preview-wide-v1"
            ).model_dump(),
        },
        {
            "id": "preview-deep-v1",
            "name": "特定分野を深掘り",
            "description": "数学の複数構造を重点的に評価。",
            "config": SetConfig(
                generator_ids=[g.id for g in REGISTRY.values() if g.category_id == "01"],
                count=60,
                profile="preview-deep-v1",
            ).model_dump(),
        },
        {
            "id": "preview-quick-v1",
            "name": "クイック",
            "description": "少量の代表問題で動作を確認。",
            "config": SetConfig(generator_ids=all_ids, count=max(20, len(all_ids))).model_dump(),
        },
        {
            "id": "custom",
            "name": "カスタム",
            "description": "生成器と配分を調整。",
            "config": SetConfig(
                generator_ids=all_ids, count=max(20, len(all_ids)), profile="custom", custom=True
            ).model_dump(),
        },
    ]
