"""Parquet store, providers, fingerprints, CSV/Parquet equivalence."""
from datetime import UTC, date, datetime

import pandas as pd
import pytest

from engine.data.adjustments import Split, adjust
from engine.data.providers.local import CSVProvider, ParquetProvider
from engine.data.providers.network import AlpacaProvider, PolygonProvider, YahooProvider
from engine.data.schema_types import (
    AdjustmentMode,
    DataIntegrityError,
    MissingCredentialsError,
    Timeframe,
)
from engine.data.store import ParquetStore, frame_checksum

from tests.helpers_data import canon_daily

ROWS = [(1, 10, 11, 9, 10.5, 100), (2, 10.5, 12, 10, 11, 120), (3, 11, 11.5, 10.5, 11, 90)]


def test_write_read_roundtrip(tmp_path):
    store = ParquetStore(tmp_path)
    df = canon_daily(ROWS)
    meta = store.write(df)
    assert meta.rows == 3
    out = store.read("X", Timeframe.D1)
    pd.testing.assert_frame_equal(out, df)


def test_date_range_query(tmp_path):
    store = ParquetStore(tmp_path)
    store.write(canon_daily(ROWS))
    out = store.read(
        "X", Timeframe.D1,
        start=datetime(2024, 1, 2, tzinfo=UTC),
        end=datetime(2024, 1, 2, 23, 59, tzinfo=UTC),
    )
    assert len(out) == 1
    assert out["close"].iloc[0] == 11.0


def test_incremental_update_and_idempotent_duplicates(tmp_path):
    store = ParquetStore(tmp_path)
    store.write(canon_daily(ROWS[:2]))
    # Re-writing overlapping identical rows + one new row: idempotent merge.
    store.write(canon_daily(ROWS[1:]))
    out = store.read("X", Timeframe.D1)
    assert len(out) == 3
    assert list(out["close"]) == [10.5, 11.0, 11.0]


def test_conflicting_values_refused(tmp_path):
    store = ParquetStore(tmp_path)
    store.write(canon_daily(ROWS))
    # OHLC-valid on its own, but close differs from the stored 11.0 —
    # a plausible lie, which is exactly what integrity checks are for.
    tampered = canon_daily([(2, 10.5, 12, 10, 11.5, 120)])
    with pytest.raises(DataIntegrityError, match="conflicting values"):
        store.write(tampered)
    # Store content unchanged
    assert list(store.read("X", Timeframe.D1)["close"]) == [10.5, 11.0, 11.0]


def test_store_refuses_adjusted_data(tmp_path):
    store = ParquetStore(tmp_path)
    adj = adjust(canon_daily(ROWS), splits=[Split(date(2024, 1, 2), 2.0)],
                 mode=AdjustmentMode.SPLIT)
    with pytest.raises(DataIntegrityError, match="raw data only"):
        store.write(adj)


def test_verify_detects_external_tampering(tmp_path):
    store = ParquetStore(tmp_path)
    store.write(canon_daily(ROWS))
    assert store.verify("X", Timeframe.D1)
    # Tamper with the file behind the store's back
    path = tmp_path / "1d" / "X.parquet"
    df = pd.read_parquet(path)
    df.loc[0, "close"] = 999.0
    df.to_parquet(path, index=False)
    with pytest.raises(DataIntegrityError, match="checksum mismatch"):
        store.verify("X", Timeframe.D1)


def test_fingerprint_stable_and_data_sensitive(tmp_path):
    s1 = ParquetStore(tmp_path / "a")
    s2 = ParquetStore(tmp_path / "b")
    s1.write(canon_daily(ROWS))
    s2.write(canon_daily(ROWS))
    start, end = datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 4, tzinfo=UTC)
    f1 = s1.snapshot(["X"], Timeframe.D1, start, end).fingerprint
    f2 = s2.snapshot(["X"], Timeframe.D1, start, end).fingerprint
    assert f1 == f2  # same data, independent stores -> same fingerprint

    s3 = ParquetStore(tmp_path / "c")
    changed = [(1, 10, 11, 9, 10.5, 100), (2, 10.5, 12, 10, 11.01, 120), (3, 11, 11.5, 10.5, 11, 90)]
    s3.write(canon_daily(changed))
    f3 = s3.snapshot(["X"], Timeframe.D1, start, end).fingerprint
    assert f3 != f1  # one close changed by a cent -> different fingerprint


