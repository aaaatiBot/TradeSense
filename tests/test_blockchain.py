"""Acceptance tests for Smart Contract & Hashing (Phase 8, AT-22 through AT-25, AT-42).

Verifies:
- AT-22: Canonical payload serialization and Keccak-256 calculation (SER-01 - SER-11).
- AT-23: Null optional field and empty list serialization.
- AT-24: Smart contract interface, methods, and error cases.
- AT-25: Blockchain audit record persistence and state transition to ANCHORED.
- AT-42: Unicode normalization (NFC vs NFD) producing identical hashes.
- SER-06: Floating point rejection.
- TST-13: >= 95% line coverage on services/blockchain_service.py.
"""
from decimal import Decimal
import os
import unicodedata
import pytest

from app.extensions import db
from app.models.blockchain_record import BlockchainRecord
from app.models.model_version import ModelVersion
from app.models.paper_trade import PaperTrade
from app.models.paper_trade_leg import PaperTradeLeg
from app.models.recommendation import Recommendation
from app.models.recommendation_item import RecommendationItem
from app.models.reference_notional_config import ReferenceNotionalConfig
from app.models.stock import Stock
from app.models.user import User
from app.services.blockchain_service import BlockchainAuditError, BlockchainService
from app.utils.clock import Clock


@pytest.fixture
def blockchain_service():
    return BlockchainService()


def test_at_22_canonical_serialization_and_keccak256(blockchain_service):
    """AT-22: Canonical payload serialization produces deterministic sorted JSON and Keccak-256 hash."""
    payload = {
        "user_id": 42,
        "mode": "CNC",
        "budget": Decimal("10000.00"),
        "created_at": Clock.utcnow(),
        "schema_version": "1.0",
        "items": [
            {"ticker": "INFY", "quantity": 10, "allocated_amount": Decimal("15000.00")},
            {"ticker": "TCS", "quantity": 5, "allocated_amount": Decimal("17500.00")},
        ],
    }

    canonical_bytes = blockchain_service.canonical_serialize(payload)
    assert isinstance(canonical_bytes, bytes)

    # Check lexicographical key sorting: 'budget' should come before 'created_at', which comes before 'items'
    canonical_str = canonical_bytes.decode("utf-8")
    pos_budget = canonical_str.find('"budget"')
    pos_created = canonical_str.find('"created_at"')
    pos_items = canonical_str.find('"items"')
    pos_user = canonical_str.find('"user_id"')

    assert pos_budget < pos_created < pos_items < pos_user

    # No insignificant whitespace
    assert ": " not in canonical_str
    assert ", " not in canonical_str

    # Compute Keccak-256 hash
    hash_str = blockchain_service.compute_payload_hash(payload)
    assert hash_str.startswith("0x")
    assert len(hash_str) == 66  # '0x' + 64 hex characters

    # Re-computing on bytes directly yields identical hash
    hash_from_bytes = blockchain_service.compute_payload_hash(canonical_bytes)
    assert hash_from_bytes == hash_str


def test_at_23_null_and_empty_array_serialization(blockchain_service):
    """AT-23: Cross-language vector for null optional fields and empty lists."""
    payload = {
        "schema_version": "1.0",
        "optional_field": None,
        "empty_list": [],
        "flag": False,
        "count": 0,
    }

    canonical_bytes = blockchain_service.canonical_serialize(payload)
    canonical_str = canonical_bytes.decode("utf-8")

    assert '"empty_list":[]' in canonical_str
    assert '"optional_field":null' in canonical_str
    assert '"flag":false' in canonical_str
    assert '"count":0' in canonical_str


def test_at_42_unicode_normalization_nfc_vs_nfd(blockchain_service):
    """AT-42 & SER-11: NFC and NFD representations of text produce identical bytes and hashes."""
    # "café": NFC is single precomposed é (\u00e9); NFD is 'e' + combining acute (\u0301)
    text_nfc = "café"
    text_nfd = unicodedata.normalize("NFD", text_nfc)

    assert text_nfc != text_nfd  # Different unicode codepoints
    assert len(text_nfc) == 4
    assert len(text_nfd) == 5

    payload_nfc = {"company_name": text_nfc, "schema_version": "1.0"}
    payload_nfd = {"company_name": text_nfd, "schema_version": "1.0"}

    bytes_nfc = blockchain_service.canonical_serialize(payload_nfc)
    bytes_nfd = blockchain_service.canonical_serialize(payload_nfd)

    assert bytes_nfc == bytes_nfd

    hash_nfc = blockchain_service.compute_payload_hash(payload_nfc)
    hash_nfd = blockchain_service.compute_payload_hash(payload_nfd)

    assert hash_nfc == hash_nfd


def test_ser_06_reject_float_in_hash_payload(blockchain_service):
    """SER-06: Floating-point JSON numbers are prohibited in hash payloads."""
    payload_with_float = {
        "budget": 1000.50,  # float, prohibited!
        "schema_version": "1.0",
    }
    with pytest.raises(ValueError, match="Floating-point JSON numbers are prohibited"):
        blockchain_service.canonical_serialize(payload_with_float)


def test_at_24_smart_contract_interface_and_file():
    """AT-24: Verifies TradeSenseAudit.sol exists and contains required functions and errors."""
    contract_path = os.path.join("contracts", "TradeSenseAudit.sol")
    assert os.path.exists(contract_path)

    with open(contract_path, "r", encoding="utf-8") as f:
        content = f.read()

    # Function declarations
    assert "function anchorRecommendation(bytes32 payloadHash)" in content
    assert "function anchorTradeResult(bytes32 payloadHash)" in content
    assert "function verifyRecommendation(bytes32 payloadHash)" in content
    assert "function verifyTradeResult(bytes32 payloadHash)" in content

    # Events
    assert "event RecommendationAnchored(" in content
    assert "event TradeResultAnchored(" in content

    # Errors & mappings
    assert "error ZeroHash();" in content
    assert "error AlreadyAnchored(bytes32 payloadHash);" in content
    assert "mapping(bytes32 => uint256) public recommendationAnchors;" in content
    assert "mapping(bytes32 => uint256) public tradeResultAnchors;" in content


