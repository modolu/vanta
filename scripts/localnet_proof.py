"""End-to-end proof against a real local subtensor node.

    docker run -d --name vanta-localnet -p 9944:9944 -p 9945:9945 \
        ghcr.io/opentensor/subtensor-localnet:latest
    python scripts/localnet_proof.py --netuid 1 --miners 4

Unlike scripts/mock_subnet.py, nothing about the chain is faked here: hotkeys are really
registered, axon endpoints are really published with the ServeAxon intent, the metagraph
is really read back, and weights are really submitted with the SetWeights intent and
read back from chain storage afterwards.

Market data stays synthetic and deterministic so the run exercises the chain integration
rather than a price feed.

Keys: every neuron uses an ephemeral development keypair derived from a ``//Vanta...``
URI, acting as its own coldkey and hotkey. Nothing is written to disk, no wallet file is
created, and these keys are worthless outside this throwaway local chain. Never point
this script at a real network.
"""

from __future__ import annotations

import argparse
import socket
import sys
import threading
import time

import uvicorn

# Reuses the offline proof's deterministic market feed and server plumbing.
from scripts.mock_subnet import (
    HORIZON,
    INTERVAL,
    WINDOW,
    SyntheticProvider,
    build_candles,
    synthetic_closes,
)
from vanta.database.sqlite import SqliteValidatorStore
from vanta.forecasting import (
    MeanReversionEngine,
    MLEngine,
    MomentumEngine,
    PersistenceEngine,
)
from vanta.log import configure_logging, get_logger
from vanta.market.resolution import ResolutionEngine
from vanta.neurons.chain import ChainError, make_signer, make_verifier
from vanta.neurons.miner import ForecastService, create_app
from vanta.neurons.validator import Validator, ValidatorConfig
from vanta.validator.collector import ForecastCollector, HttpxTransport
from vanta.validator.task_generator import TaskGenerator
from vanta.validator.weight_adapter import MinerRegistry

logger = get_logger("scripts.localnet_proof")

ENGINES = [PersistenceEngine(), MeanReversionEngine(), MomentumEngine(), MLEngine()]
FUND_TAO = 1000.0
# Must be covered by FUND_TAO, with room left for the registration burn and fees.
VALIDATOR_STAKE_TAO = 500.0


