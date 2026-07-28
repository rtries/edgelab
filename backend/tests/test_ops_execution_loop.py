"""Paper execution mechanics, backtester signal parity, crash recovery."""
import dataclasses
import json
from datetime import UTC, datetime

import pytest

from engine.backtest import Backtester
from engine.data.feeds import DataFrameFeed
from engine.data.history import HistoryService
from engine.data.schema_types import Timeframe
from engine.execution.costs import SimpleCostModel
from engine.params import resolve_params
from engine.sdk import SDKAdapter
from engine.strategies.examples import MACrossover
from engine.types import Side
from ops.deployments import RiskPolicy, deployment_from_experiment
from ops.events import MarketEvent, ReplayFeed, SimulatedLiveFeed
from ops.execution import EventLog, Ledger, PaperBroker
from ops.loop import LiveLoop
from ops.risk import SignalCandidate

from tests.ops_fixtures import ops_env  # noqa: F401

TS0 = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)


def bar_event(day: int, close: float, volume: float = 1e6, symbol="DEMO"):
    ts = datetime(2026, 1, day, 16, 0, tzinfo=UTC)
    return MarketEvent(kind="bar", symbol=symbol, ts=ts, received_at=ts,
                       data={"open": close - 0.5, "high": close + 1,
                             "low": close - 1, "close": close,
                             "volume": volume})


def make_candidate(ts, side=Side.BUY, qty=10.0):
    return SignalCandidate(deployment_id="d1", strategy="S", symbol="DEMO",
                           side=side, qty=qty, ts=ts, received_at=ts)


@pytest.fixture()
def broker(tmp_path):
    ledger = Ledger(initial_cash=100_000)
    log = EventLog(tmp_path / "paper.jsonl", stream="paper")
    return PaperBroker(ledger, log, cost_model=SimpleCostModel(),
                       max_participation=0.1), ledger, log


def test_next_bar_fill_price_hand_computed(broker):
    pb, ledger, log = broker
    bar1 = bar_event(5, 100.0)
    pb.on_event(bar1)
    ledger.mark("DEMO", 100.0, bar1.ts)
    order = pb.submit(make_candidate(bar1.ts), qty=10)
    assert order is not None
    # No fill on the signal bar; fills at the NEXT bar.
    assert pb.on_event(bar1) == []
    bar2 = bar_event(6, 102.0)                 # open = 101.5
    fills = pb.on_event(bar2)
    assert len(fills) == 1
    fill = fills[0]
    # No quote seen -> base = open + half modeled spread, + slippage:
    # half spread = 101.5 * 0.5bps/2 = 101.5 * 0.000025 = 0.00253750
    # base = 101.50253750; slip = base * 1bp = 0.01015025
    # price = 101.51268775
    assert fill.price == pytest.approx(101.51268775, rel=1e-9)
    # commission = max(0.005 * 10, 1.0) = 1.0
    assert fill.fees == 1.0
    assert fill.ts == bar2.ts
    kinds = [r["kind"] for r in log.records()]
    assert kinds == ["order_submitted", "fill"]


def test_quote_crossing_spread(broker):
    pb, ledger, _ = broker
    bar1 = bar_event(5, 100.0)
    pb.on_event(bar1)
    ledger.mark("DEMO", 100.0, bar1.ts)
    pb.submit(make_candidate(bar1.ts), qty=10)
    quote = MarketEvent(kind="quote", symbol="DEMO", ts=bar1.ts,
                        received_at=bar1.ts,
                        data={"bid": 101.0, "ask": 101.2, "spread_bps": 19.8})
    pb.on_event(quote)
    fills = pb.on_event(bar_event(6, 102.0))
    # buy lifts the ask + slippage: 101.2 * (1 + 1e-4) = 101.21012
    assert fills[0].price == pytest.approx(101.21012, rel=1e-9)


