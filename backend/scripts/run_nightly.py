"""Run the continuous-research nightly batch once, locally.

Run from backend/:  python scripts/run_nightly.py [--symbols A,B] [--budget 20]

Roots resolve the same way the API does:
  EDGELAB_DATA_ROOT      dataset store (default backend/data/store)
  EDGELAB_RESEARCH_ROOT  experiment registry (default backend/research_data)
  EDGELAB_OPS_ROOT       tested-hypothesis index + reports (default backend/ops_data)
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from engine.data.store import ParquetStore
from ops.nightly import run_nightly, write_report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbols", default="",
                        help="comma-separated symbols; default: everything in the store")
    parser.add_argument("--budget", type=int, default=20)
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()

    data_root = Path(os.environ.get("EDGELAB_DATA_ROOT", "data/store"))
    research_root = Path(os.environ.get("EDGELAB_RESEARCH_ROOT", "research_data"))
    ops_root = Path(os.environ.get("EDGELAB_OPS_ROOT", "ops_data"))

    store = ParquetStore(data_root)
    symbols = (
        [s.strip() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else sorted({key.split("/", 1)[1] for key in store._manifest})  # noqa: SLF001
    )
    if not symbols:
        print("no symbols found in the data store — seed data first "
              "(see `make seed`)")
        raise SystemExit(1)

    print(f"running nightly batch: symbols={symbols} budget={args.budget}")
    result = run_nightly(
        store, symbols,
        registry_path=research_root / "registry.json",
        tested_index_path=ops_root / "research" / "tested.json",
        budget=args.budget, seed=args.seed,
    )
    json_path, md_path = write_report(result, ops_root / "research" / "reports")

    t = result.tallies
    print(f"tested={t['tested']} rejected={t['rejected']} "
          f"needs_more_data={t['needs_more_data']} passed={t['passed']} "
          f"skipped={result.skipped_novelty} errors={len(result.errors)}")
    print(f"report: {md_path}")


if __name__ == "__main__":
    main()