def lan_ip() -> str:
    """This machine's LAN address.

    The chain rejects loopback in serve_axon, so the endpoint published on chain must be
    a real interface address; miners bind 0.0.0.0 so they are reachable at it.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("192.0.2.1", 9))  # TEST-NET-1: routes nowhere, sends nothing
        return str(sock.getsockname()[0])


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def execute(client, intent, signer, label: str):  # type: ignore[no-untyped-def]
    """Run one extrinsic, reporting the outcome plainly."""
    try:
        # execute() reports rejection through result.success, not by raising, so an
        # unchecked call silently "succeeds" against a chain that refused it.
        result = client.execute(intent, signer).raise_for_failure()
    except Exception as exc:
        logger.error("%s FAILED: %s", label, exc)
        raise
    logger.info("%s ok", label)
    return result


def submit_raw(client, call, signer, label: str, *, role: str = "coldkey"):  # type: ignore[no-untyped-def]
    """Submit a raw call, bypassing the MEV shield.

    ``BurnedRegister`` and ``AddStake`` are MEV-shield-required intents: the encrypted
    submission must be decrypted and included by the block author within an 8-block era.
    This localnet runs 0.25s fast blocks, so that era is ~2 seconds and the shielded
    extrinsic reliably expires before inclusion. The shield protects against sandwiching
    on a public chain with real value at stake; on a throwaway local node with dev keys
    there is nothing to sandwich, so the proof takes the documented escape hatch. This
    is localnet-only scaffolding and is not used by the miner or validator neurons.
    """
    try:
        result = client.submit_call(call, signer, signer=role).raise_for_failure()
    except Exception as exc:
        logger.error("%s FAILED: %s", label, exc)
        raise
    logger.info("%s ok", label)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Vanta localnet end-to-end proof")
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--network", default="local")
    parser.add_argument("--miners", type=int, default=4)
    parser.add_argument("--rounds", type=int, default=6)
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--announce-ip",
        default=None,
        help="IP published on chain (default: this machine's LAN address)",
    )
    parser.add_argument(
        "--permit-wait-blocks",
        type=int,
        default=250,
        help="blocks to wait for the validator to earn a validator permit",
    )
    args = parser.parse_args()

    configure_logging(args.log_level)

    try:
        import bittensor as bt
        from bittensor.sp_core import Keypair
    except ImportError:
        print("this proof needs the chain extra: pip install -e '.[chain]'")
        return 1

    if args.network not in ("local",):
        print(f"refusing to run against {args.network!r}: this script is localnet-only")
        return 1

    miner_count = max(1, min(args.miners, len(ENGINES)))
    engines = ENGINES[:miner_count]

    client = bt.Subtensor(args.network)
    logger.info("connected to %s at block %d", client.endpoint, client.block)

    funder = Keypair.create_from_uri("//Alice")
    validator_key = Keypair.create_from_uri("//VantaValidator")
    miner_keys = [Keypair.create_from_uri(f"//VantaMiner{i}") for i in range(miner_count)]

    metagraph = client.subnets.metagraph(args.netuid, commitments=False)
    if metagraph is None:
        print(f"netuid {args.netuid} does not exist on this node")
        return 1
    registered = {neuron.hotkey for neuron in metagraph.neurons}

    # --- fund and register -------------------------------------------------------
    for label, key in [("validator", validator_key)] + [
        (f"miner{i}", k) for i, k in enumerate(miner_keys)
    ]:
        if key.ss58_address in registered:
            logger.info("%s already registered, skipping", label)
            continue
        execute(
            client,
            bt.Transfer(dest_ss58=key.ss58_address, amount_tao=FUND_TAO),
            funder,
            f"fund {label}",
        )
        submit_raw(
            client,
            bt.calls.SubtensorModule.burned_register(netuid=args.netuid, hotkey=key.ss58_address),
            key,
            f"register {label}",
        )

    # --- stake the validator so it can earn a permit ------------------------------
    staked = False
    try:
        submit_raw(
            client,
            bt.calls.SubtensorModule.add_stake(
                hotkey=validator_key.ss58_address,
                netuid=args.netuid,
                amount_staked=int(VALIDATOR_STAKE_TAO * 1e9),
            ),
            validator_key,
            "stake validator",
        )
        staked = True
    except Exception as exc:
        # A fresh localnet subnet has its subtoken disabled until the owner issues
        # start_call, so staking (and therefore the validator permit) may be
        # unavailable. Not fatal: the run continues and reports what the chain allowed.
        logger.warning("validator could not be staked: %s", exc)

    # --- publish miner endpoints on chain (ServeAxon) -----------------------------
    announce = args.announce_ip or lan_ip()
    ports = {key.ss58_address: free_port() for key in miner_keys}
    for index, key in enumerate(miner_keys):
        execute(
            client,
            bt.ServeAxon(netuid=args.netuid, ip=announce, port=ports[key.ss58_address]),
            key,
            f"serve axon miner{index} on {announce}:{ports[key.ss58_address]}",
        )

    # --- start the real miner HTTP servers ----------------------------------------
    span = 400 + args.rounds * (HORIZON // INTERVAL) + (HORIZON // INTERVAL) + 10
    base = 1_700_000_000 - (1_700_000_000 % INTERVAL)
    provider = SyntheticProvider(build_candles(base, synthetic_closes(span)))
    first_task_at = base + 400 * INTERVAL

    servers: list[tuple[uvicorn.Server, threading.Thread]] = []
    for engine, key in zip(engines, miner_keys, strict=True):
        app = create_app(
            ForecastService(
                engine=engine,
                provider=provider,
                candle_interval_seconds=INTERVAL,
                lookback_candles=400,
            ),
            verifier=make_verifier(key.ss58_address),
        )
        config = uvicorn.Config(
            # Bound on all interfaces so the miner is reachable at the address it
            # published on chain, which cannot be loopback.
            app,
            host="0.0.0.0",
            port=ports[key.ss58_address],
            log_level="warning",
        )
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True, name=f"miner-{engine.name}")
        thread.start()
        deadline = time.monotonic() + 15.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not server.started:
            raise RuntimeError(f"miner {engine.name} failed to start")
        servers.append((server, thread))
    logger.info("%d miner neurons serving over HTTP", len(servers))

    # --- wait for the validator permit --------------------------------------------
    permit = False
    start_block = client.block
    while staked and client.block - start_block < args.permit_wait_blocks:
        graph = client.subnets.metagraph(args.netuid, commitments=False)
        me = graph.by_hotkey(validator_key.ss58_address) if graph else None
        if me is not None and me.validator_permit:
            permit = True
            break
        time.sleep(2.0)
    logger.info(
        "validator permit after %d blocks: %s",
        client.block - start_block,
        "yes" if permit else "no",
    )

    # --- run the validator against the real chain ---------------------------------
    now = float(first_task_at)

    def clock() -> float:
        return now

    from vanta.neurons import chain as chain_module

    chain = chain_module.connect(args.network, validator_key)
    resolution = ResolutionEngine(provider, candle_interval_seconds=INTERVAL)
    store = SqliteValidatorStore(":memory:")
    registry = MinerRegistry()
    validator = Validator(
        config=ValidatorConfig(
            netuid=args.netuid,
            asset="ETH-USD",
            horizon_seconds=HORIZON,
            task_interval_seconds=HORIZON,
            weight_interval_seconds=1,
            self_hotkey=validator_key.ss58_address,
        ),
        generator=TaskGenerator(
            resolution=resolution,
            asset="ETH-USD",
            horizon_seconds=HORIZON,
            submission_window_seconds=WINDOW,
            clock=clock,
        ),
        collector=ForecastCollector(
            HttpxTransport(clock=clock),
            signer=make_signer(validator_key),
            timeout_seconds=10.0,
            clock=clock,
        ),
        resolution=resolution,
        registry=registry,
        store=store,
        view=chain,
        submitter=chain,
        clock=clock,
    )

    issued = resolved = scored = 0
    queried_total = 0
    try:
        for _ in range(args.rounds):
            neurons = validator.sync()
            miners = validator.miners(neurons)
            queried_total = max(queried_total, len(miners))
            task, rejected = validator.issue_task(miners)
            if task is not None:
                issued += 1
            if rejected:
                logger.warning("rejections: %s", rejected)
            now += HORIZON + 1
            for outcome in validator.resolve_due():
                resolved += 1
                scored += outcome.scored
    finally:
        for server, thread in servers:
            server.should_exit = True
            thread.join(timeout=10)

    # --- the real weight submission ------------------------------------------------
    neurons = validator.sync()
    submission = registry.submission(neurons)
    weight_result: object = None
    weight_error: str | None = None
    if submission:
        try:
            weight_result = chain.set_weights(args.netuid, submission.weights)
        except ChainError as exc:
            weight_error = str(exc)
            logger.error("on-chain weight submission failed: %s", exc)

    # --- read the result back from chain -------------------------------------------
    on_chain: object = None
    submission_path = "unknown"
    if weight_result is not None:
        try:
            uid = client.neurons.uid(validator_key.ss58_address, args.netuid)
            plaintext = client.query(bt.storage.SubtensorModule.Weights, [args.netuid, uid])
            if client.subnets.commit_reveal_enabled(args.netuid):
                # The subnet runs commit-reveal, so SetWeights took the timelocked path.
                # The plaintext Weights map stays empty until the chain auto-reveals at
                # the drand round, so an empty map here is expected rather than a
                # failure: the TimelockedWeightsCommitted event is the evidence.
                submission_path = "timelocked commit (chain auto-reveals)"
                on_chain = (
                    f"plaintext Weights[uid {uid}] = {plaintext or 'empty'} "
                    "(expected before the reveal round)"
                )
            else:
                submission_path = "plaintext set_weights"
                on_chain = f"Weights[uid {uid}] = {plaintext}"
        except Exception as exc:  # read-back is corroboration, not the proof itself
            logger.warning("could not read weights back: %s", exc)

    store.close()

    print()
    print("VANTA - LOCALNET END-TO-END PROOF")
    print("=" * 78)
    print(f"chain endpoint            {client.endpoint}")
    print(f"announced axon ip         {announce}")
    print(f"netuid                    {args.netuid}")
    print(f"registered neurons        {len(neurons)}")
    print(f"miners queried over HTTP  {queried_total}")
    print(f"validator staked          {staked}")
    print(f"validator permit          {permit}")
    print(f"tasks issued              {issued}")
    print(f"tasks resolved            {resolved}")
    print(f"forecast scorings         {scored}")
    print(f"weight vector             {submission.weights if submission else '{}'}")
    if weight_result is not None:
        print(f"set_weights path          {submission_path}")
        print(f"set_weights result        {weight_result}")
    else:
        print(f"set_weights               FAILED: {weight_error}")
    print(f"weights read back         {on_chain}")
    print()

    ok = bool(issued and resolved and scored and weight_result)
    print("RESULT:", "PASS" if ok else "INCOMPLETE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
