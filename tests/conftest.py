"""Pytest test configuration and fixtures."""
import os
import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.extensions import db
from app.utils.clock import Clock


@pytest.fixture(autouse=True)
def reset_clock():
    """Ensure Clock abstraction is reset after every test."""
    Clock.reset()
    yield
    Clock.reset()


@pytest.fixture
def app() -> Flask:
    """Create testing application instance."""
    app_instance = create_app("testing")
    with app_instance.app_context():
        db.create_all()
        yield app_instance
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create Flask test client."""
    return app.test_client()


@pytest.fixture
def runner(app: Flask):
    """Create Flask CLI runner."""
    return app.test_cli_runner()
