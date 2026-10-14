"""Profile deterministic set construction in fresh processes; never invokes a model.

Run: uv run python scripts/profile_sets.py --counts 100 1000 8000
The explicit legacy selection keeps comparisons stable as the registry expands.
"""

import argparse
import json
import platform
import subprocess
import sys
import time

OLD_IDS = [
    "algorithm.knapsack",
    "algorithm.path",
    "code.debug",
    "code.trace",
    "context.ledger",
    "cs.lru",
    "cs.transactions",
    "data.aggregate",
    "data.join",
    "dialogue.state",
    "instruction.format",
    "language.scope",
    "logic.boolean",
    "logic.order",
    "math.crt",
    "math.expression",
    "math.linear",
    "math.median",
    "planning.schedule",
    "reading.evidence",
    "robust.consistency",
    "spatial.rotation",
    "temporal.offset",
    "tool.select",
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--counts", nargs="+", type=int, default=[100, 1000, 8000])
    parser.add_argument("--fixed-ratio", type=float, default=0)
    parser.add_argument(
        "--selection", choices=["legacy-24", "math.expression"], default="math.expression"
    )
    parser.add_argument("--worker", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker is None:
        for count in args.counts:
            subprocess.run(
                [
                    sys.executable,
                    __file__,
                    "--worker",
                    str(count),
                    "--fixed-ratio",
                    str(args.fixed_ratio),
                    "--selection",
                    args.selection,
                ],
                check=True,
            )
        return
    from llm_benchmark.domain import SetConfig
    from llm_benchmark.sets import build_set

    started = time.perf_counter()
    result = build_set(
        SetConfig(
            generator_ids=OLD_IDS if args.selection == "legacy-24" else [args.selection],
            count=args.worker,
            seed=42,
            fixed_ratio=args.fixed_ratio,
        )
    )
    elapsed = time.perf_counter() - started
    if sys.platform == "win32":
        import psutil

        peak_bytes = psutil.Process().memory_info().peak_wset
    else:
        import resource

        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        peak_bytes = peak if sys.platform == "darwin" else peak * 1024
    print(
        json.dumps(
            {
                "python": platform.python_version(),
                "platform": platform.platform(),
                "count": args.worker,
                "seed": 42,
                "fixed_ratio": args.fixed_ratio,
                "selection": args.selection,
                "elapsed_seconds": round(elapsed, 6),
                "peak_rss_bytes": peak_bytes,
                "set_hash": result.set_hash,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
