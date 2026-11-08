"""Authoritative equity transaction cost engine per SRS §4.7 (FR-CST).

Uses exact Decimal arithmetic with ROUND_HALF_UP rounding.
Supports CNC (Delivery) and MIS (Intraday) modes with versioned rate cards.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, List, Optional, Set, Tuple

from app.models.cost_breakdown import CostBreakdown


def round_currency(val: Decimal) -> Decimal:
    """Round currency value to 2 decimal places using ROUND_HALF_UP."""
    return val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def round_rate(val: Decimal) -> Decimal:
    """Round high-precision intermediate rate calculation to 4 decimal places."""
    return val.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


@dataclass
class TradeOrder:
    """Single order execution input for cost computation."""
    ticker: str
    isin: str
    action: str  # "BUY" or "SELL"
    quantity: int
    price: Decimal
    mode: str = "CNC"  # "CNC" or "MIS"


@dataclass
class CostResult:
    """Itemized breakdown of all modeled charges."""
    rate_card_version: str
    turnover: Decimal
    buy_turnover: Decimal
    sell_turnover: Decimal
    brokerage: Decimal
    stt_ctt: Decimal
    transaction_charges: Decimal
    gst: Decimal
    sebi_charges: Decimal
    stamp_duty: Decimal
    dp_charges: Decimal
    slippage: Decimal
    total_charges: Decimal

    def to_breakdown_model(self) -> CostBreakdown:
        """Convert result to CostBreakdown database entity."""
        return CostBreakdown(
            rate_card_version=self.rate_card_version,
            turnover=self.turnover,
            brokerage=self.brokerage,
            stt_ctt=self.stt_ctt,
            transaction_charges=self.transaction_charges,
            gst=self.gst,
            sebi_charges=self.sebi_charges,
            stamp_duty=self.stamp_duty,
            dp_charges=self.dp_charges,
            slippage=self.slippage,
            total_charges=self.total_charges,
        )


class CostEngine:
    """Authoritative Indian equity transaction charge calculator (FR-CST)."""

    # Default Standard Indian Equity Rate Card (Zerodha standard equivalent)
    DEFAULT_RATE_CARD_VERSION = "standard_equity_2026"

    # Standard Rates
    # Brokerage:
    #   CNC: ₹0 per executed order (or flat 0)
    #   MIS: 0.03% or ₹20 per executed order, whichever is lower
    MIS_BROKERAGE_PCT = Decimal("0.0003")
    MIS_BROKERAGE_CAP = Decimal("20.00")
    CNC_BROKERAGE_FLAT = Decimal("0.00")

    # STT / CTT:
    #   CNC: 0.1% on both Buy and Sell turnover
    #   MIS: 0.025% on Sell turnover only
    CNC_STT_BUY_PCT = Decimal("0.001")
    CNC_STT_SELL_PCT = Decimal("0.001")
    MIS_STT_SELL_PCT = Decimal("0.00025")

    # Exchange Transaction Charges (NSE standard):
    #   0.00297% on total turnover
    EXCHANGE_TXN_PCT = Decimal("0.0000297")

    # SEBI Turnover Charges:
    #   ₹10 per crore = 0.0001% (0.000001) of turnover
    SEBI_TURNOVER_PCT = Decimal("0.000001")

    # Stamp Duty:
    #   CNC: 0.015% (0.00015) on Buy turnover only
    #   MIS: 0.003% (0.00003) on Buy turnover only
    CNC_STAMP_DUTY_PCT = Decimal("0.00015")
    MIS_STAMP_DUTY_PCT = Decimal("0.00003")

    # GST:
    #   18% on (Brokerage + Exchange Txn + SEBI)
    GST_PCT = Decimal("0.18")

    # DP Charges:
    #   CNC: ₹13.50 + 18% GST (₹15.93) per distinct ISIN debited per day on Sell
    #   MIS: ₹0
    DP_CHARGE_PER_ISIN = Decimal("15.93")

    # Modeled Slippage:
    #   Default 0.05% of turnover (0.0005)
    SLIPPAGE_PCT = Decimal("0.0005")

    @classmethod
    def calculate_round_trip(
        cls,
        ticker: str,
        isin: str,
        quantity: int,
        buy_price: Decimal,
        sell_price: Decimal,
        mode: str = "CNC",
        dp_already_charged: bool = False,
        slippage_pct: Optional[Decimal] = None,
        rate_card_version: Optional[str] = None,
    ) -> CostResult:
        """Calculate complete round-trip costs for a buy + sell trade."""
        if quantity <= 0:
            raise ValueError(f"Quantity must be strictly positive, got {quantity}")
        if buy_price <= 0 or sell_price <= 0:
            raise ValueError(f"Prices must be strictly positive, got buy={buy_price}, sell={sell_price}")
        mode_upper = mode.upper()
        if mode_upper not in ("CNC", "MIS"):
            raise ValueError(f"Unsupported trading mode: {mode}. Must be 'CNC' or 'MIS'")

        q = Decimal(str(quantity))
        buy_turnover = round_currency(q * buy_price)
        sell_turnover = round_currency(q * sell_price)
        total_turnover = buy_turnover + sell_turnover

        # 1. Brokerage
        if mode_upper == "CNC":
            brokerage = cls.CNC_BROKERAGE_FLAT
        else:
            # MIS: 0.03% or ₹20 per leg (buy leg and sell leg)
            buy_leg_brokerage = min(cls.MIS_BROKERAGE_CAP, round_currency(buy_turnover * cls.MIS_BROKERAGE_PCT))
            sell_leg_brokerage = min(cls.MIS_BROKERAGE_CAP, round_currency(sell_turnover * cls.MIS_BROKERAGE_PCT))
            brokerage = buy_leg_brokerage + sell_leg_brokerage

        # 2. STT / CTT
        if mode_upper == "CNC":
            stt = round_currency(buy_turnover * cls.CNC_STT_BUY_PCT) + round_currency(sell_turnover * cls.CNC_STT_SELL_PCT)
        else:
            stt = round_currency(sell_turnover * cls.MIS_STT_SELL_PCT)

        # 3. Exchange Transaction Charges
        txn_charges = round_currency(total_turnover * cls.EXCHANGE_TXN_PCT)

        # 4. SEBI Turnover Charges
        sebi_charges = round_currency(total_turnover * cls.SEBI_TURNOVER_PCT)

        # 5. Stamp Duty (on Buy only)
        if mode_upper == "CNC":
            stamp_duty = round_currency(buy_turnover * cls.CNC_STAMP_DUTY_PCT)
        else:
            stamp_duty = round_currency(buy_turnover * cls.MIS_STAMP_DUTY_PCT)

        # 6. GST (18% on Brokerage + Txn Charges + SEBI)
        gst_taxable = brokerage + txn_charges + sebi_charges
        gst = round_currency(gst_taxable * cls.GST_PCT)

        # 7. DP Charges (CNC sell only, once per distinct ISIN per day)
        if mode_upper == "CNC" and not dp_already_charged:
            dp_charges = cls.DP_CHARGE_PER_ISIN
        else:
            dp_charges = Decimal("0.00")

        # 8. Slippage
        slip_rate = slippage_pct if slippage_pct is not None else cls.SLIPPAGE_PCT
        slippage = round_currency(total_turnover * slip_rate)

        # Total charges
        total_charges = (
            brokerage
            + stt
            + txn_charges
            + gst
            + sebi_charges
            + stamp_duty
            + dp_charges
            + slippage
        )

        return CostResult(
            rate_card_version=rate_card_version or cls.DEFAULT_RATE_CARD_VERSION,
            turnover=total_turnover,
            buy_turnover=buy_turnover,
            sell_turnover=sell_turnover,
            brokerage=brokerage,
            stt_ctt=stt,
            transaction_charges=txn_charges,
            gst=gst,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            dp_charges=dp_charges,
            slippage=slippage,
            total_charges=total_charges,
        )

    @classmethod
    def calculate_portfolio_costs(
        cls,
        trades: List[Tuple[str, str, int, Decimal, Decimal]],
        mode: str = "CNC",
        slippage_pct: Optional[Decimal] = None,
        rate_card_version: Optional[str] = None,
    ) -> CostResult:
        """Calculate aggregate costs across a portfolio, applying DP charges exactly once per distinct ISIN."""
        seen_isins: Set[str] = set()
        total_turnover = Decimal("0.00")
        total_buy_turnover = Decimal("0.00")
        total_sell_turnover = Decimal("0.00")
        total_brokerage = Decimal("0.00")
        total_stt = Decimal("0.00")
        total_txn = Decimal("0.00")
        total_gst = Decimal("0.00")
        total_sebi = Decimal("0.00")
        total_stamp = Decimal("0.00")
        total_dp = Decimal("0.00")
        total_slippage = Decimal("0.00")

        for ticker, isin, quantity, buy_price, sell_price in trades:
            dp_already = isin in seen_isins
            res = cls.calculate_round_trip(
                ticker=ticker,
                isin=isin,
                quantity=quantity,
                buy_price=buy_price,
                sell_price=sell_price,
                mode=mode,
                dp_already_charged=dp_already,
                slippage_pct=slippage_pct,
                rate_card_version=rate_card_version,
            )
            seen_isins.add(isin)

            total_turnover += res.turnover
            total_buy_turnover += res.buy_turnover
            total_sell_turnover += res.sell_turnover
            total_brokerage += res.brokerage
            total_stt += res.stt_ctt
            total_txn += res.transaction_charges
            total_gst += res.gst
            total_sebi += res.sebi_charges
            total_stamp += res.stamp_duty
            total_dp += res.dp_charges
            total_slippage += res.slippage

        total_charges = (
            total_brokerage
            + total_stt
            + total_txn
            + total_gst
            + total_sebi
            + total_stamp
            + total_dp
            + total_slippage
        )

        return CostResult(
            rate_card_version=rate_card_version or cls.DEFAULT_RATE_CARD_VERSION,
            turnover=total_turnover,
            buy_turnover=total_buy_turnover,
            sell_turnover=total_sell_turnover,
            brokerage=total_brokerage,
            stt_ctt=total_stt,
            transaction_charges=total_txn,
            gst=total_gst,
            sebi_charges=total_sebi,
            stamp_duty=total_stamp,
            dp_charges=total_dp,
            slippage=total_slippage,
            total_charges=total_charges,
        )
