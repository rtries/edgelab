"""Monte Carlo analysis. Every random component takes an explicit seed;
identical seeds produce identical outputs (tested).

TRADE-LEVEL RESAMPLING (reshuffle / bootstrap / random skip)
    Operates on the completed backtest's net trade P&Ls. Equity paths are
    rebuilt ADDITIVELY: equity_k = initial + sum(pnl_1..k). This is an
    approximation (real position sizing compounds), chosen because it is
    exact for the recorded trades and introduces no hidden model. Metrics
    per synthetic path:
      end_equity, cagr (from path endpoints over the ORIGINAL span),
      max_drawdown, profit_factor, expectancy,
      sharpe: per-trade returns r_k = pnl_k / equity_{k-1}, annualized by
      sqrt(trades_per_year) with trades_per_year = n_trades / span_years.
    All assumptions are visible here, none buried.

EXECUTION PERTURBATION (re-runs through the frozen engine)
    - perturbed_cost_runs: N full backtests, each with slippage and
      commission scaled by seeded multipliers. Ground truth, not proxy.
    - delayed_execution_runs: wraps the strategy in DelayedStrategy,
      which buffers every submission for `delay` additional bars of that
      order's symbol before forwarding it to the real context. The engine
      is untouched; delay is a strategy-layer transformation.

confidence_intervals(): np.quantile (linear interpolation) at the
requested levels across iterations.
"""
from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from engine.interfaces import TradingContext
from engine.types import Order, OrderStatus, OrderType, Side, TimeInForce

METRIC_KEYS = ["sharpe", "max_drawdown", "cagr", "profit_factor", "expectancy", "end_equity"]


# ── path metrics ──────────────────────────────────────────────────────
def path_metrics(pnls: np.ndarray, initial: float, span_years: float) -> dict[str, float]:
    equity = initial + np.concatenate([[0.0], np.cumsum(pnls)])
    end = float(equity[-1])
    cummax = np.maximum.accumulate(equity)
    max_dd = float(np.min(equity / cummax - 1.0)) if len(equity) else 0.0
    wins = pnls[pnls > 0].sum()
    losses = abs(pnls[pnls < 0].sum())
    pf = float("inf") if losses == 0 and wins > 0 else (0.0 if losses == 0 else float(wins / losses))
    expectancy = float(pnls.mean()) if len(pnls) else 0.0
    cagr = (end / initial) ** (1.0 / span_years) - 1.0 if span_years > 0 and end > 0 else 0.0

    prev = equity[:-1]
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.where(prev > 0, pnls / prev, 0.0)
    if len(rets) >= 2 and rets.std(ddof=1) > 0:
        trades_per_year = len(pnls) / span_years if span_years > 0 else float(len(pnls))
        sharpe = float(rets.mean() / rets.std(ddof=1) * np.sqrt(trades_per_year))
    else:
        sharpe = 0.0
    return {
        "sharpe": sharpe,
        "max_drawdown": max_dd,
        "cagr": float(cagr),
        "profit_factor": pf,
        "expectancy": expectancy,
        "end_equity": end,
    }


@dataclass(slots=True)
class MCResult:
    samples: pd.DataFrame              # one row per iteration, METRIC_KEYS columns
    ci: pd.DataFrame                   # rows = metrics, cols = quantile levels
    method: str
    seed: int
    n_iter: int


def confidence_intervals(
    samples: pd.DataFrame, levels: Sequence[float] = (0.025, 0.5, 0.975)
) -> pd.DataFrame:
    rows = {}
    for col in samples.columns:
        clean = samples[col].replace([np.inf, -np.inf], np.nan).dropna()
        rows[col] = (
            {f"q{lv}": float(np.quantile(clean, lv)) for lv in levels}
            if len(clean)
            else {f"q{lv}": float("nan") for lv in levels}
        )
    return pd.DataFrame(rows).T


def _resample_mc(
    trade_pnls: Sequence[float],
    initial: float,
    span_years: float,
    n_iter: int,
    seed: int,
    method: str,
    skip_prob: float = 0.0,
) -> MCResult:
    pnls = np.asarray(trade_pnls, dtype=float)
    if len(pnls) == 0:
        raise ValueError("no trades to resample")
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_iter):
        if method == "reshuffle":
            sample = rng.permutation(pnls)
        elif method == "bootstrap":
            sample = rng.choice(pnls, size=len(pnls), replace=True)
        elif method == "skip":
            keep = rng.uniform(size=len(pnls)) >= skip_prob
            sample = pnls[keep]
            if len(sample) == 0:
                sample = pnls[[rng.integers(0, len(pnls))]]
        else:
            raise ValueError(f"unknown method {method}")
        rows.append(path_metrics(sample, initial, span_years))
    samples = pd.DataFrame(rows)
    return MCResult(
        samples=samples,
        ci=confidence_intervals(samples),
        method=method,
        seed=seed,
        n_iter=n_iter,
    )


def trade_reshuffle(trade_pnls, initial, span_years, n_iter=1000, seed=0) -> MCResult:
    return _resample_mc(trade_pnls, initial, span_years, n_iter, seed, "reshuffle")


