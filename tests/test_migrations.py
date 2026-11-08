"""Tests for Alembic migration execution, idempotency, and downgrade."""
import os
import tempfile
import pytest
from alembic import command
from alembic.config import Config


def test_alembic_migrations_lifecycle():
    """Verify Alembic migration upgrade, idempotency, and downgrade lifecycle."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
        db_path = tmp_db.name

    try:
        # Prepare alembic config pointing to temporary SQLite database
        alembic_cfg = Config("alembic.ini")
        alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")

        # 1. Run upgrade head
        command.upgrade(alembic_cfg, "head")

        # 2. Run upgrade head a second time (must be idempotent per Correction 5)
        command.upgrade(alembic_cfg, "head")

        # 3. Test downgrade to base
        command.downgrade(alembic_cfg, "base")

        # 4. Re-upgrade to head
        command.upgrade(alembic_cfg, "head")

    finally:
        if os.path.exists(db_path):
            os.remove(db_path)
