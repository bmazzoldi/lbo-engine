from dataclasses import replace
from pathlib import Path

import pytest

from lbo import Deal, Operating, Revolver, Tranche, run
from lbo.sensitivity import apply, grid

CASES = Path(__file__).resolve().parents[1] / "cases"


def toy_deal(**overrides) -> Deal:
    """Small deal that is easy to check by hand: no taxes, capex, D&A, NWC or fees."""
    op = Operating(
        ltm_revenue=100.0, ltm_ebitda_margin=0.20,
        revenue_growth=[0.0, 0.0], ebitda_margin=[0.20, 0.20],
        da_pct_revenue=0.0, capex_pct_revenue=0.0, nwc_pct_revenue=0.0, tax_rate=0.0,
    )
    base = dict(
        name="Toy", entry_multiple=5.0, exit_multiple=5.0, exit_year=2, operating=op,
        tranches=[Tranche("TL", multiple=2.0, cash_rate=0.10)],
        transaction_fee_pct=0.0, financing_fee_pct=0.0, min_cash=0.0,
    )
    base.update(overrides)
    return Deal(**base)


def test_hand_calculated_case():
    # EV 100, debt 40, equity 60.
    # Y1: interest 4.0, FCF 16.0 swept -> debt 24.0
    # Y2: interest 2.4, FCF 17.6 swept -> debt 6.4
    # Exit: 5.0x * 20 = 100 - 6.4 = 93.6 -> MOIC 1.56
    r = run(toy_deal())
    assert r.returns["sponsor_equity"] == pytest.approx(60.0)
    assert r.debt.loc[("TL", "Closing")].tolist() == pytest.approx([40.0, 24.0, 6.4])
    assert r.returns["exit_equity"] == pytest.approx(93.6)
    assert r.moic == pytest.approx(1.56)
    assert r.irr == pytest.approx(1.56 ** 0.5 - 1)


def test_no_sweep_builds_cash():
    r = run(toy_deal(sweep_pct=0.0))
    assert r.debt.loc[("TL", "Closing")].tolist() == pytest.approx([40.0, 40.0, 40.0])
    assert r.projections.loc["Cash"].tolist() == pytest.approx([0.0, 16.0, 32.0])
    # Same net debt path is not expected (interest stays higher), but equity must still tie.
    assert r.returns["exit_equity"] == pytest.approx(100.0 - 40.0 + 32.0)


def test_pik_compounds():
    deal = toy_deal(tranches=[Tranche("PIK", multiple=1.0, cash_rate=0.0, pik_rate=0.12, sweep=False)],
                    sweep_pct=0.0)
    r = run(deal)
    assert r.debt.loc[("PIK", "Closing")].iloc[-1] == pytest.approx(20.0 * 1.12 ** 2)


def test_mandatory_amortization_capped_at_balance():
    deal = toy_deal(tranches=[Tranche("TL", multiple=0.5, cash_rate=0.0, amortization=0.75, sweep=False)],
                    sweep_pct=0.0)
    r = run(deal)
    assert r.debt.loc[("TL", "Mandatory")].tolist() == pytest.approx([0.0, 7.5, 2.5])
    assert r.debt.loc[("TL", "Closing")].iloc[-1] == pytest.approx(0.0)


def test_sweep_respects_priority():
    deal = toy_deal(tranches=[
        Tranche("Junior", multiple=1.0, cash_rate=0.0, priority=2),
        Tranche("Senior", multiple=1.0, cash_rate=0.0, priority=1),
    ])
    r = run(deal)
    # 20 of FCF in year 1 fully repays Senior (20) before Junior sees anything.
    assert r.debt.loc[("Senior", "Closing")].iloc[1] == pytest.approx(0.0)
    assert r.debt.loc[("Junior", "Closing")].iloc[1] == pytest.approx(20.0)


def test_revolver_funds_shortfall_and_holds_min_cash():
    op = replace(toy_deal().operating, ebitda_margin=[0.01, 0.01])
    deal = toy_deal(operating=op, min_cash=5.0, revolver=Revolver(commitment=50.0, rate=0.08))
    r = run(deal)
    draws = r.debt.loc[("Revolver", "Draw")]
    assert draws.iloc[1] > 0
    assert r.projections.loc["Cash"].tolist() == pytest.approx([5.0, 5.0, 5.0])


@pytest.mark.parametrize("case", sorted(CASES.glob("*.toml")))
def test_sources_equal_uses(case):
    r = run(Deal.from_toml(case))
    assert r.sources.sum() == pytest.approx(r.uses.sum())


@pytest.mark.parametrize("case", sorted(CASES.glob("*.toml")))
def test_attribution_sums_to_equity_gain(case):
    r = run(Deal.from_toml(case))
    gain = r.returns["exit_equity"] - r.returns["sponsor_equity"]
    assert r.attribution.sum() == pytest.approx(gain)


@pytest.mark.parametrize("case", sorted(CASES.glob("*.toml")))
def test_balances_never_negative(case):
    deal = apply(Deal.from_toml(case), "margin_delta", -0.10)
    r = run(deal)
    closing = r.debt.xs("Closing", level=1)
    assert (closing.values >= -1e-9).all()
    assert (r.projections.loc["Cash"].values >= deal.min_cash - 1e-9).all()


def test_equity_value_floored_at_zero():
    op = replace(toy_deal().operating, ebitda_margin=[0.01, 0.01])
    r = run(toy_deal(operating=op, exit_multiple=1.0,
                     tranches=[Tranche("TL", multiple=4.5, cash_rate=0.10)],
                     revolver=Revolver(commitment=100.0, rate=0.08)))
    assert r.returns["exit_equity"] < 0
    assert r.moic == 0.0
    assert r.irr == -1.0


def test_leverage_override_hits_target():
    deal = apply(Deal.from_toml(CASES / "project_halyard.toml"), "leverage", 6.0)
    assert sum(t.multiple for t in deal.tranches) == pytest.approx(6.0)
    assert run(deal).returns["entry_leverage"] == pytest.approx(6.0)


def test_irr_increases_with_exit_multiple():
    deal = Deal.from_toml(CASES / "project_halyard.toml")
    table = grid(deal, ("entry_multiple", [10.0]), ("exit_multiple", [8.0, 9.0, 10.0, 11.0]))
    row = table.iloc[0].tolist()
    assert row == sorted(row)


def test_invalid_inputs_rejected():
    with pytest.raises(ValueError):
        toy_deal(exit_year=3)
    with pytest.raises(ValueError):
        toy_deal(sweep_pct=1.5)
    with pytest.raises(ValueError):
        run(toy_deal(tranches=[Tranche("TL", multiple=6.0, cash_rate=0.1)]))
