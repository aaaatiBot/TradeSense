"""Jinja2 custom filters per SRS §10 and Phase 11."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Union


def format_inr(val: Any) -> str:
    """Format numeric values into standard Indian numbering format (e.g. ₹1,23,456.78).
    
    Handles Decimals, floats, ints, strings, and negative values.
    """
    if val is None or val == "":
        return "₹0.00"

    try:
        # Strip currency symbols or commas if already present
        cleaned = str(val).replace("₹", "").replace(",", "").strip()
        d = Decimal(cleaned)
    except Exception:
        return str(val)

    is_neg = d < 0
    d = abs(d)

    # Fixed to 2 decimal places
    formatted_dec = f"{d:.2f}"
    parts = formatted_dec.split(".")
    int_part = parts[0]
    dec_part = parts[1]

    if len(int_part) <= 3:
        formatted_int = int_part
    else:
        last3 = int_part[-3:]
        remaining = int_part[:-3]
        groups = []
        while len(remaining) > 2:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            groups.insert(0, remaining)
        formatted_int = ",".join(groups) + "," + last3

    res = f"₹{formatted_int}.{dec_part}"
    return f"-{res}" if is_neg else res


def register_filters(app) -> None:
    """Register all custom Jinja2 template filters."""
    app.jinja_env.filters["inr"] = format_inr