def test_csv_and_parquet_providers_equivalent(tmp_path):
    df = canon_daily(ROWS)
    raw = df[["ts", "open", "high", "low", "close", "volume"]]
    raw.to_csv(tmp_path / "X.csv", index=False)
    raw.to_parquet(tmp_path / "X.parquet", index=False)

    csv_df = CSVProvider(tmp_path).fetch("X", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 31))
    pq_df = ParquetProvider(tmp_path).fetch("X", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 31))
    # Identical canonical VALUES -> identical checksums (source column may differ)
    assert frame_checksum(csv_df) == frame_checksum(pq_df) == frame_checksum(df)


# ── network adapters: fixtures only, zero internet ────────────────────
def test_yahoo_parses_fixture_and_stamps_session_close():
    # Yahoo stamps daily bars at session open epoch; adapter must re-stamp
    # to session close (21:00 UTC by default calendar).
    calls = {}

    def fake_transport(url, params, headers):
        calls["url"], calls["params"] = url, params
        return {
            "chart": {"result": [{
                "timestamp": [1704207000, 1704293400],  # 2024-01-02, 2024-01-03 14:30 UTC
                "indicators": {"quote": [{
                    "open": [10.0, 10.5], "high": [11.0, 12.0],
                    "low": [9.0, 10.0], "close": [10.5, 11.0],
                    "volume": [100, 120],
                }]},
            }]}
        }

    df = YahooProvider(transport=fake_transport).fetch(
        "TEST", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert "TEST" in calls["url"]
    assert calls["params"]["interval"] == "1d"
    assert list(df["ts"]) == [
        pd.Timestamp("2024-01-02 21:00", tz="UTC"),
        pd.Timestamp("2024-01-03 21:00", tz="UTC"),
    ]
    assert df["source"].iloc[0] == "yahoo"


def test_alpaca_requires_credentials(monkeypatch):
    monkeypatch.delenv("ALPACA_API_KEY", raising=False)
    monkeypatch.delenv("ALPACA_API_SECRET", raising=False)
    with pytest.raises(MissingCredentialsError, match="ALPACA_API_KEY"):
        AlpacaProvider()


def test_alpaca_builds_auth_headers_and_shifts_intraday_to_close():
    seen = {}

    def fake_transport(url, params, headers):
        seen["headers"], seen["params"] = headers, params
        return {"bars": [
            {"t": "2024-01-02T15:00:00Z", "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100},
        ]}

    df = AlpacaProvider(api_key="k", api_secret="s", transport=fake_transport).fetch(
        "TEST", Timeframe.H1, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert seen["headers"]["APCA-API-KEY-ID"] == "k"
    assert seen["params"]["timeframe"] == "1Hour"
    assert seen["params"]["adjustment"] == "raw"
    # Alpaca stamps bar START; canonical ts is COMPLETION -> +1h.
    assert df["ts"].iloc[0] == pd.Timestamp("2024-01-02 16:00", tz="UTC")


def test_polygon_requires_key_and_parses_epoch_ms(monkeypatch):
    monkeypatch.delenv("POLYGON_API_KEY", raising=False)
    with pytest.raises(MissingCredentialsError):
        PolygonProvider()

    def fake_transport(url, params, headers):
        assert params["adjusted"] == "false"
        return {"results": [
            {"t": 1704229200000, "o": 10, "h": 11, "l": 9, "c": 10.5, "v": 100},  # 2024-01-02 21:00 UTC
        ]}

    df = PolygonProvider(api_key="k", transport=fake_transport).fetch(
        "TEST", Timeframe.D1, date(2024, 1, 1), date(2024, 1, 5)
    )
    assert df["ts"].iloc[0] == pd.Timestamp("2024-01-02 21:00", tz="UTC")
