"""Command line entry point: `lbo run cases/project_halyard.toml --excel out.xlsx`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from . import charts
from .assumptions import Deal
from .excel import export
from .model import LBOResult, run
from .sensitivity import grid


def _fmt_money(x: float) -> str:
    return f"({abs(x):,.1f})" if x < 0 else f"{x:,.1f} "


def _table(df: pd.DataFrame, fmt=_fmt_money, label_width: int = 34, col_width: int = 10) -> str:
    head = " " * label_width + "".join(f"{str(c):>{col_width}}" for c in df.columns)
    lines = [head, "-" * len(head)]
    for idx, row in df.iterrows():
        cells = "".join(f"{fmt(v) if pd.notna(v) else '':>{col_width}}" for v in row.values)
        lines.append(f"{str(idx):<{label_width}}{cells}")
    return "\n".join(lines)


def report(result: LBOResult) -> str:
    d, r = result.deal, result.returns
    out = [f"{d.name}", "=" * len(d.name), ""]

    su = pd.concat([result.sources.rename("$mm").to_frame(), result.uses.rename("$mm").to_frame()],
                   keys=["Sources", "Uses"])
    su.index = [f"{a}: {b}" for a, b in su.index]
    out += ["Sources & uses ($mm)", _table(su), ""]

    p = result.projections
    keep = ["Revenue", "EBITDA", "Cash interest", "Taxes", "Free cash flow",
            "Mandatory repayment", "Optional prepayment", "Cash", "Total debt"]
    out += ["Projections ($mm)", _table(p.loc[keep].rename(columns=lambda c: f"Y{c}")), ""]

    stats = result.credit_stats().rename(columns=lambda c: f"Y{c}")
    out += ["Credit statistics",
            _table(stats.iloc[:4], fmt=lambda v: f"{v:.1f}x"),
            _table(stats.iloc[[4]], fmt=lambda v: f"{v:.0%}").split("\n", 2)[2], ""]

    out += [
        "Returns",
        f"  Entry: {d.entry_multiple:.1f}x LTM EBITDA, {r['entry_leverage']:.1f}x leverage, "
        f"{r['equity_contribution_pct']:.0%} equity",
        f"  Exit (Y{d.exit_year}): {d.exit_multiple:.1f}x, EV {r['exit_ev']:,.1f}, "
        f"net debt {r['exit_net_debt']:,.1f}",
        f"  Sponsor equity {r['sponsor_equity']:,.1f} -> {r['exit_equity']:,.1f}",
        f"  MOIC {r['moic']:.2f}x   IRR {r['irr']:.1%}",
        "",
        "Value creation ($mm)",
    ]
    total = result.attribution.sum()
    for k, v in result.attribution.items():
        out.append(f"  {k:<22}{_fmt_money(v):>10}  {v / total:>6.0%}")
    out.append(f"  {'Total':<22}{_fmt_money(total):>10}")

    if result.warnings:
        out += ["", "Warnings"] + [f"  - {w}" for w in result.warnings]
    return "\n".join(out)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lbo", description="Leveraged buyout model")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run", help="Run a deal case and print the summary")
    p_run.add_argument("case", type=Path, help="Path to a .toml deal file")
    p_run.add_argument("--excel", type=Path, help="Write a formula-driven .xlsx model here")
    p_run.add_argument("--charts", type=Path, help="Directory to write PNG charts into")
    args = parser.parse_args(argv)

    deal = Deal.from_toml(args.case)
    result = run(deal)
    print(report(result))

    if args.excel:
        export(deal, args.excel)
        print(f"\nExcel model written to {args.excel}")
    if args.charts:
        args.charts.mkdir(parents=True, exist_ok=True)
        charts.value_bridge(result, args.charts / "value_bridge.png")
        charts.deleveraging(result, args.charts / "deleveraging.png")
        e, x = deal.entry_multiple, deal.exit_multiple
        table = grid(deal, ("entry_multiple", [e - 1, e - 0.5, e, e + 0.5, e + 1]),
                     ("exit_multiple", [x - 1, x - 0.5, x, x + 0.5, x + 1]))
        charts.sensitivity_heatmap(table, args.charts / "irr_sensitivity.png",
                                   "IRR sensitivity: entry vs exit multiple")
        print(f"Charts written to {args.charts}/")


if __name__ == "__main__":
    main()
