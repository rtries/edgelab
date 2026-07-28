"""Corporate-action adjustment layer.

The Parquet store holds RAW prices only. Adjustment is an explicit,
at-load-time transformation; the chosen mode travels in df.attrs and is
recorded in every backtest manifest. Feeds refuse mixed modes.

Definitions (back-adjustment; the latest bar is always unchanged):

SPLIT       For each split with ratio r (2.0 = 2-for-1) effective on
            ex_date: every bar strictly BEFORE ex_date has prices
            divided by r and volume multiplied by r.

TOTAL_RETURN  Split adjustment first. Then for each cash dividend with
            ex_date and amount d: let c = split-adjusted close of the
            last bar strictly before ex_date, and d' = d scaled by the
            same later-split factor as that close. Every bar strictly
            before ex_date has prices multiplied by (c - d') / c.
            (Standard CRSP-style proportional method.)
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from engine.data.schema_types import AdjustmentMode, DataValidationError

_PRICE_COLS = ["open", "high", "low", "close"]


@dataclass(frozen=True, slots=True)
class Split:
    ex_date: date
    ratio: float          # 2.0 = 2-for-1 split; 0.5 = 1-for-2 reverse split


@dataclass(frozen=True, slots=True)
class Dividend:
    ex_date: date
    amount: float         # cash per share, as declared at ex_date


def adjust(
    df: pd.DataFrame,
    *,
    splits: list[Split] | None = None,
    dividends: list[Dividend] | None = None,
    mode: AdjustmentMode,
) -> pd.DataFrame:
    """Returns a NEW canonical frame with attrs['adjustment_mode'] set.
    Raises if the input is not raw — adjusting twice is always a bug."""
    current = df.attrs.get("adjustment_mode", str(AdjustmentMode.RAW))
    if current != str(AdjustmentMode.RAW):
        raise DataValidationError(
            f"refusing to adjust data already in mode '{current}'"
        )
    out = df.copy()
    out.attrs["adjustment_mode"] = str(mode)
    if mode is AdjustmentMode.RAW:
        return out

    splits = sorted(splits or [], key=lambda s: s.ex_date)
    dividends = sorted(dividends or [], key=lambda d: d.ex_date)
    dates = out["ts"].dt.date

    # ── splits ────────────────────────────────────────────────────────
    price_factor = pd.Series(1.0, index=out.index)
    volume_factor = pd.Series(1.0, index=out.index)
    for s in splits:
        if s.ratio <= 0:
            raise DataValidationError(f"split ratio must be positive: {s}")
        before = dates < s.ex_date
        price_factor[before] /= s.ratio
        volume_factor[before] *= s.ratio
    for col in _PRICE_COLS:
        out[col] = out[col] * price_factor
    out["volume"] = out["volume"] * volume_factor

    if mode is AdjustmentMode.SPLIT:
        return out

    # ── dividends on the split-adjusted series ────────────────────────
    for d in dividends:
        if d.amount < 0:
            raise DataValidationError(f"negative dividend: {d}")
        before = dates < d.ex_date
        if not before.any():
            continue  # dividend predates our data window entirely? (no prior close)
        prior_idx = out.index[before][-1]
        c = float(out.loc[prior_idx, "close"])
        # scale declared amount by the later-split factor applied to that close
        d_adj = d.amount * float(price_factor[prior_idx])
        if d_adj >= c:
            raise DataValidationError(
                f"dividend {d} >= prior close {c}; data or actions corrupt"
            )
        out.loc[before, _PRICE_COLS] = out.loc[before, _PRICE_COLS] * ((c - d_adj) / c)
    return out
