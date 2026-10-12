import asyncio
import json
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from llm_benchmark.adapters import AdapterError, OllamaAdapter, capabilities, validate_endpoint
from llm_benchmark.domain import ModelConfig, SetConfig, StartRun, StrictModel
from llm_benchmark.generators import REGISTRY, registry_tree
from llm_benchmark.reports import export_report
from llm_benchmark.runner import Scheduler, comparison, summarize
from llm_benchmark.sandbox import sandbox_status
from llm_benchmark.sets import build_set, presets
from llm_benchmark.storage import Store


class SavePreset(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    config: SetConfig


def create_app(data_dir: Path | None = None) -> FastAPI:
    store = Store(data_dir or Path(os.environ.get("FORGE_DATA_DIR", ".benchmark-forge")))
    scheduler = Scheduler(store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        scheduler.start()
        yield
        await scheduler.close()

    app = FastAPI(title="Benchmark Forge", version="0.1.0", lifespan=lifespan)
    app.state.store = store
    app.state.scheduler = scheduler
    origins = [os.environ.get("FORGE_WEB_ORIGIN", "http://127.0.0.1:5173"), "http://localhost:5173"]
    if any(
        urlsplit(origin).hostname not in {"127.0.0.1", "localhost", "::1"} for origin in origins
    ):
        raise ValueError("Web Originはlocalhostに限定します")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        host = request.headers.get("host", "")
        try:
            parsed = urlsplit("http://" + host)
            valid = parsed.hostname in {"127.0.0.1", "localhost", "::1"} and not parsed.username
        except ValueError:
            valid = False
        origin = request.headers.get("origin")
        if not valid or (origin and origin not in origins and origin != "http://" + host):
            return JSONResponse({"detail": "ローカルOrigin/Hostのみ利用できます"}, status_code=403)
        if request.headers.get("sec-fetch-site") == "cross-site":
            return JSONResponse(
                {"detail": "外部サイトからの操作は禁止されています"}, status_code=403
            )
        if request.method == "POST":
            if not request.headers.get("content-type", "").startswith("application/json"):
                return JSONResponse({"detail": "application/jsonが必要です"}, status_code=415)
            try:
                size = int(request.headers.get("content-length", "0"))
            except ValueError:
                return JSONResponse({"detail": "Content-Lengthが不正です"}, status_code=400)
            if size > 1_000_000 or len(await request.body()) > 1_000_000:
                return JSONResponse({"detail": "リクエストが大きすぎます"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"
        )
        return response

    @app.exception_handler(KeyError)
    async def not_found(request: Request, exc: KeyError):
        return JSONResponse({"detail": str(exc.args[0])}, status_code=404)

    @app.exception_handler(ValueError)
    async def invalid(request: Request, exc: ValueError):
        return JSONResponse({"detail": str(exc)}, status_code=422)

    @app.exception_handler(AdapterError)
    async def unavailable(request: Request, exc: AdapterError):
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.1.0", "profile": "Preview v1"}

    @app.get("/api/registry")
    def registry():
        return {
            "categories": registry_tree(),
            "generator_count": len(REGISTRY),
            "covered_categories": len({g.category_id for g in REGISTRY.values()}),
            "total_categories": 16,
            "difficulty_calibrated": False,
        }

    @app.get("/api/settings")
    def settings():
        return {
            "sandbox": sandbox_status(),
            "data_directory": str(store.path.parent),
            "profile": "Preview v1",
            "code_license": "未決定",
            "paid_api_required": False,
        }

    @app.get("/api/presets")
    def get_presets():
        return presets() + store.presets()

    @app.post("/api/presets")
    def save_preset(value: SavePreset):
        config = value.config.model_copy(update={"custom": True, "profile": "custom"})
        id = store.save_preset(value.name, config.model_dump())
        return {"id": id}

    @app.get("/api/models")
    def models():
        return [
            {**model.model_dump(), "capabilities": capabilities(model)} for model in store.models()
        ]

    @app.post("/api/models")
    def save_model(model: ModelConfig):
        validate_endpoint(model.endpoint)
        store.save_model(model)
        return {**model.model_dump(), "capabilities": capabilities(model)}

    @app.post("/api/models/{model_id}/check")
    async def check_model(model_id: str):
        model = store.get_model(model_id)
        if model.backend == "ollama":
            return await OllamaAdapter(model).check()
        return capabilities(model)

    @app.post("/api/sets")
    def freeze(config: SetConfig):
        frozen = build_set(config)
        store.save_set(frozen)
        return {
            "set_id": frozen.set_id,
            "set_hash": frozen.set_hash,
            "count": len(frozen.problems),
            "fixed_count": sum(p.origin == "fixed" for p in frozen.problems),
            "dynamic_count": sum(p.origin == "dynamic" for p in frozen.problems),
            "warnings": frozen.warnings,
            "duplicate_stats": frozen.duplicate_stats,
            "sample": [p.public().model_dump() for p in frozen.problems[:2]],
        }

    @app.get("/api/sets/{set_id}")
    def get_set(set_id: str):
        frozen = store.get_set(set_id)
        return {
            "set_id": set_id,
            "set_hash": frozen.set_hash,
            "config": frozen.config,
            "problems": [p.public() for p in frozen.problems],
            "warnings": frozen.warnings,
        }

    @app.post("/api/runs")
    async def start_run(value: StartRun):
        return {"run_ids": scheduler.create(value.set_id, value.model_ids)}

    @app.get("/api/runs")
    def runs():
        return [summarize(store, r["id"], detail=False) for r in store.runs()]

    @app.get("/api/runs/{run_id}")
    def run_detail(run_id: str):
        return summarize(store, run_id)

    @app.post("/api/runs/{run_id}/{action}")
    async def control(run_id: str, action: Literal["pause", "resume", "cancel", "retry"]):
        scheduler.control(run_id, action)
        return summarize(store, run_id, detail=False)

    @app.get("/api/runs/{run_id}/events")
    async def events(run_id: str, request: Request):
        store.run(run_id)

        async def stream():
            revision = -1  # Always replay the latest durable snapshot on reconnect.
            heartbeat = 0
            while not await request.is_disconnected():
                report = summarize(store, run_id, detail=False)
                if report["revision"] != revision:
                    revision = report["revision"]
                    yield f"id: {revision}\nevent: progress\ndata: {json.dumps(report, ensure_ascii=False)}\n\n"
                else:
                    heartbeat += 1
                    if heartbeat % 40 == 0:
                        yield ": heartbeat\n\n"
                if report["status"] in {"completed", "cancelled"}:
                    break
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/runs/{run_id}/export/{format}")
    def export(run_id: str, format: Literal["jsonl", "csv", "markdown"]):
        report = summarize(store, run_id)
        content, media = export_report(report, format)
        extension = "md" if format == "markdown" else format
        return Response(
            content,
            media_type=media,
            headers={"Content-Disposition": f'attachment; filename="{run_id}.{extension}"'},
        )

    @app.get("/api/compare")
    def compare(ids: str):
        selected = ids.split(",")
        if not 2 <= len(selected) <= 10:
            raise HTTPException(422, "比較するランを2〜10件指定してください")
        return comparison([summarize(store, id, detail=False) for id in selected])

    web = Path(__file__).resolve().parents[2] / "apps/web/dist"
    if web.is_dir():
        app.mount("/", StaticFiles(directory=web, html=True), name="web")
    return app
