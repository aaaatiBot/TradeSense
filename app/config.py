"""TradeSense v3.1 Configuration Module.

Loads and validates environment variables for Development, Testing, and Production environments.
"""
from __future__ import annotations

from decimal import Decimal
import os
from typing import Dict, Type

from dotenv import load_dotenv

load_dotenv()

INSECURE_SECRET_KEYS = {
    "change-this-in-production-to-a-secure-random-32-byte-hex-string",
    "secret",
    "dev-secret-key",
    "password",
    "default",
    "",
}


class BaseConfig:
    """Base configuration shared across environments."""

    ENV: str = os.getenv("FLASK_ENV", "production")
    DEBUG: bool = False
    TESTING: bool = False

    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "5000"))

    SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-key-change-me")

    # Database
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///tradesense.db")
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI: str = DATABASE_URL
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False

    # Security & Hashing
    ARGON2_TIME_COST: int = int(os.getenv("ARGON2_TIME_COST", "3"))
    ARGON2_MEMORY_COST: int = int(os.getenv("ARGON2_MEMORY_COST", "65536"))
    ARGON2_PARALLELISM: int = int(os.getenv("ARGON2_PARALLELISM", "4"))
    SESSION_LIFETIME_HOURS: int = int(os.getenv("SESSION_LIFETIME_HOURS", "8"))
    PASSWORD_RESET_TOKEN_LIFETIME_HOURS: int = int(os.getenv("PASSWORD_RESET_TOKEN_LIFETIME_HOURS", "1"))

    # Budget & Trading Parameters
    DEFAULT_BUDGET_MIN: Decimal = Decimal(str(os.getenv("DEFAULT_BUDGET_MIN", "100.00")))
    DEFAULT_BUDGET_MAX: Decimal = Decimal(str(os.getenv("DEFAULT_BUDGET_MAX", "100000.00")))
    DEFAULT_CASH_BUFFER_PCT: Decimal = Decimal(str(os.getenv("DEFAULT_CASH_BUFFER_PCT", "0.005")))
    REFERENCE_TRADE_SIZE: Decimal = Decimal(str(os.getenv("REFERENCE_TRADE_SIZE", "500.00")))

    # Rate Limiting
    RATE_LIMIT_STORAGE_URL: str = os.getenv("RATE_LIMIT_STORAGE_URL", "memory://")
    RATE_LIMIT_DEFAULT: str = os.getenv("RATE_LIMIT_DEFAULT", "100/minute")

    # Market Data
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "nse_stub")
    MARKET_DATA_API_KEY: str = os.getenv("MARKET_DATA_API_KEY", "")
    MARKET_DATA_BASE_URL: str = os.getenv("MARKET_DATA_BASE_URL", "")
    MARKET_DATA_TIMEOUT_SECONDS: float = float(os.getenv("MARKET_DATA_TIMEOUT_SECONDS", "5.0"))

    # Gemini Integration
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    GEMINI_TIMEOUT_SECONDS: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "10.0"))

    # Blockchain
    BLOCKCHAIN_PROVIDER_URL: str = os.getenv("BLOCKCHAIN_PROVIDER_URL", "")
    BLOCKCHAIN_CHAIN_ID: int = int(os.getenv("BLOCKCHAIN_CHAIN_ID", "11155111"))
    BLOCKCHAIN_CONTRACT_ADDRESS: str = os.getenv("BLOCKCHAIN_CONTRACT_ADDRESS", "")
    BLOCKCHAIN_SIGNER_PRIVATE_KEY: str = os.getenv("BLOCKCHAIN_SIGNER_PRIVATE_KEY", "")
    BLOCKCHAIN_CONFIRMATION_BLOCKS: int = int(os.getenv("BLOCKCHAIN_CONFIRMATION_BLOCKS", "2"))

    # ML & Return Estimation (§4.5.1, §9.4.1)
    CONDITIONAL_RETURN_METHOD_VERSION: str = os.getenv("CONDITIONAL_RETURN_METHOD_VERSION", "1.0")
    G_PLUS_PRIOR: Decimal = Decimal(str(os.getenv("G_PLUS_PRIOR", "0.0060")))
    G_MINUS_PRIOR: Decimal = Decimal(str(os.getenv("G_MINUS_PRIOR", "-0.0060")))
    SAMPLE_THRESHOLD_TICKER: int = int(os.getenv("SAMPLE_THRESHOLD_TICKER", "30"))
    SAMPLE_THRESHOLD_UNIVERSE: int = int(os.getenv("SAMPLE_THRESHOLD_UNIVERSE", "200"))

    # Observability & Retention
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    RETENTION_SWEEP_SCHEDULE: str = os.getenv("RETENTION_SWEEP_SCHEDULE", "0 2 * * *")

    @classmethod
    def validate(cls) -> None:
        """Validate core configuration rules."""
        if cls.DEFAULT_BUDGET_MIN <= 0:
            raise ValueError(f"DEFAULT_BUDGET_MIN must be > 0, got {cls.DEFAULT_BUDGET_MIN}")
        if cls.DEFAULT_BUDGET_MAX <= cls.DEFAULT_BUDGET_MIN:
            raise ValueError(
                f"DEFAULT_BUDGET_MAX ({cls.DEFAULT_BUDGET_MAX}) must be greater than DEFAULT_BUDGET_MIN ({cls.DEFAULT_BUDGET_MIN})"
            )
        if cls.DEFAULT_CASH_BUFFER_PCT < 0 or cls.DEFAULT_CASH_BUFFER_PCT >= 1:
            raise ValueError(
                f"DEFAULT_CASH_BUFFER_PCT must be between 0 and 1, got {cls.DEFAULT_CASH_BUFFER_PCT}"
            )
        if cls.REFERENCE_TRADE_SIZE <= 0:
            raise ValueError(
                f"REFERENCE_TRADE_SIZE must be > 0, got {cls.REFERENCE_TRADE_SIZE}"
            )


class DevelopmentConfig(BaseConfig):
    """Configuration for local development."""

    DEBUG: bool = True
    ENV: str = "development"


class TestingConfig(BaseConfig):
    """Configuration for automated test execution."""

    TESTING: bool = True
    DEBUG: bool = False
    ENV: str = "testing"
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    SECRET_KEY: str = "test-static-key-32-bytes-secure-for-testing"


class ProductionConfig(BaseConfig):
    """Strict configuration for production environments."""

    DEBUG: bool = False
    ENV: str = "production"

    @classmethod
    def validate(cls) -> None:
        super().validate()
        if not cls.SECRET_KEY or cls.SECRET_KEY in INSECURE_SECRET_KEYS or len(cls.SECRET_KEY) < 32:
            raise ValueError(
                "CRITICAL: Production SECRET_KEY must be a cryptographically secure random string with length >= 32"
            )
        if cls.SQLALCHEMY_DATABASE_URI.startswith("sqlite:"):
            # Warn or require non-sqlite for production concurrent queue worker safety per SRS §2.3
            pass


config_by_name: Dict[str, Type[BaseConfig]] = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "production": ProductionConfig,
}
