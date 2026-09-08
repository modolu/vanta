"""The forecast-engine boundary (ARCHITECTURE.md §10, §12, §29).

A miner is two layers: the Bittensor neuron, and the forecast engine behind it. Only the
engine lives here, so an operator can replace their model without touching neuron code.

Vanta never prescribes *how* a miner predicts (§12) — the strategies in this package are
reference implementations that give the mechanism something to score, not part of the
protocol. What the protocol does fix is the shape of the answer (``probability_up`` and
``expected_return``, §6) and the data an engine is allowed to see (§29).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from dataclasses import dataclass
from typing import ClassVar

from vanta.market.errors import InsufficientMarketDataError
from vanta.market.provider import Candle
from vanta.market.resolution import MarketWindow
from vanta.protocol.forecast import Forecast, ForecastTask
from vanta.validation import require_finite

__all__ = ["ForecastContext", "ForecastEngine", "Prediction"]


@dataclass(frozen=True, slots=True)
class Prediction:
    """An engine's raw answer, before it is wrapped into a protocol :class:`Forecast`.

    ``probability_up`` is clamped into ``[0, 1]`` so ordinary floating-point overshoot
    from a squashing function cannot fail a forecast. A non-finite value is a bug rather
    than a rounding artifact and is raised instead.
    """

    probability_up: float
    expected_return: float

    def __post_init__(self) -> None:
        probability = require_finite(self.probability_up, "probability_up")
        object.__setattr__(self, "probability_up", min(1.0, max(0.0, probability)))
        object.__setattr__(
            self, "expected_return", require_finite(self.expected_return, "expected_return")
        )


@dataclass(frozen=True, slots=True)
class ForecastContext:
    """Everything an engine is permitted to see for one task.

    The history is a :class:`MarketWindow` pinned to the task's reference instant ``T``.
    Candles closing after ``T`` are dropped when the window is built and rejected if one
    is inserted by hand, so an engine cannot reach the outcome it is forecasting — the
    boundary is structural, not a convention the engine is trusted to respect (§29).
    """

    task: ForecastTask
    history: MarketWindow

    def __post_init__(self) -> None:
        if self.history.as_of != self.task.timestamp:
            raise InsufficientMarketDataError(
                f"history is pinned to {self.history.as_of} but task {self.task.task_id!r} "
                f"has reference time {self.task.timestamp}"
            )

    @classmethod
    def build(cls, task: ForecastTask, candles: Iterable[Candle]) -> ForecastContext:
        """Bound ``candles`` to the task's reference instant and pair them with the task."""
        return cls(task=task, history=MarketWindow.build(candles, task.timestamp))

    @property
    def closes(self) -> tuple[float, ...]:
        """Closing prices visible at ``T``, oldest first."""
        return self.history.closes()

    @property
    def reference_price(self) -> float:
        return self.task.reference_price

    @property
    def interval_seconds(self) -> int:
        """Candle interval of the visible history."""
        return self.history.latest.interval_seconds

    @property
    def horizon_steps(self) -> int:
        """Forecast horizon expressed in candles."""
        interval = self.interval_seconds
        horizon = self.task.horizon_seconds
        if horizon % interval != 0:
            raise InsufficientMarketDataError(
                f"horizon {horizon}s is not a whole number of {interval}s candles"
            )
        return horizon // interval


class ForecastEngine(ABC):
    """A swappable forecasting model (§10).

    Subclasses implement :meth:`predict`; :meth:`forecast` handles the history check and
    the wrapping into a protocol :class:`Forecast`.
    """

    name: ClassVar[str] = "engine"
    version: ClassVar[str] = "v1"
    min_history: ClassVar[int] = 0

    @abstractmethod
    def predict(self, context: ForecastContext) -> Prediction:
        """Return this engine's view of the task, using only ``context``."""

    def required_history(self, context: ForecastContext) -> int:
        """Candles this engine needs. Overridden where the need depends on the horizon."""
        return self.min_history

    def forecast(self, context: ForecastContext, *, miner_uid: int) -> Forecast:
        """Produce a protocol forecast, failing explicitly on insufficient history."""
        required = self.required_history(context)
        available = len(context.history.candles)
        if available < required:
            raise InsufficientMarketDataError(
                f"{self.name} needs {required} candles at {context.task.timestamp}, got {available}"
            )
        prediction = self.predict(context)
        return Forecast(
            task_id=context.task.task_id,
            miner_uid=miner_uid,
            probability_up=prediction.probability_up,
            expected_return=prediction.expected_return,
            model_version=f"{self.name}-{self.version}",
        )
