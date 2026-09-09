"""The chain boundary: isolation from the mechanism, and real btauth/1 authentication.

The signing tests use the installed SDK's own crypto with ephemeral development
keypairs. No wallet file is written, no coldkey exists, and nothing touches the network
or a chain node.
"""

from __future__ import annotations

import importlib
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from vanta.neurons.chain import (
    ChainError,
    NeuronRecord,
    make_signer,
    make_verifier,
)
from vanta.neurons.miner import create_app
from vanta.protocol.synapse import FORECAST_PATH, task_to_request

from .helpers import make_task
from .test_miner import service

T = 1_788_900_000

bittensor = pytest.importorskip("bittensor", reason="chain extra not installed")
Keypair = importlib.import_module("bittensor.sp_core").Keypair


def keypair(uri: str):  # type: ignore[no-untyped-def]
    """An ephemeral development keypair. Never written to disk."""
    return Keypair.create_from_uri(uri)


class TestIsolation:
    def test_the_mechanism_imports_without_the_chain_sdk(self) -> None:
        """CLAUDE.md rule 5 / §10: the forecast engine must not depend on chain code."""
        code = (
            "import sys;"
            "sys.modules['bittensor'] = None;"
            "import vanta.protocol.forecast, vanta.protocol.synapse, vanta.validator.scorer,"
            "vanta.validator.reputation, vanta.validator.weights, vanta.validator.collector,"
            "vanta.validator.task_generator, vanta.forecasting, vanta.market.resolution,"
            "vanta.simulation.replay, vanta.database.sqlite;"
            "print('ok')"
        )
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout

    def test_importing_the_chain_module_does_not_import_the_sdk(self) -> None:
        """The SDK import is deferred, so the module is free to import."""
        code = "import sys;import vanta.neurons.chain;print('bittensor' in sys.modules)"
        result = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "False"


class TestNeuronRecord:
    def test_a_served_endpoint_is_queryable(self) -> None:
        assert NeuronRecord(
            uid=0, hotkey="a", axon="127.0.0.1:9000", validator_permit=False, stake=0.0
        ).is_servable

    @pytest.mark.parametrize("axon", [None, ""])
    def test_an_unserved_neuron_is_not_queryable(self, axon: str | None) -> None:
        assert not NeuronRecord(
            uid=0, hotkey="a", axon=axon, validator_permit=False, stake=0.0
        ).is_servable


class TestBtauth:
    """End-to-end btauth/1 against the real miner app, in process."""

    def call(self, client: TestClient, signer, receiver: str, body: bytes):  # type: ignore[no-untyped-def]
        headers = signer(method="POST", path=FORECAST_PATH, body=body, receiver_ss58=receiver)
        headers["content-type"] = "application/json"
        return client.post(FORECAST_PATH, content=body, headers=headers)

    def test_a_correctly_signed_request_is_served(self) -> None:
        validator, miner = keypair("//Alice"), keypair("//Bob")
        app = create_app(service(), verifier=make_verifier(miner.ss58_address))
        body = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")

        response = self.call(TestClient(app), make_signer(validator), miner.ss58_address, body)
        assert response.status_code == 200

    def test_an_unsigned_request_is_rejected(self) -> None:
        miner = keypair("//Bob")
        app = create_app(service(), verifier=make_verifier(miner.ss58_address))
        body = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")

        response = TestClient(app).post(FORECAST_PATH, content=body)
        assert response.status_code == 401

    def test_a_request_signed_for_another_miner_is_rejected(self) -> None:
        """Receiver binding: a signature harvested from miner B is useless against C."""
        validator, miner, other = keypair("//Alice"), keypair("//Bob"), keypair("//Charlie")
        app = create_app(service(), verifier=make_verifier(miner.ss58_address))
        body = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")

        response = self.call(TestClient(app), make_signer(validator), other.ss58_address, body)
        assert response.status_code == 401

    def test_a_tampered_body_is_rejected(self) -> None:
        """The signature covers the body hash, so a modified task fails to verify."""
        validator, miner = keypair("//Alice"), keypair("//Bob")
        app = create_app(service(), verifier=make_verifier(miner.ss58_address))
        body = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")

        headers = make_signer(validator)(
            method="POST", path=FORECAST_PATH, body=body, receiver_ss58=miner.ss58_address
        )
        headers["content-type"] = "application/json"
        tampered = body.replace(b'"reference_price":4500.0', b'"reference_price":9999.0')
        assert tampered != body

        response = TestClient(app).post(FORECAST_PATH, content=tampered, headers=headers)
        assert response.status_code == 401

    def test_a_replayed_request_is_rejected(self) -> None:
        """Each retry must sign a fresh nonce; re-sending the same headers is a replay."""
        validator, miner = keypair("//Alice"), keypair("//Bob")
        app = create_app(service(), verifier=make_verifier(miner.ss58_address))
        client = TestClient(app)
        body = task_to_request(make_task(timestamp=T)).model_dump_json().encode("utf-8")

        headers = make_signer(validator)(
            method="POST", path=FORECAST_PATH, body=body, receiver_ss58=miner.ss58_address
        )
        headers["content-type"] = "application/json"

        assert client.post(FORECAST_PATH, content=body, headers=headers).status_code == 200
        assert client.post(FORECAST_PATH, content=body, headers=headers).status_code == 401

    def test_the_verifier_raises_a_chain_error_not_an_sdk_error(self) -> None:
        """Callers handle ChainError without importing bittensor."""
        verifier = make_verifier(keypair("//Bob").ss58_address)
        with pytest.raises(ChainError):
            verifier(headers={}, body=b"", method="POST", path=FORECAST_PATH)

    def test_signing_produces_the_documented_btauth_headers(self) -> None:
        headers = make_signer(keypair("//Alice"))(
            method="POST",
            path=FORECAST_PATH,
            body=b"{}",
            receiver_ss58=keypair("//Bob").ss58_address,
        )
        assert headers["X-Bittensor-Version"] == "1"
        assert headers["X-Bittensor-Hotkey"] == keypair("//Alice").ss58_address
        assert headers["X-Bittensor-Receiver"] == keypair("//Bob").ss58_address
        assert headers["X-Bittensor-Signature"].startswith("0x")
