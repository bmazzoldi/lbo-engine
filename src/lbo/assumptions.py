"""Deal inputs. Everything is in $mm unless the field name says otherwise."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tranche:
    name: str
    multiple: float                 # turns of LTM EBITDA raised at close
    cash_rate: float                # cash-pay coupon on opening balance
    pik_rate: float = 0.0           # accrues to principal
    amortization: float = 0.0       # mandatory annual repayment, % of original principal
    sweep: bool = True              # eligible for excess cash flow sweep
    priority: int = 1               # sweep order; lower is repaid first


@dataclass(frozen=True)
class Revolver:
    commitment: float
    rate: float
    undrawn_fee: float = 0.0


@dataclass(frozen=True)
class Operating:
    ltm_revenue: float
    ltm_ebitda_margin: float
    revenue_growth: list[float]     # one entry per projection year
    ebitda_margin: list[float]
    da_pct_revenue: float
    capex_pct_revenue: float
    nwc_pct_revenue: float
    tax_rate: float

    @property
    def ltm_ebitda(self) -> float:
        return self.ltm_revenue * self.ltm_ebitda_margin

    @property
    def years(self) -> int:
        return len(self.revenue_growth)


@dataclass(frozen=True)
class Deal:
    name: str
    entry_multiple: float
    exit_multiple: float
    exit_year: int
    operating: Operating
    tranches: list[Tranche]
    revolver: Revolver | None = None
    transaction_fee_pct: float = 0.02       # % of purchase EV
    financing_fee_pct: float = 0.025        # % of funded debt, amortized for tax
    financing_fee_amort_years: int = 7
    exit_fee_pct: float = 0.0               # % of exit EV
    min_cash: float = 0.0
    sweep_pct: float = 1.0                  # share of excess cash used to prepay debt

    def __post_init__(self) -> None:
        op = self.operating
        if len(op.ebitda_margin) != op.years:
            raise ValueError("revenue_growth and ebitda_margin must have the same length")
        if not 1 <= self.exit_year <= op.years:
            raise ValueError(f"exit_year must be between 1 and {op.years}")
        if not 0.0 <= self.sweep_pct <= 1.0:
            raise ValueError("sweep_pct must be between 0 and 1")
        names = [t.name for t in self.tranches]
        if len(set(names)) != len(names):
            raise ValueError("tranche names must be unique")

    def with_overrides(self, **kwargs) -> "Deal":
        """Copy of the deal with top-level fields replaced (used for sensitivities)."""
        values = {f: getattr(self, f) for f in self.__dataclass_fields__}
        values.update(kwargs)
        return Deal(**values)

    @classmethod
    def from_toml(cls, path: str | Path) -> "Deal":
        raw = tomllib.loads(Path(path).read_text())
        op = Operating(**raw.pop("operating"))
        tranches = [Tranche(**t) for t in raw.pop("tranche")]
        revolver = Revolver(**raw.pop("revolver")) if "revolver" in raw else None
        return cls(operating=op, tranches=tranches, revolver=revolver, **raw)