def bootstrap_trades(trade_pnls, initial, span_years, n_iter=1000, seed=0) -> MCResult:
    return _resample_mc(trade_pnls, initial, span_years, n_iter, seed, "bootstrap")


def skip_trades(
    trade_pnls, initial, span_years, n_iter=1000, seed=0, skip_prob=0.1
) -> MCResult:
    return _resample_mc(trade_pnls, initial, span_years, n_iter, seed, "skip", skip_prob)


# ── execution perturbations (full engine re-runs) ─────────────────────
def perturbed_cost_runs(
    run_with_cost_scales: Callable[[float, float], object],
    n_iter: int,
    seed: int,
    slippage_range: tuple[float, float] = (0.5, 2.0),
    commission_range: tuple[float, float] = (0.5, 2.0),
) -> MCResult:
    """run_with_cost_scales(slippage_mult, commission_mult) -> BacktestResult.
    Each iteration draws multipliers from the seeded RNG and re-runs the
    full (deterministic) backtest."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n_iter):
        s_mult = float(rng.uniform(*slippage_range))
        c_mult = float(rng.uniform(*commission_range))
        result = run_with_cost_scales(s_mult, c_mult)
        m = result.metrics
        rows.append({k: m.get(k, float("nan")) for k in METRIC_KEYS if k != "end_equity"}
                    | {"end_equity": m.get("end_equity", float("nan")),
                       "slippage_mult": s_mult, "commission_mult": c_mult})
    samples = pd.DataFrame(rows)
    metric_cols = samples[[c for c in samples.columns if c in METRIC_KEYS]]
    return MCResult(
        samples=samples,
        ci=confidence_intervals(metric_cols),
        method="perturbed_costs",
        seed=seed,
        n_iter=n_iter,
    )


def delayed_execution_runs(
    run_with_delay: Callable[[int], object],
    delays: Sequence[int],
) -> pd.DataFrame:
    """Deterministic sweep: one full backtest per delay value. Returns a
    table of metrics per delay (delays are few and discrete; sweeping all
    of them beats sampling)."""
    rows = []
    for d in delays:
        result = run_with_delay(int(d))
        rows.append({"delay_bars": int(d), **result.metrics})
    return pd.DataFrame(rows)


# ── strategy-layer delay wrapper (engine untouched) ───────────────────
@dataclass(slots=True)
class _Intent:
    symbol: str
    side: Side
    qty: float
    type: OrderType
    limit_price: float | None
    stop_price: float | None
    tif: TimeInForce
    release_at_count: int


class _DeferringContext:
    """Context proxy: reads pass through; submissions are queued."""

    def __init__(self, wrapper: "DelayedStrategy", real: TradingContext, symbol_count: int):
        self._wrapper = wrapper
        self._real = real
        self._count = symbol_count

    @property
    def portfolio(self):  # noqa: ANN201
        return self._real.portfolio

    def pending_orders(self, symbol: str | None = None):
        return self._real.pending_orders(symbol)

    def cancel(self, order_id: int) -> bool:
        return self._real.cancel(order_id)

    def submit(
        self,
        symbol: str,
        side: Side,
        qty: float,
        type: OrderType = OrderType.MARKET,  # noqa: A002
        limit_price: float | None = None,
        stop_price: float | None = None,
        tif: TimeInForce = TimeInForce.GTC,
    ) -> Order:
        if self._wrapper.delay_bars == 0:
            # No delay: behave exactly like the unwrapped context.
            return self._real.submit(symbol, side, qty, type, limit_price, stop_price, tif)
        self._wrapper.queue.append(
            _Intent(symbol, side, qty, type, limit_price, stop_price, tif,
                    release_at_count=self._count + self._wrapper.delay_bars)
        )
        # Placeholder for API compatibility; not an engine order.
        return Order(id=-1, symbol=symbol, side=side, qty=qty, type=type,
                     limit_price=limit_price, stop_price=stop_price,
                     status=OrderStatus.PENDING)


class DelayedStrategy:
    """Wraps any engine-protocol Strategy; every submission waits
    `delay_bars` additional bars of its symbol before reaching the real
    context. delay_bars=0 must be behaviorally identical to no wrapper
    (tested)."""

    def __init__(self, inner, delay_bars: int) -> None:
        if delay_bars < 0:
            raise ValueError("delay_bars must be >= 0")
        self.inner = inner
        self.delay_bars = delay_bars
        self.queue: list[_Intent] = []
        self._bar_count: dict[str, int] = {}

    def on_start(self, ctx: TradingContext, params: dict) -> None:
        self.inner.on_start(_DeferringContext(self, ctx, 0), params)

    def on_bar(self, bar, ctx: TradingContext) -> None:  # noqa: ANN001
        count = self._bar_count.get(bar.symbol, 0) + 1
        self._bar_count[bar.symbol] = count
        due = [i for i in self.queue
               if i.symbol == bar.symbol and i.release_at_count <= count]
        for intent in due:
            self.queue.remove(intent)
            ctx.submit(intent.symbol, intent.side, intent.qty, intent.type,
                       intent.limit_price, intent.stop_price, intent.tif)
        self.inner.on_bar(bar, _DeferringContext(self, ctx, count))

    def on_fill(self, fill) -> None:  # noqa: ANN001
        self.inner.on_fill(fill)
