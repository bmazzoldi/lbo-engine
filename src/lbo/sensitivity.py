"""Two-way sensitivity tables over deal inputs."""

from __future__ import annotations

from dataclasses import replace
from typing import Iterable

import pandas as pd

from .assumptions import Deal
from .model import run


def apply(deal: Deal, field: str, value: float) -> Deal:
    if field == "leverage":
        # Scale every tranche so total funded debt hits the target multiple.
        total = sum(t.multiple for t in deal.tranches)
        tranches = [replace(t, multiple=t.multiple * value / total) for t in deal.tranches]
        return deal.with_overrides(tranches=tranches)
    if field == "margin_delta":
        # Parallel shift in projected EBITDA margins (e.g. -0.02 = 200bp miss every year).
        op = deal.operating
        margins = [m + value for m in op.ebitda_margin]
        return deal.with_overrides(operating=replace(op, ebitda_margin=margins))
    if field not in deal.__dataclass_fields__:
        raise KeyError(f"Unknown deal field: {field}")
    return deal.with_overrides(**{field: value})


def grid(
    deal: Deal,
    rows: tuple[str, Iterable[float]],
    cols: tuple[str, Iterable[float]],
    metric: str = "irr",
) -> pd.DataFrame:
    row_field, row_values = rows
    col_field, col_values = cols
    row_values, col_values = list(row_values), list(col_values)
    out = pd.DataFrame(index=pd.Index(row_values, name=row_field),
                       columns=pd.Index(col_values, name=col_field), dtype=float)
    for r in row_values:
        base = apply(deal, row_field, r)
        for c in col_values:
            out.loc[r, c] = run(apply(base, col_field, c)).returns[metric]
    return out
