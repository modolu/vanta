"""Register the Vanta topology on a Bittensor test subnet and publish miner endpoints.

    python scripts/testnet_register.py --netuid 1 --miners 4 --announce-ip <public ip>

One-time setup. It registers the validator hotkey and each miner hotkey on the subnet
(paying the registration burn from the wallet's coldkey) and publishes each miner's
ip:port on chain with the ServeAxon intent. Afterwards, run the neurons with
scripts/run_miner.py and scripts/run_validator.py.

Run scripts/testnet_preflight.py first: it reports what this will cost and what is
missing, and spends nothing.

Keys come from the standard Bittensor wallet directory. Nothing is read from this
repository, no mnemonic or private key is ever printed, and the coldkey is unlocked only
by btcli/SDK prompts. ``--dry-run`` previews every extrinsic without submitting.

This script refuses to run against mainnet.
"""

from __future__ import annotations

import argparse
import sys

from vanta.log import configure_logging, get_logger
from vanta.neurons import chain as chain_module
from vanta.neurons.chain import ChainError

logger = get_logger("scripts.testnet_register")

# Registering on mainnet burns real TAO. Vanta is a hackathon MVP; this is a hard stop.
FORBIDDEN_NETWORKS = {"finney", "archive"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Register Vanta neurons on a test subnet")
    parser.add_argument("--network", default="test")
    parser.add_argument("--netuid", type=int, required=True)
    parser.add_argument("--miners", type=int, default=4)
    parser.add_argument("--wallet-name", default="vanta")
    parser.add_argument("--validator-hotkey", default="validator")
    parser.add_argument(
        "--miner-hotkey-prefix",
        default="miner",
        help="hotkey names are <prefix>0 .. <prefix>N-1",
    )
    parser.add_argument(
        "--announce-ip",
        default=None,
        help="public IP validators will reach the miners on; the chain rejects loopback",
    )
    parser.add_argument("--base-port", type=int, default=8091)
    parser.add_argument("--skip-serve", action="store_true", help="register only")
    parser.add_argument("--dry-run", action="store_true", help="preview without submitting")
    parser.add_argument("--log-level", default="INFO")
    args = parser.parse_args()

    configure_logging(args.log_level)

    if args.network in FORBIDDEN_NETWORKS:
        print(f"refusing to run against {args.network!r}: this script is for test networks only")
        return 1

    try:
        import bittensor as bt
    except ImportError:
        print("the Bittensor SDK is not installed; run: pip install -e '.[chain]'")
        return 1

    if not args.skip_serve and not args.announce_ip:
        print(
            "--announce-ip is required to publish miner endpoints (the chain rejects "
            "loopback addresses). Pass --skip-serve to register without serving."
        )
        return 1

    client = bt.Subtensor(args.network)
    logger.info("connected to %s at block %d", client.endpoint, client.block)

    names = [(args.validator_hotkey, "validator")] + [
        (f"{args.miner_hotkey_prefix}{index}", f"miner{index}") for index in range(args.miners)
    ]

    wallets = {}
    try:
        for hotkey_name, label in names:
            wallet = chain_module.load_wallet(args.wallet_name, hotkey_name)
            # Touch the hotkey now so a missing keyfile fails here, with a clear
            # message, rather than mid-way through a sequence of paid extrinsics.
            chain_module.hotkey_address(wallet)
            wallets[label] = wallet
    except ChainError as exc:
        print(f"wallet problem: {exc}")
        print()
        print("Run the readiness check for the exact commands to create the wallet:")
        print(
            f"  python scripts/testnet_preflight.py --network {args.network} "
            f"--netuid {args.netuid} --miners {args.miners} --wallet-name {args.wallet_name}"
        )
        return 1

    graph = client.subnets.metagraph(args.netuid, commitments=False)
    if graph is None:
        print(f"netuid {args.netuid} does not exist on {args.network}")
        return 1
    registered = {neuron.hotkey for neuron in graph.neurons}

    burn = client.subnets.burn(args.netuid)
    logger.info("registration burn on netuid %d: %s per hotkey", args.netuid, burn)

    # --- register -------------------------------------------------------------------
    for _hotkey_name, label in names:
        wallet = wallets[label]
        address = chain_module.hotkey_address(wallet)
        if address in registered:
            logger.info("%s (%s) already registered, skipping", label, address)
            continue
        intent = bt.BurnedRegister(netuid=args.netuid, hotkey_ss58=address)
        if args.dry_run:
            plan = client.plan(intent, wallet)
            logger.info("[dry-run] register %s (%s): %s", label, address, plan)
            continue
        # execute() reports rejection through result.success rather than raising.
        result = client.execute(intent, wallet).raise_for_failure()
        logger.info(
            "registered %s (%s): block=%s extrinsic=%s",
            label,
            address,
            result.block_hash,
            result.extrinsic_id,
        )

    if args.skip_serve:
        return 0

    # --- publish endpoints ------------------------------------------------------------
    for index in range(args.miners):
        label = f"miner{index}"
        wallet = wallets[label]
        port = args.base_port + index
        intent = bt.ServeAxon(netuid=args.netuid, ip=args.announce_ip, port=port)
        if args.dry_run:
            plan = client.plan(intent, wallet)
            logger.info("[dry-run] serve %s at %s:%d: %s", label, args.announce_ip, port, plan)
            continue
        result = client.execute(intent, wallet).raise_for_failure()
        logger.info(
            "published %s at %s:%d: block=%s extrinsic=%s",
            label,
            args.announce_ip,
            port,
            result.block_hash,
            result.extrinsic_id,
        )

    if args.dry_run:
        print("\ndry run complete; nothing was submitted")
        return 0

    # --- verify ------------------------------------------------------------------------
    graph = client.subnets.metagraph(args.netuid, commitments=False)
    print()
    print("REGISTERED TOPOLOGY")
    print("=" * 78)
    for _hotkey_name, label in names:
        address = chain_module.hotkey_address(wallets[label])
        neuron = graph.by_hotkey(address) if graph else None
        if neuron is None:
            print(f"{label:<10} NOT FOUND {address}")
        else:
            print(f"{label:<10} uid={neuron.uid:<4} axon={neuron.axon or '-':<22} {neuron.hotkey}")
    print()
    print("Next:")
    for index in range(args.miners):
        print(
            f"  python scripts/run_miner.py --network {args.network} --netuid {args.netuid} "
            f"--wallet-name {args.wallet_name} --wallet-hotkey {args.miner_hotkey_prefix}{index} "
            f"--port {args.base_port + index} --announce-ip {args.announce_ip}"
        )
    print(
        f"  python scripts/run_validator.py --network {args.network} --netuid {args.netuid} "
        f"--wallet-name {args.wallet_name} --wallet-hotkey {args.validator_hotkey}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
