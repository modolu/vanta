"""Logistic-regression engine (ARCHITECTURE.md §11, miner 5).

Fits two small models at forecast time on the history visible at ``T``: a logistic
regression for direction and a linear regression for the horizon return. Both are trained
by plain batch gradient descent in pure Python — deterministic, dependency-free, and
small enough to read.

Why no scikit-learn: this needs one logistic and one linear fit on a few hundred rows and
five features. That is about forty lines of arithmetic. Adding scikit-learn would pull in
NumPy and SciPy, and its iterative solvers can differ across BLAS builds, which would put
the reproducibility the mechanism depends on at the mercy of the install. Nothing here
would be materially simpler with it.

Training labels come from candles that had already closed at ``T``: a sample at index
``i`` is labelled by the price at ``i + horizon_steps``, and samples are only generated
while that index is still inside the visible window. The model therefore never sees the
outcome of the task it is forecasting (§29).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import ClassVar

from vanta.forecasting.base import ForecastContext, ForecastEngine, Prediction
from vanta.forecasting.features import (
    FEATURE_WARMUP,
    bounded_probability,
    feature_row,
    logistic,
)
from vanta.market.errors import InsufficientMarketDataError

__all__ = ["MLEngine"]

Matrix = list[list[float]]

DEFAULT_EPOCHS = 300
DEFAULT_LEARNING_RATE = 0.1
DEFAULT_MIN_SAMPLES = 30


def _standardize(rows: Matrix) -> tuple[Matrix, list[float], list[float]]:
    """Centre and scale each column so gradient descent converges at one learning rate."""
    columns = len(rows[0])
    means = [sum(row[index] for row in rows) / len(rows) for index in range(columns)]
    deviations = [
        math.sqrt(sum((row[index] - means[index]) ** 2 for row in rows) / len(rows))
        for index in range(columns)
    ]
    # A constant column carries no information; scaling by 1.0 leaves it at zero.
    scales = [deviation if deviation > 1e-12 else 1.0 for deviation in deviations]
    standardized = [
        [(row[index] - means[index]) / scales[index] for index in range(columns)] for row in rows
    ]
    return standardized, means, scales


def _apply(row: Sequence[float], means: Sequence[float], scales: Sequence[float]) -> list[float]:
    return [(value - mean) / scale for value, mean, scale in zip(row, means, scales, strict=True)]


def _fit(
    rows: Matrix,
    targets: Sequence[float],
    *,
    logistic_link: bool,
    epochs: int,
    learning_rate: float,
) -> tuple[list[float], float]:
    """Batch gradient descent from a zero start; returns ``(weights, bias)``.

    A zero initialization and a fixed epoch count keep the fit deterministic — there is no
    random state to seed and no early stopping to depend on floating-point ties.
    """
    columns = len(rows[0])
    weights = [0.0] * columns
    bias = 0.0
    count = len(rows)

    for _ in range(epochs):
        weight_gradient = [0.0] * columns
        bias_gradient = 0.0
        for row, target in zip(rows, targets, strict=True):
            raw = bias + sum(weight * value for weight, value in zip(weights, row, strict=True))
            predicted = logistic(raw) if logistic_link else raw
            error = predicted - target
            bias_gradient += error
            for index in range(columns):
                weight_gradient[index] += error * row[index]
        step = learning_rate / count
        bias -= step * bias_gradient
        for index in range(columns):
            weights[index] -= step * weight_gradient[index]

    return weights, bias


class MLEngine(ForecastEngine):
    """Direction by logistic regression, magnitude by linear regression."""

    name: ClassVar[str] = "ml"

    def __init__(
        self,
        *,
        volatility_window: int = 20,
        epochs: int = DEFAULT_EPOCHS,
        learning_rate: float = DEFAULT_LEARNING_RATE,
        min_samples: int = DEFAULT_MIN_SAMPLES,
    ) -> None:
        self._volatility_window = volatility_window
        self._epochs = epochs
        self._learning_rate = learning_rate
        self._min_samples = min_samples

    def required_history(self, context: ForecastContext) -> int:
        """Warm-up for the features, plus one horizon of labels, plus the sample budget."""
        return FEATURE_WARMUP + context.horizon_steps + self._min_samples

    def _training_set(
        self, closes: Sequence[float], horizon_steps: int
    ) -> tuple[Matrix, list[float], list[float]]:
        rows: Matrix = []
        directions: list[float] = []
        returns: list[float] = []
        # `end` stops one horizon short of the visible edge, so every label is a price
        # that had already printed by T.
        end = len(closes) - horizon_steps
        for index in range(FEATURE_WARMUP, end):
            history = closes[: index + 1]
            future = closes[index + horizon_steps]
            current = history[-1]
            if current <= 0:
                continue
            rows.append(feature_row(history, volatility_window=self._volatility_window))
            directions.append(1.0 if future > current else 0.0)
            returns.append((future - current) / current)
        return rows, directions, returns

    def predict(self, context: ForecastContext) -> Prediction:
        closes = context.closes
        horizon_steps = context.horizon_steps
        rows, directions, returns = self._training_set(closes, horizon_steps)

        if len(rows) < self._min_samples:
            raise InsufficientMarketDataError(
                f"{self.name} needs {self._min_samples} training samples at "
                f"{context.task.timestamp}, got {len(rows)}"
            )

        standardized, means, scales = _standardize(rows)
        direction_weights, direction_bias = _fit(
            standardized,
            directions,
            logistic_link=True,
            epochs=self._epochs,
            learning_rate=self._learning_rate,
        )
        return_weights, return_bias = _fit(
            standardized,
            returns,
            logistic_link=False,
            epochs=self._epochs,
            learning_rate=self._learning_rate,
        )

        live = _apply(feature_row(closes, volatility_window=self._volatility_window), means, scales)
        direction_raw = direction_bias + sum(
            weight * value for weight, value in zip(direction_weights, live, strict=True)
        )
        expected_return = return_bias + sum(
            weight * value for weight, value in zip(return_weights, live, strict=True)
        )

        return Prediction(
            probability_up=bounded_probability(logistic(direction_raw)),
            expected_return=expected_return,
        )
