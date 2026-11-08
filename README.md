# TradeSense: Educational Stock-Advisory & Cryptographic Paper Trading Platform

[![CI Test Suite](https://img.shields.io/badge/tests-91%20passed-brightgreen.svg)]()
[![Code Coverage](https://img.shields.io/badge/coverage-91%25%20total%20%7C%20%E2%89%A595%25%20critical-blue.svg)]()
[![Specification](https://img.shields.io/badge/SRS-v3.1%20Authoritative-purple.svg)]()
[![Python](https://img.shields.io/badge/python-3.11-blue.svg)]()
[![Framework](https://img.shields.io/badge/flask-3.x-lightgrey.svg)]()
[![Blockchain](https://img.shields.io/badge/solidity-0.8.20-orange.svg)]()

TradeSense is a full-featured educational stock-advisory and simulated paper-trading platform engineered for retail investors in the Indian equity markets (NSE/BSE). Built strictly to the **TradeSense Software Requirements Specification (SRS) v3.1**, the platform couples versioned machine learning forecasts and integer-constrained portfolio optimization with an immutable Ethereum blockchain audit layer to guarantee non-repudiation of recommendations and paper-trade outcomes.

---

## Key Architectural Principles

1. **Strict Financial Determinism & Exact Arithmetic**:
   - Zero use of floating-point arithmetic for financial calculations. All turnover, taxes, statutory levies, DP charges, and PnL values are computed using Python `Decimal` with `ROUND_HALF_UP` precision.
   - Comprehensive implementation of SEBI and Indian brokerage rate structures (CNC Delivery & MIS Intraday), accounting for Brokerage, STT/CTT, Exchange Transaction Charges, SEBI Turnover Fees, Stamp Duty, 18% GST, and per-ISIN daily DP charges (₹15.93).

2. **Expectation-Driven Portfolio Optimization**:
   - Strictly enforces that probability alone is never multiplied by stock price ($p_i \cdot P_i \ne \text{expected profit}$).
   - Integrates class-conditional return magnitudes $E[G_i(1)] = p_i \cdot G_i^+ + (1 - p_i) \cdot G_i^-$ with empirical fallback hierarchy (Ticker Baseline $\to$ Universe Baseline $\to$ Empirical Prior).
   - Mixed-Integer Linear Programming (MILP) solver (`scipy.optimize.milp`) allocates discrete integer share quantities strictly within user budgets, cash buffers, and single-position constraints.

3. **Immutable Smart Contract Audit Trail**:
   - Uses Ethereum smart contract (`TradeSenseAudit.sol`) to anchor pre-commitment recommendation hashes before market outcomes are known, and trade-result commitments upon closing.
   - Deterministic canonical serialization (RFC 8785) with NFC Unicode normalization and Keccak-256 cryptographic hashing.
   - Durable, lease-locked database job worker (`job_queue`) with exponential retry backoff and crash recovery.

4. **SEBI Compliance & Regulatory Transparency**:
   - Statutory disclaimers embedded and verified across all user-facing screens and API responses.
   - Non-authoritative, educational Gemini AI explanations for news sentiment and rationale without altering financial decisions.
   - Full automated retention policy sweep and right-to-erasure (GDPR / Indian DPDP Act) anonymization.

---

## System Architecture

```text
TradeSense/
├── app/
│   ├── config.py                  # Strict environment configuration & secrets validation
│   ├── extensions.py              # SQLAlchemy, Flask-Limiter
│   ├── __init__.py                # Flask application factory with security headers & metrics
│   ├── models/                    # 21 SQLAlchemy declarative models per SRS §7
│   │   ├── base.py
│   │   ├── user.py, session.py, password_reset.py
│   │   ├── stock.py, price.py, news_item.py
│   │   ├── cost_rate_card.py, cost_rate.py, cost_breakdown.py
│   │   ├── model_version.py, reference_notional_config.py
│   │   ├── conditional_return_estimate.py
│   │   ├── recommendation.py, recommendation_item.py
│   │   ├── paper_trade.py, paper_trade_leg.py
│   │   ├── blockchain_record.py, job.py, idempotency.py
│   │   ├── api_deprecation.py, disclaimer.py
│   ├── routes/                    # RESTful API blueprints per SRS §6
│   │   ├── auth.py                # Argon2id registration, login, logout, account erasure
│   │   ├── health.py              # Honest per-dependency status check (SRS §5.7.4)
│   │   ├── recommendations.py     # E[G_i] estimation & integer MILP optimizer
│   │   ├── paper_trades.py        # Simulated trade opening, closing, and PnL realization
│   │   ├── history.py             # User isolated trade performance audit trail
│   │   ├── verification.py        # Independent cryptographic proof verification
│   │   ├── admin.py               # Observability metrics, queue depth, audit dashboard
│   │   └── ui.py                  # Jinja2 views with statutory disclaimers
│   ├── services/                  # Core domain logic
│   │   ├── auth_service.py        # Authentication & RBAC
│   │   ├── blockchain_service.py  # Canonical serialization & Keccak-256 anchoring (≥95% cov)
│   │   ├── conditional_return_service.py # G^+/G^- estimation & fallback hierarchy
│   │   ├── cost_engine.py         # Exact Indian equity transaction charges (≥95% cov)
│   │   ├── disclaimer_service.py  # Statutory disclaimer registry & validation
│   │   ├── expected_return_service.py # E[G_i] computation (≥95% cov)
│   │   ├── feature_service.py     # Leak-free technical indicator feature generation
│   │   ├── gemini_service.py      # Resilient LLM sentiment & educational rationale
│   │   ├── market_data_service.py # Bar ingestion, OHLCV validation, stale detection
│   │   ├── optimizer_service.py   # Integer portfolio allocation via MILP
│   │   ├── paper_trade_service.py # Simulated trade lifecycle with Idempotency-Key
│   │   ├── prediction_service.py  # Walk-forward model inference & promotion gates
│   │   ├── retention_service.py   # Scheduled rolling retention sweep & erasure
│   │   ├── universe_service.py    # Stock eligibility & status safeguards
│   │   └── verification_service.py# Cryptographic on-chain proof verification
│   ├── templates/                 # Jinja2 templates (Login, Dashboard, Rec, Trade, History, Ver)
│   ├── utils/                     # Clock abstraction, structured JSON logging, metrics
│   └── workers/                   # Background durable blockchain queue worker
├── contracts/                     # Solidity smart contract (TradeSenseAudit.sol)
├── migrations/                    # Alembic schema migrations
├── tests/                         # Comprehensive pytest test suite (AT-01 through AT-45)
│   ├── test_auth.py
│   ├── test_blockchain.py
│   ├── test_clock_and_logger.py
│   ├── test_cost_engine.py
│   ├── test_durable_worker.py
│   ├── test_end_to_end_journey.py
│   ├── test_factory_and_config.py
│   ├── test_gemini_service.py
│   ├── test_health.py
│   ├── test_market_data_and_universe.py
│   ├── test_migrations.py
│   ├── test_ml_and_conditional_return.py
│   ├── test_models.py
│   ├── test_optimizer.py
│   ├── test_paper_trading.py
│   └── test_phase11_ui_security_retention.py
└── pytest.ini
```

---

## 12-Milestone Acceptance Test Traceability Matrix

| Milestone | Phase Focus | Key SRS Requirements | Acceptance Tests Verified | Status |
|---|---|---|---|---|
| **Phase 1** | Repository & Base DB | Flask Scaffold, Config, 21 Models, Alembic, Clock Abstraction | Factory, Config, Migrations, Health envelope | **PASSED** |
| **Phase 2** | Authentication & RBAC | Argon2id, SHA-256 Session Hashes, Role Isolation, Erasure | AT-02, AT-03, AT-04 | **PASSED** |
| **Phase 3** | Transaction Cost Engine | CNC/MIS charges, Brokerage Cap, STT, DP Charges, Slippage | AT-11, AT-12, AT-13, AT-14, AT-15 (95% cov) | **PASSED** |
| **Phase 4** | Market Data & Features | OHLCV Ingestion, Stale Data Detection, Leak-Free Technical Features | AT-05, AT-06, AT-19, AT-41 | **PASSED** |
| **Phase 5** | ML & Return Estimation | Walk-Forward Split, Promotion Report Gate, Model Rollback | AT-20, AT-21, AT-36, AT-37, AT-38, AT-39 | **PASSED** |
| **Phase 6** | Return & MILP Optimizer | E[G_i] Expectation, Integer MILP Allocation, Budget Boundary | AT-07, AT-08, AT-09, AT-10, OPT-11, OPT-12 (97% cov) | **PASSED** |
| **Phase 7** | Paper Trading & History | Simulated Fills, Idempotency-Key, Rule 9 Gate, Realized PnL | AT-16, AT-17, AT-34 | **PASSED** |
| **Phase 8** | Smart Contract & Hashing | Canonical Serialization, Keccak-256, NFC Normalization | AT-22, AT-23, AT-24, AT-25, AT-42 (99% cov) | **PASSED** |
| **Phase 9** | Durable Blockchain Worker | Lease Locking, Exponential Retry Backoff, Crash Recovery | AT-26, AT-27, AT-28, AT-29, AT-30 | **PASSED** |
| **Phase 10** | Gemini Integration | Educational Explanations, News Sentiment, Graceful Degradation | AT-18 (99% cov) | **PASSED** |
| **Phase 11** | UI, Security & Retention | Security Headers, Rate Limits, XSS, Purge Sweeps, Disclaimers, RFC 8594 | AT-31, AT-32, AT-33, AT-40, AT-43, AT-44, AT-45 | **PASSED** |
| **Phase 12** | End-to-End User Journey | Full user lifecycle: Register -> Recommend -> Anchor -> Trade -> Close -> Verify | AT-35 (Full Suite Integration) | **PASSED** |

---

## Test Execution and Coverage Verification

Run the complete test suite with line coverage reporting:

```powershell
# Activate Python virtual environment
.venv\Scripts\activate

# Run all 91 test cases across the entire test suite
pytest -v --cov=app/services --cov-report=term-missing
```

### Coverage Gate Verification (TST-12 & TST-13)

| Target Module | Required Coverage Gate | Achieved Coverage | Gate Status |
|---|---|---|---|
| `app/services/cost_engine.py` | $\ge 95\%$ | **95%** | **SATISFIED** |
| `app/services/expected_return_service.py` | $\ge 95\%$ | **97%** | **SATISFIED** |
| `app/services/blockchain_service.py` | $\ge 95\%$ | **99%** | **SATISFIED** |
| `app/services/gemini_service.py` | N/A | **99%** | **SATISFIED** |
| `app/services/market_data_service.py` | N/A | **96%** | **SATISFIED** |
| `app/services/auth_service.py` | N/A | **98%** | **SATISFIED** |
| `app/services/disclaimer_service.py` | N/A | **100%** | **SATISFIED** |
| `app/services/verification_service.py` | N/A | **100%** | **SATISFIED** |
| **Overall `app/services/` Line Coverage** | $\ge 80\%$ | **91%** | **SATISFIED** |

---

## Local Development & Setup Instructions

### 1. Prerequisites
- Python 3.11+
- Git

### 2. Installation
```powershell
# Clone the repository
git clone https://github.com/aaaatiBot/TradeSense.git
cd TradeSense

# Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Database Migration
```powershell
# Upgrade schema to latest migration head
alembic upgrade head
```

### 4. Running the Development Server
```powershell
# Set environment variables
$env:FLASK_APP = "app:create_app()"
$env:FLASK_ENV = "development"

# Run Flask application
flask run --port 5000
```

### 5. Running the Background Blockchain Worker
```powershell
python -c "from app import create_app; from app.workers.blockchain_worker import BlockchainWorker; app = create_app(); app.app_context().push(); worker = BlockchainWorker(); worker.run_forever()"
```

---

## Statutory Legal & Ethical Disclaimer

**Mandatory SEBI Disclosure**: TradeSense is an educational simulation platform. It does not provide investment advice, financial planning, portfolio management services, or brokerage services. All trades, orders, positions, and balances are purely simulated; no real capital is deployed and no orders are routed to any securities exchange. Machine learning models produce statistical estimates, not financial guarantees.
