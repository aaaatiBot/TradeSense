"""Acceptance tests for Expected Return and Optimizer (Phase 6, AT-07 through AT-10).

Verifies:
- AT-07: Budget boundary enforcement. Total committed <= effective_budget.
- AT-08: Position limit enforcement.
- AT-09: No affordable allocation handling (budget too small or zero affordable).
- AT-10: Expected net P&L matches independent authoritative calculation.
- OPT-11: Optimizer takes E[G_i] from ExpectedReturnService.
- OPT-12: Prior caution flag propagation.
- TST-13: >= 95% coverage on services/expected_return_service.py.
"""
from decimal import Decimal
import pytest

from app.services.cost_engine import CostEngine
from app.services.conditional_return_service import ConditionalReturnEstimate, ConditionalReturnService
from app.services.expected_return_service import (
    ExpectedReturnService,
    PortfolioExpectedReturn,
    StockReturnEstimate,
)
from app.services.optimizer_service import AllocatedPosition, OptimizationResult, OptimizerService


@pytest.fixture
def cost_engine():
    return CostEngine()


@pytest.fixture
def mock_conditional_service(mocker):
    service = mocker.MagicMock(spec=ConditionalReturnService)
    return service


@pytest.fixture
def expected_service(cost_engine, mock_conditional_service):
    return ExpectedReturnService(
        conditional_return_service=mock_conditional_service,
        cost_engine=cost_engine,
    )


@pytest.fixture
def optimizer_service(expected_service, cost_engine):
    return OptimizerService(
        expected_return_service=expected_service,
        cost_engine=cost_engine,
    )


