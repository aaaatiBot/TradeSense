# TradeSense v3.1

Budget-Constrained Stock Advisory and Paper Trading System with Blockchain Audit.

Authoritative specification: **Software Requirements Specification — TradeSense v3.1 (09 November 2026)**.

---

## 1. Quick Start

### 1.1 Prerequisites
- Python 3.11+
- Virtual environment tool (`uv` or `venv`)

### 1.2 Setup Environment
```bash
# Initialize virtual environment
python -m uv venv --python 3.11 .venv

# Activate environment
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux / macOS:
source .venv/bin/activate

# Install dependencies
python -m uv pip install -r requirements.txt
```

### 1.3 Configuration
Copy the template configuration file:
```bash
copy .env.example .env
```
Ensure `SECRET_KEY` and other credentials are appropriately configured.

### 1.4 Database Migrations
Initialize and upgrade database tables via Alembic:
```bash
alembic upgrade head
```

### 1.5 Run Automated Test Suite
```bash
# Run all tests with coverage on domain services
pytest -v --cov=app/services --cov-report=term-missing

# Run full project coverage
pytest -v --cov=app --cov-report=term-missing
```

### 1.6 Run Development Server
```bash
python run.py
```
Check health endpoint:
```bash
curl http://127.0.0.1:5000/api/v1/health
```

---

## 2. Architecture & Directory Structure (SRS §3.3)

```text
STANKS/
|-- app/
|   |-- __init__.py                  # Application factory (create_app)
|   |-- config.py                    # Environment-based configuration & validation
|   |-- extensions.py                # Database and extension instances
|   |-- models/                      # SQLAlchemy models (§7.1-§7.17, §6.5, §6.6, §9.4.1, §15.1)
|   |-- routes/                      # Route blueprints (API v1)
|   |-- services/                    # Domain services with docstrings / stubs
|   |-- repositories/                # Data-access repositories
|   |-- workers/                     # Durable background queue workers
|   |-- templates/                   # Jinja2 presentation templates
|   |-- static/                      # Static assets (css, js, images)
|   |-- utils/                       # Clock abstraction, structured logger, API envelope
|-- contracts/                       # Solidity smart contracts (§8)
|-- ml/                              # Machine learning training, inference & artifacts (§9)
|-- migrations/                      # Alembic migrations
|-- tests/                           # Acceptance and unit test suite
|-- requirements.txt                 # Dependencies
|-- .env.example                     # Exhaustive configuration template
|-- README.md                        # Documentation
|-- run.py                           # WSGI entrypoint
```
