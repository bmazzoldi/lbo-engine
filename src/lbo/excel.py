"""Write a formula-driven Excel version of the model.

Every number on the Model and Returns sheets is a live formula that traces back to the
Assumptions sheet, so a reviewer can change an input in Excel and watch it flow through.
The only hardcoded outputs are the sensitivity tables, which are pasted from the Python
engine and labeled as such.

Formatting follows the usual banking convention: blue = hardcoded input, black = formula,
green = link to another sheet.
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from .assumptions import Deal
from .sensitivity import grid

NUM = '#,##0.0_);(#,##0.0);"–"_)'
PCT = '0.0%_);(0.0%);"–"_)'
MULT = '0.0"x"'
INPUT = Font(name="Calibri", size=10, color="0000FF")
LINK = Font(name="Calibri", size=10, color="008000")
CALC = Font(name="Calibri", size=10, color="000000")
BOLD = Font(name="Calibri", size=10, bold=True)
HEADER_FONT = Font(name="Calibri", size=10, bold=True, color="FFFFFF")
HEADER_FILL = PatternFill("solid", fgColor="1F3864")
SECTION_FONT = Font(name="Calibri", size=10, bold=True, color="1F3864")
TOP_RULE = Border(top=Side(style="thin"))

A = "Assumptions"


class _Sheet:
    """Small helper that hands out rows top-to-bottom and remembers where things went."""

    def __init__(self, ws: Worksheet, first_data_col: int = 3):
        self.ws = ws
        self.row = 2
        self.c0 = first_data_col
        self.addr: dict[str, int] = {}
        ws.sheet_view.showGridLines = False
        ws.column_dimensions["A"].width = 2
        ws.column_dimensions["B"].width = 38

    def col(self, i: int) -> str:
        return get_column_letter(self.c0 + i)

    def header(self, text: str, labels: list[str] | None = None) -> None:
        ws = self.ws
        ws.cell(self.row, 2, text)
        width = len(labels) if labels else 1
        for j in range(width + 1):
            c = ws.cell(self.row, 2 + j)
            c.font, c.fill = HEADER_FONT, HEADER_FILL
        for j, lab in enumerate(labels or []):
            c = ws.cell(self.row, self.c0 + j, lab)
            c.alignment = Alignment(horizontal="right")
        self.row += 1

    def section(self, text: str) -> None:
        self.row += 1
        self.ws.cell(self.row, 2, text).font = SECTION_FONT
        self.row += 1

    def line(self, key: str, label: str, values: list, fmt: str = NUM, font=CALC,
             bold: bool = False, rule: bool = False) -> int:
        ws = self.ws
        ws.cell(self.row, 2, label).font = BOLD if bold else CALC
        for j, v in enumerate(values):
            if v is None:
                continue
            c = ws.cell(self.row, self.c0 + j, v)
            is_input = not (isinstance(v, str) and v.startswith("="))
            is_link = isinstance(v, str) and "!" in v
            c.font = INPUT if is_input else (LINK if is_link else CALC)
            if bold:
                c.font = Font(name="Calibri", size=10, bold=True, color=c.font.color)
            c.number_format = fmt
            if rule:
                c.border = TOP_RULE
        self.addr[key] = self.row
        self.row += 1
        return self.row - 1

    def ref(self, key: str, i: int, absolute: bool = False) -> str:
        col = self.col(i)
        return f"${col}${self.addr[key]}" if absolute else f"{col}{self.addr[key]}"


def export(deal: Deal, path: str | Path, sensitivities: bool = True) -> Path:
    path = Path(path)
    wb = Workbook()
    a = _Sheet(wb.active)
    wb.active.title = A
    op = deal.operating
    n = op.years
    tranches = sorted(deal.tranches, key=lambda t: t.priority)

    # ---- Assumptions --------------------------------------------------------------------
    ws = a.ws
    ws.cell(1, 2, deal.name).font = Font(name="Calibri", size=14, bold=True)
    a.header("Transaction", ["Input"])
    a.line("entry", "Entry multiple (x LTM EBITDA)", [deal.entry_multiple], MULT)
    a.line("exit_mult", "Exit multiple (x EBITDA)", [deal.exit_multiple], MULT)
    a.line("exit_year", "Exit year", [deal.exit_year], "0")
    a.line("tx_fee", "Transaction fees (% of EV)", [deal.transaction_fee_pct], PCT)
    a.line("fin_fee", "Financing fees (% of debt)", [deal.financing_fee_pct], PCT)
    a.line("fee_years", "Financing fee amortization (years)", [deal.financing_fee_amort_years], "0")
    a.line("exit_fee", "Exit fees (% of exit EV)", [deal.exit_fee_pct], PCT)
    a.line("min_cash", "Minimum cash", [deal.min_cash])
    a.line("sweep_pct", "Excess cash flow sweep", [deal.sweep_pct], PCT)

    a.section("Operating")
    a.line("ltm_rev", "LTM revenue", [op.ltm_revenue])
    a.line("ltm_margin", "LTM EBITDA margin", [op.ltm_ebitda_margin], PCT)
    a.line("da", "D&A (% of revenue)", [op.da_pct_revenue], PCT)
    a.line("capex", "Capex (% of revenue)", [op.capex_pct_revenue], PCT)
    a.line("nwc", "Net working capital (% of revenue)", [op.nwc_pct_revenue], PCT)
    a.line("tax", "Tax rate", [op.tax_rate], PCT)

    a.section("Revolver")
    rv = deal.revolver
    a.line("rv_commit", "Commitment", [rv.commitment if rv else 0.0])
    a.line("rv_rate", "Drawn rate", [rv.rate if rv else 0.0], PCT)
    a.line("rv_fee", "Undrawn fee", [rv.undrawn_fee if rv else 0.0], PCT)

    a.row += 1
    a.header("Debt tranches (in sweep order)",
             ["x EBITDA", "Cash rate", "PIK rate", "Amort. %", "Sweep (1/0)"])
    for t in tranches:
        r = a.row
        ws.cell(r, 2, t.name).font = CALC
        for j, (v, fmt) in enumerate([(t.multiple, MULT), (t.cash_rate, PCT), (t.pik_rate, PCT),
                                      (t.amortization, PCT), (int(t.sweep), "0")]):
            c = ws.cell(r, a.c0 + j, v)
            c.font, c.number_format = INPUT, fmt
        a.addr[f"tr:{t.name}"] = r
        a.row += 1

    a.row += 1
    a.header("Projections", [f"Year {i}" for i in range(1, n + 1)])
    a.line("growth", "Revenue growth", list(op.revenue_growth), PCT)
    a.line("margin", "EBITDA margin", list(op.ebitda_margin), PCT)
    for j in range(max(6, n + 1)):
        ws.column_dimensions[a.col(j)].width = 12

    def av(key: str) -> str:
        return f"{A}!$C${a.addr[key]}"

    def tr(t, j: int) -> str:
        return f"{A}!${a.col(j)}${a.addr['tr:' + t.name]}"

    # ---- Sources & Uses -----------------------------------------------------------------
    su = _Sheet(wb.create_sheet("Sources & Uses"))
    su.ws.cell(1, 2, "Sources & Uses").font = Font(name="Calibri", size=14, bold=True)
    su.header("Uses", ["$mm"])
    su.line("ltm_ebitda", "LTM EBITDA", [f"={av('ltm_rev')}*{av('ltm_margin')}"])
    su.line("ev", "Purchase enterprise value", [f"={av('entry')}*C{su.addr['ltm_ebitda']}"])
    su.line("tx_fees", "Transaction fees", [f"={av('tx_fee')}*C{su.addr['ev']}"])
    fin_row = su.row
    su.row += 1  # financing fees depend on total debt, filled in below
    su.line("cash", "Cash to balance sheet", [f"={av('min_cash')}"])
    su.line("uses", "Total uses", [f"=SUM(C{su.addr['ev']}:C{su.addr['cash']})"], bold=True, rule=True)

    su.row += 1
    su.header("Sources", ["$mm", "x EBITDA"])
    first_src = su.row
    for t in tranches:
        su.line(f"src:{t.name}", t.name,
                [f"={tr(t, 0)}*$C${su.addr['ltm_ebitda']}", f"={tr(t, 0)}"])
        su.ws.cell(su.row - 1, 4).number_format = MULT
    last_src = su.row - 1
    su.line("debt", "Total debt", [f"=SUM(C{first_src}:C{last_src})",
                                   f"=C{su.row}/$C${su.addr['ltm_ebitda']}"], rule=True)
    su.ws.cell(su.addr["debt"], 4).number_format = MULT
    su.line("equity", "Sponsor equity", [f"=C{su.addr['uses']}-C{su.addr['debt']}"])
    su.line("sources", "Total sources", [f"=C{su.addr['debt']}+C{su.addr['equity']}"],
            bold=True, rule=True)
    su.line("eq_pct", "Equity contribution", [f"=C{su.addr['equity']}/C{su.addr['sources']}"], PCT)

    su.row, saved = fin_row, su.row
    su.line("fin_fees", "Financing fees", [f"={av('fin_fee')}*C{su.addr['debt']}"])
    su.row = saved
    su.ws.column_dimensions["C"].width = 12
    su.ws.column_dimensions["D"].width = 12

    def sref(key: str) -> str:
        return f"'Sources & Uses'!$C${su.addr[key]}"

    # ---- Model --------------------------------------------------------------------------
    m = _Sheet(wb.create_sheet("Model"))
    mw = m.ws
    mw.cell(1, 2, f"{deal.name}: projections and debt schedule ($mm)").font = Font(
        name="Calibri", size=14, bold=True)
    m.addr["year"] = m.row
    m.header("Fiscal year", list(range(n + 1)))
    P = range(1, n + 1)

    def proj(key: str, j: int) -> str:
        return f"{A}!{a.col(j - 1)}${a.addr[key]}"

    def prev(key: str, j: int) -> str:
        return m.ref(key, j - 1)

    def cur(key: str, j: int) -> str:
        return m.ref(key, j)

    def row_of(key0, fn) -> list:
        return [key0] + [fn(j) for j in P]

    m.section("Operating build")
    m.addr["rev"] = m.row  # revenue grows off its own prior year
    m.line("rev", "Revenue", row_of(f"={av('ltm_rev')}", lambda j: f"={prev('rev', j)}*(1+{proj('growth', j)})"))
    m.line("ebitda", "EBITDA", row_of(f"={sref('ltm_ebitda')}",
                                      lambda j: f"={cur('rev', j)}*{proj('margin', j)}"), bold=True)
    m.line("ebitda_m", "EBITDA margin", [f"={cur('ebitda', j)}/{cur('rev', j)}" for j in range(n + 1)], PCT)
    m.line("da", "D&A", [f"={cur('rev', j)}*{av('da')}" for j in range(n + 1)])
    m.line("ebit", "EBIT", [f"={cur('ebitda', j)}-{cur('da', j)}" for j in range(n + 1)], rule=True)
    m.line("capex", "Capex", [f"={cur('rev', j)}*{av('capex')}" for j in range(n + 1)])
    m.line("nwc", "Net working capital", [f"={cur('rev', j)}*{av('nwc')}" for j in range(n + 1)])
    m.line("dnwc", "Increase in NWC", row_of(None, lambda j: f"={cur('nwc', j)}-{prev('nwc', j)}"))

    # The income statement, cash flow and debt schedule reference each other, so lay out
    # every row number first and fill in the formulas afterwards.
    m.section("Income statement")
    is_start = m.row
    is_keys = ["cash_int", "pik_int", "fee_amort", "ebt", "taxes", "ni"]
    for i, k in enumerate(is_keys):
        m.addr[k] = is_start + i
    m.row = is_start + len(is_keys)

    m.section("Cash flow")
    cf_start = m.row
    cf_keys = ["cfo", "fcf", "mand_total", "available", "sweep_pool", "sweep_total", "cash"]
    for i, k in enumerate(cf_keys):
        m.addr[k] = cf_start + i
    m.row = cf_start + len(cf_keys)

    # Debt schedule
    m.section("Debt schedule")
    for t in tranches:
        k = t.name
        m.ws.cell(m.row, 2, k).font = BOLD
        m.row += 1
        base = m.row
        for i, line in enumerate(["open", "cint", "pik", "mand", "sweep", "close"]):
            m.addr[f"{k}:{line}"] = base + i
        m.row = base + 6

    m.ws.cell(m.row, 2, "Revolver").font = BOLD
    m.row += 1
    base = m.row
    for i, line in enumerate(["open", "draw", "repay", "close", "int"]):
        m.addr[f"rv:{line}"] = base + i
    m.row = base + 5
    m.row += 1
    tot_debt_row = m.row
    m.addr["total_debt"] = tot_debt_row
    m.row += 1
    m.addr["net_debt"] = m.row
    m.row += 1
    m.addr["lev"] = m.row
    end_row = m.row + 1

    # Now write all reserved rows.
    def write(key: str, label: str, values: list, fmt=NUM, bold=False, rule=False):
        saved_row = m.row
        m.row = m.addr[key]
        m.line(key, label, values, fmt, bold=bold, rule=rule)
        m.row = saved_row

    tnames = [t.name for t in tranches]

    def sum_of(line: str, j: int) -> str:
        return "+".join(m.ref(f"{k}:{line}", j) for k in tnames)

    write("cash_int", "Cash interest expense", row_of(None, lambda j: f"={sum_of('cint', j)}+{cur('rv:int', j)}"))
    write("pik_int", "PIK interest", row_of(None, lambda j: f"={sum_of('pik', j)}"))
    write("fee_amort", "Amortization of financing fees",
          row_of(None, lambda j: f"=IF({cur('year', j)}<={av('fee_years')},{sref('fin_fees')}/{av('fee_years')},0)"))
    write("ebt", "Pre-tax income", row_of(None, lambda j: (
        f"={cur('ebit', j)}-{cur('cash_int', j)}-{cur('pik_int', j)}-{cur('fee_amort', j)}")), rule=True)
    write("taxes", "Taxes", row_of(None, lambda j: f"=MAX({cur('ebt', j)},0)*{av('tax')}"))
    write("ni", "Net income", row_of(None, lambda j: f"={cur('ebt', j)}-{cur('taxes', j)}"), bold=True, rule=True)

    write("cfo", "Cash flow from operations", row_of(None, lambda j: (
        f"={cur('ni', j)}+{cur('da', j)}+{cur('pik_int', j)}+{cur('fee_amort', j)}-{cur('dnwc', j)}")))
    write("fcf", "Free cash flow (pre debt repayment)", row_of(None, lambda j: f"={cur('cfo', j)}-{cur('capex', j)}"),
          bold=True)
    write("mand_total", "Mandatory amortization", row_of(None, lambda j: f"={sum_of('mand', j)}"))
    write("available", "Cash available after mandatory payments", row_of(None, lambda j: (
        f"={prev('cash', j)}+{cur('fcf', j)}-{av('min_cash')}-{cur('mand_total', j)}")))
    write("sweep_pool", "Cash available for sweep", row_of(None, lambda j: (
        f"=MAX({cur('available', j)}-{cur('rv:repay', j)},0)*{av('sweep_pct')}")))
    write("sweep_total", "Optional prepayments", row_of(None, lambda j: f"={sum_of('sweep', j)}"))
    write("cash", "Ending cash", row_of(f"={sref('cash')}", lambda j: (
        f"={prev('cash', j)}+{cur('fcf', j)}-{cur('mand_total', j)}+{cur('rv:draw', j)}"
        f"-{cur('rv:repay', j)}-{cur('sweep_total', j)}")), bold=True, rule=True)

    for idx, t in enumerate(tranches):
        k = t.name
        earlier = tnames[:idx]

        def sweep_formula(j, k=k, t=t, earlier=earlier):
            after = f"({cur(k + ':open', j)}+{cur(k + ':pik', j)}-{cur(k + ':mand', j)})"
            used = "".join(f"-{m.ref(e + ':sweep', j)}" for e in earlier)
            return f"=IF({tr(t, 4)}=1,MIN({after},MAX({cur('sweep_pool', j)}{used},0)),0)"

        write(f"{k}:open", "Opening balance", row_of(None, lambda j, k=k: f"={prev(k + ':close', j)}"))
        write(f"{k}:cint", "Cash interest", row_of(None, lambda j, k=k, t=t: f"={cur(k + ':open', j)}*{tr(t, 1)}"))
        write(f"{k}:pik", "PIK interest", row_of(None, lambda j, k=k, t=t: f"={cur(k + ':open', j)}*{tr(t, 2)}"))
        write(f"{k}:mand", "Mandatory amortization", row_of(None, lambda j, k=k, t=t: (
            f"=MIN({tr(t, 3)}*{m.ref(k + ':close', 0, absolute=True)},{cur(k + ':open', j)})")))
        write(f"{k}:sweep", "Optional prepayment", row_of(None, sweep_formula))
        write(f"{k}:close", "Closing balance", row_of(
            f"='Sources & Uses'!$C${su.addr['src:' + k]}",
            lambda j, k=k: f"={cur(k + ':open', j)}+{cur(k + ':pik', j)}-{cur(k + ':mand', j)}-{cur(k + ':sweep', j)}"),
            bold=True, rule=True)

    write("rv:open", "Opening balance", row_of(None, lambda j: f"={prev('rv:close', j)}"))
    write("rv:draw", "Draw", row_of(None, lambda j: f"=MAX(-{cur('available', j)},0)"))
    write("rv:repay", "Repayment", row_of(None, lambda j: f"=MIN({cur('rv:open', j)},MAX({cur('available', j)},0))"))
    write("rv:close", "Closing balance", row_of(0.0, lambda j: (
        f"={cur('rv:open', j)}+{cur('rv:draw', j)}-{cur('rv:repay', j)}")), bold=True, rule=True)
    write("rv:int", "Interest and undrawn fee", row_of(None, lambda j: (
        f"={cur('rv:open', j)}*{av('rv_rate')}+({av('rv_commit')}-{cur('rv:open', j)})*{av('rv_fee')}")))

    closings = lambda j: "+".join([m.ref(f"{k}:close", j) for k in tnames] + [m.ref("rv:close", j)])
    write("total_debt", "Total debt", [f"={closings(j)}" for j in range(n + 1)], bold=True)
    write("net_debt", "Net debt", [f"={cur('total_debt', j)}-{cur('cash', j)}" for j in range(n + 1)])
    write("lev", "Net debt / EBITDA", [f"={cur('net_debt', j)}/{cur('ebitda', j)}" for j in range(n + 1)], MULT)
    m.row = end_row
    for j in range(n + 1):
        mw.column_dimensions[m.col(j)].width = 11
    mw.freeze_panes = "C3"

    # ---- Returns ------------------------------------------------------------------------
    r = _Sheet(wb.create_sheet("Returns"))
    r.ws.cell(1, 2, "Exit and returns").font = Font(name="Calibri", size=14, bold=True)

    def model_row(key: str) -> str:
        row = m.addr[key]
        return f"Model!${m.col(1)}${row}:${m.col(n)}${row}"

    r.header("Exit", ["$mm"])
    r.line("exit_ebitda", "Exit-year EBITDA", [f"=INDEX({model_row('ebitda')},{av('exit_year')})"])
    r.line("exit_ev", "Exit enterprise value", [f"={av('exit_mult')}*C{r.addr['exit_ebitda']}"])
    r.line("exit_nd", "Less: net debt at exit",
           [f"=INDEX({model_row('total_debt')},{av('exit_year')})-INDEX({model_row('cash')},{av('exit_year')})"])
    r.line("exit_fees", "Less: exit fees", [f"={av('exit_fee')}*C{r.addr['exit_ev']}"])
    r.line("exit_eq", "Sponsor equity at exit",
           [f"=C{r.addr['exit_ev']}-C{r.addr['exit_nd']}-C{r.addr['exit_fees']}"], bold=True, rule=True)
    r.line("entry_eq", "Sponsor equity invested", [f"={sref('equity')}"])
    r.line("moic", "MOIC", [f"=MAX(C{r.addr['exit_eq']},0)/C{r.addr['entry_eq']}"], '0.00"x"', bold=True)
    r.line("irr", "IRR", [f"=IF(C{r.addr['moic']}>0,C{r.addr['moic']}^(1/{av('exit_year')})-1,-1)"], PCT, bold=True)

    r.row += 1
    r.header("Value creation bridge", ["$mm"])
    r.line("b_growth", "EBITDA growth",
           [f"=(C{r.addr['exit_ebitda']}-{sref('ltm_ebitda')})*{av('entry')}"])
    r.line("b_mult", "Multiple expansion",
           [f"=({av('exit_mult')}-{av('entry')})*C{r.addr['exit_ebitda']}"])
    r.line("b_debt", "Debt paydown",
           [f"=({sref('debt')}-{sref('cash')})-C{r.addr['exit_nd']}"])
    r.line("b_fees", "Fees and expenses",
           [f"=-({sref('tx_fees')}+{sref('fin_fees')}+C{r.addr['exit_fees']})"])
    r.line("b_total", "Equity value created",
           [f"=SUM(C{r.addr['b_growth']}:C{r.addr['b_fees']})"], bold=True, rule=True)
    r.line("b_check", "Check (should be zero)",
           [f"=ROUND(C{r.addr['b_total']}-(C{r.addr['exit_eq']}-C{r.addr['entry_eq']}),6)"])
    r.ws.column_dimensions["C"].width = 12

    if sensitivities:
        _sensitivity_sheet(wb.create_sheet("Sensitivity"), deal)

    wb.save(path)
    return path


def _sensitivity_sheet(ws: Worksheet, deal: Deal) -> None:
    ws.sheet_view.showGridLines = False
    ws.column_dimensions["A"].width = 2
    ws.column_dimensions["B"].width = 22
    ws.cell(1, 2, "Sensitivity tables").font = Font(name="Calibri", size=14, bold=True)
    ws.cell(2, 2, "Values computed by the Python engine (lbo.sensitivity.grid); not live formulas.").font = Font(
        name="Calibri", size=9, italic=True, color="808080")

    e, x = deal.entry_multiple, deal.exit_multiple
    tables = [
        ("IRR: entry multiple (rows) vs exit multiple (cols)",
         ("entry_multiple", [e - 1, e - 0.5, e, e + 0.5, e + 1]),
         ("exit_multiple", [x - 1, x - 0.5, x, x + 0.5, x + 1]), MULT, MULT),
        ("IRR: total leverage (rows) vs exit multiple (cols)",
         ("leverage", [4.0, 4.5, 5.0, 5.5, 6.0]),
         ("exit_multiple", [x - 1, x - 0.5, x, x + 0.5, x + 1]), MULT, MULT),
        ("IRR: EBITDA margin shift (rows) vs exit year (cols)",
         ("margin_delta", [-0.03, -0.015, 0.0, 0.015, 0.03]),
         ("exit_year", [y for y in range(3, deal.operating.years + 1)]), '+0.0%;-0.0%;0.0%', "0"),
    ]
    row = 4
    for title, rows, cols, rfmt, cfmt in tables:
        table = grid(deal, rows, cols)
        ws.cell(row, 2, title).font = SECTION_FONT
        row += 1
        for j, c in enumerate(table.columns):
            cell = ws.cell(row, 3 + j, c)
            cell.font, cell.fill, cell.number_format = HEADER_FONT, HEADER_FILL, cfmt
        ws.cell(row, 2).fill = HEADER_FILL
        row += 1
        for rv, values in table.iterrows():
            ws.cell(row, 2, rv).number_format = rfmt
            for j, v in enumerate(values):
                cell = ws.cell(row, 3 + j, float(v))
                cell.number_format = PCT
                cell.font = CALC
            row += 1
        row += 2
    for j in range(8):
        ws.column_dimensions[get_column_letter(3 + j)].width = 10
