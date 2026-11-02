"""Fractional ordering positions for cards within a column."""

from __future__ import annotations

STEP = 1024.0
MIN_GAP = 1e-6


def position_between(prev: float | None, nxt: float | None) -> float | None:
    """Return a position strictly between prev and nxt (None = open end).
    Returns None when the gap is exhausted and the column must be rebalanced."""
    if prev is None and nxt is None:
        return STEP
    if prev is None:
        assert nxt is not None
        return nxt - STEP
    if nxt is None:
        return prev + STEP
    if nxt - prev <= MIN_GAP:
        return None
    return (prev + nxt) / 2


def rebalanced(count: int) -> list[float]:
    return [(i + 1) * STEP for i in range(count)]