def test_partial_fill_on_participation_cap(broker):
    pb, ledger, log = broker
    bar1 = bar_event(5, 100.0, volume=1e6)
    pb.on_event(bar1)
    ledger.mark("DEMO", 100.0, bar1.ts)
    pb.submit(make_candidate(bar1.ts, qty=300), qty=300)
    thin = bar_event(6, 100.0, volume=2000)    # cap = 0.1 * 2000 = 200
    fills = pb.on_event(thin)
    assert fills[0].qty == 200.0
    assert pb.working_orders("DEMO")[0].remaining == 100.0
    # remainder fills on the following bar
    fills2 = pb.on_event(bar_event(7, 100.0, volume=2000))
    assert fills2[0].qty == 100.0
    assert pb.working_orders("DEMO") == []
    partial_flags = [r["partial"] for r in log.records() if r["kind"] == "fill"]
    assert partial_flags == [True, False]


def test_rejections_logged(broker):
    pb, ledger, log = broker
    bar1 = bar_event(5, 100.0)
    pb.on_event(bar1)
    ledger.mark("DEMO", 100.0, bar1.ts)
    # market closed (Saturday)
    weekend = dataclasses.replace(make_candidate(bar1.ts),
                                  ts=datetime(2026, 1, 3, 16, 0, tzinfo=UTC))
    assert pb.submit(weekend, qty=10) is None
    # insufficient cash
    assert pb.submit(make_candidate(bar1.ts), qty=10_000) is None
    reasons = [r["reason"] for r in log.records() if r["kind"] == "order_rejected"]
    assert reasons[0] == "market closed"
    assert "insufficient buying power" in reasons[1]


def test_ledger_round_trip_pairing(broker):
    pb, ledger, _ = broker
    for day, close, action in [
        (5, 100.0, ("buy", 10)), (6, 101.0, None), (7, 103.0, ("sell", 10)),
        (8, 104.0, None),
    ]:
        bar = bar_event(day, close)
        pb.on_event(bar)
        ledger.mark("DEMO", close, bar.ts)
        if action:
            side = Side.BUY if action[0] == "buy" else Side.SELL
            pb.submit(make_candidate(bar.ts, side=side, qty=action[1]),
                      qty=action[1])
    assert len(ledger.round_trips) == 1
    rt = ledger.round_trips[0]
    assert rt.qty == 10 and rt.direction == 1
    assert rt.gross_pnl > 0                    # bought ~100.5, sold ~103.5
    # equity identity: cash + marks == equity
    p = ledger.portfolio
    assert p.equity == pytest.approx(
        p.cash + sum(p.position_qty(s) * p.last_price[s] for s in p.books)
    )


# ── the two critical guarantees ───────────────────────────────────────
def full_loop(ops_env, tmp_path, name, feed=None, checkpoint=None,
              policy=None):
    exp = ops_env["experiment"]
    dep = deployment_from_experiment(
        exp,
        risk=policy or RiskPolicy(
            sizing_mode="fixed_qty", sizing_value=10,
            min_dollar_volume=0.0, max_spread_bps=1e9,
            max_position_pct=100.0, max_gross_exposure_pct=100.0,
            daily_loss_limit_pct=1.0,
        ),
    )
    dep = dataclasses.replace(dep, confidence="strong", id="")
    ledger = Ledger(initial_cash=100_000)
    log = EventLog(tmp_path / f"{name}.jsonl", stream="paper")
    broker = PaperBroker(ledger, log, max_participation=None)
    feed = feed or ReplayFeed(ops_env["data_store"], ["DEMO"], Timeframe.D1)
    return LiveLoop(dep, feed, ledger, broker, log,
                    checkpoint_path=checkpoint), dep


