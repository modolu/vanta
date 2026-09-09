"""The Bittensor miner neuron (ARCHITECTURE.md §10).

Two layers, strictly separated. This module is the outer one: it serves an HTTP
endpoint, authenticates callers by hotkey, validates the request, and formats the
response. It contains no forecasting logic whatsoever — the inner layer is any
:class:`~vanta.forecasting.base.ForecastEngine`, injected here and replaceable without
touching a line of neuron code.

bittensor v11 removed the axon/dendrite/synapse stack, so "serving an axon" is now two
independent things: running this HTTP service, and publishing its ``ip:port`` on chain
with the ServeAxon intent (see :func:`vanta.neurons.chain.BittensorChain.serve_axon`).

No look-ahead (§29)
-------------------
The handler builds its context with :meth:`ForecastContext.build`, which drops every
candle closing after the task's reference instant ``T``. The engine therefore cannot
see the bar it is being asked to forecast even if the market provider returns it. The
boundary is structural, not a convention this module is trusted to honour.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from vanta.forecasting.base import ForecastContext, ForecastEngine
from vanta.log import get_logger
from vanta.market.errors import MarketDataError
from vanta.market.normalization import align_down
from vanta.market.provider import MarketDataProvider
from vanta.neurons.chain import ChainError, RequestVerifier, SubnetView
from vanta.protocol.synapse import (
    FORECAST_PATH,
    ForecastRequest,
    ForecastResponse,
    forecast_to_response,
    request_to_task,
)
from vanta.validation import VantaValidationError

__all__ = ["ForecastService", "HotkeyGate", "create_app", "serve"]

logger = get_logger(__name__)


class HotkeyGate:
    """Who may query this miner (§25 — the blacklist an unguarded endpoint lacks).

    Only hotkeys registered on the subnet are served, and optionally only those holding
    a minimum stake (in the subnet's own units). The registered set is refreshed from the
    metagraph on a timer, so a newly registered validator becomes able to query within one
    refresh interval without restarting the miner.

    With no :class:`SubnetView` the gate is open: that is the mock/local mode used by
    the offline end-to-end proof, never a chain deployment.
    """

    def __init__(
        self,
        view: SubnetView | None,
        netuid: int,
        *,
        min_stake: float = 0.0,
        refresh_seconds: float = 300.0,
        require_validator_permit: bool = False,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if refresh_seconds <= 0:
            raise ValueError("refresh_seconds must be > 0")
        self._view = view
        self._netuid = netuid
        self._min_stake = min_stake
        self._refresh = refresh_seconds
        self._require_permit = require_validator_permit
        self._clock = clock
        self._allowed: frozenset[str] = frozenset()
        self._refreshed_at: float | None = None

    @property
    def is_open(self) -> bool:
        """True when no chain view backs this gate, so every caller is served."""
        return self._view is None

    def allows(self, hotkey: str) -> bool:
        """Whether ``hotkey`` may query this miner."""
        if self._view is None:
            return True
        self._maybe_refresh()
        return hotkey in self._allowed

    def _maybe_refresh(self) -> None:
        now = self._clock()
        if self._refreshed_at is not None and now - self._refreshed_at < self._refresh:
            return
        assert self._view is not None
        try:
            neurons = self._view.neurons(self._netuid)
        except ChainError as exc:
            # Keep serving the previous set rather than locking every validator out on a
            # transient chain read failure.
            logger.warning("hotkey gate refresh failed, keeping the previous set: %s", exc)
            self._refreshed_at = now
            return
        self._allowed = frozenset(
            neuron.hotkey
            for neuron in neurons
            if neuron.stake >= self._min_stake
            and (neuron.validator_permit or not self._require_permit)
        )
        self._refreshed_at = now
        logger.debug("hotkey gate refreshed: %d callers allowed", len(self._allowed))


@dataclass(slots=True)
class ForecastService:
    """The inner request handler: task in, forecast out.

    Deliberately free of any HTTP or chain type so it can be unit-tested directly.
    """

    engine: ForecastEngine
    provider: MarketDataProvider
    candle_interval_seconds: int = 60
    lookback_candles: int = 600
    miner_uid: int = 0

    def __post_init__(self) -> None:
        if self.candle_interval_seconds <= 0:
            raise ValueError("candle_interval_seconds must be > 0")
        if self.lookback_candles <= 0:
            raise ValueError("lookback_candles must be > 0")

    def forecast(self, request: ForecastRequest) -> ForecastResponse:
        """Answer one forecast request.

        Raises:
            VantaValidationError: if the request violates a protocol invariant.
            MarketDataError: if there is not enough history to forecast.
        """
        # Rebuilding the domain task re-checks every invariant, including that the
        # submission deadline falls before resolution (§27, §29).
        task = request_to_task(request)
        context = ForecastContext.build(task, self._history(task.asset, task.timestamp))
        forecast = self.engine.forecast(context, miner_uid=self.miner_uid)
        return forecast_to_response(forecast)

    def _history(self, asset: str, as_of: int) -> Any:
        """Candles up to ``as_of``.

        ``end`` is the task instant, never later. Even so, the context builder filters
        again on ``close_time`` — the request bound is an optimization, the filter is
        the guarantee.
        """
        interval = self.candle_interval_seconds
        end = align_down(as_of, interval)
        start = end - self.lookback_candles * interval
        return self.provider.fetch_candles(asset, interval, start, as_of)


def create_app(
    service: ForecastService,
    *,
    gate: HotkeyGate | None = None,
    verifier: RequestVerifier | None = None,
) -> Any:
    """Build the miner's FastAPI application.

    ``verifier`` authenticates callers with btauth/1; without one the endpoint is
    unauthenticated, which is only appropriate for the offline mock proof. ``gate``
    additionally restricts callers to registered (optionally staked) hotkeys.
    """
    app = FastAPI(title="Vanta miner", version="1")

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "status": "ok",
            "engine": service.engine.name,
            "version": service.engine.version,
            "authenticated": verifier is not None,
        }

    @app.post(FORECAST_PATH)
    async def forecast(request: Request) -> JSONResponse:
        # Hash the bytes as received: the signature covers exactly what arrived, before
        # any parsing or re-serialization.
        body = await request.body()

        caller = "anonymous"
        if verifier is not None:
            target = request.scope["raw_path"].decode()
            if request.scope.get("query_string"):
                target += "?" + request.scope["query_string"].decode()
            try:
                caller = verifier(
                    headers=dict(request.headers),
                    body=body,
                    method=request.method,
                    path=target,
                )
            except ChainError as exc:
                raise HTTPException(status_code=401, detail=str(exc)) from exc

        if gate is not None and not gate.allows(caller):
            raise HTTPException(
                status_code=403, detail=f"hotkey {caller} is not permitted to query this miner"
            )

        try:
            parsed = ForecastRequest.model_validate_json(body)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"malformed request: {exc}") from exc

        try:
            response = service.forecast(parsed)
        except VantaValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except MarketDataError as exc:
            # Not the caller's fault: this miner cannot answer right now.
            logger.warning("cannot answer task %s: %s", parsed.task_id, exc)
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        logger.info(
            "answered task %s for %s: p_up=%.4f expected_return=%+.6f",
            parsed.task_id,
            caller,
            response.probability_up,
            response.expected_return,
        )
        return JSONResponse(content=response.model_dump(mode="json"))

    return app


def serve(app: Any, host: str, port: int) -> None:
    """Run the miner's HTTP service (blocking)."""
    import uvicorn

    uvicorn.run(app, host=host, port=port, log_level="info")
