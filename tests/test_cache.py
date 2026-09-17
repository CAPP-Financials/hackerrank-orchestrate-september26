import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "code"))

import cache


def test_cache_miss_returns_sentinel(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    result = cache.get({"kind": "message_fact", "message_text": "hello"}, "test-model")
    assert result is cache.MISS


def test_cache_put_then_get_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    payload = {"kind": "message_fact", "message_text": "hello"}
    cache.put(payload, "test-model", {"has_fact": True, "fact_type": "confirmation", "confidence": "high"})
    result = cache.get(payload, "test-model")
    assert result == {"has_fact": True, "fact_type": "confirmation", "confidence": "high"}


def test_cache_key_changes_with_model(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    payload = {"kind": "message_fact", "message_text": "hello"}
    cache.put(payload, "model-a", {"has_fact": False, "fact_type": "no_actionable_fact", "confidence": "high"})
    assert cache.get(payload, "model-b") is cache.MISS


def test_cache_stores_a_legitimate_none_value(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path)
    payload = {"kind": "image_amount", "image_id": "image_99"}
    cache.put(payload, "test-model", None)
    result = cache.get(payload, "test-model")
    assert result is None  # a real cached value, distinct from cache.MISS
