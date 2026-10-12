"""Private, data-only JSONL import. Never evaluate code, URLs, archives or paths."""

import json
from datetime import UTC, datetime
from typing import Literal

from pydantic import Field

from llm_benchmark.domain import (
    AnswerSpec,
    FrozenSet,
    Problem,
    SetConfig,
    StrictModel,
    canonical,
    digest,
)
from llm_benchmark.grading import grade


class Header(StrictModel):
    format: Literal["forge-holdout-v1"] = Field(alias="schema")
    name: str = Field(min_length=1, max_length=100)
    source: str = Field(min_length=1, max_length=300)
    license: str = Field(min_length=1, max_length=300)
    visibility: Literal["private"] = "private"


class Item(StrictModel):
    prompt: str = Field(min_length=1, max_length=100000)
    category_id: str = Field(pattern=r"^(0[1-9]|1[0-6])$")
    target_difficulty: float = Field(ge=0, le=100)
    answer_spec: AnswerSpec
    tags: list[str] = Field(default_factory=list, max_length=20)


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def constant(value):
        raise ValueError("non-finite")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=constant)


def import_holdout(text: str) -> FrozenSet:
    if len(text.encode("utf-8")) > 900_000:
        raise ValueError("holdoutは900KB以下にしてください")
    lines = [line for line in text.splitlines() if line.strip()]
    if not 2 <= len(lines) <= 1001:
        raise ValueError("先頭のメタデータ行と1〜1000件の問題行が必要です")
    try:
        header = Header.model_validate(strict_json(lines[0]))
        items = [Item.model_validate(strict_json(line)) for line in lines[1:]]
        for item in items:
            spec = item.answer_spec
            if spec.type == "number" and (
                isinstance(spec.expected, bool) or not isinstance(spec.expected, (int, float))
            ):
                raise ValueError("number expected")
            if spec.type == "text" and not isinstance(spec.expected, str):
                raise ValueError("text expected")
            rendered = spec.expected if spec.type == "text" else canonical(spec.expected)
            if not grade(rendered, spec).correct:
                raise ValueError("invalid reference answer")
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        # Pydantic errors include input values; never echo private input in errors.
        raise ValueError("holdoutの形式・分類・解答型を確認してください（内容は非表示）") from exc
    if len({digest(item.prompt) for item in items}) != len(items):
        raise ValueError("同一問題文の重複があります")
    problems = []
    for item in items:
        content_hash = digest(item.model_dump())
        problems.append(
            Problem(
                problem_id="p-" + content_hash[:24],
                generator_id="holdout.import",
                generator_version="1.0.0",
                category_id=item.category_id,
                subcategory_id="私有holdout",
                tags=item.tags,
                seed=0,
                target_difficulty=item.target_difficulty,
                prompt=item.prompt,
                answer_spec=item.answer_spec,
                grading_type=item.answer_spec.type,
                verification="experimental",
                origin="fixed",
                template="private-import",
                features={},
                provenance=canonical(header.model_dump(by_alias=True)),
                content_hash=content_hash,
            )
        )
    categories = {p.category_id for p in problems}
    weights = {
        p.problem_id: 1 / len(categories) / sum(q.category_id == p.category_id for q in problems)
        for p in problems
    }
    config = SetConfig(
        generator_ids=["holdout.import"],
        count=len(problems),
        fixed_ratio=1,
        profile="private-holdout-v1",
        custom=True,
    )
    payload = {
        "config": config.model_dump(),
        "problems": [p.model_dump() for p in problems],
        "weights": weights,
        "metadata": header.model_dump(by_alias=True),
        "grader_version": "1.0.0",
        "profile_version": "Private holdout v1",
    }
    hash = digest(payload)
    return FrozenSet(
        set_id="set-" + hash[:24],
        set_hash=hash,
        config=config,
        problems=problems,
        profile_version="Private holdout v1",
        weights=weights,
        metadata=header.model_dump(by_alias=True),
        warnings=[
            "私有holdout: 参照解答の意味的正しさ・出典の権利は取り込み元の責任で確認してください。",
            "難易度は自己申告・未校正。公開Standardとは比較できません。",
            "結果とエクスポートには私有問題・参照解答を含みます。外部へ自動送信しません。",
        ],
        duplicate_stats={"surface_rejected": 0, "adopted": len(problems)},
        created_at=datetime.now(UTC).isoformat(),
    )
