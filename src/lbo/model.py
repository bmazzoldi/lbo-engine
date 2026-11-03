"""Annual LBO projection: operating build, debt schedule with cash sweep, and exit returns.

Conventions (kept identical in the Excel export so the two tie out):
  * Interest is charged on opening balances, which avoids the circular reference that
    average-balance interest creates. The cost is a small understatement of interest
    savings from in-year paydown.
  * Taxes are max(EBT, 0) * rate. No NOL carryforwards.
  * Mandatory amortization is a % of original principal, capped at the opening balance.
  * Excess cash first repays the revolver, then sweep_pct of what is left prepays
    sweep-eligible tranches in priority order. Anything not swept stays on balance sheet.
  * A cash shortfall after mandatory payments is funded by the revolver.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .assumptions import Deal


@dataclass
class LBOResult:
    deal: Deal
    sources: pd.Series
    uses: pd.Series
    projections: pd.DataFrame           # rows = line items, columns = years 0..N
    debt: pd.DataFrame                  # MultiIndex rows (tranche, line), columns = years
    returns: dict[str, float]
    attribution: pd.Series
    warnings: list[str]

    @property
    def irr(self) -> float:
        return self.returns["irr"]

    @property
    def moic(self) -> float:
        return self.returns["moic"]

    def credit_stats(self) -> pd.DataFrame:
        p = self.projections
        total_debt = p.loc["Total debt"]
        net_debt = total_debt - p.loc["Cash"]
        cash_interest = p.loc["Cash interest"].replace(0, float("nan"))
        return pd.DataFrame(
            {
                "Total debt / EBITDA": total_debt / p.loc["EBITDA"],
                "Net debt / EBITDA": net_debt / p.loc["EBITDA"],
                "EBITDA / cash interest": p.loc["EBITDA"] / cash_interest,
                "(EBITDA - capex) / cash interest": (p.loc["EBITDA"] - p.loc["Capex"]) / cash_interest,
                "Cumulative debt paydown %": 1 - total_debt / total_debt.iloc[0],
            }
        ).T


def run(deal: Deal) -> LBOResult:
    op = deal.operating
    n = op.years
    ltm_ebitda = op.ltm_ebitda
    warnings: list[str] = []

    # ---- Sources & uses -------------------------------------------------------------
    purchase_ev = deal.entry_multiple * ltm_ebitda
    principal = {t.name: t.multiple * ltm_ebitda for t in deal.tranches}
    funded_debt = sum(principal.values())
    transaction_fees = deal.transaction_fee_pct * purchase_ev
    financing_fees = deal.financing_fee_pct * funded_debt
    total_uses = purchase_ev + transaction_fees + financing_fees + deal.min_cash
    sponsor_equity = total_uses - funded_debt
    if sponsor_equity <= 0:
        raise ValueError("Debt exceeds total uses; sponsor equity would be non-positive")

    sources = pd.Series({**principal, "Sponsor equity": sponsor_equity}, name="Sources")
    uses = pd.Series(
        {
            "Purchase enterprise value": purchase_ev,
            "Transaction fees": transaction_fees,
            "Financing fees": financing_fees,
            "Cash to balance sheet": deal.min_cash,
        },
        name="Uses",
    )

    # ---- Projection loop --------------------------------------------------------------
    rows: dict[str, list[float]] = {k: [] for k in _LINE_ITEMS}
    tranches = sorted(deal.tranches, key=lambda t: t.priority)
    bal = {t.name: [principal[t.name]] for t in deal.tranches}
    sched = {t.name: {"Cash interest": [0.0], "PIK interest": [0.0], "Mandatory": [0.0], "Sweep": [0.0]}
             for t in deal.tranches}
    revolver = [0.0]
    revolver_draw = [0.0]
    revolver_repay = [0.0]
    cash = [deal.min_cash]
    fee_amort = financing_fees / deal.financing_fee_amort_years

    revenue = op.ltm_revenue
    nwc = op.ltm_revenue * op.nwc_pct_revenue
    _append_year0(rows, op, ltm_ebitda, funded_debt, deal.min_cash)

    for t in range(1, n + 1):
        revenue = revenue * (1 + op.revenue_growth[t - 1])
        ebitda = revenue * op.ebitda_margin[t - 1]
        da = revenue * op.da_pct_revenue
        ebit = ebitda - da
        capex = revenue * op.capex_pct_revenue
        new_nwc = revenue * op.nwc_pct_revenue
        delta_nwc = new_nwc - nwc
        nwc = new_nwc

        cash_int = {k.name: bal[k.name][-1] * k.cash_rate for k in tranches}
        pik_int = {k.name: bal[k.name][-1] * k.pik_rate for k in tranches}
        rev_int = 0.0
        if deal.revolver:
            rev_int = (revolver[-1] * deal.revolver.rate
                       + (deal.revolver.commitment - revolver[-1]) * deal.revolver.undrawn_fee)
        total_cash_int = sum(cash_int.values()) + rev_int
        total_pik = sum(pik_int.values())
        amort = fee_amort if t <= deal.financing_fee_amort_years else 0.0

        ebt = ebit - total_cash_int - total_pik - amort
        taxes = max(ebt, 0.0) * op.tax_rate
        net_income = ebt - taxes
        cfo = net_income + da + total_pik + amort - delta_nwc
        fcf = cfo - capex

        mandatory = {k.name: min(k.amortization * principal[k.name], bal[k.name][-1]) for k in tranches}
        total_mandatory = sum(mandatory.values())
        available = cash[-1] + fcf - deal.min_cash - total_mandatory

        draw = max(-available, 0.0)
        repay = min(revolver[-1], max(available, 0.0))
        pool = max(available - repay, 0.0) * deal.sweep_pct
        sweep = {}
        for k in tranches:
            after_mand = bal[k.name][-1] + pik_int[k.name] - mandatory[k.name]
            pay = min(after_mand, pool) if k.sweep else 0.0
            sweep[k.name] = pay
            pool -= pay
        total_sweep = sum(sweep.values())

        for k in tranches:
            bal[k.name].append(bal[k.name][-1] + pik_int[k.name] - mandatory[k.name] - sweep[k.name])
            s = sched[k.name]
            s["Cash interest"].append(cash_int[k.name])
            s["PIK interest"].append(pik_int[k.name])
            s["Mandatory"].append(mandatory[k.name])
            s["Sweep"].append(sweep[k.name])
        revolver.append(revolver[-1] + draw - repay)
        revolver_draw.append(draw)
        revolver_repay.append(repay)
        cash.append(cash[-1] + fcf - total_mandatory + draw - repay - total_sweep)

        if deal.revolver and revolver[-1] > deal.revolver.commitment + 1e-9:
            warnings.append(f"Year {t}: revolver balance {revolver[-1]:,.1f} exceeds commitment")
        if ebt < 0:
            warnings.append(f"Year {t}: pre-tax loss of {ebt:,.1f} (no NOL benefit modeled)")

        total_debt = sum(b[-1] for b in bal.values()) + revolver[-1]
        for key, val in (
            ("Revenue", revenue), ("EBITDA", ebitda), ("D&A", da), ("EBIT", ebit),
            ("Cash interest", total_cash_int), ("PIK interest", total_pik),
            ("Financing fee amortization", amort), ("EBT", ebt), ("Taxes", taxes),
            ("Net income", net_income), ("Change in NWC", delta_nwc), ("Capex", capex),
            ("Free cash flow", fcf), ("Mandatory repayment", total_mandatory),
            ("Revolver draw / (repayment)", draw - repay), ("Optional prepayment", total_sweep),
            ("Cash", cash[-1]), ("Total debt", total_debt),
        ):
            rows[key].append(val)

    years = list(range(0, n + 1))
    projections = pd.DataFrame(rows, index=years).T
    projections.columns.name = "Year"

    debt_frames = {}
    for k in tranches:
        s = sched[k.name]
        debt_frames[k.name] = pd.DataFrame(
            {"Opening": [0.0] + bal[k.name][:-1], **s, "Closing": bal[k.name]}, index=years
        ).T
    if deal.revolver:
        debt_frames["Revolver"] = pd.DataFrame(
            {"Opening": [0.0] + revolver[:-1], "Draw": revolver_draw, "Repayment": revolver_repay,
             "Closing": revolver}, index=years
        ).T
    debt = pd.concat(debt_frames)

    # ---- Exit -----------------------------------------------------------------------
    x = deal.exit_year
    exit_ebitda = projections.loc["EBITDA", x]
    exit_ev = deal.exit_multiple * exit_ebitda
    exit_net_debt = projections.loc["Total debt", x] - projections.loc["Cash", x]
    exit_fees = deal.exit_fee_pct * exit_ev
    exit_equity = exit_ev - exit_net_debt - exit_fees
    moic = max(exit_equity, 0.0) / sponsor_equity  # equity can't be worth less than zero
    irr = moic ** (1 / x) - 1 if moic > 0 else -1.0

    entry_net_debt = funded_debt - deal.min_cash
    attribution = pd.Series(
        {
            "EBITDA growth": (exit_ebitda - ltm_ebitda) * deal.entry_multiple,
            "Multiple expansion": (deal.exit_multiple - deal.entry_multiple) * exit_ebitda,
            "Debt paydown": entry_net_debt - exit_net_debt,
            "Fees and expenses": -(transaction_fees + financing_fees + exit_fees),
        }
    )

    returns = {
        "sponsor_equity": sponsor_equity,
        "exit_ev": exit_ev,
        "exit_net_debt": exit_net_debt,
        "exit_equity": exit_equity,
        "moic": moic,
        "irr": irr,
        "entry_leverage": funded_debt / ltm_ebitda,
        "equity_contribution_pct": sponsor_equity / total_uses,
    }
    returns = {k: float(v) for k, v in returns.items()}
    return LBOResult(deal, sources, uses, projections, debt, returns, attribution, warnings)


_LINE_ITEMS = [
    "Revenue", "EBITDA", "D&A", "EBIT", "Cash interest", "PIK interest",
    "Financing fee amortization", "EBT", "Taxes", "Net income", "Change in NWC", "Capex",
    "Free cash flow", "Mandatory repayment", "Revolver draw / (repayment)",
    "Optional prepayment", "Cash", "Total debt",
]


def _append_year0(rows, op, ltm_ebitda, funded_debt, min_cash) -> None:
    year0 = {k: 0.0 for k in _LINE_ITEMS}
    year0.update(
        {
            "Revenue": op.ltm_revenue,
            "EBITDA": ltm_ebitda,
            "D&A": op.ltm_revenue * op.da_pct_revenue,
            "EBIT": ltm_ebitda - op.ltm_revenue * op.da_pct_revenue,
            "Capex": op.ltm_revenue * op.capex_pct_revenue,
            "Cash": min_cash,
            "Total debt": funded_debt,
        }
    )
    for k, v in year0.items():
        rows[k].append(v)
