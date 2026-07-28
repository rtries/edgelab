"""Research assistant: deterministic hypothesis generation, novelty
filtering, honest classification. Nightly: batch execution, tallies,
report generation, resilience to a bad hypothesis."""
import json

import pytest

from engine.data.store import ParquetStore
from ops.assistant import (
    STRATEGY_CLASSES,
    classify,
    filter_novel,
    generate_hypotheses,
    load_tested,
    mark_tested,
    run_hypothesis,
)
from ops.nightly import run_nightly, write_report

from tests.test_research_pipeline import synth_frame


@pytest.fixture(scope="module")
def assistant_store(tmp_path_factory):
    root = tmp_path_factory.mktemp("assistant_env")
    store = ParquetStore(root / "data")
    store.write(synth_frame(symbol="AAA", n=120, seed=1))
    store.write(synth_frame(symbol="BBB", n=120, seed=2))
    return store, root


def test_hypothesis_generation_deterministic_and_covers_registry(assistant_store):
    store, _ = assistant_store
    a = generate_hypotheses(store, ["AAA", "BBB"], seed=3)
    b = generate_hypotheses(store, ["AAA", "BBB"], seed=3)
    assert [h.fingerprint for h in a] == [h.fingerprint for h in b]
    c = generate_hypotheses(store, ["AAA", "BBB"], seed=9)
    assert [h.fingerprint for h in a] != [h.fingerprint for h in c]
    strategies = {h.strategy for h in a}
    assert strategies == set(STRATEGY_CLASSES)
    assert all(h.rationale for h in a)
    assert all(len(h.symbols) == 1 for h in a)   # one symbol per hypothesis


def test_novelty_filter(assistant_store):
    store, _ = assistant_store
    hyps = generate_hypotheses(store, ["AAA"], seed=1)
    assert len(hyps) == 5   # 2 MACrossover grids + 1 each of the other 3 templates
    tested = {hyps[0].fingerprint, hyps[2].fingerprint}
    novel, skipped = filter_novel(hyps, tested)
    assert len(novel) == 3 and len(skipped) == 2
    assert all(h.fingerprint not in tested for h in novel)


def test_tested_index_roundtrip(tmp_path):
    path = tmp_path / "tested.json"
    assert load_tested(path) == set()
    mark_tested(path, {"a", "b"})
    assert load_tested(path) == {"a", "b"}


def test_run_hypothesis_classifies_honestly(assistant_store, tmp_path):
    store, _ = assistant_store
    hyps = generate_hypotheses(store, ["AAA"], seed=5)
    ma_hyp = next(h for h in hyps if h.strategy == "MACrossover")
    result = run_hypothesis(ma_hyp, store, tmp_path / "registry.json", seed=1)
    assert result["classification"] in ("rejected", "needs_more_data", "passed")
    assert result["experiment_id"]
    assert "sharpe" in result["headline"]
    # classify() is a pure function of confidence/warnings — spot check directly
    assert classify({"confidence": {"level": "strong"}, "warnings": []}) == "passed"
    assert classify({"confidence": {"level": "insufficient"},
                     "warnings": [{"code": "few_trades", "severity": "critical"}]}
                    ) == "needs_more_data"
    assert classify({"confidence": {"level": "weak"}, "warnings": []}) == "rejected"


def test_nightly_batch_tallies_and_skips_retested(assistant_store, tmp_path):
    store, _ = assistant_store
    registry = tmp_path / "registry.json"
    tested_index = tmp_path / "tested.json"
    result1 = run_nightly(store, ["AAA"], registry, tested_index,
                          budget=3, seed=42)
    assert result1.tallies["tested"] == 3
    assert result1.tallies["tested"] == (
        result1.tallies["rejected"] + result1.tallies["needs_more_data"]
        + result1.tallies["passed"]
    )
    assert result1.skipped_novelty == 0

    # Same seed again: everything just tested should be skipped as non-novel.
    result2 = run_nightly(store, ["AAA"], registry, tested_index,
                          budget=3, seed=42)
    assert result2.skipped_novelty >= 3


def test_nightly_survives_one_bad_hypothesis(assistant_store, tmp_path, monkeypatch):
    store, _ = assistant_store
    registry = tmp_path / "registry.json"
    tested_index = tmp_path / "tested.json"

    import ops.nightly as nightly_mod
    real_run = nightly_mod.run_hypothesis
    calls = {"n": 0}

    def flaky(hypothesis, store, registry_path, seed=0):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("simulated failure")
        return real_run(hypothesis, store, registry_path, seed=seed)

    monkeypatch.setattr(nightly_mod, "run_hypothesis", flaky)
    result = run_nightly(store, ["AAA"], registry, tested_index,
                         budget=3, seed=7)
    assert len(result.errors) == 1
    assert result.errors[0]["error"] == "simulated failure"
    assert result.tallies["tested"] == 2   # the other two still ran


def test_report_written_json_and_markdown(assistant_store, tmp_path):
    store, _ = assistant_store
    registry = tmp_path / "registry.json"
    tested_index = tmp_path / "tested.json"
    result = run_nightly(store, ["AAA"], registry, tested_index,
                         budget=2, seed=11)
    json_path, md_path = write_report(result, tmp_path / "reports")
    assert json_path.exists() and md_path.exists()
    payload = json.loads(json_path.read_text())
    assert payload["tallies"]["tested"] == 2
    text = md_path.read_text()
    assert "Ideas Tested" in text
    assert "cannot predict future prices" in text
