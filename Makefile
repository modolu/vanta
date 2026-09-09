.PHONY: help install test lint check fetch-history simulation mock-subnet localnet-up localnet-down localnet-proof testnet-preflight network-state

VENV ?= .venv
PY   ?= $(VENV)/bin/python
NETWORK ?= test
NETUID  ?= 1

help:  ## Show this help
	@grep -hE '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk -F':.*?## ' '{printf "  %-20s %s\n", $$1, $$2}'

install:  ## Create the venv and install Vanta with the chain extra
	python3.12 -m venv $(VENV)
	$(PY) -m pip install -q --upgrade pip
	$(PY) -m pip install -q -e '.[chain,dev]'
	@echo "installed; activate with: source $(VENV)/bin/activate"

test:  ## Run the test suite (no network access)
	$(PY) -m pytest

lint:  ## Lint and format check
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .

check: lint test  ## Full quality gate

fetch-history:  ## Download 60 days of ETH candles into data/ (needed once before `simulation`)
	$(PY) scripts/fetch_history.py 60

simulation:  ## Replay the 60-day historical baseline (run `fetch-history` first)
	$(PY) scripts/run_simulation.py

mock-subnet:  ## Offline end-to-end proof: 4 signed HTTP miners + validator, no chain
	$(PY) scripts/mock_subnet.py --rounds 8 --miners 4

localnet-up:  ## Start a local subtensor node in Docker
	docker run -d --name vanta-localnet -p 9944:9944 -p 9945:9945 \
		ghcr.io/opentensor/subtensor-localnet:latest
	@echo "waiting for the node to produce blocks..."; sleep 30

localnet-down:  ## Stop and remove the local subtensor node
	-docker rm -f vanta-localnet

localnet-proof:  ## Full proof against the local chain (needs localnet-up)
	PYTHONPATH=. $(PY) scripts/localnet_proof.py --rounds 4 --miners 4

testnet-preflight:  ## Check readiness to deploy on the public test network (spends nothing)
	$(PY) scripts/testnet_preflight.py --network $(NETWORK) --netuid $(NETUID) --miners 4

network-state:  ## Show a subnet's on-chain Vanta topology
	$(PY) scripts/network_state.py --network $(NETWORK) --netuid $(NETUID)
