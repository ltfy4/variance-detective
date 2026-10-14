"""Number formatting shared by narrator, verifier and reports (so all three agree)."""
from __future__ import annotations


def fmt_num(x: float | None, decimals: int = 1) -> str:
    if x is None:
        return "n/a"
    ax = abs(x)
    sign = "-" if x < 0 else ""
    if ax >= 1_000_000_000:
        return f"{sign}{ax / 1_000_000_000:.{decimals}f}bn"
    if ax >= 1_000_000:
        return f"{sign}{ax / 1_000_000:.{decimals}f}M"
    if ax >= 10_000:
        return f"{sign}{ax / 1_000:.0f}k"
    if ax >= 1_000:
        return f"{sign}{ax / 1_000:.{decimals}f}k"
    if ax >= 100:
        return f"{sign}{ax:.0f}"
    return f"{sign}{ax:.{decimals}f}"


def fmt_money(x: float | None, symbol: str = "£", decimals: int = 1, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    s = fmt_num(abs(x), decimals)
    if x < 0:
        return f"-{symbol}{s}"
    return f"+{symbol}{s}" if signed else f"{symbol}{s}"


def fmt_pct(x: float | None, decimals: int = 1, signed: bool = False) -> str:
    if x is None:
        return "n/a"
    v = x * 100
    return f"{v:+.{decimals}f}%" if signed else f"{v:.{decimals}f}%"


def fmt_pts(x: float | None, decimals: int = 1) -> str:
    """Percentage-point difference, e.g. -1.6pts."""
    if x is None:
        return "n/a"
    return f"{x * 100:+.{decimals}f}pts"


def fmt_value(x: float | None, unit: str, symbol: str = "£", signed: bool = False) -> str:
    if unit == "currency":
        return fmt_money(x, symbol, signed=signed)
    if unit == "percent":
        return fmt_pct(x, signed=signed)
    return (("+" if signed and (x or 0) > 0 else "") + fmt_num(x)) if x is not None else "n/a"
