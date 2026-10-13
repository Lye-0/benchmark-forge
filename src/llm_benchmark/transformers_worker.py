"""Trusted local inference, not a sandbox for submitted code or remote model code."""

import contextlib
import importlib
import json
import sys
import time
from pathlib import Path

from llm_benchmark.domain import ModelConfig, PublicProblem, Response
from llm_benchmark.platform_support import peak_ram


def infer(config: ModelConfig, problem: PublicProblem) -> Response:
    torch = importlib.import_module("torch")
    transformers = importlib.import_module("transformers")
    if config.device == "cuda" and not torch.cuda.is_available():
        raise ValueError("CUDA unavailable")
    path = str(Path(config.model).resolve(strict=True))
    if config.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
    started = time.perf_counter()
    options = {"local_files_only": True, "trust_remote_code": False}
    tokenizer = transformers.AutoTokenizer.from_pretrained(path, **options)
    model = transformers.AutoModelForCausalLM.from_pretrained(
        path,
        **options,
        use_safetensors=True,
    ).to(config.device)
    model.eval()
    if config.device == "cuda":
        torch.cuda.synchronize()
    load_seconds = time.perf_counter() - started
    if tokenizer.chat_template:
        prompt = tokenizer.apply_chat_template(
            [{"role": "user", "content": problem.prompt}],
            tokenize=False,
            add_generation_prompt=True,
        )
        inputs = tokenizer(prompt, return_tensors="pt", add_special_tokens=False)
    else:
        inputs = tokenizer(problem.prompt, return_tensors="pt")
    input_length = inputs["input_ids"].shape[-1]
    limits = [
        n
        for n in (config.context_length, getattr(model.config, "max_position_embeddings", None))
        if isinstance(n, int) and n > 0
    ]
    if limits and input_length + config.max_tokens > min(limits):
        raise ValueError("Context limit exceeded; never silently truncate a benchmark prompt")
    inputs = {key: value.to(config.device) for key, value in inputs.items()}
    torch.manual_seed(config.inference_seed)
    generation: dict = {"max_new_tokens": config.max_tokens, "do_sample": config.temperature > 0}
    if config.temperature > 0:
        generation["temperature"] = config.temperature
    started = time.perf_counter()
    with torch.inference_mode():
        output = model.generate(**inputs, **generation)
    if config.device == "cuda":
        torch.cuda.synchronize()
    generation_seconds = time.perf_counter() - started
    tokens = output[0, input_length:]
    text = tokenizer.decode(tokens, skip_special_tokens=True)
    if len(text) > 200_000:
        raise ValueError("Output too large")
    ram_bytes, ram_scope = peak_ram()
    return Response(
        text=text,
        output_tokens=len(tokens),
        metrics={
            "load_seconds": load_seconds,
            "generation_seconds": generation_seconds,
            "peak_ram_bytes": ram_bytes,
            "peak_vram_allocated_bytes": torch.cuda.max_memory_allocated()
            if config.device == "cuda"
            else None,
            "vram_unavailable_reason": None if config.device == "cuda" else "CPU execution",
            "ram_scope": ram_scope,
            "vram_scope": "worker PyTorch allocator; not total GPU memory",
            "device": config.device,
            "gpu": torch.cuda.get_device_name() if config.device == "cuda" else None,
            "torch_version": torch.__version__,
            "transformers_version": transformers.__version__,
            "cuda_version": torch.version.cuda,
            "chat_template": "model-local" if tokenizer.chat_template else "raw-prompt",
            "timing_policy": "cold worker per problem; generation includes prefill; TTFT/decode N/A",
        },
    )


def main():
    try:
        data = json.loads(sys.stdin.buffer.read(2_000_001))
        config = ModelConfig.model_validate(data["config"])
        problem = PublicProblem.model_validate(data["problem"])
        # Libraries may log to stdout. Reserve stdout exclusively for our response protocol.
        with contextlib.redirect_stdout(sys.stderr):
            response = infer(config, problem)
        print(response.model_dump_json())
    except Exception:
        # Never serialize library errors, paths, prompts or the environment.
        sys.exit(1)


if __name__ == "__main__":
    main()
