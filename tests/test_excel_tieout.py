"""The Excel export must reproduce the Python engine exactly.

pycel evaluates the workbook's formulas in Python, so this runs in CI without Excel.
"""

from pathlib import Path

import pytest
from openpyxl import load_workbook

from lbo import Deal, run
from lbo.excel import export
from lbo.sensitivity import apply

pycel = pytest.importorskip("pycel")

CASES = Path(__file__).resolve().parents[1] / "cases"


def _scenarios():
    for case in sorted(CASES.glob("*.toml")):
        deal = Deal.from_toml(case)
        yield pytest.param(deal, id=f"{case.stem}-base")
        yield pytest.param(deal.with_overrides(sweep_pct=0.5), id=f"{case.stem}-half-sweep")
        # Deep margin miss at higher leverage forces revolver draws.
        yield pytest.param(apply(apply(deal, "margin_delta", -0.10), "leverage", 6.0),
                           id=f"{case.stem}-revolver-draw")
        yield pytest.param(deal.with_overrides(exit_year=3, exit_multiple=11.0), id=f"{case.stem}-early-exit")


def _label_rows(path: Path, sheet: str) -> dict[str, int]:
    ws = load_workbook(path)[sheet]
    return {ws.cell(i, 2).value: i for i in range(1, ws.max_row + 1) if ws.cell(i, 2).value}


@pytest.mark.parametrize("deal", _scenarios())
def test_excel_matches_python(deal, tmp_path):
    path = export(deal, tmp_path / "model.xlsx", sensitivities=False)
    xl = pycel.ExcelCompiler(filename=str(path))
    rows = _label_rows(path, "Returns")
    result = run(deal)

    assert xl.evaluate(f"Returns!C{rows['IRR']}") == pytest.approx(result.irr, abs=1e-9)
    assert xl.evaluate(f"Returns!C{rows['MOIC']}") == pytest.approx(result.moic, abs=1e-9)
    assert xl.evaluate(f"Returns!C{rows['Sponsor equity at exit']}") == pytest.approx(
        result.returns["exit_equity"], abs=1e-6)
    assert xl.evaluate(f"Returns!C{rows['Check (should be zero)']}") == pytest.approx(0.0, abs=1e-6)
