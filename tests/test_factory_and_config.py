"""Tests for application factory and configuration validation."""
import pytest
from app import create_app
from app.config import ProductionConfig, BaseConfig


def test_create_app_testing():
    """Verify application factory creates testing app successfully."""
    app = create_app("testing")
    assert app.config["TESTING"] is True
    assert app.config["ENV"] == "testing"


def test_create_app_development():
    """Verify application factory creates development app."""
    app = create_app("development")
    assert app.config["DEBUG"] is True
    assert app.config["ENV"] == "development"


def test_production_config_rejects_insecure_secret_key():
    """Verify production mode rejects default or insecure SECRET_KEY."""
    original_secret = ProductionConfig.SECRET_KEY
    try:
        ProductionConfig.SECRET_KEY = "insecure-short-key"
        with pytest.raises(ValueError, match="CRITICAL: Production SECRET_KEY must be a cryptographically secure"):
            ProductionConfig.validate()

        ProductionConfig.SECRET_KEY = "change-this-in-production-to-a-secure-random-32-byte-hex-string"
        with pytest.raises(ValueError, match="CRITICAL: Production SECRET_KEY"):
            ProductionConfig.validate()
    finally:
        ProductionConfig.SECRET_KEY = original_secret


def test_production_config_accepts_valid_secret_key():
    """Verify production mode accepts strong 32+ character SECRET_KEY."""
    original_secret = ProductionConfig.SECRET_KEY
    try:
        ProductionConfig.SECRET_KEY = "a-very-strong-production-secret-key-that-is-at-least-32-bytes-long"
        ProductionConfig.validate()
    finally:
        ProductionConfig.SECRET_KEY = original_secret


def test_config_budget_validation():
    """Verify budget boundaries validation."""
    original_min = BaseConfig.DEFAULT_BUDGET_MIN
    original_max = BaseConfig.DEFAULT_BUDGET_MAX
    try:
        # Invalid min > max
        BaseConfig.DEFAULT_BUDGET_MIN = 2000
        BaseConfig.DEFAULT_BUDGET_MAX = 1000
        with pytest.raises(ValueError, match="DEFAULT_BUDGET_MAX .* must be greater"):
            BaseConfig.validate()
    finally:
        BaseConfig.DEFAULT_BUDGET_MIN = original_min
        BaseConfig.DEFAULT_BUDGET_MAX = original_max
