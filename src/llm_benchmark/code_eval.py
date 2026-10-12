"""One code-generation structure; hidden inputs and reference outputs stay out of prompts."""

import random
from datetime import UTC, datetime

from pydantic import Field

from llm_benchmark.domain import AnswerSpec, FrozenSet, Problem, SetConfig, StrictModel, digest


class CodeConfig(StrictModel):
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    count: int = Field(default=5, ge=1, le=100)


def build_code_set(config: CodeConfig) -> FrozenSet:
    rng = random.Random(config.seed)
    problems = []
    for i in range(config.count):
        threshold = rng.randint(-20, 20)
        prompt = f"コード課題: filtered-square-sum\nPython関数 solve(values) を実装してください。整数リストvaluesのうち{threshold}以上の偶数の平方和を返します。空リストの結果は0です。関数定義のコードだけを返し、Markdownや説明は付けないでください。"
        cases = [
            [],
            [threshold, threshold + 1, threshold - 1],
            [-2, 0, 2],
            [rng.randint(-50, 50) for _ in range(50)],
        ]
        outputs = [sum(v * v for v in values if v >= threshold and v % 2 == 0) for values in cases]
        content = digest({"prompt": prompt, "cases": cases, "outputs": outputs, "index": i})
        problems.append(
            Problem(
                problem_id="p-" + content[:24],
                generator_id="code.filtered-square-sum",
                generator_version="1.0.0",
                category_id="04",
                subcategory_id="コード生成",
                tags=["隔離実行"],
                seed=config.seed,
                target_difficulty=30,
                prompt=prompt,
                answer_spec=AnswerSpec(expected=outputs, type="json"),
                grading_type="json",
                origin="dynamic",
                template="code-filtered-square-sum",
                features={"test_count": len(cases)},
                simulation={"cases": cases},
                content_hash=content,
            )
        )
    settings = SetConfig(
        generator_ids=["code.filtered-square-sum"],
        count=config.count,
        seed=config.seed,
        fixed_ratio=0,
        profile="code-preview-v1",
        custom=True,
        evaluation_mode="code",
    )
    weights = {p.problem_id: 1 / len(problems) for p in problems}
    hash = digest(
        {
            "config": settings.model_dump(),
            "problems": [p.model_dump() for p in problems],
            "weights": weights,
            "profile": "Code preview v1",
        }
    )
    return FrozenSet(
        set_id="set-" + hash[:24],
        set_hash=hash,
        config=settings,
        problems=problems,
        weights=weights,
        profile_version="Code preview v1",
        created_at=datetime.now(UTC).isoformat(),
        metadata={"mode": "code", "structure_count": 1},
        warnings=[
            "独立したコード生成評価。値違いを別構造とは数えません。",
            "検証済み使い捨てDockerワーカーがない場合は実行しません。",
        ],
        duplicate_stats={"adopted": len(problems), "structures": 1},
    )


def harness(answer: str, cases: list) -> str:
    # Code and test INPUTS only enter the disposable container. Expected outputs stay in grader.
    return (
        "import json\nnamespace={}\nexec(compile("
        + repr(answer)
        + ',"<candidate>","exec"),namespace)\n'
        'outputs=[namespace["solve"](values) for values in ' + repr(cases) + "]\n"
        "print(json.dumps(outputs,allow_nan=False))\n"
    )
