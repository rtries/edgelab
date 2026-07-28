# Engine semantics (Phase 1)

Authoritative reference for how the simulator behaves. Every rule here is
enforced by a test in `backend/tests/`.

## Event loop (per bar)
1. **Fills** — open orders for the bar's symbol, in submission-id order.
   An order can never fill on the bar it was submitted during
   (`eligible_after` gate). DAY orders die on the first bar of a later
   calendar date.
2. **Mark** — symbol marked at bar close; equity + exposure recorded.
3. **Signal** — `strategy.on_bar` runs; submissions validate immediately
   (risk veto → buying-power check) and become eligible next bar.

## Fill semantics (all conservative)
| Type | Rule |
|---|---|
| Market | Fills at bar **open**, aggressive (slippage + half-spread against you) |
| Limit | Fills at limit if touched intrabar; at **open if the market gaps through favorably** (you fill better, never worse); passive (no slippage) |
| Stop | Triggers intrabar → fills at stop (aggressive). **Gap through the stop → fills at the open**, not your stop price |
| Stop-limit | Stop latches (`triggered`); fills only if the limit is marketable at the trigger; otherwise rests as a limit. No favorable intrabar path is assumed after triggering |
| Any | **Zero volume ⇒ no fill.** Fill size capped at `max_participation × bar volume`; remainder stays open (`PARTIAL`) |

## Accounting identities (hold at every bar; invariant-tested)
```
equity       = cash + long_value − short_value
equity       = initial_cash + realized_pnl + unrealized_pnl − total_fees
buying_power = max(0, margin_multiplier × equity − gross_exposure)
```
- Realized P&L is **gross**; fees accumulate separately (fee drag is always
  visible, and the second identity stays exact).
- Short proceeds credit cash; short market value is a liability.
- Order rejection checks only the **exposure-increasing** portion — closing
  a position is always allowed.
- Lot matching is pluggable FIFO/LIFO; oversized opposing fills flip the
  book and split into two round trips.

## Metric definitions
Pinned in the docstring of `engine/metrics/performance.py`. Sharpe uses
sample std (ddof=1) × √252; Sortino uses full-sample downside deviation;
win rate counts breakeven trades as non-wins. If a definition changes, its
hand-computed fixture must change with it.

## Known simplifications (deliberate, revisit later)
- Float arithmetic with 1e-6 test tolerance (a Decimal ledger can swap in
  behind the same Portfolio interface).
- No borrow fees / short locate, no overnight margin interest.
- DAY orders expire on date change, not exchange session close.
- Volume participation is a flat cap, not an impact model.
