"""Check whether this machine is ready to deploy Vanta on the Bittensor test network.

    python scripts/testnet_preflight.py [--netuid N] [--miners 4]

Read-only. It spends nothing, signs nothing, and creates nothing — it connects to the
public test network, reports what exists and what each remaining step costs, and prints
the exact commands still required. Safe to run before you hold any testnet TAO.

Run it again after funding to confirm the deployment can proceed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from vanta.log import configure_logging, get_logger

logger = get_logger("scripts.testnet_preflight")

WALLET_ROOT = Path.home() / ".bittensor" / "wallets"


def heading(text: str) -> None:
    print()
    print(text)
    print("-" * 78)


def main() -> int:
    parser = argparse.ArgumentParser(description="Vanta testnet readiness check")
    parser.add_argument("--network", default="test")
    parser.add_argument(
        "--netuid",
        type=int,
        default=None,
        help="existing subnet to deploy onto; omit to cost creating your own",
    )
    parser.add_argument("--miners", type=int, default=4)
    parser.add_argument("--wallet-name", default="vanta")
    parser.add_argument("--log-level", default="WARNING")
    args = parser.parse_args()

    configure_logging(args.log_level)

    try:
        import bittensor as bt
    except ImportError:
        print("the Bittensor SDK is not installed; run: pip install -e '.[chain]'")
        return 1

    print("VANTA - TESTNET PREFLIGHT")
    print("=" * 78)

    # --- 1. wallets ---------------------------------------------------------------
    heading("1. WALLETS")
    wallets: list[str] = []
    if WALLET_ROOT.is_dir():
        wallets = sorted(p.name for p in WALLET_ROOT.iterdir() if p.is_dir())
    print(f"wallet directory   {WALLET_ROOT}")
    print(f"wallets found      {wallets or 'NONE'}")

    coldkey_ss58: str | None = None
    hotkeys: list[str] = []
    if args.wallet_name in wallets:
        wallet_dir = WALLET_ROOT / args.wallet_name
        pub = wallet_dir / "coldkeypub.txt"
        if pub.is_file():
            try:
                import json

                coldkey_ss58 = json.loads(pub.read_text()).get("ss58Address")
            except Exception as exc:
                print(f"could not read coldkeypub: {exc}")
        hotkey_dir = wallet_dir / "hotkeys"
        if hotkey_dir.is_dir():
            # btcli writes each hotkey as <name> (encrypted) plus <name>pub.txt; only
            # the former is a hotkey.
            hotkeys = sorted(
                p.name
                for p in hotkey_dir.iterdir()
                if p.is_file() and not p.name.endswith("pub.txt")
            )
        print(f"coldkey            {coldkey_ss58 or 'unreadable'}")
        print(f"hotkeys            {hotkeys or 'NONE'}")
    else:
        print(f"wallet {args.wallet_name!r} does not exist yet")

    # --- 2. chain -----------------------------------------------------------------
    heading("2. NETWORK")
    try:
        client = bt.Subtensor(args.network)
        block = client.block
    except Exception as exc:
        print(f"CANNOT REACH {args.network}: {exc}")
        return 1
    print(f"network            {args.network}")
    print(f"endpoint           {client.endpoint}")
    print(f"block              {block}")
    print(f"block time         {client.block_time()}s")
    print(f"spec_version       {client.spec_version}")

    # --- 3. balance ---------------------------------------------------------------
    heading("3. BALANCE")
    balance_tao = 0.0
    if coldkey_ss58:
        try:
            balance = client.balances.balance(coldkey_ss58=coldkey_ss58)
            balance_tao = float(balance.amount)
            print(f"free balance       {balance}")
        except Exception as exc:
            print(f"could not read balance: {exc}")
    else:
        print("no coldkey to check")

    # --- 4. costs -----------------------------------------------------------------
    heading("4. COST OF DEPLOYMENT")
    neuron_count = 1 + args.miners  # one validator plus the miners
    subnet_lock = 0.0
    per_neuron = 0.0
    try:
        if args.netuid is None:
            subnet_lock = float(client.subnets.burn(0).amount)
            print(f"create own subnet  {subnet_lock:.6f} TAO (lock cost)")
            print("  (registration burn on a new subnet is read after it exists)")
        else:
            per_neuron = float(client.subnets.burn(args.netuid).amount)
            print(f"netuid {args.netuid} reg burn   {per_neuron:.6f} TAO per hotkey")
    except Exception as exc:
        print(f"could not read costs: {exc}")

    needed = subnet_lock + per_neuron * neuron_count
    # Extrinsic fees on testnet are negligible but non-zero; leave headroom.
    needed_with_headroom = needed * 1.5 + 0.05
    print(f"neurons to register {neuron_count} (1 validator + {args.miners} miners)")
    print(f"estimated need     ~{needed_with_headroom:.4f} TAO (incl. headroom)")

    # --- 5. subnet constraints ------------------------------------------------------
    if args.netuid is not None:
        heading(f"5. SUBNET {args.netuid} CONSTRAINTS")
        try:
            info = client.subnets.info(args.netuid)
            print(f"tempo              {info.tempo}")
            print(f"neurons            {info.neuron_count}")
            print(f"commit-reveal      {client.subnets.commit_reveal_enabled(args.netuid)}")
            rate_limit = client.hyperparameters.weights_rate_limit(args.netuid)
            print(f"weights rate limit {rate_limit} blocks")
            print(f"min allowed weights {client.hyperparameters.min_allowed_weights(args.netuid)}")
            graph = client.subnets.metagraph(args.netuid, commitments=False)
            if graph is not None:
                mine = [n for n in graph.neurons if n.hotkey in _hotkey_addresses(args, wallets)]
                print(f"our neurons        {len(mine)} registered")
                for neuron in mine:
                    print(
                        f"  uid {neuron.uid:<4} axon={neuron.axon} permit={neuron.validator_permit}"
                    )
        except Exception as exc:
            print(f"could not read subnet: {exc}")

    # --- 6. verdict -----------------------------------------------------------------
    heading("6. WHAT IS STILL REQUIRED")
    blockers: list[str] = []
    if not wallets or args.wallet_name not in wallets:
        blockers.append("wallet")
    if balance_tao < needed_with_headroom:
        blockers.append("funds")
    if len(hotkeys) < neuron_count:
        blockers.append("hotkeys")

    if not blockers:
        if args.netuid is None:
            print("READY. Create the subnet first, then register onto its netuid:")
            print(
                f"  btcli subnets create --network {args.network} "
                f"-w {args.wallet_name} -H validator"
            )
            print(
                f"  python scripts/testnet_register.py --network {args.network} "
                f"--netuid <new netuid> --miners {args.miners} --wallet-name {args.wallet_name}"
            )
        else:
            print("READY. Deploy with:")
            print(
                f"  python scripts/testnet_register.py --network {args.network} "
                f"--netuid {args.netuid} --miners {args.miners} --wallet-name {args.wallet_name}"
            )
        return 0

    step = 1
    if "wallet" in blockers:
        print(f"{step}. Create a coldkey (writes an encrypted key + mnemonic YOU must back up):")
        print(f"     btcli wallet new-coldkey --wallet {args.wallet_name}")
        step += 1
    if "hotkeys" in blockers:
        print(f"{step}. Create {neuron_count} hotkeys (validator + {args.miners} miners):")
        print(f"     btcli wallet new-hotkey --wallet {args.wallet_name} -H validator")
        for index in range(args.miners):
            print(f"     btcli wallet new-hotkey --wallet {args.wallet_name} -H miner{index}")
        step += 1
    if "funds" in blockers:
        print(f"{step}. Fund the coldkey with ~{needed_with_headroom:.4f} testnet TAO.")
        print("     There is NO faucet command: the `faucet` extrinsic is disabled on every")
        print("     real network (SDK error FaucetDisabled). Testnet TAO must come from")
        print("     the Bittensor Discord testnet faucet channel, or a transfer from an")
        print("     already-funded testnet coldkey:")
        print(f"       btcli wallet transfer --wallet <funded> --network {args.network} \\")
        print(
            f"           --dest {coldkey_ss58 or '<your coldkey ss58>'} --amount "
            f"{needed_with_headroom:.4f}"
        )
        step += 1

    print()
    print(f"BLOCKED ON: {', '.join(blockers)}")
    return 2


def _hotkey_addresses(args, wallets: list[str]) -> set[str]:
    """ss58 addresses of this wallet's hotkeys, read from their public files only."""
    addresses: set[str] = set()
    hotkey_dir = WALLET_ROOT / args.wallet_name / "hotkeys"
    if not hotkey_dir.is_dir():
        return addresses
    import json

    for path in hotkey_dir.iterdir():
        if not path.is_file():
            continue
        try:
            addresses.add(json.loads(path.read_text())["ss58Address"])
        except Exception:
            continue
    return addresses


if __name__ == "__main__":
    sys.exit(main())
