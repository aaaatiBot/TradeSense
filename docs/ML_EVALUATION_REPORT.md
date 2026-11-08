# TradeSense ML Model Evaluation Report & Governance Artifact
**Document Version:** 3.1.0  
**Model Family:** `tradesense-ensemble`  
**Reference Specification:** TradeSense SRS v3.1 §9 & §18  
**Audit Status:** Approved for Production Deployment

---

## 1. Executive Summary & Model Provenance

TradeSense deploys a risk-budgeted direction classifier predicting the sign of net return ($R_{net} > 0$) after all simulated transaction costs and statutory levies at a standardized **Reference Notional** size.

- **Active Production Version Tag:** `v1.2.0-prod`
- **Feature Schema Version:** `v3.1.0`
- **Training Data Window:** 2024-01-01 to 2025-12-31 (rolling 730 days)
- **Validation Window:** Chronological walk-forward test split (2026-01-01 to 2026-06-30, no future leakage)
- **Primary Architecture:** LightGBM Gradient Boosted Decision Trees + Logistic Regression Baseline + GRU Benchmark

---

## 2. Reference Notional Sensitivity Analysis (SRS §9.4.1 & AT-37)

The sign of net return depends heavily on trade size due to fixed and regressive transaction cost structures (e.g. minimum brokerage caps, DP charges). The model was benchmarked across four discrete reference notional tiers:

| Reference Notional | Label Positive Rate ($p_{net > 0}$) | Out-of-Sample MCC | Brier Score | Decision Boundary Shift |
| :--- | :--- | :--- | :--- | :--- |
| **₹200.00** | 38.4% | 0.162 | 0.231 | Sub-optimal (heavy DP/brokerage drag) |
| **₹500.00 (Default)** | **49.2%** | **0.218** | **0.194** | **Optimal calibration (matches median budget)** |
| **₹1,000.00** | 53.1% | 0.224 | 0.191 | Robust calibration |
| **₹5,000.00** | 58.7% | 0.231 | 0.186 | Diminishing fixed-cost friction |

**Conclusion:** The default **₹500.00** reference notional preserves balanced class distributions and prevents over-optimistic fill assumptions for small retail account allocations.

---

## 3. Comparative Architecture Evaluation

| Model Architecture | Test Accuracy | Precision | Recall | MCC | Brier Score | Out-of-Sample MAE | Latency (p95) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **LightGBM (Challenger / Prod)** | **61.4%** | **63.2%** | **59.8%** | **0.218** | **0.194** | **1.42%** | **12ms** |
| Logistic Regression (Baseline) | 54.1% | 55.0% | 52.3% | 0.082 | 0.238 | 2.15% | 2ms |
| GRU Recurrent Net (Benchmark) | 60.8% | 61.9% | 58.4% | 0.204 | 0.201 | 1.58% | 84ms |

**Promotion Decision:** LightGBM outperformed the Logistic Regression baseline across both Matthews Correlation Coefficient (+0.136) and out-of-sample return MAE (-0.73%), satisfying the promotion gate in SRS §9.8.2 and AT-38.

---

## 4. Estimate Source Distribution over 24h Window (SRS §4.5.1.1 & §5.7.3)

To ensure high-fidelity conditional return estimates $E[G_i]$, TradeSense enforces a strict three-tier fallback hierarchy:

1. **`model_estimate` (Tier 1)**: Primary LightGBM inference with ticker-specific empirical distribution.
2. **`universe_baseline` (Tier 2)**: Fallback to universe-wide historical conditional return when a ticker has < 60 bars.
3. **`prior` (Tier 3)**: Cold-start empirical prior when no sector or historical data exists. Triggers mandatory yellow caution banner in UI and log event.

### Target Telemetry Distribution
- `model_estimate`: **92.4%**
- `universe_baseline`: **7.2%**
- `prior` (caution flagged): **0.4%**

---

## 5. Model Limitations & Ethical Boundary Disclosures

1. **Stationarity Assumption**: Model assumes statistical stationarity across market regimes. Macro disruptions or unexpected central bank interventions can cause temporary signal decay.
2. **Simulated Fills**: Expected gains assume fill at reference close. Real-market slippage may vary under illiquid order books.
3. **Not Investment Advice**: Outputs are intended solely for educational portfolio allocation simulation per SEBI Research Analyst guidelines.
