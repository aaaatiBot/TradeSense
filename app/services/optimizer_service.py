"""Budget-constrained portfolio optimizer per SRS §4.6 (FR-OPT).

Phase 6 deliverable.
Solves integer programming allocation under exact user budget constraints.
Requirements:
- OPT-01 through OPT-10: Budget safety, integer shares, position limits.
- OPT-11: Does NOT compute G^+ or G^- itself; consumes them from ExpectedReturnService (§4.5.1).
- OPT-12: When estimate_source == 'prior', flags caution on recommendation.
- Authoritative Decimal verification: Recomputes final allocation via CostEngine.
- Rejects any allocation exceeding effective budget.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp

from app.services.cost_engine import CostEngine, CostResult
from app.services.expected_return_service import ExpectedReturnService, PortfolioExpectedReturn, StockReturnEstimate


class OptimizationError(Exception):
    """Raised when optimization encounters an unrecoverable invalid state."""
    pass


@dataclass(frozen=True)
class AllocatedPosition:
    """Individual stock allocation in the optimized portfolio."""

    ticker: str
    quantity: int
    price: Decimal
    allocated_amount: Decimal
    p_i: Decimal
    g_plus: Decimal
    g_minus: Decimal
    estimate_source: str
    method_version: str
    reference_notional: Decimal
    expected_gain: Decimal
    has_prior_caution: bool


@dataclass(frozen=True)
class OptimizationResult:
    """Result of budget-constrained portfolio optimization."""

    status: str  # 'SUCCESS' or 'NO_AFFORDABLE_ALLOCATION'
    budget: Decimal
    effective_budget: Decimal
    cash_buffer: Decimal
    total_allocated: Decimal
    total_buy_costs: Decimal
    total_capital_committed: Decimal
    expected_net_pnl: Decimal
    expected_return_rate: Decimal
    total_modeled_costs: Decimal
    positions: List[AllocatedPosition] = field(default_factory=list)
    has_prior_caution: bool = False
    reason: Optional[str] = None


class OptimizerService:
    """Deterministic integer portfolio optimizer."""

    def __init__(
        self,
        expected_return_service: Optional[ExpectedReturnService] = None,
        cost_engine: Optional[CostEngine] = None,
        default_cash_buffer_pct: Union[Decimal, str, float] = Decimal("0.005"),
        default_max_candidate_set: int = 20,
    ) -> None:
        self.expected_service = expected_return_service or ExpectedReturnService()
        self.cost_engine = cost_engine or CostEngine()
        self.default_cash_buffer_pct = Decimal(str(default_cash_buffer_pct))
        self.default_max_candidate_set = default_max_candidate_set

    def optimize_allocation(
        self,
        budget: Union[Decimal, str, float],
        candidates: Sequence[StockReturnEstimate],
        mode: str = "CNC",
        horizon: str = "1d",
        cash_buffer_pct: Optional[Union[Decimal, str, float]] = None,
        max_position_pct: Optional[Union[Decimal, str, float]] = Decimal("0.50"),
        isin_map: Optional[Dict[str, str]] = None,
    ) -> OptimizationResult:
        """Optimize portfolio allocation subject to strict budget and position constraints.
        
        Args:
            budget: Total available investment budget in INR.
            candidates: Pre-calculated StockReturnEstimate candidates (OPT-11).
            mode: 'CNC' or 'MIS'.
            horizon: Investment horizon (e.g. '1d', '5d').
            cash_buffer_pct: Buffer ratio (default 0.005 = 0.5%).
            max_position_pct: Maximum fraction of effective budget per stock.
            isin_map: Ticker -> ISIN mapping for accurate DP charges.
        """
        budget_dec = Decimal(str(budget)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if budget_dec <= Decimal("0.0"):
            raise ValueError(f"Budget must be positive, got {budget}")

        buf_pct = Decimal(str(cash_buffer_pct)) if cash_buffer_pct is not None else self.default_cash_buffer_pct
        if not (Decimal("0.0") <= buf_pct < Decimal("1.0")):
            raise ValueError(f"Cash buffer pct must be in [0, 1), got {buf_pct}")

        pos_pct = Decimal(str(max_position_pct)) if max_position_pct is not None else Decimal("1.0")
        if not (Decimal("0.0") < pos_pct <= Decimal("1.0")):
            raise ValueError(f"Max position pct must be in (0, 1], got {pos_pct}")

        # Effective budget calculation
        effective_budget = (budget_dec * (Decimal("1.0") - buf_pct)).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        cash_buffer = (budget_dec - effective_budget).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

        # Filter candidate set (limit to max_candidate_set, default 20 per §4.6)
        valid_candidates = [c for c in candidates if c.unit_expected_gain > Decimal("0.0") and c.price > Decimal("0.0")]
        # Sort descending by unit expected return rate (unit_gain / price)
        valid_candidates.sort(key=lambda c: (c.unit_expected_gain / c.price), reverse=True)
        valid_candidates = valid_candidates[: self.default_max_candidate_set]

        if not valid_candidates:
            return OptimizationResult(
                status="NO_AFFORDABLE_ALLOCATION",
                budget=budget_dec,
                effective_budget=effective_budget,
                cash_buffer=cash_buffer,
                total_allocated=Decimal("0.00"),
                total_buy_costs=Decimal("0.00"),
                total_capital_committed=Decimal("0.00"),
                expected_net_pnl=Decimal("0.00"),
                expected_return_rate=Decimal("0.000000"),
                total_modeled_costs=Decimal("0.00"),
                positions=[],
                reason="No candidate stocks with positive expected gain",
            )

        # Check if the cheapest candidate is affordable with 1 share
        cheapest_price = min(c.price for c in valid_candidates)
        if cheapest_price > effective_budget:
            return OptimizationResult(
                status="NO_AFFORDABLE_ALLOCATION",
                budget=budget_dec,
                effective_budget=effective_budget,
                cash_buffer=cash_buffer,
                total_allocated=Decimal("0.00"),
                total_buy_costs=Decimal("0.00"),
                total_capital_committed=Decimal("0.00"),
                expected_net_pnl=Decimal("0.00"),
                expected_return_rate=Decimal("0.000000"),
                total_modeled_costs=Decimal("0.00"),
                positions=[],
                reason="Budget is lower than minimum share price for all eligible candidates",
            )

        n = len(valid_candidates)
        # Compute maximum quantity upper bound per candidate
        max_pos_budget = (effective_budget * pos_pct).quantize(Decimal("0.01"), rounding=ROUND_FLOOR)
        upper_bounds = []
        for c in valid_candidates:
            max_qty = int(max_pos_budget // c.price)
            upper_bounds.append(max_qty)

        if all(ub == 0 for ub in upper_bounds):
            # If position limit prevented even 1 share of any stock
            return OptimizationResult(
                status="NO_AFFORDABLE_ALLOCATION",
                budget=budget_dec,
                effective_budget=effective_budget,
                cash_buffer=cash_buffer,
                total_allocated=Decimal("0.00"),
                total_buy_costs=Decimal("0.00"),
                total_capital_committed=Decimal("0.00"),
                expected_net_pnl=Decimal("0.00"),
                expected_return_rate=Decimal("0.000000"),
                total_modeled_costs=Decimal("0.00"),
                positions=[],
                reason="Position limit constraint prevents purchasing at least 1 share of any candidate",
            )

        # Approximate buy cost multiplier (e.g., 0.15% to cover brokerage, GST, stamp duty)
        cost_multiplier = 1.002

        # Formulate MILP integer program
        # Maximize: sum(q_i * unit_expected_gain_i)
        # scipy.optimize.milp minimizes c^T x
        c_obj = -np.array([float(c.unit_expected_gain) for c in valid_candidates], dtype=np.float64)

        # Constraint: sum(q_i * price_i * cost_multiplier) <= float(effective_budget)
        A_budget = np.array([[float(c.price) * cost_multiplier for c in valid_candidates]], dtype=np.float64)
        constraints = LinearConstraint(A_budget, lb=0.0, ub=float(effective_budget))

        # Integrality: 1 for integer variable
        integrality = np.ones(n, dtype=int)
        bounds = Bounds(lb=np.zeros(n, dtype=np.float64), ub=np.array(upper_bounds, dtype=np.float64))

        res = milp(c=c_obj, integrality=integrality, bounds=bounds, constraints=constraints)

        if not res.success or res.x is None:
            raw_quantities = {c.ticker: 0 for c in valid_candidates}
        else:
            raw_quantities = {
                valid_candidates[i].ticker: int(np.round(res.x[i])) for i in range(n)
            }

        # --- Exact Authoritative Decimal Verification ---
        # Ensure that exact capital committed (allocation + buy costs via CostEngine) <= effective_budget
        alloc_quantities = {t: q for t, q in raw_quantities.items() if q > 0}

        def verify_budget_compliance(current_quantities: Dict[str, int]) -> tuple[bool, Decimal, Decimal, Decimal]:
            if not current_quantities:
                return True, Decimal("0.00"), Decimal("0.00"), Decimal("0.00")
            
            allocated_val = Decimal("0.00")
            buy_costs_val = Decimal("0.00")
            for c in valid_candidates:
                q = current_quantities.get(c.ticker, 0)
                if q <= 0:
                    continue
                pos_val = (Decimal(str(q)) * c.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                allocated_val += pos_val
                
                # Single-leg buy costs
                b_costs = self.cost_engine.calculate_single_leg(
                    quantity=q,
                    price=c.price,
                    action="BUY",
                    mode=mode,
                )
                buy_costs_val += b_costs.total_charges

            total_committed = allocated_val + buy_costs_val
            is_compliant = total_committed <= effective_budget
            return is_compliant, allocated_val, buy_costs_val, total_committed

        compliant, total_allocated, total_buy_costs, total_committed = verify_budget_compliance(alloc_quantities)

        # If slightly over budget due to flat costs/rounding, back off iteratively
        while not compliant and alloc_quantities:
            # Pick candidate with smallest unit gain per share to decrement
            active_tickers = [c for c in valid_candidates if alloc_quantities.get(c.ticker, 0) > 0]
            if not active_tickers:
                break
            # Sort by ascending unit gain per rupee
            active_tickers.sort(key=lambda c: (c.unit_expected_gain / c.price))
            ticker_to_decrement = active_tickers[0].ticker
            alloc_quantities[ticker_to_decrement] -= 1
            if alloc_quantities[ticker_to_decrement] <= 0:
                del alloc_quantities[ticker_to_decrement]
            compliant, total_allocated, total_buy_costs, total_committed = verify_budget_compliance(alloc_quantities)

        if not alloc_quantities or total_allocated == Decimal("0.00"):
            return OptimizationResult(
                status="NO_AFFORDABLE_ALLOCATION",
                budget=budget_dec,
                effective_budget=effective_budget,
                cash_buffer=cash_buffer,
                total_allocated=Decimal("0.00"),
                total_buy_costs=Decimal("0.00"),
                total_capital_committed=Decimal("0.00"),
                expected_net_pnl=Decimal("0.00"),
                expected_return_rate=Decimal("0.000000"),
                total_modeled_costs=Decimal("0.00"),
                positions=[],
                reason="Costs exceed remaining budget; no non-zero allocation satisfies budget constraints",
            )

        # Compute full portfolio expected net return and modeled costs via ExpectedReturnService (EXP-03)
        portfolio_return: PortfolioExpectedReturn = self.expected_service.calculate_portfolio_expected_net_pnl(
            estimates=[c for c in valid_candidates if alloc_quantities.get(c.ticker, 0) > 0],
            quantities=alloc_quantities,
            mode=mode,
            isin_map=isin_map,
        )

        # Build position list
        positions = []
        has_prior = False
        for c in valid_candidates:
            qty = alloc_quantities.get(c.ticker, 0)
            if qty <= 0:
                continue
            if c.has_prior_caution:
                has_prior = True
            amt = (Decimal(str(qty)) * c.price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            gain = c.compute_expected_gain(qty)
            positions.append(
                AllocatedPosition(
                    ticker=c.ticker,
                    quantity=qty,
                    price=c.price,
                    allocated_amount=amt,
                    p_i=c.p_i,
                    g_plus=c.g_plus,
                    g_minus=c.g_minus,
                    estimate_source=c.estimate_source,
                    method_version=c.method_version,
                    reference_notional=c.reference_notional,
                    expected_gain=gain,
                    has_prior_caution=c.has_prior_caution,
                )
            )

        return OptimizationResult(
            status="SUCCESS",
            budget=budget_dec,
            effective_budget=effective_budget,
            cash_buffer=cash_buffer,
            total_allocated=total_allocated,
            total_buy_costs=total_buy_costs,
            total_capital_committed=total_committed,
            expected_net_pnl=portfolio_return.expected_net_pnl,
            expected_return_rate=portfolio_return.expected_return_rate,
            total_modeled_costs=portfolio_return.total_modeled_costs,
            positions=positions,
            has_prior_caution=has_prior,
        )
