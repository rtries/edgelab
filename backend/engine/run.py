"""Reproducible research runs.

run_research_backtest() is the one entry point that ties together: store
reads, explicit adjustment, SDK strategies, the Phase 1 engine, metrics,
and a RunManifest recording everything needed to reproduce the run.

Reproducibility contract (tested): same strategy class, params, engine
version, and dataset fingerprint => identical equity curve, trades, and
fills. The only field allowed to differ is run_at.
"""
from __future__ import annotations

import hashlib
import inspect
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from engine import __version__ as ENGINE_VERSION
from engine.backtest import Backtester, BacktestResult
from engine.data.adjustments import Dividend, Split, adjust
from engine.data.feeds import DataFrameFeed
from engine.data.history import HistoryService
from engine.data.schema_types import AdjustmentMode, Timeframe
from engine.data.store import ParquetStore
from engine.interfaces import ExecutionCostModel
from engine.metrics.performance import full_report
from engine.params import resolve_params
from engine.sdk import SDKAdapter, SDKStrategy
from engine.types import LotMethod


def strategy_code_hash(strategy: SDKStrategy) -> str:
    """sha256 of the strategy class source. Edits to the code change the
    hash; runs pinned to a hash are pinned to exact logic."""
    src = inspect.getsource(type(strategy))
    return hashlib.sha256(src.encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class RunManifest:
    strategy_name: str
    strategy_code_hash: str
    params: dict
    dataset_fingerprint: str
    dataset_snapshot: dict
    symbols: tuple[str, ...]
    timeframe: str
    start: str
    end: str
    adjustment_mode: str
    commission_model: str
    slippage_model: str
    engine_version: str
    initial_cash: float
    margin_multiplier: float
    lot_method: str
    max_participation: float | None
    run_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_research_backtest(
    *,
    store: ParquetStore,
    strategy: SDKStrategy,
    symbols: list[str],
    timeframe: Timeframe,
    start: datetime,
    end: datetime,
    params: dict | None = None,
    cost_model: ExecutionCostModel,
    adjustment_mode: AdjustmentMode = AdjustmentMode.RAW,
    splits: dict[str, list[Split]] | None = None,
    dividends: dict[str, list[Dividend]] | None = None,
    initial_cash: float = 100_000.0,
    margin_multiplier: float = 1.0,
    lot_method: LotMethod = LotMethod.FIFO,
    max_participation: float | None = 0.1,
    extra_history: dict[tuple[str, str], "object"] | None = None,
) -> BacktestResult:
    resolved = resolve_params(strategy.params, params)

    # Dataset: fingerprint the exact slice, then load + explicitly adjust.
    snapshot = store.snapshot(symbols, timeframe, start, end)
    frames = {}
    for sym in symbols:
        raw = store.read(sym, timeframe, start, end)
        frames[sym] = adjust(
            raw,
            splits=(splits or {}).get(sym),
            dividends=(dividends or {}).get(sym),
            mode=adjustment_mode,
        )

    history_frames = {(sym, str(timeframe)): df for sym, df in frames.items()}
    if extra_history:
        history_frames.update(extra_history)  # e.g. higher-timeframe context
    history = HistoryService(history_frames)

    adapter = SDKAdapter(strategy, resolved, history_service=history)
    feed = DataFrameFeed(frames)
    engine = Backtester(
        feed=feed,
        strategy=adapter,
        cost_model=cost_model,
        initial_cash=initial_cash,
        margin_multiplier=margin_multiplier,
        lot_method=lot_method,
        max_participation=max_participation,
    )
    result = engine.run(resolved)

    result.metrics = full_report(
        result.equity_curve, result.trade_pnls, result.exposure
    ) if len(result.equity_curve) else {}

    manifest = RunManifest(
        strategy_name=type(strategy).__name__,
        strategy_code_hash=strategy_code_hash(strategy),
        params=resolved,
        dataset_fingerprint=snapshot.fingerprint,
        dataset_snapshot=snapshot.to_dict(),
        symbols=tuple(sorted(symbols)),
        timeframe=str(timeframe),
        start=str(start),
        end=str(end),
        adjustment_mode=str(adjustment_mode),
        commission_model=repr(cost_model),
        slippage_model=repr(cost_model),
        engine_version=ENGINE_VERSION,
        initial_cash=initial_cash,
        margin_multiplier=margin_multiplier,
        lot_method=str(lot_method),
        max_participation=max_participation,
        run_at=datetime.now(UTC).isoformat(),
    )
    result.manifest = manifest.to_dict()
    return result
