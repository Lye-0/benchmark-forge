import pytest

from llm_benchmark.domain import SetConfig
from llm_benchmark.generators import REGISTRY
from llm_benchmark.sets import build_set
from llm_benchmark.storage import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "data")


@pytest.fixture
def frozen(store):
    frozen = build_set(SetConfig(generator_ids=list(REGISTRY)[:14], count=20))
    store.save_set(frozen)
    return frozen
