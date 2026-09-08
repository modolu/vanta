"""Reference forecast engines (ARCHITECTURE.md §11).

Vanta does not prescribe how a miner predicts (§12). These engines exist to give the
mechanism a spread of intelligence levels to score, from pure noise to a fitted model.
"""

from vanta.forecasting.adversarial import AdversarialEngine
from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.forecasting.mean_reversion import MeanReversionEngine
from vanta.forecasting.ml import MLEngine
from vanta.forecasting.momentum import MomentumEngine
from vanta.forecasting.persistence import PersistenceEngine
from vanta.forecasting.random import RandomEngine

__all__ = [
    "AdversarialEngine",
    "ForecastContext",
    "ForecastEngine",
    "MLEngine",
    "MeanReversionEngine",
    "MomentumEngine",
    "PersistenceEngine",
    "Prediction",
    "RandomEngine",
    "default_engines",
]


def default_engines() -> list[ForecastEngine]:
    """The reference line-up used by the simulation and the mechanism tests."""
    return [
        RandomEngine(seed=1),
        PersistenceEngine(),
        MeanReversionEngine(),
        MomentumEngine(),
        MLEngine(),
        AdversarialEngine(),
    ]
