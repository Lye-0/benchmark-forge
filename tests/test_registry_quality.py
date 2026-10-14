from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from llm_benchmark.api import create_app
from llm_benchmark.domain import SetConfig
from llm_benchmark.generators import REGISTRY, registry_tree
from llm_benchmark.sets import SetUnavailable, build_set, presets


def test_experimental_verification_is_not_promoted(monkeypatch, store):
    selected = [g for g in REGISTRY.values() if g.category_id == "05"]
    for g in selected:
        monkeypatch.setitem(REGISTRY, g.id, replace(g, status="experimental"))
    assert REGISTRY["cs.lru"].generate(1, 20).verification == "experimental"
    assert registry_tree()[4]["status"] == "experimental"
    with pytest.raises(SetUnavailable, match="verified"):
        build_set(SetConfig(generator_ids=["cs.lru"], count=1))
    # The default all-category presets must not select experimental generators.
    for preset in presets():
        if preset["id"] != "preview-deep-v1":
            assert all(REGISTRY[i].status == "verified" for i in preset["config"]["generator_ids"])
    with TestClient(create_app(store.path.parent), base_url="http://127.0.0.1") as client:
        registry = client.get("/api/registry").json()
        assert registry["generator_count"] == len(REGISTRY) - len(selected)
        assert registry["covered_categories"] == 14


def test_unavailable_generator_cannot_generate_or_mark_category_verified(monkeypatch):
    for g in list(REGISTRY.values()):
        if g.category_id == "05":
            monkeypatch.setitem(REGISTRY, g.id, replace(g, status="unavailable"))
    assert registry_tree()[4]["status"] == "unavailable"
    with pytest.raises(ValueError, match="利用できません"):
        REGISTRY["cs.lru"].generate(1, 20)
