"""Small formatting helpers reused across cogs."""

from __future__ import annotations


def humanise_gp(amount: int) -> str:
    """Format a gp amount as e.g. '1.5m', '342k', '987'."""
    if amount is None:
        return "—"
    abs_amount = abs(amount)
    sign = "-" if amount < 0 else ""
    if abs_amount >= 1_000_000_000:
        return f"{sign}{abs_amount / 1_000_000_000:.2f}b"
    if abs_amount >= 1_000_000:
        return f"{sign}{abs_amount / 1_000_000:.2f}m"
    if abs_amount >= 1_000:
        return f"{sign}{abs_amount / 1_000:.1f}k"
    return f"{sign}{abs_amount}"


def commas(n: int | None) -> str:
    if n is None:
        return "—"
    return f"{n:,}"


def rank_or_dash(rank: int | None) -> str:
    if rank is None or rank < 0:
        return "—"
    return f"#{rank:,}"
