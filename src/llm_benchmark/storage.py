import json
import platform
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from llm_benchmark.domain import FrozenSet, ModelConfig, Problem, Result, canonical
from llm_benchmark.environment import backend_versions, hardware_inventory


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
    def connection(self, *, cross_thread: bool = False):
        con = sqlite3.connect(self.path, timeout=15, check_same_thread=not cross_thread)
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
            if version > 3:
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
            if version < 2:
                con.executescript("""
                    CREATE TABLE attempts(id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id),
                        idx INTEGER NOT NULL, ordinal INTEGER NOT NULL, status TEXT NOT NULL,
                        started_at TEXT, finished_at TEXT, data TEXT,
                        UNIQUE(run_id,idx,ordinal));
                    CREATE INDEX attempts_run ON attempts(run_id,idx);
                    INSERT INTO attempts(run_id,idx,ordinal,status,data)
                        SELECT run_id,idx,1,json_extract(data,'$.status'),data FROM results;
                    PRAGMA user_version=2;
                """)
            if version < 3:
                # All three operations commit together: a failed split leaves v2 intact.
                con.execute("BEGIN IMMEDIATE")
                con.execute(
                    "CREATE TABLE IF NOT EXISTS set_items(set_id TEXT NOT NULL REFERENCES sets(id), idx INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(set_id,idx))"
                )
                con.execute(
                    "INSERT OR IGNORE INTO set_items SELECT sets.id, CAST(item.key AS INTEGER), item.value FROM sets, json_each(sets.data,'$.problems') AS item"
                )
                con.execute(
                    "UPDATE sets SET data=json_remove(data,'$.problems') WHERE json_type(data,'$.problems')='array'"
                )
                con.execute("PRAGMA user_version=3")
            for model in DEFAULT_MODELS:
                con.execute(
                    "INSERT OR IGNORE INTO models VALUES(?,?)",
                    (model.model_id, model.model_dump_json()),
                )

    def save_set(self, value: FrozenSet):
        with self.connection() as con:
            inserted = con.execute(
                "INSERT OR IGNORE INTO sets VALUES(?,?)",
                (value.set_id, value.model_dump_json(exclude={"problems"})),
            ).rowcount
            if inserted:
                con.executemany(
                    "INSERT INTO set_items VALUES(?,?,?)",
                    ((value.set_id, i, p.model_dump_json()) for i, p in enumerate(value.problems)),
                )

    def set_header(self, id: str) -> dict:
        with self.connection() as con:
            row = con.execute("SELECT data FROM sets WHERE id=?", (id,)).fetchone()
        if row is None:
            raise KeyError("問題セットが見つかりません")
        return FrozenSet.model_validate({**json.loads(row[0]), "problems": []}).model_dump(
            exclude={"problems"}
        )

    def iter_problems(self, id: str, *, metadata_only: bool = False):
        # Immutable rows, bounded batches, and no read transaction held during inference.
        projection = (
            "json_set(data,'$.prompt','','$.answer_spec.expected',NULL,'$.features',json('{}'),'$.simulation',json('{}'))"
            if metadata_only
            else "data"
        )
        after = -1
        while True:
            with self.connection() as con:
                rows = con.execute(
                    f"SELECT idx,{projection} FROM set_items WHERE set_id=? AND idx>? ORDER BY idx LIMIT 32",
                    (id, after),
                ).fetchall()
            if not rows:
                return
            for row in rows:
                yield Problem.model_validate_json(row[1])
            after = rows[-1][0]

    def get_set(self, id: str, *, metadata_only: bool = False) -> FrozenSet:
        """metadata_only is for aggregation only; omitted payloads must never be re-saved."""
        return FrozenSet.model_validate(
            {
                **self.set_header(id),
                "problems": list(self.iter_problems(id, metadata_only=metadata_only)),
            }
        )

    def result_page(
        self, id: str, *, offset: int = 0, limit: int = 50, status: str | None = None
    ) -> dict:
        if offset < 0 or not 1 <= limit <= 100:
            raise ValueError("ログ取得範囲が不正です")
        with self.connection() as con:
            con.execute("BEGIN")
            run = con.execute("SELECT set_id,revision FROM runs WHERE id=?", (id,)).fetchone()
            if run is None:
                raise KeyError("ランが見つかりません")
            where = "run_id=?" + (" AND json_extract(data,'$.status')=?" if status else "")
            parameters = (id, status) if status else (id,)
            total = con.execute(
                f"SELECT count(*) FROM results WHERE {where}", parameters
            ).fetchone()[0]
            results: list[dict] = []
            attempts: list[dict] = []
            for row in con.execute(
                f"SELECT idx,data FROM results WHERE {where} ORDER BY idx LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ):
                problem = con.execute(
                    "SELECT data FROM set_items WHERE set_id=? AND idx=?",
                    (run["set_id"], row["idx"]),
                ).fetchone()
                results.append({**json.loads(row["data"]), "problem": json.loads(problem[0])})
                attempts.extend(
                    {**dict(a), "data": json.loads(a["data"]) if a["data"] else None}
                    for a in con.execute(
                        "SELECT * FROM attempts WHERE run_id=? AND idx=? ORDER BY ordinal",
                        (id, row["idx"]),
                    )
                )
            return {
                "revision": run["revision"],
                "total": total,
                "offset": offset,
                "limit": limit,
                "results": results,
                "attempts": attempts,
            }

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
                **hardware_inventory(),
                "package_versions": backend_versions(),
                "os": platform.platform(),
                "python": platform.python_version(),
                "cpu": platform.machine(),
                "execution_policy": "sequential",
                "warmup": False,
                "batch_size": 1,
                "streaming": model.backend == "ollama"
                and model.streaming
                and self.set_header(set_id)["config"]["evaluation_mode"]
                not in {"native-tools", "agent"},
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
                "inference_seed": model.inference_seed,
                "gpu_sampling": model.gpu_sampling,
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

    def record_model_observation(self, id: str, observation: dict) -> int | None:
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute("SELECT status,environment FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            if row["status"] == "cancelled":
                return None
            environment = json.loads(row["environment"])
            observations = environment.setdefault("model_observations", [])
            observations.append({**observation, "observed_at": now()})
            con.execute(
                "UPDATE runs SET environment=?,updated_at=?,revision=revision+1 WHERE id=?",
                (canonical(environment), now(), id),
            )
            return len(observations) - 1

    def run(self, id: str, *, include_payloads: bool = True) -> dict:
        with self.connection() as con:
            con.execute("BEGIN")
            row = con.execute("SELECT * FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            projection = (
                "data"
                if include_payloads
                else "json_set(json_remove(data,'$.metrics.trace','$.metrics.raw_output'),'$.answer','','$.reason','')"
            )
            results = [
                Result.model_validate_json(r[0])
                for r in con.execute(
                    f"SELECT {projection} FROM results WHERE run_id=? ORDER BY rowid", (id,)
                )
            ]
        return {
            **dict(row),
            "model": json.loads(row["model"]),
            "environment": json.loads(row["environment"]),
            "results": sorted(results, key=lambda result: result.index),
            "_recent_results": results[-20:],
        }

    def run_ids(self) -> list[str]:
        with self.connection() as con:
            ids = [
                row[0]
                for row in con.execute("SELECT id FROM runs ORDER BY created_at DESC LIMIT 200")
            ]
        return ids

    def runs(self) -> list[dict]:
        return [self.run(id) for id in self.run_ids()]

    def run_revision(self, id: str) -> int:
        with self.connection() as con:
            row = con.execute("SELECT revision FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            return row[0]

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
                "UPDATE attempts SET status='interrupted',finished_at=? WHERE status='running'",
                (now(),),
            )
            con.execute(
                "UPDATE runs SET status='paused', updated_at=?, revision=revision+1 WHERE status IN ('queued','running','pausing')",
                (now(),),
            )

    def run_status(self, id: str) -> str:
        with self.connection() as con:
            row = con.execute("SELECT status FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            return row[0]

    def begin_attempt(self, id: str, index: int) -> int:
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            ordinal = con.execute(
                "SELECT coalesce(max(ordinal),0)+1 FROM attempts WHERE run_id=? AND idx=?",
                (id, index),
            ).fetchone()[0]
            cursor = con.execute(
                "INSERT INTO attempts(run_id,idx,ordinal,status,started_at) VALUES(?,?,?,'running',?)",
                (id, index, ordinal, now()),
            )
            return int(cursor.lastrowid)

    def end_attempt(self, attempt: int, status: str):
        with self.connection() as con:
            con.execute(
                "UPDATE attempts SET status=?,finished_at=? WHERE id=? AND status='running'",
                (status, now(), attempt),
            )

    def attempts(self, id: str) -> list[dict]:
        with self.connection() as con:
            return [
                {**dict(row), "data": json.loads(row["data"]) if row["data"] else None}
                for row in con.execute(
                    "SELECT * FROM attempts WHERE run_id=? ORDER BY idx,ordinal", (id,)
                )
            ]

    def save_result(self, id: str, value: Result, attempt: int | None = None):
        with self.connection() as con:
            con.execute("BEGIN IMMEDIATE")
            inserted = con.execute(
                "INSERT OR IGNORE INTO results VALUES(?,?,?)",
                (id, value.index, value.model_dump_json()),
            ).rowcount
            if not inserted:
                return
            if attempt is None:
                ordinal = con.execute(
                    "SELECT coalesce(max(ordinal),0)+1 FROM attempts WHERE run_id=? AND idx=?",
                    (id, value.index),
                ).fetchone()[0]
                con.execute(
                    "INSERT INTO attempts(run_id,idx,ordinal,status,finished_at,data) VALUES(?,?,?,?,?,?)",
                    (id, value.index, ordinal, value.status, now(), value.model_dump_json()),
                )
            else:
                updated = con.execute(
                    "UPDATE attempts SET status=?,finished_at=?,data=? WHERE id=? AND run_id=? AND idx=? AND status='running'",
                    (value.status, now(), value.model_dump_json(), attempt, id, value.index),
                ).rowcount
                if not updated:
                    raise ValueError("試行と結果の対応が不正です")
            con.execute("UPDATE runs SET updated_at=?, revision=revision+1 WHERE id=?", (now(), id))

    def retry_failed(self, id: str):
        with self.connection() as con:
            con.execute(
                "DELETE FROM results WHERE run_id=? AND json_extract(data,'$.status') IN ('error','timeout')",
                (id,),
            )

            con.execute(
                "UPDATE runs SET status='queued',updated_at=?,revision=revision+1 WHERE id=?",
                (now(), id),
            )

    def iter_export(self, id: str):
        """Consistent SQLite read snapshot. Only one result/attempt is decoded at a time.

        Frozen problems are decoded one at a time; slow consumers retain a WAL read snapshot.
        """
        # StreamingResponse advances this generator sequentially across worker threads.
        with self.connection(cross_thread=True) as con:
            con.execute("BEGIN")
            row = con.execute("SELECT * FROM runs WHERE id=?", (id,)).fetchone()
            if row is None:
                raise KeyError("ランが見つかりません")
            frozen = FrozenSet.model_validate(
                {
                    **json.loads(
                        con.execute(
                            "SELECT data FROM sets WHERE id=?", (row["set_id"],)
                        ).fetchone()[0]
                    ),
                    "problems": [],
                }
            ).model_dump(exclude={"problems"})
            set_id = row["set_id"]
            header = {
                **dict(row),
                "model": json.loads(row["model"]),
                "environment": json.loads(row["environment"]),
                "set_hash": frozen["set_hash"],
                "profile_version": frozen["profile_version"],
                "grader_version": frozen["grader_version"],
                "config": frozen["config"],
                "weights": frozen["weights"],
                "set_metadata": frozen["metadata"],
                "warnings": frozen["warnings"],
                "total": len(frozen["weights"]),
                "test_only": json.loads(row["model"])["backend"] == "mock",
                "export_schema": "forge-stream-v1",
            }
            yield {"type": "run", **header}
            # Include the full frozen set even for interrupted/unanswered problems.
            for item in con.execute(
                "SELECT idx,data FROM set_items WHERE set_id=? ORDER BY idx", (set_id,)
            ):
                yield {"type": "problem", "index": item["idx"], **json.loads(item["data"])}
            for row in con.execute("SELECT data FROM results WHERE run_id=? ORDER BY idx", (id,)):
                result = json.loads(row[0])
                yield {
                    "type": "result",
                    **result,
                    "problem": json.loads(
                        con.execute(
                            "SELECT data FROM set_items WHERE set_id=? AND idx=?",
                            (set_id, result["index"]),
                        ).fetchone()[0]
                    ),
                }
            for row in con.execute(
                "SELECT * FROM attempts WHERE run_id=? ORDER BY idx,ordinal", (id,)
            ):
                yield {
                    "type": "attempt",
                    **dict(row),
                    "data": json.loads(row["data"]) if row["data"] else None,
                }

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
