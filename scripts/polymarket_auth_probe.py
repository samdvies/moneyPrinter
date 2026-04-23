"""W0 probe: Polymarket API-key derivation from a throwaway Polygon wallet.

Generates a fresh Polygon EOA, signs the EIP-712 L1 auth payload, and calls
``POST /auth/api-key`` against ``clob.polymarket.com`` to derive L2 API
credentials. This proves whether the auth handshake is reachable from the
current egress IP. It does NOT place orders, does NOT fund the wallet, and
does NOT touch any service code under ``services/``.

Run with (NL VPN active recommended — the same reasoning as the read probe):

    uv run --with py-clob-client --with eth-account \
        python scripts/polymarket_auth_probe.py

On success the fresh private key, address, and API creds are written to
``artifacts/polymarket_wallet.json`` (gitignored) so the wallet can be
reused or funded later. On failure the script prints the error and exits 1.

An optional --save-key flag controls whether the private key is written to
disk; default is to write so the wallet is recoverable.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import traceback
from pathlib import Path

import httpx
from eth_account import Account
from py_clob_client.client import ClobClient
from py_clob_client.constants import POLYGON

HOST = "https://clob.polymarket.com"
ARTIFACT_PATH = Path("artifacts/polymarket_wallet.json")


def egress_guard() -> tuple[str, str]:
    resp = httpx.get("https://ipinfo.io/json", timeout=10.0)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("ip", "?"), payload.get("country", "?")


def main() -> int:
    parser = argparse.ArgumentParser(description="Polymarket W0 auth probe")
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Do not write the wallet to artifacts/ (key is ephemeral).",
    )
    args = parser.parse_args()

    ip, country = egress_guard()
    print(f"egress: {ip} ({country})")
    if country in {"GB", "US"}:
        print(f"refusing to proceed from {country}: VPN not active")
        return 2

    acct = Account.create()
    pk_hex = acct.key.hex()
    if not pk_hex.startswith("0x"):
        pk_hex = "0x" + pk_hex
    address = acct.address

    print(f"fresh EOA: {address}")
    print(f"host:      {HOST}")
    print("attempting EIP-712 L1 sign -> POST /auth/api-key ...")

    t0 = time.perf_counter()
    try:
        client = ClobClient(HOST, key=pk_hex, chain_id=POLYGON)
        creds = client.create_or_derive_api_creds()
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        print(f"AUTH FAILED in {elapsed_ms} ms")
        print(f"  type:  {type(exc).__name__}")
        print(f"  error: {exc}")
        print()
        traceback.print_exc()
        return 1

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    print(f"AUTH OK in {elapsed_ms} ms")
    print(f"  api_key fingerprint: {creds.api_key[:8]}...{creds.api_key[-4:]}")
    print(f"  api_secret length:   {len(creds.api_secret)}")
    print(f"  passphrase length:   {len(creds.api_passphrase)}")

    if not args.no_save:
        ARTIFACT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ARTIFACT_PATH.write_text(
            json.dumps(
                {
                    "address": address,
                    "private_key": pk_hex,
                    "chain_id": POLYGON,
                    "host": HOST,
                    "api_key": creds.api_key,
                    "api_secret": creds.api_secret,
                    "passphrase": creds.api_passphrase,
                    "egress_ip": ip,
                    "egress_country": country,
                    "created_unix": int(time.time()),
                },
                indent=2,
            )
        )
        print(f"wrote {ARTIFACT_PATH} (gitignored)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
