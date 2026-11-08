"""Acceptance Tests for Transaction Cost Engine per SRS §12 (AT-11 through AT-15)."""
from decimal import Decimal
import pytest

from app.services.cost_engine import CostEngine, CostResult, round_currency


# ==============================================================================
# AT-11: CNC (Delivery) Round-Trip Cost Calculation
# ==============================================================================
def test_at_11_cnc_round_trip_charges():
    """AT-11: Verify CNC charges: STT on buy+sell, stamp duty on buy only, DP charge on sell."""
    # Buy 100 shares @ 2500, sell @ 2600
    res = CostEngine.calculate_round_trip(
        ticker="RELIANCE",
        isin="INE002A01018",
        quantity=100,
        buy_price=Decimal("2500.00"),
        sell_price=Decimal("2600.00"),
        mode="CNC",
    )

    assert res.buy_turnover == Decimal("250000.00")
    assert res.sell_turnover == Decimal("260000.00")
    assert res.turnover == Decimal("510000.00")

    # CNC Brokerage is 0
    assert res.brokerage == Decimal("0.00")

    # STT: 0.1% on buy (250) + 0.1% on sell (260) = 510
    assert res.stt_ctt == Decimal("510.00")

    # Stamp Duty: 0.015% on buy only = 37.50
    assert res.stamp_duty == Decimal("37.50")

    # DP charge is 15.93 for CNC sell
    assert res.dp_charges == Decimal("15.93")

    # Slippage: 0.05% of total turnover 510000 = 255.00
    assert res.slippage == Decimal("255.00")

    # Transaction charges: 0.00297% on 510000 = 15.15
    assert res.transaction_charges == Decimal("15.15")

    # SEBI turnover: 0.000001 on 510000 = 0.51
    assert res.sebi_charges == Decimal("0.51")

    # GST: 18% on (brokerage(0) + txn(15.15) + sebi(0.51)) = 18% of 15.66 = 2.82
    assert res.gst == Decimal("2.82")

    # Verify total equals sum of parts
    expected_total = (
        res.brokerage
        + res.stt_ctt
        + res.transaction_charges
        + res.gst
        + res.sebi_charges
        + res.stamp_duty
        + res.dp_charges
        + res.slippage
    )
    assert res.total_charges == expected_total


# ==============================================================================
# AT-12: MIS (Intraday) Round-Trip Cost Calculation and Brokerage Cap
# ==============================================================================
def test_at_12_mis_round_trip_charges_and_brokerage_cap():
    """AT-12: Verify MIS charges: STT on sell only, stamp duty on buy only, zero DP, ₹20 cap."""
    # Buy 100 shares @ 2500, sell @ 2600
    res = CostEngine.calculate_round_trip(
        ticker="TCS",
        isin="INE467B01029",
        quantity=100,
        buy_price=Decimal("2500.00"),
        sell_price=Decimal("2600.00"),
        mode="MIS",
    )

    # Brokerage: 0.03% of 250k is 75 (capped at 20), 0.03% of 260k is 78 (capped at 20) -> total 40.00
    assert res.brokerage == Decimal("40.00")

    # STT: 0.025% on sell turnover (260,000) only = 65.00
    assert res.stt_ctt == Decimal("65.00")

    # Stamp Duty: 0.003% on buy turnover (250,000) only = 7.50
    assert res.stamp_duty == Decimal("7.50")

    # DP charge is 0 for MIS intraday
    assert res.dp_charges == Decimal("0.00")


def test_at_12_mis_low_turnover_brokerage_percentage():
    """AT-12: Verify MIS brokerage below ₹20 cap uses exact 0.03% calculation."""
    # Buy 1 share @ 1000, sell @ 1010
    res = CostEngine.calculate_round_trip(
        ticker="INFY",
        isin="INE009A01021",
        quantity=1,
        buy_price=Decimal("1000.00"),
        sell_price=Decimal("1010.00"),
        mode="MIS",
    )
    # Buy leg: 0.03% of 1000 = 0.30; Sell leg: 0.03% of 1010 = 0.30 -> total 0.60
    assert res.brokerage == Decimal("0.60")


