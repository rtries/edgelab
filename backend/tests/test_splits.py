"""Window generation and final-test protection. Exact positions by hand."""
import pytest

from engine.validation.splits import WindowSpec, reserve_final_test

from tests.helpers import ts

IDX = [ts(d) for d in range(1, 21)]   # 20 bars: Jan 1 .. Jan 20


def test_rolling_windows_exact():
    # train 6, val 3, step 3 over 20 bars:
    # fold0: train pos 0-5,  val 6-8
    # fold1: train pos 3-8,  val 9-11
    # fold2: train pos 6-11, val 12-14
    # fold3: train pos 9-14, val 15-17
    # next train_end pos 17 -> val needs 18-20: only 18,19 exist -> stop.
    folds = WindowSpec(train_size=6, val_size=3, step=3).folds(IDX)
    assert len(folds) == 4
    assert folds[0].train_positions == (0, 5) and folds[0].val_positions == (6, 8)
    assert folds[1].train_positions == (3, 8) and folds[1].val_positions == (9, 11)
    assert folds[3].train_positions == (9, 14) and folds[3].val_positions == (15, 17)
    assert folds[0].train_start == ts(1) and folds[0].train_end == ts(6)
    assert folds[0].val_start == ts(7) and folds[0].val_end == ts(9)


def test_expanding_windows_grow_from_zero():
    folds = WindowSpec(train_size=6, val_size=3, step=3, expanding=True).folds(IDX)
    assert [f.train_positions for f in folds] == [(0, 5), (0, 8), (0, 11), (0, 14)]
    assert [f.val_positions for f in folds] == [(6, 8), (9, 11), (12, 14), (15, 17)]


def test_overlapping_validation_step_lt_val():
    # step 2 < val 4 -> validation windows overlap by 2 bars.
    folds = WindowSpec(train_size=8, val_size=4, step=2).folds(IDX)
    assert folds[0].val_positions == (8, 11)
    assert folds[1].val_positions == (10, 13)   # overlaps previous by 2


def test_default_step_is_val_size():
    folds = WindowSpec(train_size=6, val_size=3).folds(IDX)
    assert folds[1].train_positions == (3, 8)   # stepped by val_size = 3


def test_invalid_specs_raise():
    with pytest.raises(ValueError, match=">= 1"):
        WindowSpec(train_size=0, val_size=3).folds(IDX)
    with pytest.raises(ValueError, match="need >="):
        WindowSpec(train_size=15, val_size=10).folds(IDX)
    with pytest.raises(ValueError, match="step"):
        WindowSpec(train_size=5, val_size=3, step=0).folds(IDX)


def test_reserve_final_test_splits_tail():
    work, guard = reserve_final_test(IDX, test_size=5)
    assert len(work) == 15
    assert work[-1] == ts(15)
    assert guard.start == ts(16) and guard.end == ts(20)
    assert guard.n_bars == 5
    # Windows built on `work` can never touch the reserve.
    folds = WindowSpec(train_size=6, val_size=3).folds(work)
    assert all(f.val_end <= ts(15) for f in folds)


def test_final_test_evaluates_exactly_once():
    calls = []

    class FakeResult:
        metrics = {"sharpe": 1.0}

    def runner(params, start, end):
        calls.append((params, start, end))
        return FakeResult()

    work, guard = reserve_final_test(IDX, test_size=5)
    assert not guard.consumed
    guard.evaluate(runner, {"fast": 2})
    assert guard.consumed
    assert calls == [({"fast": 2}, ts(16), ts(20))]
    with pytest.raises(RuntimeError, match="already consumed"):
        guard.evaluate(runner, {"fast": 3})
    assert len(calls) == 1


def test_reserve_size_bounds():
    with pytest.raises(ValueError):
        reserve_final_test(IDX, 0)
    with pytest.raises(ValueError):
        reserve_final_test(IDX, 20)
