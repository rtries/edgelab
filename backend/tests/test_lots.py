"""Lot book: FIFO/LIFO matching, flips, average entry. All hand-calculated."""
from engine.portfolio.lots import LotBook
from engine.types import LotMethod, Side

from tests.helpers import ts


def test_fifo_realized_pnl():
    # Buy 10 @ 100, buy 10 @ 110, sell 10 @ 120.
    # FIFO consumes the 100-lot: realized = (120 - 100) * 10 = 200.
    # Remaining: 10 @ 110.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.BUY, 10, 100.0, ts(1))
    book.apply(Side.BUY, 10, 110.0, ts(2))
    result = book.apply(Side.SELL, 10, 120.0, ts(3))
    assert result.realized_pnl == 200.0
    assert book.qty == 10
    assert book.avg_price == 110.0


def test_lifo_realized_pnl():
    # Same trades, LIFO consumes the 110-lot: realized = (120 - 110) * 10 = 100.
    # Remaining: 10 @ 100.
    book = LotBook(method=LotMethod.LIFO)
    book.apply(Side.BUY, 10, 100.0, ts(1))
    book.apply(Side.BUY, 10, 110.0, ts(2))
    result = book.apply(Side.SELL, 10, 120.0, ts(3))
    assert result.realized_pnl == 100.0
    assert book.qty == 10
    assert book.avg_price == 100.0


def test_partial_lot_consumption():
    # Buy 10 @ 100; sell 4 @ 105 -> realized 20, 6 left @ 100.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.BUY, 10, 100.0, ts(1))
    result = book.apply(Side.SELL, 4, 105.0, ts(2))
    assert result.realized_pnl == 20.0
    assert result.closed_qty == 4
    assert result.opened_qty == 0
    assert book.qty == 6
    assert book.avg_price == 100.0


def test_flip_long_to_short_in_one_fill():
    # Long 5 @ 100; sell 8 @ 90:
    #   closes 5 -> realized (90 - 100) * 5 = -50
    #   opens short 3 @ 90.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.BUY, 5, 100.0, ts(1))
    result = book.apply(Side.SELL, 8, 90.0, ts(2))
    assert result.realized_pnl == -50.0
    assert result.closed_qty == 5
    assert result.opened_qty == 3
    assert book.qty == -3
    assert book.direction == -1
    assert book.avg_price == 90.0


def test_short_lot_pnl_and_unrealized():
    # Short 10 @ 50; price falls to 45: unrealized = (50 - 45) * 10 = +50.
    # Cover 10 @ 45: realized +50, book flat.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.SELL, 10, 50.0, ts(1))
    assert book.qty == -10
    assert book.unrealized_pnl(45.0) == 50.0
    result = book.apply(Side.BUY, 10, 45.0, ts(2))
    assert result.realized_pnl == 50.0
    assert book.qty == 0
    assert book.direction == 0


def test_weighted_average_entry():
    # 10 @ 100 and 30 @ 120 -> avg = (1000 + 3600) / 40 = 115.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.BUY, 10, 100.0, ts(1))
    book.apply(Side.BUY, 30, 120.0, ts(2))
    assert book.avg_price == 115.0
    assert book.qty == 40


def test_multi_lot_close_spans_lots():
    # Buy 5 @ 100, buy 5 @ 110; sell 8 @ 120 (FIFO):
    #   5 from lot1: (120-100)*5 = 100
    #   3 from lot2: (120-110)*3 = 30    -> realized 130, 2 @ 110 remain.
    book = LotBook(method=LotMethod.FIFO)
    book.apply(Side.BUY, 5, 100.0, ts(1))
    book.apply(Side.BUY, 5, 110.0, ts(2))
    result = book.apply(Side.SELL, 8, 120.0, ts(3))
    assert result.realized_pnl == 130.0
    assert len(result.closed) == 2
    assert book.qty == 2
    assert book.avg_price == 110.0
