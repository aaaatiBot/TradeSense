# TradeSense v3.1

<p align="center">
  <img src="https://img.shields.io/badge/TradeSense-v3.1-blue.svg" alt="TradeSense Version" />
  <img src="https://img.shields.io/badge/python-3.11+-blue.svg" alt="Python 3.11+" />
  <img src="https://img.shields.io/badge/Flask-3.x-lightgrey.svg" alt="Flask 3.x" />
  <img src="https://img.shields.io/badge/SQLAlchemy-2.x-red.svg" alt="SQLAlchemy 2.x" />
  <img src="https://img.shields.io/badge/coverage-98%25%20services-brightgreen.svg" alt="Test Coverage" />
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License" />
</p>

> **Budget-Constrained Stock Advisory and Paper Trading System with Blockchain Audit**  
> *Authoritative specification: Software Requirements Specification — TradeSense v3.1 (09 November 2026)*

---

## 📌 Project Overview

TradeSense is an educational stock-advisory and simulated paper-trading platform designed for retail investors in India. Users specify a budget, select a trading mode (CNC or MIS) and horizon, and receive mathematically optimized allocations under strict budget constraints. 

### Key System Pillars
1. **Advisor, Not Executor**: Strictly simulated orders; no real broker order placement or real-money transactions.
2. **Deterministic Financial Engine**: Precision `Decimal` arithmetic for statutory taxes (STT, GST, Stamp Duty, SEBI) and brokerage charges.
3. **Ex-Ante Blockchain Audit**: Cryptographically commits recommendation hashes on-chain before trading outcomes occur, enabling verifiable audit trails.
4. **Transparent Uncertainty**: Expected return estimation using class-conditional profit magnitudes ($G_i^+, G_i^-$) rather than uncalibrated probabilities.

---

## 🏗️ Architecture & Directory Structure (SRS §3.3)

```text
STANKS/
|-- app/
|   |-- __init__.py                  # Application factory (create_app)
|   |-- config.py                    # Environment-based config (Dev, Test, Prod) + validation
|   |-- extensions.py                # Database, limiter, and extension singletons
|   |-- models/                      # SQLAlchemy models (§7.1-§7.17, §6.5, §6.6, §9.4.1, §15.1)
|   |-- routes/                      # Route blueprints (API v1)
|   |-- services/                    # Domain services (auth, cost, optimizer, blockchain, ML)
|   |-- repositories/                # Data-access repositories
|   |-- workers/                     # Durable background queue workers (§7.14)
|   |-- templates/                   # Jinja2 presentation templates
|   |-- static/                      # Static assets (css, js, images)
|   |-- utils/                       # Clock abstraction, structured logger, API envelope, decorators
|-- contracts/                       # Solidity smart contracts (§8)
|-- ml/                              # Machine learning training, inference & artifacts (§9)
|-- migrations/                      # Alembic migrations (21 tables + versioning)
|-- tests/                           # Acceptance and unit test suite
|-- requirements.txt                 # Pinned dependencies
|-- .env.example                     # Exhaustive configuration template
|-- README.md                        # Documentation
|-- run.py                           # WSGI entrypoint
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- Python 3.11+
- Virtual environment tool (`uv` recommended or standard `venv`)

### 2. Environment Setup
```bash
# Clone the repository
git clone https://github.com/aaaatiBot/TradeSense.git
cd TradeSense

# Initialize virtual environment with Python 3.11
python -m uv venv --python 3.11 .venv

# Activate environment
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Linux / macOS:
source .venv/bin/activate

# Install dependencies
python -m uv pip install -r requirements.txt
```

### 3. Configuration
Copy the template configuration file:
```bash
cp .env.example .env
```
Ensure `SECRET_KEY` and other credentials are appropriately configured.

### 4. Database Migrations
Initialize and upgrade database tables via Alembic:
```bash
alembic upgrade head
```

### 5. Automated Test Suite
```bash
# Run all tests with coverage on domain services (98% line coverage in Phase 2)
pytest -v --cov=app/services --cov-report=term-missing

# Run full project coverage (96% overall coverage)
pytest -v --cov=app --cov-report=term-missing
```

### 6. Run the Application
```bash
python run.py
```

### 7. Inspect Health & Observability
Check the structured dependency health check endpoint:
```bash
python scripts/curl_health.py
```
Or with curl:
```bash
curl http://127.0.0.1:5000/api/v1/health
```

---

## 📋 Implementation Roadmap (12 Phases)

| Phase | Milestone | Status |
|:---:|---|:---:|
| **1** | **Repository, Flask scaffold, configuration, base DB & health endpoint** | ✅ **Completed** |
| **2** | **Authentication and authorization (FR-AUTH)** | ✅ **Completed** |
| 3 | Transaction cost engine (FR-CST) | ⏳ Pending |
| 4 | Market data and features (FR-MKT) | ⏳ Pending |
| 5 | ML training and conditional-return estimation (FR-PRD, §4.5.1) | ⏳ Pending |
| 6 | Expected return and optimizer (FR-EXP, FR-OPT) | ⏳ Pending |
| 7 | Paper trading and history (FR-TRD) | ⏳ Pending |
| 8 | Smart contract and hashing (FR-AUD, §8) | ⏳ Pending |
| 9 | Durable blockchain worker (§7.14) | ⏳ Pending |
| 10 | Gemini integration (FR-NWS) | ⏳ Pending |
| 11 | UI, security, retention, monitoring (§5.7, §7.18) | ⏳ Pending |
| 12 | Full end-to-end testing and verification | ⏳ Pending |
