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
    count: int = 24,
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
            with output.open("x", encoding="utf-8") as file:
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
            if db.get_set(set_id).config.evaluation_mode == "code":
                await scheduler.sandbox.verify()
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
def report(
    run_id: str, format: str = "markdown", output: Path | None = None, compress: bool = False
):
    """CSV/JSONL/Markdownを出力。既存ファイルは上書きしない。"""
    try:
        content, _ = export_report(summarize(store(), run_id), format)
        if compress and not output:
            raise ValueError("圧縮時は--outputを指定してください")
        if output:
            import gzip

            with (
                gzip.open(output, "xt", encoding="utf-8")
                if compress
                else output.open("x", encoding="utf-8") as file
            ):
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


@app.command("archive")
def archive(run_id: str, output: Path, compress: bool = False):
    """全問題・結果・試行を逐次JSONLへ出力。未回答問題も保持。"""
    import gzip

    from llm_benchmark.reports import stream_jsonl

    db = store()
    try:
        db.run_status(run_id)
        with (
            gzip.open(output, "xt", encoding="utf-8")
            if compress
            else output.open("x", encoding="utf-8") as file
        ):
            for line in stream_jsonl(db, run_id):
                file.write(line)
    except (OSError, ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("archive-split")
def archive_split(
    run_id: str,
    output: Path,
    part_mib: int = typer.Option(64, min=1, max=4096),
    compress: bool = False,
):
    """新規フォルダーへ分割JSONLとSHA-256マニフェストを出力。"""
    from llm_benchmark.archive import split_archive

    try:
        manifest = split_archive(store(), run_id, output, part_mib * 1024 * 1024, compress)
        typer.echo(json.dumps({"parts": len(manifest["parts"]), "records": manifest["records"]}))
    except (OSError, ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("archive-verify")
def archive_verify(directory: Path):
    """分割ファイルの欠落・サイズ・SHA-256を検証（真正性や採点の検証ではない）。"""
    from llm_benchmark.archive import verify_archive

    try:
        typer.echo(json.dumps(verify_archive(directory), ensure_ascii=False))
    except (OSError, ValueError, KeyError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("tool-set")
def tool_set(mode: str = "native-tools", count: int = 5, seed: int = 42):
    """native-tools / agentの独立セットを作成。"""
    from llm_benchmark.tool_eval import ToolConfig, build_tool_set

    frozen = build_tool_set(ToolConfig.model_validate({"mode": mode, "count": count, "seed": seed}))
    store().save_set(frozen)
    typer.echo(frozen.set_id)


@app.command("code-set")
def code_set(count: int = 5, seed: int = 42):
    """隔離採点用のコード生成セットを作成。"""
    from llm_benchmark.code_eval import CodeConfig, build_code_set

    frozen = build_code_set(CodeConfig(count=count, seed=seed))
    store().save_set(frozen)
    typer.echo(frozen.set_id)


@app.command("model-register")
def model_register(path: Path):
    """ローカルJSON設定からモデルを登録。認証情報は含めない。"""
    from llm_benchmark.adapters import validate_endpoint
    from llm_benchmark.domain import ModelConfig

    try:
        with path.open("rb") as file:
            model = ModelConfig.model_validate_json(file.read(10001))
        validate_endpoint(model.endpoint)
        store().save_model(model)
        typer.echo(model.model_id)
    except (OSError, ValueError):
        typer.echo("モデル設定を読み込めません（内容は非表示）", err=True)
        raise typer.Exit(1) from None


@app.command("resume")
def resume(run_id: str, retry: bool = False):
    """停止したランを再開。--retryは失敗のみ再試行し過去の試行を保持。"""

    async def execute():
        db = store()
        scheduler = Scheduler(db)
        scheduler.start()
        try:
            saved = db.run(run_id)
            if db.get_set(saved["set_id"]).config.evaluation_mode == "code":
                check = await scheduler.sandbox.verify()
                if not check["available"]:
                    raise RuntimeError(check["reason"])
            scheduler.control(run_id, "retry" if retry else "resume")
            await scheduler.queue.join()
            typer.echo(json.dumps(summarize(db, run_id, detail=False), ensure_ascii=False))
        finally:
            await scheduler.close()

    try:
        asyncio.run(execute())
    except (ValueError, KeyError, RuntimeError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("calibration")
def calibration(run_id: str, output: Path):
    """実モデルの観測を校正用JSONLへ出力。Mock・未完了ランは拒否。"""
    from llm_benchmark.analysis import calibration_rows

    try:
        rows = calibration_rows(summarize(store(), run_id))
        with output.open("x", encoding="utf-8") as file:
            for row in rows:
                file.write(json.dumps(row, ensure_ascii=False) + "\n")
    except (ValueError, KeyError, OSError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("speed-probe")
def speed_probe(input_repetitions: int = 100, output_repetitions: int = 32, repetitions: int = 3):
    """能力評価と区別した速度試験セットを確定。forge runで評価可能。"""
    from llm_benchmark.speed_probe import SpeedConfig, build_speed_probe

    frozen = build_speed_probe(
        SpeedConfig(
            input_repetitions=input_repetitions,
            output_repetitions=output_repetitions,
            repetitions=repetitions,
        )
    )
    store().save_set(frozen)
    typer.echo(
        json.dumps({"set_id": frozen.set_id, "warnings": frozen.warnings}, ensure_ascii=False)
    )


@app.command("sandbox-check")
def sandbox_check():
    """固定Dockerイメージ上で通信・権限・資源制限を実検証（自動pullなし）。"""
    from llm_benchmark.sandbox import DockerSandbox

    result = asyncio.run(DockerSandbox().verify())
    typer.echo(json.dumps(result, ensure_ascii=False))
    if not result["available"]:
        raise typer.Exit(1)


@app.command("import-holdout")
def holdout_import(path: Path):
    """私有JSONLを検証しローカルDBに確定保存。外部送信なし。"""
    from llm_benchmark.holdout import import_holdout

    try:
        with path.open("rb") as file:
            data = file.read(900_001)
        frozen = import_holdout(data.decode("utf-8"))
        store().save_set(frozen)
        typer.echo(
            json.dumps(
                {
                    "set_id": frozen.set_id,
                    "set_hash": frozen.set_hash,
                    "count": len(frozen.problems),
                }
            )
        )
    except (ValueError, OSError):
        typer.echo(
            "取り込みに失敗しました。JSONL形式・サイズ・読取権限を確認してください", err=True
        )
        raise typer.Exit(1) from None


@app.command("doctor")
def doctor(torch: bool = False):
    """OS/機器構成を診断。--torch時のみPyTorch/CUDAを明示検査。"""
    import platform

    from llm_benchmark.environment import backend_versions, hardware_inventory, torch_status

    report = {"os": platform.system(), **hardware_inventory(), "packages": backend_versions()}
    if torch:
        report["torch"] = torch_status()
    typer.echo(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    app()