def test_at_07_budget_boundary_enforcement(optimizer_service):
    """AT-07: Allocation shall never exceed effective budget."""
    candidates = [
        StockReturnEstimate(
            ticker="TICKER_A",
            price=Decimal("150.00"),
            p_i=Decimal("0.65"),
            g_plus=Decimal("15.00"),
            g_minus=Decimal("-8.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("6.95"),  # 0.65*15 + 0.35*(-8) = 9.75 - 2.80 = 6.95
        ),
        StockReturnEstimate(
            ticker="TICKER_B",
            price=Decimal("280.00"),
            p_i=Decimal("0.60"),
            g_plus=Decimal("25.00"),
            g_minus=Decimal("-15.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("9.00"),  # 0.60*25 + 0.40*(-15) = 15.0 - 6.0 = 9.00
        ),
    ]

    test_budgets = [
        Decimal("500.00"),
        Decimal("1000.00"),
        Decimal("5000.00"),
        Decimal("10000.00"),
        Decimal("50000.00"),
    ]

    for budget in test_budgets:
        res: OptimizationResult = optimizer_service.optimize_allocation(
            budget=budget,
            candidates=candidates,
            mode="CNC",
            cash_buffer_pct=Decimal("0.005"),  # 0.5%
            max_position_pct=Decimal("0.60"),
        )
        if res.status == "SUCCESS":
            # Strict boundary check: Capital committed <= effective_budget
            assert res.total_capital_committed <= res.effective_budget, (
                f"Budget violation: committed {res.total_capital_committed} > effective {res.effective_budget}"
            )
            assert res.total_allocated + res.total_buy_costs == res.total_capital_committed
            assert res.cash_buffer == budget - res.effective_budget
            assert len(res.positions) > 0


def test_at_08_position_limit_enforcement(optimizer_service):
    """AT-08: No single position shall exceed max_position_pct of effective budget."""
    candidates = [
        StockReturnEstimate(
            ticker="HIGH_ALPHA",
            price=Decimal("100.00"),
            p_i=Decimal("0.90"),
            g_plus=Decimal("30.00"),
            g_minus=Decimal("-5.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("26.50"),
        ),
        StockReturnEstimate(
            ticker="MED_ALPHA",
            price=Decimal("100.00"),
            p_i=Decimal("0.60"),
            g_plus=Decimal("15.00"),
            g_minus=Decimal("-10.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("5.00"),
        ),
    ]

    budget = Decimal("10000.00")
    max_pos_pct = Decimal("0.40")  # Max 40% in any single stock

    res = optimizer_service.optimize_allocation(
        budget=budget,
        candidates=candidates,
        mode="CNC",
        cash_buffer_pct=Decimal("0.01"),  # 1% buffer => effective budget 9900.00
        max_position_pct=max_pos_pct,
    )

    assert res.status == "SUCCESS"
    max_allowed = res.effective_budget * max_pos_pct

    for pos in res.positions:
        assert pos.allocated_amount <= max_allowed, (
            f"Position limit breached: {pos.ticker} allocated {pos.allocated_amount} > max allowed {max_allowed}"
        )


def test_at_09_no_affordable_allocation(optimizer_service):
    """AT-09: Insufficient budget or negative alpha yields clean NO_AFFORDABLE_ALLOCATION."""
    # Case 1: Budget too small for minimum share price
    expensive_candidates = [
        StockReturnEstimate(
            ticker="MRF",
            price=Decimal("120000.00"),
            p_i=Decimal("0.70"),
            g_plus=Decimal("5000.00"),
            g_minus=Decimal("-2000.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("2900.00"),
        )
    ]

    res = optimizer_service.optimize_allocation(
        budget=Decimal("1000.00"),
        candidates=expensive_candidates,
        mode="CNC",
    )
    assert res.status == "NO_AFFORDABLE_ALLOCATION"
    assert len(res.positions) == 0
    assert "lower than minimum share price" in res.reason

    # Case 2: All candidates have negative or zero expected gain
    loser_candidates = [
        StockReturnEstimate(
            ticker="LOSER_A",
            price=Decimal("50.00"),
            p_i=Decimal("0.20"),
            g_plus=Decimal("5.00"),
            g_minus=Decimal("-10.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            reference_notional=Decimal("500.00"),
            unit_expected_gain=Decimal("-7.00"),  # negative
        )
    ]

    res_losers = optimizer_service.optimize_allocation(
        budget=Decimal("5000.00"),
        candidates=loser_candidates,
        mode="CNC",
    )
    assert res_losers.status == "NO_AFFORDABLE_ALLOCATION"
    assert len(res_losers.positions) == 0
    assert "positive expected gain" in res_losers.reason


def test_at_10_expected_net_pnl_calculation_matches_independent_value(cost_engine, expected_service):
    """AT-10: Expected net P&L E[NP] = sum(E[G_i]) - C_portfolio(q) matches exact calculation."""
    # Stock 1: Price 200, p=0.7, G+=20, G-=-10 => E[G(1)] = 0.7*20 + 0.3*(-10) = 14 - 3 = 11.00
    # Quantity: 10 shares => Expected gain = 110.00
    est1 = StockReturnEstimate(
        ticker="TICKER_X",
        price=Decimal("200.00"),
        p_i=Decimal("0.70"),
        g_plus=Decimal("20.00"),
        g_minus=Decimal("-10.00"),
        estimate_source="ticker_baseline",
        method_version="1.0",
        reference_notional=Decimal("500.00"),
        unit_expected_gain=Decimal("11.00"),
    )

    # Stock 2: Price 100, p=0.6, G+=10, G-=-8 => E[G(1)] = 0.6*10 + 0.4*(-8) = 6 - 3.2 = 2.80
    # Quantity: 5 shares => Expected gain = 14.00
    est2 = StockReturnEstimate(
        ticker="TICKER_Y",
        price=Decimal("100.00"),
        p_i=Decimal("0.60"),
        g_plus=Decimal("10.00"),
        g_minus=Decimal("-8.00"),
        estimate_source="universe_baseline",
        method_version="1.0",
        reference_notional=Decimal("500.00"),
        unit_expected_gain=Decimal("2.80"),
    )

    quantities = {"TICKER_X": 10, "TICKER_Y": 5}

    # Expected gross gain = 10 * 11.00 + 5 * 2.80 = 110.00 + 14.00 = 124.00
    expected_gross = Decimal("124.00")

    # Authoritative modeled cost calculation:
    costs_portfolio = cost_engine.calculate_portfolio_costs(
        trades=[
            ("TICKER_X", "INE_TICKER_X", 10, Decimal("200.00"), Decimal("200.00")),
            ("TICKER_Y", "INE_TICKER_Y", 5, Decimal("100.00"), Decimal("100.00")),
        ],
        mode="CNC",
    )

    total_expected_costs = costs_portfolio.total_charges
    independent_net_pnl = expected_gross - total_expected_costs

    portfolio_res = expected_service.calculate_portfolio_expected_net_pnl(
        estimates=[est1, est2],
        quantities=quantities,
        mode="CNC",
    )

    assert portfolio_res.total_expected_gain == expected_gross
    assert portfolio_res.total_modeled_costs == total_expected_costs
    assert portfolio_res.expected_net_pnl == independent_net_pnl


def test_opt_12_prior_caution_flag_propagation(optimizer_service):
    """OPT-12: If an allocated stock has estimate_source == 'prior', flag prior caution."""
    prior_candidate = StockReturnEstimate(
        ticker="NEW_IPO",
        price=Decimal("50.00"),
        p_i=Decimal("0.80"),
        g_plus=Decimal("6.00"),
        g_minus=Decimal("-2.00"),
        estimate_source="prior",  # Uncalibrated prior
        method_version="1.0",
        reference_notional=Decimal("500.00"),
        unit_expected_gain=Decimal("4.40"),
    )

    res = optimizer_service.optimize_allocation(
        budget=Decimal("1000.00"),
        candidates=[prior_candidate],
        mode="CNC",
    )

    assert res.status == "SUCCESS"
    assert res.has_prior_caution is True
    assert res.positions[0].has_prior_caution is True
    assert res.positions[0].estimate_source == "prior"


def test_expected_return_service_validation_and_unit(expected_service, mock_conditional_service):
    """Verifies input validation and edge cases on ExpectedReturnService."""
    mock_conditional_service.get_estimates.return_value = ConditionalReturnEstimate(
        ticker="RELIANCE",
        horizon="1d",
        mode="CNC",
        g_plus=Decimal("25.00"),
        g_minus=Decimal("-12.00"),
        sample_count=95,
        estimate_source="ticker_baseline",
        method_version="1.0",
    )

    # Valid estimate
    est = expected_service.estimate_stock_return(
        ticker="RELIANCE",
        price=Decimal("2500.00"),
        horizon="1d",
        mode="CNC",
        p_i=Decimal("0.60"),
    )
    assert est.ticker == "RELIANCE"
    assert est.p_i == Decimal("0.60")
    # unit_gain = 0.6 * 25 + 0.4 * (-12) = 15 - 4.8 = 10.20
    assert est.unit_expected_gain == Decimal("10.200000")
    assert est.compute_expected_gain(5) == Decimal("51.0000")

    # Invalid probability
    with pytest.raises(ValueError, match="Probability p_i must be in"):
        expected_service.estimate_stock_return(
            ticker="RELIANCE",
            price=Decimal("2500.00"),
            horizon="1d",
            mode="CNC",
            p_i=Decimal("1.50"),
        )

    # Negative price
    with pytest.raises(ValueError, match="Share price must be positive"):
        expected_service.estimate_stock_return(
            ticker="RELIANCE",
            price=Decimal("-10.00"),
            horizon="1d",
            mode="CNC",
            p_i=Decimal("0.50"),
        )

    # Negative quantity in compute_expected_gain
    with pytest.raises(ValueError, match="Quantity must be non-negative"):
        est.compute_expected_gain(-5)


def test_optimizer_validation_errors(optimizer_service):
    """Verifies parameter validation in OptimizerService."""
    candidate = StockReturnEstimate(
        ticker="INFY",
        price=Decimal("1500.00"),
        p_i=Decimal("0.60"),
        g_plus=Decimal("20.00"),
        g_minus=Decimal("-10.00"),
        estimate_source="ticker_baseline",
        method_version="1.0",
        reference_notional=Decimal("500.00"),
        unit_expected_gain=Decimal("8.00"),
    )

    # Negative budget
    with pytest.raises(ValueError, match="Budget must be positive"):
        optimizer_service.optimize_allocation(budget=Decimal("-100"), candidates=[candidate])

    # Invalid cash buffer pct
    with pytest.raises(ValueError, match="Cash buffer pct must be in"):
        optimizer_service.optimize_allocation(
            budget=Decimal("1000"), candidates=[candidate], cash_buffer_pct=Decimal("1.5")
        )

    # Invalid max position pct
    with pytest.raises(ValueError, match="Max position pct must be in"):
        optimizer_service.optimize_allocation(
            budget=Decimal("1000"), candidates=[candidate], max_position_pct=Decimal("0.0")
        )
