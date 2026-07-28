"""Research assistant — an automated research workflow, honestly named.

It NEVER places trades and never touches the ops loop. It:
  1. generates hypotheses (deterministic, seeded enumeration of strategy
     templates × symbols × parameter grids, with rationale text built
     from measured dataset statistics — templates, not claims),
  2. checks novelty against the experiment registry (already-tested
     combinations are skipped, and the skip is recorded),
  3. runs each hypothesis through the SAME Phase 4 validation pipeline
     every human-run experiment goes through — no shortcuts, holdout
     first, the works,
  4. classifies results:  rejected | needs_more_data | passed,
  5. stores everything in the experiment registry + a research queue.

This generator is rule-based. An LLM can be plugged in at the
hypothesis step in Phase 6; nothing downstream would change, because
hypotheses are just structured proposals and validation is the gate.
The mission stays inverted from a trading bot: the pipeline exists to
REJECT ideas, and most of what this assistant produces should die.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore
from engine.strategies import examples as ex
from research.pipeline import run_experiment

STRATEGY_TEMPLATES: dict[str, list[dict]] = {
    "MACrossover": [
        {"fast": [2, 4], "slow": [8, 12]},
        {"fast": [3, 6], "slow": [15, 30]},
    ],
    "RSIMeanReversion": [
        {"period": [7, 14], "oversold": [25, 30], "overbought": [70, 75]},
    ],
    "VolatilityBreakout": [
        {"lookback": [10, 20], "mult": [1.5, 2.0]},
    ],
    "BuyAndHold": [{"invest_pct": [0.5, 0.95]}],
}

STRATEGY_CLASSES = {
    "MACrossover": ex.MACrossover,
    "RSIMeanReversion": ex.RSIMeanReversion,
    "VolatilityBreakout": ex.VolatilityBreakout,
    "BuyAndHold": ex.BuyAndHold,
}


@dataclass(slots=True)
class Hypothesis:
    id: str
    strategy: str
    symbols: list[str]
    param_values: dict
    rationale: str
    created_at: str
    fingerprint: str = ""

    def __post_init__(self) -> None:
        if not self.fingerprint:
            payload = json.dumps(
                {"strategy": self.strategy, "symbols": self.symbols,
                 "grid": self.param_values},
                sort_keys=True,
            )
            self.fingerprint = hashlib.sha256(payload.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return asdict(self)


def _dataset_stats(store: ParquetStore, symbol: str) -> dict:
    frame = store.read(symbol, Timeframe.D1)
    closes = frame["close"].astype(float)
    returns = closes.pct_change().dropna()
    total = closes.iloc[-1] / closes.iloc[0] - 1.0
    return {
        "n_bars": len(frame),
        "ann_vol": float(returns.std(ddof=1) * np.sqrt(252)),
        "total_return": float(total),
    }


def generate_hypotheses(
    store: ParquetStore,
    symbols: list[str],
    seed: int = 0,
    limit: int | None = None,
) -> list[Hypothesis]:
    """Deterministic under (store contents, symbols, seed)."""
    now = datetime.now(UTC).isoformat()
    stats = {s: _dataset_stats(store, s) for s in symbols}
    candidates: list[Hypothesis] = []
    for strategy, grids in sorted(STRATEGY_TEMPLATES.items()):
        for grid_index, grid in enumerate(grids):
            for symbol in sorted(symbols):
                st = stats[symbol]
                n_combos = int(np.prod([len(v) for v in grid.values()])) if grid else 1
                rationale = (
                    f"{symbol} shows {st['ann_vol']:.0%} annualized volatility "
                    f"over {st['n_bars']} bars (total move {st['total_return']:+.0%}). "
                    f"Testing whether the {strategy} family (grid #{grid_index + 1}, "
                    f"{n_combos} combinations) finds structure that survives "
                    "walk-forward validation. Expectation: most variants should "
                    "be rejected."
                )
                candidates.append(Hypothesis(
                    id=uuid.uuid4().hex[:12],
                    strategy=strategy,
                    symbols=[symbol],
                    param_values=grid,
                    rationale=rationale,
                    created_at=now,
                ))
    rng = np.random.default_rng(seed)
    order = rng.permutation(len(candidates))
    ordered = [candidates[i] for i in order]
    return ordered[:limit] if limit else ordered


def load_tested(path: Path) -> set[str]:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def mark_tested(path: Path, fingerprints: set[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(fingerprints)))


def filter_novel(
    hypotheses: list[Hypothesis], tested: set[str]
) -> tuple[list[Hypothesis], list[Hypothesis]]:
    novel = [h for h in hypotheses if h.fingerprint not in tested]
    skipped = [h for h in hypotheses if h.fingerprint in tested]
    return novel, skipped


def classify(exp: dict) -> str:
    level = exp["confidence"]["level"]
    if level in ("moderate", "strong"):
        return "passed"
    critical = {w["code"] for w in exp["warnings"]
                if w["severity"] == "critical"}
    if "few_trades" in critical:
        return "needs_more_data"
    return "rejected"


def run_hypothesis(
    hypothesis: Hypothesis,
    store: ParquetStore,
    registry_path: Path,
    seed: int = 0,
) -> dict:
    """One hypothesis through the full Phase 4 pipeline, budget scaled
    to the dataset (small but the SAME code path — holdout enforced)."""
    frame = store.read(hypothesis.symbols[0], Timeframe.D1)
    n = len(frame)
    test = max(int(n * 0.2), 10)
    val = max(int(n * 0.1), 8)
    train = n - test - 2 * val
    exp = run_experiment(
        data_store=store,
        strategy_cls=STRATEGY_CLASSES[hypothesis.strategy],
        symbols=hypothesis.symbols,
        param_values=hypothesis.param_values,
        train_size=train, val_size=val, test_size=test,
        mc_iters=40, fan_paths=30, cost_iters=3,
        seed=seed, delays=(0, 1),
        tags=["assistant", f"hypothesis:{hypothesis.id}"],
        registry_path=registry_path,
    )
    verdict = classify(exp)
    dev = exp["development"]["metrics"]
    return {
        "hypothesis": hypothesis.to_dict(),
        "experiment_id": exp["id"],
        "confidence": exp["confidence"]["level"],
        "classification": verdict,
        "headline": {
            "sharpe": dev.get("sharpe"),
            "max_drawdown": dev.get("max_drawdown"),
            "n_trades": dev.get("n_trades"),
            "win_rate": dev.get("win_rate"),
        },
        "warnings": [w["code"] for w in exp["warnings"]],
        "finished_at": datetime.now(UTC).isoformat(),
    }
