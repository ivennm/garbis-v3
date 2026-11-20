import json

from garbis_server.memory import Memory


def test_append_then_drop_oldest_half(tmp_path):
    m = Memory(tmp_path / "memory.json", max_exchanges=10)
    for i in range(10):
        assert m.add(f"q{i}", f"a{i}") is False
    assert m.exchanges == 10
    assert m.add("q10", "a10") is True          # 11th exchange: drop the oldest 5
    assert m.exchanges == 6
    assert m.messages[0] == {"role": "user", "content": "q5"}
    assert m.messages[-1] == {"role": "assistant", "content": "a10"}


def test_save_and_load_roundtrip(tmp_path):
    path = tmp_path / "data" / "memory.json"
    m = Memory(path, 10)
    m.add("garbis hi", "Hello Supreme Master Leader Sama, beep.")
    m.save(m.snapshot())
    loaded = Memory(path, 10)
    loaded.load()
    assert loaded.messages == m.messages
    assert not path.with_suffix(".json.tmp").exists()


def test_malformed_file_starts_fresh(tmp_path):
    path = tmp_path / "memory.json"
    path.write_text("{not json")
    m = Memory(path, 10)
    m.load()
    assert m.messages == []

    path.write_text(json.dumps({"messages": [{"role": "assistant", "content": "out of order"}]}))
    m.load()
    assert m.messages == []


def test_load_trims_to_max(tmp_path):
    path = tmp_path / "memory.json"
    big = Memory(path, 50)
    for i in range(20):
        big.add(f"q{i}", f"a{i}")
    big.save()
    m = Memory(path, 10)
    m.load()
    assert m.exchanges == 10
    assert m.messages[0]["content"] == "q10"
