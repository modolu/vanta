"""Show the current on-chain state of a Vanta subnet.

    python scripts/network_state.py --network test --netuid 1
    python scripts/network_state.py --network local --netuid 1 --json

Read-only. Prints the metagraph as Vanta sees it — who is registered, which endpoints
are published, who holds a validator permit — plus the subnet's weight-setting
constraints. Use it to verify a deployment or to capture submission evidence.
"""

from __future__ import annotations

import argparse
import json
import sys

from vanta.log import configure_logging, get_logger
from vanta.neurons import chain as chain_module

logger = get_logger("scripts.network_state")


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a Vanta subnet on chain")
    parser.add_argument("--network", default="test")
    parser.add_argument("--netuid", type=int, default=1)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    configure_logging(args.log_level)

    try:
        import bittensor as bt
    except ImportError:
        print("the Bittensor SDK is not installed; run: pip install -e '.[chain]'")
        return 1

    try:
        client = bt.Subtensor(args.network)
        graph = client.subnets.metagraph(args.netuid, commitments=False)
    except Exception as exc:
        print(f"could not read {args.network} netuid {args.netuid}: {exc}")
        return 1

    if graph is None:
        print(f"netuid {args.netuid} does not exist on {args.network}")
        return 1

    # Reuse the neurons' own projection so this shows exactly what the validator sees.
    neurons = [
        chain_module.NeuronRecord(
            uid=int(n.uid),
            hotkey=str(n.hotkey),
            axon=n.axon,
            validator_permit=bool(n.validator_permit),
            stake=chain_module.balance_amount(n.total_stake),
        )
        for n in graph.neurons
    ]
    served = [n for n in neurons if n.is_servable]

    payload = {
        "network": args.network,
        "endpoint": client.endpoint,
        "netuid": args.netuid,
        "block": graph.block,
        "tempo": graph.tempo,
        "neurons": len(neurons),
        "serving_endpoints": len(served),
        "commit_reveal": client.subnets.commit_reveal_enabled(args.netuid),
        "weights_rate_limit_blocks": client.hyperparameters.weights_rate_limit(args.netuid),
        "min_allowed_weights": client.hyperparameters.min_allowed_weights(args.netuid),
        "registry": [
            {
                "uid": n.uid,
                "hotkey": n.hotkey,
                "axon": n.axon,
                "validator_permit": n.validator_permit,
                "stake": n.stake,
            }
            for n in neurons
        ],
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return 0

    print(f"VANTA NETWORK STATE - {args.network} netuid {args.netuid}")
    print("=" * 78)
    print(f"endpoint            {payload['endpoint']}")
    print(f"block               {payload['block']}")
    print(f"tempo               {payload['tempo']}")
    print(f"neurons             {payload['neurons']}")
    print(f"serving endpoints   {payload['serving_endpoints']}")
    print(f"commit-reveal       {payload['commit_reveal']}")
    print(f"weights rate limit  {payload['weights_rate_limit_blocks']} blocks")
    print(f"min allowed weights {payload['min_allowed_weights']}")
    print()
    print(f"{'UID':>5}  {'AXON':<24} {'PERMIT':<7} {'STAKE':>14}  HOTKEY")
    print("-" * 78)
    for neuron in neurons:
        if not neuron.is_servable and not neuron.validator_permit:
            continue  # keep the table to the participants that matter
        print(
            f"{neuron.uid:>5}  {neuron.axon or '-':<24} "
            f"{'yes' if neuron.validator_permit else 'no':<7} {neuron.stake:>14.6f}  "
            f"{neuron.hotkey}"
        )
    print("-" * 78)
    print(f"{len(served)} of {len(neurons)} neurons publish an endpoint a validator can query")
    return 0


if __name__ == "__main__":
    sys.exit(main())
