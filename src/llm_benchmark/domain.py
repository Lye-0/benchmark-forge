import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class AnswerSpec(StrictModel):
    expected: Any
    type: Literal["number", "json", "text"]
    tolerance: float = Field(default=0, ge=0, le=1)


class PublicProblem(StrictModel):
    problem_id: str
    prompt: str


class Problem(StrictModel):
    problem_id: str
    schema_version: str = "1"
    generator_id: str
    generator_version: str = "1.0.0"
    category_id: str
    subcategory_id: str
    tags: list[str]
    seed: int
    target_difficulty: float = Field(ge=0, le=100)
    empirical_difficulty: float | None = None
    prompt: str
    answer_spec: AnswerSpec
    grading_type: str
    verification: Literal["verified", "experimental"] = "verified"
    origin: Literal["fixed", "dynamic"]
    template: str
    representation: str = "text+json"
    features: dict[str, Any]
    provenance: str = "algorithmic-original"
    simulation: dict[str, Any] = Field(default_factory=dict)
    content_hash: str

    def public(self) -> PublicProblem:
        return PublicProblem(problem_id=self.problem_id, prompt=self.prompt)


class SetConfig(StrictModel):
    generator_ids: list[str] = Field(min_length=1, max_length=100)
    count: int = Field(default=20, ge=1, le=8000)
    seed: int = Field(default=42, ge=0, le=2**32 - 1)
    difficulty_min: float = Field(default=0, ge=0, le=100)
    difficulty_max: float = Field(default=100, ge=0, le=100)
    fixed_ratio: float = Field(default=0.5, ge=0, le=1)
    profile: str = Field(default="preview-quick-v1", max_length=100)
    custom: bool = False
    evaluation_mode: Literal["text", "native-tools", "agent", "code"] = "text"

    @model_validator(mode="after")
    def valid_range(self) -> "SetConfig":
        if self.difficulty_min > self.difficulty_max:
            raise ValueError("難易度の下限は上限以下にしてください")
        if len(set(self.generator_ids)) != len(self.generator_ids):
            raise ValueError("生成器の重複選択はできません")
        if self.count < len(self.generator_ids):
            raise ValueError("各生成器に最低1問を割り当てる問題数が必要です")
        return self


class FrozenSet(StrictModel):
    set_id: str
    set_hash: str
    config: SetConfig
    problems: list[Problem]
    profile_version: str = "Preview v1"
    grader_version: str = "1.0.0"
    weights: dict[str, float]
    warnings: list[str]
    duplicate_stats: dict[str, int]
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelConfig(StrictModel):
    model_id: str = Field(pattern=r"^[A-Za-z0-9_.-]{1,80}$")
    name: str = Field(min_length=1, max_length=100)
    backend: Literal["mock", "ollama", "transformers", "codex-cli", "codex-app-server"]
    model: str = Field(default="reference", max_length=200)
    endpoint: str = Field(default="http://127.0.0.1:11434", max_length=200)
    revision: str = Field(default="unrecorded", max_length=200)
    quantization: str = Field(default="N/A", max_length=80)
    context_length: int | None = Field(default=None, ge=1, le=10_000_000)
    streaming: bool = False
    native_tools: bool = False
    device: Literal["cpu", "cuda"] = "cpu"
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=512, ge=1, le=32768)
    timeout_seconds: float = Field(default=30, ge=0.1, le=600)
    mock_behavior: Literal["reference", "wrong", "timeout", "error", "empty"] = "reference"


class StartRun(StrictModel):
    set_id: str = Field(pattern=r"^set-[a-f0-9]{24}$")
    model_ids: list[str] = Field(min_length=1, max_length=10)


class Response(StrictModel):
    text: str
    output_tokens: int | None = None
    decode_seconds: float | None = None
    ttft_seconds: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)


class Grade(StrictModel):
    correct: bool
    reason: str
    parsed: Any = None


class Result(StrictModel):
    index: int
    problem_id: str
    status: Literal["correct", "incorrect", "timeout", "error", "empty", "ungradable"]
    correct: bool
    answer: str
    reason: str
    latency_seconds: float
    output_tokens: int | None = None
    decode_tokens_per_second: float | None = None
    ttft_seconds: float | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