def test_runtime_signal_parity_with_backtester(ops_env, tmp_path):
    """THE parity test: on identical bars, the runtime's approved signal
    stream equals the backtester's order stream (ts, symbol, side, qty)."""
    exp = ops_env["experiment"]
    loop, dep = full_loop(ops_env, tmp_path, "parity")
    loop.run()
    submitted = [r for r in loop.log.records() if r["kind"] == "order_submitted"]

    frames = {"DEMO": ops_env["data_store"].read("DEMO", Timeframe.D1)}
    history = HistoryService({("DEMO", "1d"): frames["DEMO"]})
    adapter = SDKAdapter(
        MACrossover(),
        resolve_params(MACrossover.params, dep.params),
        history,
    )
    bt = Backtester(DataFrameFeed(frames), adapter, SimpleCostModel(),
                    initial_cash=100_000, max_participation=None)
    result = bt.run(resolve_params(MACrossover.params, dep.params))

    bt_orders = [(o.created_ts.isoformat(), o.symbol, o.side.value)
                 for o in result.orders]
    live_orders = [(r["ts"], r["symbol"], r["side"]) for r in submitted]
    assert len(live_orders) == len(bt_orders) > 0
    assert live_orders == bt_orders


def test_crash_recovery_equals_uninterrupted_run(ops_env, tmp_path):
    # Uninterrupted reference run.
    ref, _ = full_loop(ops_env, tmp_path, "ref")
    ref_summary = ref.run()

    # Crashed run: process 60 events, checkpoint, abandon the loop object.
    ckpt = tmp_path / "ckpt.json"
    crashed, dep = full_loop(ops_env, tmp_path, "crashed", checkpoint=ckpt)
    crashed.checkpoint_every = 10
    crashed.run(max_events=60)
    assert ckpt.exists()

    # Resume in a NEW loop from the checkpoint and finish.
    log2 = EventLog(tmp_path / "crashed.jsonl", stream="paper")
    feed = ReplayFeed(ops_env["data_store"], ["DEMO"], Timeframe.D1)
    resumed = LiveLoop.resume(dep, feed, log2, ckpt)
    resumed_summary = resumed.run_resumed()

    assert resumed_summary["processed_events"] == ref_summary["processed_events"]
    assert resumed_summary["n_trades"] == ref_summary["n_trades"]
    assert resumed_summary["ledger"]["equity"] == pytest.approx(
        ref_summary["ledger"]["equity"]
    )
    assert resumed_summary["ledger"]["cash"] == pytest.approx(
        ref_summary["ledger"]["cash"]
    )
    # fill-for-fill: the combined crashed+resumed log equals the reference log
    ref_fills = [(r["ts"], r["qty"], r["price"])
                 for r in ref.log.records() if r["kind"] == "fill"]
    combined_fills = [(r["ts"], r["qty"], r["price"])
                      for r in log2.records() if r["kind"] == "fill"]
    assert combined_fills == ref_fills


def test_sim_live_feed_through_loop_deterministic(ops_env, tmp_path):
    replay = ReplayFeed(ops_env["data_store"], ["DEMO"], Timeframe.D1)
    loop_a, _ = full_loop(ops_env, tmp_path, "sim_a",
                          feed=SimulatedLiveFeed(replay, seed=3))
    loop_b, _ = full_loop(ops_env, tmp_path, "sim_b",
                          feed=SimulatedLiveFeed(replay, seed=3))
    a, b = loop_a.run(), loop_b.run()
    assert a["ledger"] == b["ledger"]
    # same schema across the log streams (identical-logs requirement)
    keys_a = {frozenset(r) for r in loop_a.log.records() if r["kind"] == "fill"}
    keys_b = {frozenset(r) for r in loop_b.log.records() if r["kind"] == "fill"}
    assert keys_a == keys_b


def test_emergency_stop_flag_blocks_new_orders(ops_env, tmp_path):
    stop = {"on": False}
    loop, _ = full_loop(ops_env, tmp_path, "estop")
    loop.emergency_stop_flag = lambda: stop["on"]
    events = list(loop.feed.events())
    for event in events[:40]:
        loop.process(event)
    orders_before = len([r for r in loop.log.records()
                         if r["kind"] == "order_submitted"])
    stop["on"] = True
    for event in events[40:]:
        loop.process(event)
    records = loop.log.records()
    orders_after = len([r for r in records if r["kind"] == "order_submitted"])
    assert orders_after == orders_before      # nothing new got through
    stops = [r for r in records if r.get("check") == "emergency_stop"]
    assert len(stops) > 0                      # and the blocks left evidence
