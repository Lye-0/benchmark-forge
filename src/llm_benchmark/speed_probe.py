"""Separate fixed-text workload; no claim of tokenizer-independent token lengths."""

from datetime import UTC, datetime

from pydantic import Field

from llm_benchmark.domain import AnswerSpec, FrozenSet, Problem, SetConfig, StrictModel, digest


class SpeedConfig(StrictModel):
    input_repetitions: int = Field(default=100, ge=1, le=2000)
    output_repetitions: int = Field(default=32, ge=1, le=512)
    repetitions: int = Field(default=3, ge=1, le=20)


def build_speed_probe(config: SpeedConfig) -> FrozenSet:
    problems = []
    for i in range(config.repetitions):
        prompt = (
            f"速度測定 {i + 1}。次の資料を読んだ後、xを{config.output_repetitions}個、半角空白1文字で区切って出力してください。説明は禁止。\n資料: "
            + ("sample " * config.input_repetitions)
        )
        expected = " ".join(["x"] * config.output_repetitions)
        content = digest({"prompt": prompt, "expected": expected})
        problems.append(
            Problem(
                problem_id="p-" + content[:24],
                generator_id="speed.fixed-text",
                generator_version="1.0.0",
                category_id="07",
                subcategory_id="専用速度試験",
                tags=["速度測定"],
                seed=0,
                target_difficulty=0,
                prompt=prompt,
                answer_spec=AnswerSpec(expected=expected, type="text"),
                grading_type="text",
                origin="fixed",
                template="speed-fixed-text",
                features=config.model_dump(),
                content_hash=content,
            )
        )
    settings = SetConfig(
        generator_ids=["speed.fixed-text"],
        count=len(problems),
        fixed_ratio=1,
        profile="speed-probe-v1",
        custom=True,
    )
    weights = {p.problem_id: 1 / len(problems) for p in problems}
    hash = digest(
        {
            "config": settings.model_dump(),
            "problems": [p.model_dump() for p in problems],
            "weights": weights,
            "profile": "Speed probe v1",
        }
    )
    return FrozenSet(
        set_id="set-" + hash[:24],
        set_hash=hash,
        config=settings,
        problems=problems,
        weights=weights,
        profile_version="Speed probe v1",
        created_at=datetime.now(UTC).isoformat(),
        metadata={
            "purpose": "speed-only",
            "length_policy": "fixed text, token counts vary with tokenizer",
            "workload": config.model_dump(),
        },
        warnings=[
            "能力評価とは別の専用速度試験です。正答率は出力長遵守の確認のみ。",
            "入力文字列・要求出力を固定。モデル間でトークン数が同じとは限りません。",
            "打切り・短い出力は要求長未達として扱います。cold/warm条件を揃えてください。",
        ],
        duplicate_stats={"adopted": len(problems)},
    )
