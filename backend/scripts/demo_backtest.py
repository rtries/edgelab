"""End-to-end Phase 2 demo: synthesize data -> import -> reproducible backtest.

Run from backend/:  python scripts/demo_backtest.py

Steps:
  1. Generate a deterministic synthetic daily OHLCV CSV (seeded RNG).
  2. Import it through CSVProvider into the ParquetStore (data/ directory).
  3. Verify store integrity, print the dataset snapshot fingerprint.
  4. Run MACrossover through run_research_backtest().
  5. Print the manifest and metrics. Run it twice: fingerprints and
     results are identical — that is the reproducibility contract.
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

from engine.data.providers.local import CSVProvider
from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.execution.costs import SimpleCostModel
from engine.run import run_research_backtest
from engine.strategies.examples import MACrossover

ROOT = Path(__file__).resolve().parent.parent
CSV_DIR = ROOT / "data" / "csv"
STORE_DIR = ROOT / "data" / "store"


def synthesize_csv(symbol: str = "DEMO", n_days: int = 120, seed: int = 42) -> Path:
    rng = np.random.default_rng(seed)
    sessions = pd.bdate_range("2024-01-01", periods=n_days, tz="UTC")
    closes = 100.0 * np.exp(np.cumsum(rng.normal(0.0003, 0.015, n_days)))
    opens = np.concatenate([[100.0], closes[:-1]]) * (1 + rng.normal(0, 0.002, n_days))
    highs = np.maximum(opens, closes) * (1 + np.abs(rng.normal(0, 0.004, n_days)))
    lows = np.minimum(opens, closes) * (1 - np.abs(rng.normal(0, 0.004, n_days)))
    volume = rng.integers(500_000, 2_000_000, n_days).astype(float)
    df = pd.DataFrame({
        # canonical convention: ts = bar COMPLETION time = session close 21:00 UTC
        "ts": [s.replace(hour=21) for s in sessions],
        "open": opens, "high": highs, "low": lows, "close": closes,
        "volume": volume,
    })
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    path = CSV_DIR / f"{symbol}.csv"
    df.to_csv(path, index=False)
    print(f"[1] synthesized {n_days} daily bars -> {path}")
    return path


def import_to_store(symbol: str = "DEMO") -> ParquetStore:
    provider = CSVProvider(CSV_DIR)
    frame = provider.fetch(symbol, Timeframe.D1, date(2024, 1, 1), date(2024, 12, 31))
    store = ParquetStore(STORE_DIR)
    meta = store.write(frame)
    store.verify(symbol, Timeframe.D1)
    print(f"[2] imported {meta.rows} rows; checksum {meta.checksum[:16]}… (verified)")
    return store


def run_backtest(store: ParquetStore, symbol: str = "DEMO"):
    result = run_research_backtest(
        store=store,
        strategy=MACrossover(),
        symbols=[symbol],
        timeframe=Timeframe.D1,
        start=datetime(2024, 1, 1, tzinfo=UTC),
        end=datetime(2024, 12, 31, tzinfo=UTC),
        params={"fast": 5, "slow": 15},
        cost_model=SimpleCostModel(),
        adjustment_mode=AdjustmentMode.RAW,
        initial_cash=100_000,
    )
    return result


def main() -> None:
    synthesize_csv()
    store = import_to_store()
    r1 = run_backtest(store)
    r2 = run_backtest(store)

    print("[3] dataset fingerprint:", r1.manifest["dataset_fingerprint"][:32], "…")
    print("[4] manifest:")
    shown = {k: v for k, v in r1.manifest.items() if k != "dataset_snapshot"}
    print(json.dumps(shown, indent=2, default=str))
    print("[5] metrics:")
    for k, v in r1.metrics.items():
        print(f"      {k:>14}: {v:.6f}")
    same = (
        r1.equity_curve.equals(r2.equity_curve)
        and r1.manifest["dataset_fingerprint"] == r2.manifest["dataset_fingerprint"]
    )
    print(f"[6] rerun identical: {same}")
    print("\nNOTE: MACrossover is an engine-verification example. Its results")
    print("on synthetic data claim nothing about real-market profitability.")


if __name__ == "__main__":
    main()
