"""Random forecast engine — the negative control (ARCHITECTURE.md §11, miner 1).

Produces pure noise. Its job is to lose: if the mechanism works, this engine's reputation
must decay below every competent miner as the sample size grows (§41).
"""

from __future__ import annotations

import hashlib
import random
from typing import ClassVar

from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction

__all__ = ["RandomEngine"]

# Magnitude of the noise drawn for expected_return, roughly a large 15m ETH move.
NOISE_RETURN = 0.01


def _deterministic_seed(seed: int, task_id: str) -> int:
    """Fold a task id into the base seed reproducibly across processes.

    ``hash()`` is salted per interpreter run, so it cannot be used here: the same task
    must yield the same forecast on every machine that replays the simulation.
    """
    digest = hashlib.blake2b(task_id.encode("utf-8"), digest_size=8).digest()
    return (seed ^ int.from_bytes(digest, "big")) & ((1 << 64) - 1)


class RandomEngine(ForecastEngine):
    """Uniform-random probability and return, seeded per task."""

    name: ClassVar[str] = "random"
    min_history: ClassVar[int] = 0

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def predict(self, context: ForecastContext) -> Prediction:
        rng = random.Random(_deterministic_seed(self._seed, context.task.task_id))
        return Prediction(
            probability_up=rng.random(),
            expected_return=rng.uniform(-NOISE_RETURN, NOISE_RETURN),
        )