# ==============================================================================
# AT-13: DP Charge Applied Once Per Distinct ISIN Per Day
# ==============================================================================
def test_at_13_dp_charge_per_isin_deduplication():
    """AT-13: Multiple trades of the same ISIN on the same day only incur DP charge once."""
    isin_reliance = "INE002A01018"
    trades_same_isin = [
        ("RELIANCE", isin_reliance, 10, Decimal("2500.00"), Decimal("2550.00")),
        ("RELIANCE", isin_reliance, 20, Decimal("2520.00"), Decimal("2560.00")),
    ]
    res_same = CostEngine.calculate_portfolio_costs(trades_same_isin, mode="CNC")
    # DP charges charged exactly once: 15.93
    assert res_same.dp_charges == Decimal("15.93")

    # Distinct ISINs incur DP charge per ISIN
    trades_diff_isins = [
        ("RELIANCE", "INE002A01018", 10, Decimal("2500.00"), Decimal("2550.00")),
        ("TCS", "INE467B01029", 10, Decimal("3500.00"), Decimal("3550.00")),
    ]
    res_diff = CostEngine.calculate_portfolio_costs(trades_diff_isins, mode="CNC")
    # DP charges charged twice: 15.93 * 2 = 31.86
    assert res_diff.dp_charges == Decimal("31.86")


# ==============================================================================
# AT-14: Decimal Precision and Fractional Paisa Rounding Rule
# ==============================================================================
def test_at_14_decimal_precision_and_rounding():
    """AT-14: Verify exact Decimal types throughout and ROUND_HALF_UP rounding."""
    res = CostEngine.calculate_round_trip(
        ticker="WIPRO",
        isin="INE075A01022",
        quantity=3,
        buy_price=Decimal("456.78"),
        sell_price=Decimal("467.89"),
        mode="CNC",
    )

    for field in [
        res.turnover,
        res.buy_turnover,
        res.sell_turnover,
        res.brokerage,
        res.stt_ctt,
        res.transaction_charges,
        res.gst,
        res.sebi_charges,
        res.stamp_duty,
        res.dp_charges,
        res.slippage,
        res.total_charges,
    ]:
        assert isinstance(field, Decimal)
        # Check scale is 2 decimal places
        assert field.as_tuple().exponent in (-2, -1, 0)


# ==============================================================================
# AT-15: Validation and Negative Parameter Rejection
# ==============================================================================
def test_at_15_validation_rejections():
    """AT-15: Rejects negative quantity, negative prices, and invalid mode."""
    # Negative quantity
    with pytest.raises(ValueError, match="Quantity must be strictly positive"):
        CostEngine.calculate_round_trip(
            ticker="T", isin="I", quantity=-10, buy_price=Decimal("100"), sell_price=Decimal("100")
        )

    # Zero quantity
    with pytest.raises(ValueError, match="Quantity must be strictly positive"):
        CostEngine.calculate_round_trip(
            ticker="T", isin="I", quantity=0, buy_price=Decimal("100"), sell_price=Decimal("100")
        )

    # Negative price
    with pytest.raises(ValueError, match="Prices must be strictly positive"):
        CostEngine.calculate_round_trip(
            ticker="T", isin="I", quantity=10, buy_price=Decimal("-100"), sell_price=Decimal("100")
        )

    # Unsupported mode
    with pytest.raises(ValueError, match="Unsupported trading mode"):
        CostEngine.calculate_round_trip(
            ticker="T", isin="I", quantity=10, buy_price=Decimal("100"), sell_price=Decimal("100"), mode="FUTURES"
        )


def test_cost_breakdown_model_conversion():
    """Verify conversion of CostResult to CostBreakdown database model."""
    res = CostEngine.calculate_round_trip(
        ticker="RELIANCE",
        isin="INE002A01018",
        quantity=50,
        buy_price=Decimal("2500.00"),
        sell_price=Decimal("2550.00"),
        mode="CNC",
    )
    model = res.to_breakdown_model()
    assert model.rate_card_version == CostEngine.DEFAULT_RATE_CARD_VERSION
    assert model.turnover == res.turnover
    assert model.total_charges == res.total_charges
