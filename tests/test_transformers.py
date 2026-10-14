import asyncio
import sys
from unittest.mock import MagicMock

import psutil
import pytest

from llm_benchmark.adapters import AdapterError, capabilities, make_adapter
from llm_benchmark.domain import ModelConfig, PublicProblem
from llm_benchmark.transformers_adapter import TransformersAdapter
from llm_benchmark.transformers_worker import infer


def config(**kwargs):
    return ModelConfig(model_id="local", name="Local", backend="transformers", **kwargs)


def test_readiness_fails_closed(tmp_path, monkeypatch):
    assert not capabilities(config(model=str(tmp_path / "missing")))["available"]
    with pytest.raises(AdapterError):
        make_adapter(config(model=str(tmp_path), quantization="int4"))
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    assert not capabilities(config(model=str(tmp_path)))["available"]


@pytest.fixture
def worker_command(monkeypatch, tmp_path):
    original = asyncio.create_subprocess_exec
    processes = []

    def install(script):
        path = tmp_path / "fixture.py"
        path.write_text(script)

        async def spawn(*args, **kwargs):
            assert kwargs["env"]["HF_HUB_OFFLINE"] == "1"
            assert "HF_TOKEN" not in kwargs["env"]
            proc = await original(sys.executable, str(path), **kwargs)
            processes.append(proc)
            return proc

        monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
        return processes

    return install


async def test_worker_protocol_public_only_and_metrics(worker_command):
    processes = worker_command("""import sys,json
request=json.load(sys.stdin)
assert set(request['problem']) == {'prompt','problem_id'}
print(json.dumps({'text': 'fixture response', 'output_tokens': 2, 'metrics': {'load_seconds': .2}}))
""")
    response = await TransformersAdapter(config()).complete(
        PublicProblem(problem_id="p", prompt="public")
    )
    assert response.text == "fixture response"
    assert response.decode_seconds is None
    assert response.metrics["load_seconds"] == 0.2
    assert processes[0].returncode == 0


@pytest.mark.parametrize("mode", ["timeout", "cancel", "oversize", "error", "invalid"])
async def test_worker_termination_and_sanitized_failures(worker_command, mode):
    body = {
        "oversize": "print('x' * 1_100_000)",
        "error": "raise RuntimeError('secret-fixture')",
        "invalid": "print('secret-fixture')",
    }.get(mode, "import time; time.sleep(60)")
    processes = worker_command("import sys; sys.stdin.read()\n" + body)
    pending = asyncio.create_task(
        TransformersAdapter(config(timeout_seconds=0.15)).complete(
            PublicProblem(problem_id="p", prompt="public")
        )
    )
    if mode == "cancel":
        while not processes:
            await asyncio.sleep(0.005)
        pending.cancel()
    expected = (
        asyncio.CancelledError
        if mode == "cancel"
        else TimeoutError
        if mode == "timeout"
        else AdapterError
    )
    with pytest.raises(expected) as error:
        await pending
    assert "secret-fixture" not in str(error.value)
    assert processes[0].returncode is not None
    assert not psutil.pid_exists(processes[0].pid)


@pytest.mark.parametrize("model_type", ["other", "qwen3"])
def test_inference_contract_without_real_model(tmp_path, monkeypatch, model_type):
    torch, transformers = MagicMock(), MagicMock()
    torch.__version__ = "fixture"
    torch.version.cuda = None
    transformers.__version__ = "fixture"
    tokenizer = transformers.AutoTokenizer.from_pretrained.return_value
    tokenizer.chat_template = None
    tensor = MagicMock()
    tensor.shape = (1, 3)
    tokenizer.return_value = {"input_ids": tensor}
    tokenizer.decode.return_value = "<think>fixture</think>\n\n12"
    model = transformers.AutoModelForCausalLM.from_pretrained.return_value.to.return_value
    model.config.model_type = model_type
    model.generation_config.eos_token_id = 8
    model.config.max_position_embeddings = 100
    model.generate.return_value.__getitem__.return_value = [7, 8]
    monkeypatch.setattr(
        "importlib.import_module", lambda name: {"torch": torch, "transformers": transformers}[name]
    )
    result = infer(
        config(model=str(tmp_path), max_tokens=10, inference_seed=12345),
        PublicProblem(problem_id="p", prompt="public"),
    )
    torch.manual_seed.assert_called_once_with(12345)
    assert result.output_tokens == 2
    assert result.metrics["done_reason"] == "stop"
    assert result.text == ("12" if model_type == "qwen3" else tokenizer.decode.return_value)
    assert result.decode_seconds is None and result.ttft_seconds is None
    assert result.metrics["peak_ram_bytes"] > 0
    assert result.metrics["peak_vram_allocated_bytes"] is None
    kwargs = transformers.AutoModelForCausalLM.from_pretrained.call_args.kwargs
    assert kwargs == {"local_files_only": True, "trust_remote_code": False, "use_safetensors": True}
    assert model.generate.call_args.kwargs["max_new_tokens"] == 10
    assert model.generate.call_args.kwargs["do_sample"] is False
    with pytest.raises(ValueError, match="Context limit"):
        infer(
            config(model=str(tmp_path), context_length=5),
            PublicProblem(problem_id="p", prompt="public"),
        )
