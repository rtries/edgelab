"""Local Parquet store with integrity tracking and dataset fingerprints.

Layout:
  root/
    manifest.json                     partition metadata + checksums
    {timeframe}/{symbol}.parquet      RAW canonical data, one partition
                                      per (symbol, timeframe)

Rules:
- The store holds RAW prices ONLY. Writing adjusted data is refused;
  adjustment happens at load time and is recorded in run manifests.
- Writes are incremental merges. Rows identical to existing rows are
  idempotent no-ops. A row with an existing (symbol, ts) key but
  DIFFERENT values is a conflict -> DataIntegrityError. Nothing is
  silently repaired or overwritten.
- Checksums are sha256 over a canonical CSV serialization of the values
  (not the parquet bytes, which are not byte-stable across writers), so
  the same data always fingerprints identically — including when it
  arrived via CSV vs Parquet providers.
- snapshot() fingerprints the exact (symbols, timeframe, range) slice a
  backtest consumes; the manifest of every run stores it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from engine.data.schema import CANONICAL_COLUMNS, validate
from engine.data.schema_types import (
    AdjustmentMode,
    DataIntegrityError,
    Timeframe,
)

_VALUE_COLS = ["ts", "open", "high", "low", "close", "volume"]


def frame_checksum(df: pd.DataFrame) -> str:
    """Deterministic content hash of a canonical frame's values."""
    payload = df[_VALUE_COLS].to_csv(index=False, float_format="%.10g")
    return hashlib.sha256(payload.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class DatasetSnapshot:
    symbols: tuple[str, ...]
    timeframe: str
    start: str
    end: str
    per_symbol_checksums: tuple[tuple[str, str], ...]
    fingerprint: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class _PartitionMeta:
    rows: int
    start: str
    end: str
    sources: list[str]
    checksum: str
    updated_at: str


@dataclass(slots=True)
class ParquetStore:
    root: Path
    _manifest: dict[str, dict] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        self.root.mkdir(parents=True, exist_ok=True)
        mf = self.root / "manifest.json"
        if mf.exists():
            self._manifest = json.loads(mf.read_text())

    # ── internals ─────────────────────────────────────────────────────
    def _key(self, symbol: str, timeframe: Timeframe | str) -> str:
        return f"{timeframe}/{symbol}"

    def _path(self, symbol: str, timeframe: Timeframe | str) -> Path:
        return self.root / str(timeframe) / f"{symbol}.parquet"

    def _save_manifest(self) -> None:
        (self.root / "manifest.json").write_text(json.dumps(self._manifest, indent=2))

    # ── writes ────────────────────────────────────────────────────────
    def write(self, df: pd.DataFrame) -> _PartitionMeta:
        if len(df) == 0:
            raise DataIntegrityError("refusing to write an empty frame")
        mode = df.attrs.get("adjustment_mode", str(AdjustmentMode.RAW))
        if mode != str(AdjustmentMode.RAW):
            raise DataIntegrityError(
                f"store holds raw data only; got adjustment_mode='{mode}'"
            )
        validate(df)
        symbol = str(df["symbol"].iloc[0])
        timeframe = str(df["timeframe"].iloc[0])
        if (df["symbol"] != symbol).any() or (df["timeframe"] != timeframe).any():
            raise DataIntegrityError("write() takes one (symbol, timeframe) at a time")

        path = self._path(symbol, timeframe)
        if path.exists():
            existing = pd.read_parquet(path)
            merged = pd.concat([existing, df], ignore_index=True)
            merged = merged.drop_duplicates(subset=CANONICAL_COLUMNS, keep="first")
            conflicts = merged.duplicated(subset=["symbol", "ts"], keep=False)
            if conflicts.any():
                clash = merged.loc[conflicts, "ts"].astype(str).unique()[:5].tolist()
                raise DataIntegrityError(
                    f"{symbol} {timeframe}: conflicting values for existing "
                    f"timestamps (e.g. {clash}); refusing to overwrite"
                )
            merged = merged.sort_values("ts", kind="stable").reset_index(drop=True)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            merged = df.sort_values("ts", kind="stable").reset_index(drop=True)

        merged.attrs["adjustment_mode"] = str(AdjustmentMode.RAW)
        validate(merged)
        merged.to_parquet(path, index=False)

        sources = sorted(set(merged["source"].astype(str)))
        meta = _PartitionMeta(
            rows=len(merged),
            start=str(merged["ts"].iloc[0]),
            end=str(merged["ts"].iloc[-1]),
            sources=sources,
            checksum=frame_checksum(merged),
            updated_at=datetime.now(UTC).isoformat(),
        )
        self._manifest[self._key(symbol, timeframe)] = asdict(meta)
        self._save_manifest()
        return meta

    # ── reads ─────────────────────────────────────────────────────────
    def read(
        self,
        symbol: str,
        timeframe: Timeframe | str,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> pd.DataFrame:
        path = self._path(symbol, timeframe)
        if not path.exists():
            raise FileNotFoundError(f"no data for {symbol} {timeframe} in {self.root}")
        df = pd.read_parquet(path)
        if start is not None:
            df = df[df["ts"] >= pd.Timestamp(start)]
        if end is not None:
            df = df[df["ts"] <= pd.Timestamp(end)]
        df = df.reset_index(drop=True)
        df.attrs["adjustment_mode"] = str(AdjustmentMode.RAW)
        return df

    # ── integrity ─────────────────────────────────────────────────────
    def verify(self, symbol: str, timeframe: Timeframe | str) -> bool:
        key = self._key(symbol, timeframe)
        meta = self._manifest.get(key)
        if meta is None:
            raise DataIntegrityError(f"no manifest entry for {key}")
        actual = frame_checksum(pd.read_parquet(self._path(symbol, timeframe)))
        if actual != meta["checksum"]:
            raise DataIntegrityError(
                f"{key}: checksum mismatch — stored data was modified outside "
                f"the store (manifest {meta['checksum'][:12]}…, actual {actual[:12]}…)"
            )
        return True

    def snapshot(
        self,
        symbols: list[str],
        timeframe: Timeframe | str,
        start: datetime,
        end: datetime,
    ) -> DatasetSnapshot:
        per_symbol = []
        for sym in sorted(symbols):
            df = self.read(sym, timeframe, start, end)
            per_symbol.append((sym, frame_checksum(df)))
        digest = hashlib.sha256(
            "|".join(f"{s}:{c}" for s, c in per_symbol).encode()
        ).hexdigest()
        return DatasetSnapshot(
            symbols=tuple(sorted(symbols)),
            timeframe=str(timeframe),
            start=str(pd.Timestamp(start)),
            end=str(pd.Timestamp(end)),
            per_symbol_checksums=tuple(per_symbol),
            fingerprint=digest,
        )
