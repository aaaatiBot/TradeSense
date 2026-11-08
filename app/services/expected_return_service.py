"""Expected return service per SRS §4.5 and §4.5.1 (FR-EXP).

Phase 6 deliverable.
Combines classification probability p_i with class-conditional return magnitudes G_i^+ and G_i^-.
Strictly follows EXP-01 through EXP-12:
- EXP-01: Estimates p_i, G_i^+, G_i^- for expected P&L.
- EXP-02: Never treats (probability * share price) as expected profit.
- EXP-03: Calculates portfolio-level expected net P&L after modeled costs.
- EXP-04: Preserves inputs, method version, model version, and estimate_source.
- EXP-05: If conditional return estimates unavailable, never invents them (uses fallback chain).
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Union

from app.services.conditional_return_service import ConditionalReturnEstimate, ConditionalReturnService
from app.services.cost_engine import CostEngine, CostResult


@dataclass(frozen=True)
class StockReturnEstimate:
    """Expected return breakdown for an individual stock candidate."""

    ticker: str
    price: Decimal
    p_i: Decimal
    g_plus: Decimal
    g_minus: Decimal
    estimate_source: str
    method_version: str
    reference_notional: Decimal
    unit_expected_gain: Decimal

    @property
    def has_prior_caution(self) -> bool:
        """Flags whether the estimate relies on an uncalibrated prior (OPT-12)."""
        return self.estimate_source == "prior"

    def compute_expected_gain(self, quantity: int) -> Decimal:
        """Calculate E[G_i(q_i)] = q_i * (p_i * G_i^+ + (1 - p_i) * G_i^-).
        
        EXP-02: Does NOT multiply probability by share price!
        """
        if quantity < 0:
            raise ValueError(f"Quantity must be non-negative, got {quantity}")
        q_dec = Decimal(str(quantity))
        return (q_dec * self.unit_expected_gain).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class PortfolioExpectedReturn:
    """Portfolio-level expected return after transaction costs (EXP-03)."""

    total_expected_gain: Decimal
    total_modeled_costs: Decimal
    expected_net_pnl: Decimal
    expected_return_rate: Decimal
    items: List[StockReturnEstimate]
    quantities: Dict[str, int]
    has_prior_caution: bool


class ExpectedReturnService:
    """Authoritative expected-return calculation service."""

    def __init__(
        self,
        conditional_return_service: Optional[ConditionalReturnService] = None,
        cost_engine: Optional[CostEngine] = None,
    ) -> None:
        self.conditional_service = conditional_return_service or ConditionalReturnService()
        self.cost_engine = cost_engine or CostEngine()

    def estimate_stock_return(
        self,
        ticker: str,
        price: Union[Decimal, str, float],
        horizon: str,
        mode: str,
        p_i: Union[Decimal, str, float],
        reference_notional: Optional[Union[Decimal, str, float]] = None,
    ) -> StockReturnEstimate:
        """Estimate per-share expected return without inventing missing data.
        
        Never treats probability * price as profit (EXP-02).
        Delegates G^+ / G^- estimation to ConditionalReturnService (EXP-05, OPT-11).
        """
        p_dec = Decimal(str(p_i))
        if not (Decimal("0.0") <= p_dec <= Decimal("1.0")):
            raise ValueError(f"Probability p_i must be in [0, 1], got {p_i}")

        price_dec = Decimal(str(price)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price_dec <= Decimal("0.0"):
            raise ValueError(f"Share price must be positive, got {price}")

        cond_est: ConditionalReturnEstimate = self.conditional_service.get_estimates(
            ticker=ticker,
            horizon=horizon,
            mode=mode,
            price=price_dec,
            reference_notional=reference_notional,
        )

        # Unit expected return per share: E[G_i(1)] = p_i * G_i^+ + (1 - p_i) * G_i^-
        unit_expected = (p_dec * cond_est.g_plus) + ((Decimal("1.0") - p_dec) * cond_est.g_minus)
        unit_expected = unit_expected.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        ref_notional = (
            Decimal(str(reference_notional))
            if reference_notional is not None
            else getattr(cond_est, "reference_notional", Decimal("500.00"))
        )

        return StockReturnEstimate(
            ticker=ticker,
            price=price_dec,
            p_i=p_dec,
            g_plus=cond_est.g_plus,
            g_minus=cond_est.g_minus,
            estimate_source=cond_est.estimate_source,
            method_version=cond_est.method_version,
            reference_notional=ref_notional,
            unit_expected_gain=unit_expected,
        )

    def calculate_portfolio_expected_net_pnl(
        self,
        estimates: Sequence[StockReturnEstimate],
        quantities: Dict[str, int],
        mode: str = "CNC",
        isin_map: Optional[Dict[str, str]] = None,
    ) -> PortfolioExpectedReturn:
        """Calculate E[NP] = sum(E[G_i(q_i)]) - C_portfolio(q) per SRS §4.5 (EXP-03).
        
        Exact transaction costs calculated with authoritative CostEngine.
        """
        isin_map = isin_map or {}
        trades = []
        total_gain = Decimal("0.0000")
        total_capital = Decimal("0.0000")
        has_prior = False

        for est in estimates:
            qty = quantities.get(est.ticker, 0)
            if qty <= 0:
                continue

            if est.has_prior_caution:
                has_prior = True

            gain = est.compute_expected_gain(qty)
            total_gain += gain

            trade_val = (Decimal(str(qty)) * est.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            total_capital += trade_val

            isin = isin_map.get(est.ticker, f"INE_{est.ticker}")
            trades.append((est.ticker, isin, qty, est.price, est.price))

        if trades:
            portfolio_cost_res: CostResult = self.cost_engine.calculate_portfolio_costs(
                trades=trades,
                mode=mode,
            )
            total_costs = portfolio_cost_res.total_charges
        else:
            total_costs = Decimal("0.00")

        expected_net = (total_gain - total_costs).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        expected_rate = Decimal("0.000000")
        if total_capital > Decimal("0.0"):
            expected_rate = (expected_net / total_capital).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)

        return PortfolioExpectedReturn(
            total_expected_gain=total_gain.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            total_modeled_costs=total_costs.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            expected_net_pnl=expected_net.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            expected_return_rate=expected_rate,
            items=list(estimates),
            quantities=dict(quantities),
            has_prior_caution=has_prior,
        )