def test_at_25_blockchain_record_persistence(app, blockchain_service):
    """AT-25: Anchoring recommendation and trade result creates audit records and sets status."""
    with app.app_context():
        # Setup prerequisite entities
        notional = ReferenceNotionalConfig(
            version_tag="v1.0_bc",
            notional_amount=Decimal("500.00"),
        )
        db.session.add(notional)
        db.session.commit()

        mv = ModelVersion(
            version_tag="mv_bc_test",
            artifact_hash="11" * 32,
            feature_schema_version="1.0",
            reference_notional_id=notional.id,
            reference_notional=Decimal("500.00"),
            training_data_window_start=Clock.utcnow(),
            training_data_window_end=Clock.utcnow(),
            estimate_source_method_version="1.0",
            is_active=True,
        )
        stock = Stock(ticker="WIPRO", isin="INE075A01022", name="Wipro Limited", status="active")
        user = User(email="bc_auditor@tradesense.edu", password_hash="pwd_hash", role="user")
        db.session.add_all([mv, stock, user])
        db.session.commit()

        rec = Recommendation(
            user_id=user.id,
            budget=Decimal("5000.00"),
            effective_budget=Decimal("4975.00"),
            cash_buffer=Decimal("25.00"),
            mode="CNC",
            horizon="1d",
            model_version_id=mv.id,
            rate_card_version="standard_equity_2026",
            reference_notional=Decimal("500.00"),
            status="DRAFT",
        )
        db.session.add(rec)
        db.session.flush()

        item = RecommendationItem(
            recommendation_id=rec.id,
            stock_id=stock.id,
            ticker="WIPRO",
            quantity=10,
            allocated_amount=Decimal("4500.00"),
            expected_return_rate=Decimal("0.030000"),
            p_i=Decimal("0.650000"),
            g_plus=Decimal("20.00"),
            g_minus=Decimal("-10.00"),
            estimate_source="ticker_baseline",
            method_version="1.0",
            stock_status_at_creation="active",
        )
        db.session.add(item)
        db.session.commit()

        # 1. Anchor Recommendation
        bc_record = blockchain_service.anchor_recommendation(rec.id)
        assert bc_record.record_type == "RECOMMENDATION"
        assert bc_record.reference_id == rec.id
        assert bc_record.commitment_hash.startswith("0x")
        assert bc_record.tx_hash.startswith("0x")
        assert bc_record.status == "CONFIRMED"

        # Verify recommendation model updated
        updated_rec = db.session.get(Recommendation, rec.id)
        assert updated_rec.status == "ANCHORED"
        assert updated_rec.commitment_hash == bc_record.commitment_hash
        assert updated_rec.tx_hash == bc_record.tx_hash

        # 2. Anchor Trade Result
        trade = PaperTrade(
            user_id=user.id,
            recommendation_id=rec.id,
            mode="CNC",
            status="CLOSED",
            total_gross_pnl=Decimal("150.00"),
            total_net_pnl=Decimal("125.50"),
            opened_at=Clock.utcnow(),
            closed_at=Clock.utcnow(),
        )
        db.session.add(trade)
        db.session.flush()

        leg = PaperTradeLeg(
            paper_trade_id=trade.id,
            stock_id=stock.id,
            ticker="WIPRO",
            action="BUY",
            quantity=10,
            price=Decimal("450.00"),
        )
        db.session.add(leg)
        db.session.commit()

        trade_bc_record = blockchain_service.anchor_trade_result(trade.id)
        assert trade_bc_record.record_type == "TRADE_RESULT"
        assert trade_bc_record.reference_id == trade.id
        assert trade_bc_record.commitment_hash.startswith("0x")
        assert trade_bc_record.status == "CONFIRMED"

        # Verify trade model updated
        updated_trade = db.session.get(PaperTrade, trade.id)
        assert updated_trade.commitment_hash == trade_bc_record.commitment_hash
        assert updated_trade.tx_hash == trade_bc_record.tx_hash

        # Verification check
        payload = blockchain_service.build_recommendation_payload(rec)
        assert blockchain_service.verify_payload_hash(payload, updated_rec.commitment_hash) is True
        assert blockchain_service.verify_payload_hash(payload, "0x" + "00" * 32) is False


def test_blockchain_service_validation_errors(app, blockchain_service):
    """Verifies error handling on invalid inputs in BlockchainService."""
    # Non-dictionary root
    with pytest.raises(ValueError, match="Payload root must be a dictionary"):
        blockchain_service.canonical_serialize(["not", "a", "dict"])

    # Invalid non-string key
    with pytest.raises(ValueError, match="Payload keys must be strings"):
        blockchain_service.canonical_serialize({123: "val"})

    # Non-existent entities
    with app.app_context():
        with pytest.raises(BlockchainAuditError, match="RECOMMENDATION_NOT_FOUND"):
            blockchain_service.anchor_recommendation(999999)

        with pytest.raises(BlockchainAuditError, match="TRADE_NOT_FOUND"):
            blockchain_service.anchor_trade_result(999999)

    # Invalid type for compute_payload_hash
    with pytest.raises(TypeError, match="Expected dict or bytes"):
        blockchain_service.compute_payload_hash(12345)
