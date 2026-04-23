"""W1 probe: Polymarket order submission from an unfunded throwaway wallet.

Re-uses the wallet + API credentials saved by ``polymarket_auth_probe.py``
and submits one signed BUY order that cannot fill:

- far below market (price 0.01 on a token quoted ~0.53)
- minimum size (5 shares = $0.05 notional)
- wallet has zero USDC and no token allowances

The goal is to find out which validation layer Polymarket's server rejects
first. The error we want to distinguish between:

- ``GEOBLOCKED`` / HTTP 403 / "forbidden" -> trading blocked at IP level
  even with VPN; read-only is the ceiling for a UK operator.
- ``INSUFFICIENT_BALANCE`` / "not enough balance" -> trading path is open;
  full unlock needs USDC on Polygon (explicit user approval required
  before that step).
- Anything else -> document and reassess.

Run with NL VPN active:

    uv run --with py-clob-client --with eth-account --with httpx \
        python scripts/polymarket_order_probe.py

Saves the raw response / exception to
``artifacts/polymarket_order_probe.json`` (gitignored).
"""

from __future__ import annotations

import json
import sys
import time
import traceback
from pathlib import Path

import httpx
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType

WALLET_PATH = Path("artifacts/polymarket_wallet.json")
RESULT_PATH = Path("artifacts/polymarket_order_probe.json")

RUSSIA_UKRAINE_YES_TOKEN = (
    "8501497159083948713316135768103773293754490207922884688769443031624417212426"
)
FAR_BELOW_MARKET_PRICE = 0.01
MIN_SIZE_SHARES = 5.0
SIDE = "BUY"


def egress_guard() -> tuple[str, str]:
    resp = httpx.get("https://ipinfo.io/json", timeout=10.0)
    resp.raise_for_status()
    payload = resp.json()
    return payload.get("ip", "?"), payload.get("country", "?")


def main() -> int:
    ip, country = egress_guard()
    print(f"egress: {ip} ({country})")
    if country in {"GB", "US"}:
        print(f"refusing to proceed from {country}: VPN not active")
        return 2

    if not WALLET_PATH.exists():
        print(f"missing {WALLET_PATH}: run polymarket_auth_probe.py first")
        return 2
    wallet = json.loads(WALLET_PATH.read_text())
    print(f"wallet: {wallet['address']}")

    client = ClobClient(
        host=wallet["host"],
        key=wallet["private_key"],
        chain_id=wallet["chain_id"],
        creds=ApiCreds(
            api_key=wallet["api_key"],
            api_secret=wallet["api_secret"],
            api_passphrase=wallet["passphrase"],
        ),
    )

    order_args = OrderArgs(
        price=FAR_BELOW_MARKET_PRICE,
        size=MIN_SIZE_SHARES,
        side=SIDE,
        token_id=RUSSIA_UKRAINE_YES_TOKEN,
    )
    print(
        f"order: {SIDE} {MIN_SIZE_SHARES} @ {FAR_BELOW_MARKET_PRICE} "
        f"on token {RUSSIA_UKRAINE_YES_TOKEN[:10]}...{RUSSIA_UKRAINE_YES_TOKEN[-6:]}"
    )

    result: dict[str, object] = {
        "egress_ip": ip,
        "egress_country": country,
        "wallet_address": wallet["address"],
        "order": {
            "side": SIDE,
            "price": FAR_BELOW_MARKET_PRICE,
            "size": MIN_SIZE_SHARES,
            "token_id": RUSSIA_UKRAINE_YES_TOKEN,
        },
        "ts_unix": int(time.time()),
    }

    t0 = time.perf_counter()
    try:
        signed = client.create_order(order_args)
        result["sign_ok"] = True
        print("signed ok, posting ...")
        resp = client.post_order(signed, OrderType.GTC)
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        print(f"POST /order returned in {elapsed_ms} ms")
        print(json.dumps(resp, indent=2, default=str))
        result["elapsed_ms"] = elapsed_ms
        result["response"] = resp
        result["outcome"] = "server_accepted_or_rejected_with_payload"
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        print(f"EXCEPTION after {elapsed_ms} ms")
        print(f"  type:  {type(exc).__name__}")
        print(f"  error: {exc}")
        print()
        tb = traceback.format_exc()
        print(tb)
        result["elapsed_ms"] = elapsed_ms
        result["exception_type"] = type(exc).__name__
        result["exception_message"] = str(exc)
        result["traceback"] = tb
        result["outcome"] = "client_or_server_exception"
        RESULT_PATH.write_text(json.dumps(result, indent=2, default=str))
        print(f"wrote {RESULT_PATH}")
        return 1

    RESULT_PATH.write_text(json.dumps(result, indent=2, default=str))
    print(f"wrote {RESULT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
