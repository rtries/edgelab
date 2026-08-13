"""Import REAL historical daily bars from Alpaca into the shared data
store, so research/pipeline.run_experiment can backtest against actual
market history instead of synthetic data.

Run from backend/ (uses the same ALPACA_API_KEY/SECRET already
configured in the environment):

    python scripts/seed_real_data.py AAPL MSFT NVDA

Writes to EDGELAB_DATA_ROOT (defaults to data/store), same as
scripts/seed_research.py's synthetic data — respects the env var this
time, since that script's ROOT-relative-to-itself bug is exactly what
sent us hunting through Northflank shells the last time real/expected
data-root mismatches happened.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from engine.data.schema import normalize
from engine.data.schema_types import Timeframe
from engine.data.store import ParquetStore

DATA_BASE_URL = "https://data.alpaca.markets"


def fetch_bars(symbol: str, api_key: str, api_secret: str, limit: int = 1000) -> list[dict]:
    qs = urllib.parse.urlencode(
        {"timeframe": "1Day", "start": "2015-01-01", "limit": limit, "feed": "iex", "adjustment": "raw", "sort": "asc"}
    )
    url = f"{DATA_BASE_URL}/v2/stocks/{symbol.upper()}/bars?{qs}"
    req = urllib.request.Request(
        url, headers={"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": api_secret}
    )
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
        payload = json.loads(resp.read())
    return payload.get("bars") or []


def main() -> None:
    symbols = sys.argv[1:]
    if not symbols:
        print("usage: python scripts/seed_real_data.py SYMBOL [SYMBOL ...]")
        sys.exit(1)

    api_key = os.environ.get("ALPACA_API_KEY", "")
    api_secret = os.environ.get("ALPACA_API_SECRET", "")
    if not api_key or not api_secret:
        print("ALPACA_API_KEY / ALPACA_API_SECRET not set in the environment")
        sys.exit(1)

    data_root = Path(os.environ.get("EDGELAB_DATA_ROOT", "data/store"))
    store = ParquetStore(data_root)

    for symbol in symbols:
        try:
            bars = fetch_bars(symbol, api_key, api_secret)
        except urllib.error.HTTPError as exc:
            print(f"[{symbol}] Alpaca error {exc.code}: {exc.read().decode(errors='replace')}")
            continue
        if not bars:
            print(f"[{symbol}] no bars returned")
            continue
        raw = pd.DataFrame(
            {
                "ts": [b["t"] for b in bars],
                "open": [b["o"] for b in bars],
                "high": [b["h"] for b in bars],
                "low": [b["l"] for b in bars],
                "close": [b["c"] for b in bars],
                "volume": [b["v"] for b in bars],
            }
        )
        normalized = normalize(raw, symbol=symbol.upper(), timeframe=Timeframe.D1, source="alpaca")
        meta = store.write(normalized)
        print(f"[{symbol}] wrote {meta.rows} real bars ({normalized['ts'].min()} to {normalized['ts'].max()}), checksum {meta.checksum[:12]}…")

    print(f"\nDone. EDGELAB_DATA_ROOT={data_root}")


if __name__ == "__main__":
    main()
