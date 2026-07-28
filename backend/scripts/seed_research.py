"""Seed the research workspace: two synthetic symbols, four strategies,
one experiment each. Gives the terminal real content on first open.

Run from backend/:  python scripts/seed_research.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.data.schema import normalize
from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore
from engine.strategies.examples import (
    BuyAndHold,
    MACrossover,
    RSIMeanReversion,
    VolatilityBreakout,
)
from research.pipeline import run_experiment
from research.store import ExperimentStore

ROOT = Path(__file__).resolve().parent.parent
DATA_ROOT = ROOT / "data" / "store"
RESEARCH_ROOT = ROOT / "research_data"


def synth(symbol: str, n: int, seed: int, drift: float, vol: float,
          cycle: int, amp: float) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2023-06-01", periods=n, tz="UTC")
    t = np.arange(n)
    closes = 100.0 * np.exp(
        np.cumsum(rng.normal(drift, vol, n)) + amp * np.sin(2 * np.pi * t / cycle)
    )
    opens = np.concatenate([[100.0], closes[:-1]])
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.004, n)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.004, n)))
    raw = pd.DataFrame({
        "ts": [s.replace(hour=21) for s in sessions],
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": rng.integers(3e5, 3e6, n).astype(float),
    })
    return normalize(raw, symbol=symbol, timeframe=Timeframe.D1, source="synthetic")


RUNS = [
    (MACrossover, "SYNA", {"fast": [2, 3, 5, 8], "slow": [10, 15, 21, 34]},
     ["momentum", "trend"]),
    (RSIMeanReversion, "SYNB", {"period": [5, 8, 14], "entry": [25.0, 30.0, 35.0]},
     ["mean-reversion"]),
    (VolatilityBreakout, "SYNA", {"lookback": [5, 10, 15], "atr_mult": [1.5, 2.0, 3.0]},
     ["breakout", "momentum"]),
    (BuyAndHold, "SYNB", {"invest_pct": [0.5, 0.75, 0.95]}, ["benchmark"]),
]


def main() -> None:
    store = ParquetStore(DATA_ROOT)
    for symbol, seed, drift, vol, cycle, amp in [
        ("SYNA", 21, 0.0005, 0.011, 17, 0.035),
        ("SYNB", 22, 0.0001, 0.016, 9, 0.02),
    ]:
        try:
            store.read(symbol, Timeframe.D1)
            print(f"[data] {symbol} already imported")
        except FileNotFoundError:
            meta = store.write(synth(symbol, 260, seed, drift, vol, cycle, amp))
            print(f"[data] {symbol}: {meta.rows} bars, checksum {meta.checksum[:12]}…")

    experiments = ExperimentStore(RESEARCH_ROOT)
    for strategy_cls, symbol, values, tags in RUNS:
        exp = run_experiment(
            data_store=store, strategy_cls=strategy_cls, symbols=[symbol],
            param_values=values, train_size=90, val_size=30, test_size=40,
            mc_iters=400, fan_paths=500, cost_iters=16, seed=13, tags=tags,
            registry_path=RESEARCH_ROOT / "registry.json",
        )
        experiments.save(exp)
        dev = exp["development"]["metrics"]
        print(f"[exp] {exp['id']} {strategy_cls.__name__:<18} on {symbol} "
              f"confidence={exp['confidence']['level']:<12} "
              f"dev_sharpe={dev.get('sharpe', float('nan')):+.2f} "
              f"holdout_sharpe={exp['final_test'].get('sharpe', float('nan')):+.2f} "
              f"warnings={len(exp['warnings'])}")
    print(f"\nSeeded. API roots: EDGELAB_DATA_ROOT={DATA_ROOT} "
          f"EDGELAB_RESEARCH_ROOT={RESEARCH_ROOT}")


if __name__ == "__main__":
    main()
