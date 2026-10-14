"""Regenerate versioned fixed items and append 20 deterministic items per new generator.

Existing IDs, seeds, order and bytes are retained when a generator is unchanged.
A changed output without a generator version bump is rejected.
"""

from pathlib import Path

from llm_benchmark.domain import Problem
from llm_benchmark.generators import REGISTRY


def main():
    path = Path(__file__).resolve().parents[1] / "src/llm_benchmark/fixed_catalogue.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    output, present = [], set()
    for line in lines:
        old = Problem.model_validate_json(line)
        present.add(old.generator_id)
        generator = REGISTRY[old.generator_id]
        new = generator.generate(old.seed, old.target_difficulty, "fixed")
        if new == old:
            output.append(line)
        elif old.generator_version == generator.version:
            raise ValueError(f"Version bump required: {generator.id}")
        else:
            output.append(new.model_dump_json())
    for index, generator in enumerate(REGISTRY.values()):
        if generator.id in present or generator.status != "verified":
            continue
        for band, difficulty in enumerate([0, 25, 50, 75, 100]):
            for sample in range(4):
                seed = 100000 + index * 1000 + band * 100 + sample
                output.append(generator.generate(seed, difficulty, "fixed").model_dump_json())
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    print(f"Fixed catalogue: {len(output)} problems")


if __name__ == "__main__":
    main()
