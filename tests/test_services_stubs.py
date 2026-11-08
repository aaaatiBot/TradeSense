"""Test service stubs are importable and properly defined."""
from app.services.auth_service import AuthService
from app.services.blockchain_service import BlockchainService
from app.services.conditional_return_service import ConditionalReturnService
from app.services.cost_engine import CostEngine
from app.services.expected_return_service import ExpectedReturnService
from app.services.feature_service import FeatureService
from app.services.gemini_service import GeminiService
from app.services.market_data_service import MarketDataService
from app.services.optimizer_service import OptimizerService
from app.services.paper_trade_service import PaperTradeService
from app.services.prediction_service import PredictionService
from app.services.retention_service import RetentionService
from app.services.universe_service import UniverseService
from app.services.verification_service import VerificationService


def test_service_stubs_instantiation():
    """Verify all required Phase 1 service stubs exist and instantiate."""
    services = [
        AuthService(),
        BlockchainService(),
        ConditionalReturnService(),
        CostEngine(),
        ExpectedReturnService(),
        FeatureService(),
        GeminiService(),
        MarketDataService(),
        OptimizerService(),
        PaperTradeService(),
        PredictionService(),
        RetentionService(),
        UniverseService(),
        VerificationService(),
    ]
    for s in services:
        assert s is not None
