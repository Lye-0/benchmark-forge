import asyncio
import json
import os
from pathlib import Path

import typer

from llm_benchmark.domain import SetConfig
from llm_benchmark.generators import REGISTRY, registry_tree
from llm_benchmark.reports import export_report
from llm_benchmark.runner import Scheduler, summarize
from llm_benchmark.sets import build_set
from llm_benchmark.storage import Store

app = typer.Typer(help="Benchmark Forge / ローカルで再現可能なLLM評価", no_args_is_help=True)


def store() -> Store:
    return Store(Path(os.environ.get("FORGE_DATA_DIR", ".benchmark-forge")))


@app.command()
def generators():
    """登録された16カテゴリと検証済み生成器を表示。"""
    typer.echo(json.dumps(registry_tree(), ensure_ascii=False, indent=2))


@app.command()
def generate(
    count: int = 20,
    seed: int = 42,
    fixed_ratio: float = 0.5,
    difficulty_min: float = 0,
    difficulty_max: float = 100,
    generators: str = "",
    output: Path | None = None,
):
    """問題セットを確定・保存（出力ファイルは参照解答を含むためモデルに渡さない）。"""
    try:
        ids = generators.split(",") if generators else list(REGISTRY)
        frozen = build_set(
            SetConfig(
                generator_ids=ids,
                count=count,
                seed=seed,
                fixed_ratio=fixed_ratio,
                difficulty_min=difficulty_min,
                difficulty_max=difficulty_max,
            )
        )
        store().save_set(frozen)
        if output:
            with output.open("x") as file:
                file.write(frozen.model_dump_json(indent=2))
        typer.echo(
            json.dumps(
                {
                    "set_id": frozen.set_id,
                    "set_hash": frozen.set_hash,
                    "count": len(frozen.problems),
                    "warnings": frozen.warnings,
                },
                ensure_ascii=False,
            )
        )
    except (ValueError, FileExistsError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def run(set_id: str, models: str = "mock-reference"):
    """同一の確定セットをモデルごとに順次評価。Mockはソフトウェア診断専用。"""

    async def execute():
        db = store()
        scheduler = Scheduler(db)
        scheduler.start()
        try:
            ids = scheduler.create(set_id, models.split(","))
            await scheduler.queue.join()
            for id in ids:
                typer.echo(json.dumps(summarize(db, id, detail=False), ensure_ascii=False))
        finally:
            await scheduler.close()

    try:
        asyncio.run(execute())
    except (ValueError, KeyError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def report(run_id: str, format: str = "markdown", output: Path | None = None):
    """CSV/JSONL/Markdownを出力。既存ファイルは上書きしない。"""
    try:
        content, _ = export_report(summarize(store(), run_id), format)
        if output:
            with output.open("x") as file:
                file.write(content)
        else:
            typer.echo(content)
    except (ValueError, KeyError, FileExistsError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def serve(port: int = int(os.environ.get("FORGE_API_PORT", "8000"))):
    """APIおよびビルド済みUIを127.0.0.1で起動。"""
    import uvicorn

    from llm_benchmark.api import create_app

    if not 1 <= port <= 65535:
        raise typer.BadParameter("ポートは1〜65535です")
    uvicorn.run(create_app(), host="127.0.0.1", port=port)


if __name__ == "__main__":
    app()
