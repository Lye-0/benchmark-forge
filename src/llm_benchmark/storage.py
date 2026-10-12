import json
import platform
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from llm_benchmark.domain import FrozenSet, ModelConfig, Result, canonical


def now() -> str:
    return datetime.now(UTC).isoformat()


DEFAULT_MODELS = [
    ModelConfig(
        model_id="mock-reference", name="Mock / 参照ソルバー", backend="mock", revision="1.0.0"
    ),
    ModelConfig(
        model_id="mock-wrong",
        name="Mock / 誤答テスト",
        backend="mock",
        mock_behavior="wrong",
        revision="1.0.0",
    ),
]


class Store:
    """Short transactions, per-operation connections; no answers in public model objects."""

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = directory / "forge.sqlite3"
        self.migrate()

    @contextmanager
    def connection(self):
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys=ON")
        try:
            with con:
                yield con
        finally:
            con.close()

    def migrate(self):
        with self.connection() as con:
            con.execute("PRAGMA journal_mode=WAL")
            version = con.execute("PRAGMA user_version").fetchone()[0]
            if version > 1:
                raise RuntimeError("未対応のDB版です。新しいアプリで開いてください")
            if version == 0:
                con.executescript("""
                    CREATE TABLE sets(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE models(id TEXT PRIMARY KEY, data TEXT NOT NULL);
                    CREATE TABLE runs(id TEXT PRIMARY KEY, set_id TEXT NOT NULL REFERENCES sets(id),
                        model TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 0, environment TEXT NOT NULL);
                    CREATE TABLE results(run_id TEXT NOT NULL REFERENCES runs(id), idx INTEGER NOT NULL,
                        data TEXT NOT NULL, PRIMARY KEY(run_id,idx));
                    CREATE TABLE presets(id TEXT PRIMARY KEY, name TEXT NOT NULL, data TEXT NOT NULL);
                    PRAGMA user_version=1;
                """)
            for model in DEFAULT_MODELS:
                con.execute(
                    "INSERT OR IGNORE INTO models VALUES(?,?)",
                    (model.model_id, model.model_dump_json()),
                )

    def save_set(self, value: FrozenSet):
        with self.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO sets VALUES(?,?)", (value.set_id, value.model_dump_json())
            )

    def get_set(self, id: str) -> FrozenSet:
        with self.connection() as con:
            row = con.execute("SELECT data FROM sets WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError("問題セットが見つかりません")
        return FrozenSet.model_validate_json(row[0])

    def models(self) -> list[ModelConfig]:
        with self.connection() as con:
            return [
                ModelConfig.model_validate_json(row[0])
                for row in con.execute("SELECT data FROM models ORDER BY id")
            ]

    def get_model(self, id: str) -> ModelConfig:
        for model in self.models():
            if model.model_id == id:
                return model
        raise KeyError("モデルが見つかりません")

    def save_model(self, model: ModelConfig):
        with self.connection() as con:
            con.execute(
                "INSERT INTO models VALUES(?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data",
                (model.model_id, model.model_dump_json()),
            )

    def create_run(self, set_id: str, model: ModelConfig) -> str:
        id = f"run-{uuid.uuid4().hex[:24]}"
        with self.connection() as con:
            environment = {
                "os": platform.platform(),
                "python": platform.python_version(),
                "cpu": platform.machine(),
                "execution_policy": "sequential",
                "warmup": False,
                "batch_size": 1,
                "streaming": False,
                "peak_vram_bytes": None,
                "peak_ram_bytes": None,
                "gpu": None,
                "resource_unavailable_reason": "成功応答のresults[].metricsにワーカー局所計測を保存"
                if model.backend == "transformers"
                else "バックエンドのプロセス別計測は未対応",
                "worker_policy": "cold-process-per-problem"
                if model.backend == "transformers"
                else "backend-managed",
                "model_file_hash": None,
                "chat_template": "backend-default",
                "inference_seed": 0,
                "measurement": "E2E wall time",
            }
            con.execute(
                "INSERT INTO runs VALUES(?,?,?,?,?,?,0,?)",
                (
                    id,
                    set_id,
                    model.model_dump_json(),
                    "queued",
                    now(),
                    now(),
                    canonical(environment),
                ),
            )
        return id

    def run(self, id: str) -> dict:
        with self.connection() as con:
            row = con.execute("SELECT * FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            results = [
                Result.model_validate_json(r[0])
                for r in con.execute("SELECT data FROM results WHERE run_id=? ORDER BY idx", (id,))
            ]
        return {
            **dict(row),
            "model": json.loads(row["model"]),
            "environment": json.loads(row["environment"]),
            "results": results,
        }

    def runs(self) -> list[dict]:
        with self.connection() as con:
            ids = [
                row[0]
                for row in con.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 200")
            ]
        return [self.run(id) for id in ids]

    def status(self, id: str, status: str):
        with self.connection() as con:
            updated = con.execute(
                "UPDATE runs SET status=?, updated_at=?, revision=revision+1 WHERE id=?",
                (status, now(), id),
            )
            if not updated.rowcount:
                raise KeyError("ランが見つかりません")

    def recover(self):
        with self.connection() as con:
            con.execute(
                "UPDATE runs SET status='paused', updated_at=?, revision=revision+1 WHERE status IN ('queued','running','pausing')",
                (now(),),
            )

    def save_result(self, id: str, value: Result):
        with self.connection() as con:
            con.execute(
                "INSERT OR IGNORE INTO results VALUES(?,?,?)",
                (id, value.index, value.model_dump_json()),
            )
            con.execute("UPDATE runs SET updated_at=?, revision=revision+1 WHERE id=?", (now(), id))

    def retry_failed(self, id: str):
        with self.connection() as con:
            con.execute(
                "DELETE FROM results WHERE run_id=? AND json_extract(data,'$.status') IN ('error','timeout')",
                (id,),
            )

    def save_preset(self, name: str, config: dict) -> str:
        id = f"user-{uuid.uuid4().hex[:12]}"
        with self.connection() as con:
            con.execute("INSERT INTO presets VALUES(?,?,?)", (id, name, canonical(config)))
        return id

    def presets(self) -> list[dict]:
        with self.connection() as con:
            return [
                {
                    "id": r[0],
                    "name": r[1],
                    "config": json.loads(r[2]),
                    "description": "ユーザー定義",
                }
                for r in con.execute("SELECT * FROM presets ORDER BY name")
            ]
