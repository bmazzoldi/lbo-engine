"""Static charts for reports and the README."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .model import LBOResult  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#6250d6"]
INK = "#0b0b0b"
INK_2 = "#52514e"
GRID = "#e4e3df"
POS, NEG, TOTAL = "#2a78d6", "#e34948", "#52514e"


def _style(ax, title: str, subtitle: str | None = None) -> None:
    ax.spines[["top", "right", "left"]].set_visible(False)
    ax.spines["bottom"].set_color(GRID)
    ax.tick_params(colors=INK_2, length=0, labelsize=9)
    ax.yaxis.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold",
                 pad=22 if subtitle else 10)
    if subtitle:
        ax.text(0, 1.02, subtitle, transform=ax.transAxes, fontsize=9, color=INK_2)


def value_bridge(result: LBOResult, path: str | Path) -> Path:
    r, attr = result.returns, result.attribution
    steps = [("Equity\ninvested", r["sponsor_equity"], "total")]
    steps += [(k.replace(" and ", " & ").replace(" ", "\n", 1), v, "delta") for k, v in attr.items()]
    steps.append(("Equity\nat exit", r["exit_equity"], "total"))

    fig, ax = plt.subplots(figsize=(8, 4.2), dpi=200)
    pad = max(r["exit_equity"], r["sponsor_equity"]) * 0.015
    running = 0.0
    for i, (label, value, kind) in enumerate(steps):
        if kind == "total":
            bottom, height, color = 0.0, value, TOTAL
            running = value
        else:
            bottom = running if value >= 0 else running + value
            height, color = abs(value), POS if value >= 0 else NEG
            running += value
        ax.bar(i, height, bottom=bottom, color=color, width=0.62, edgecolor="white", linewidth=2)
        text = f"{value:,.0f}" if kind == "total" else f"{value:+,.0f}"
        ax.text(i, bottom + height + pad, text, ha="center", va="bottom",
                fontsize=9, color=INK)
        if i < len(steps) - 1:
            ax.plot([i + 0.31, i + 0.69], [running, running], color=INK_2, linewidth=0.8)
    ax.set_xticks(range(len(steps)), [s[0] for s in steps])
    ax.set_ylabel("$mm", color=INK_2, fontsize=9)
    _style(ax, f"{result.deal.name}: sponsor value creation",
           f"{r['moic']:.2f}x MOIC, {r['irr']:.1%} IRR over {result.deal.exit_year} years")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return Path(path)


def deleveraging(result: LBOResult, path: str | Path) -> Path:
    debt = result.debt
    years = list(debt.columns)
    closing = {name: debt.loc[(name, "Closing")].values
               for name in debt.index.get_level_values(0).unique()}
    closing = {k: v for k, v in closing.items() if np.any(np.abs(v) > 1e-6)}

    fig, (ax, ax2) = plt.subplots(1, 2, figsize=(10, 4), dpi=200,
                                  gridspec_kw={"width_ratios": [1.5, 1]})
    bottom = np.zeros(len(years))
    for i, (name, values) in enumerate(closing.items()):
        ax.bar(years, values, bottom=bottom, color=SERIES[i % len(SERIES)], width=0.62,
               label=name, edgecolor="white", linewidth=2)
        bottom += values
    for x, total in zip(years, bottom):
        ax.text(x, total + 8, f"{total:,.0f}", ha="center", fontsize=8.5, color=INK)
    ax.set_xticks(years, [f"Y{y}" for y in years])
    ax.set_ylabel("$mm", color=INK_2, fontsize=9)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    _style(ax, "Debt outstanding by tranche", "Closing balance, $mm")

    lev = result.credit_stats().loc["Net debt / EBITDA"]
    ax2.plot(years, lev.values, color=SERIES[0], linewidth=2, marker="o", markersize=6,
             markeredgecolor="white", markeredgewidth=1.5)
    for x, v in zip(years, lev.values):
        ax2.text(x + 0.08, v + 0.25, f"{v:.1f}x", ha="left", fontsize=8.5, color=INK)
    ax2.set_xticks(years, [f"Y{y}" for y in years])
    ax2.set_xlim(years[0] - 0.4, years[-1] + 0.6)
    ax2.set_ylim(0, max(lev.values) * 1.2)
    _style(ax2, "Net leverage", "Net debt / EBITDA")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return Path(path)


def sensitivity_heatmap(table: pd.DataFrame, path: str | Path, title: str,
                        row_fmt: str = "{:.1f}x", col_fmt: str = "{:.1f}x",
                        hurdle: float = 0.20) -> Path:
    fig, ax = plt.subplots(figsize=(6.4, 4.2), dpi=200)
    data = table.values.astype(float)
    ax.imshow(data, cmap="Blues", aspect="auto", vmin=np.nanmin(data) - 0.05, vmax=np.nanmax(data))
    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            v = data[i, j]
            shade = (v - np.nanmin(data)) / (np.nanmax(data) - np.nanmin(data) + 1e-12)
            weight = "bold" if round(v, 3) >= hurdle else "normal"
            ax.text(j, i, f"{v:.1%}", ha="center", va="center", fontsize=9, fontweight=weight,
                    color="white" if shade > 0.55 else INK)
    ax.set_xticks(range(data.shape[1]), [col_fmt.format(c) for c in table.columns])
    ax.set_yticks(range(data.shape[0]), [row_fmt.format(r) for r in table.index])
    ax.set_xlabel(table.columns.name.replace("_", " ").capitalize(), color=INK_2, fontsize=9)
    ax.set_ylabel(table.index.name.replace("_", " ").capitalize(), color=INK_2, fontsize=9)
    ax.tick_params(length=0, labelsize=9, colors=INK_2)
    for s in ax.spines.values():
        s.set_visible(False)
    ax.set_title(title, loc="left", fontsize=12, color=INK, fontweight="bold", pad=22)
    ax.text(0, 1.02, f"Sponsor IRR; bold = clears {hurdle:.0%} hurdle", transform=ax.transAxes,
            fontsize=9, color=INK_2)
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    return Path(path)
