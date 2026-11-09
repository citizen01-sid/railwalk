#!/usr/bin/env python3
"""railwalk - measure whether the 1F916 rail's chain observer is current.

Keyless. Read-only. Two independent sources: the registry's own /api/rail
(observer marks) and Base JSON-RPC (block timestamps, finalized head).

The question this answers is narrow and checkable by a stranger:

    When GET /api/rail serves `observed_payments: 0` for a listing,
    as of what moment is that zero true?

The registry answers part of it in its own walk_note: a count of zero is
meaningful only once the funder wallet's last_block is past the block the
listing was posted at. That is a rule, not an observation. This tool turns
it into a number.

Usage:
    python3 check.py                # full report
    python3 check.py --json         # machine-readable

Exit codes:
    0  observer current (lag <= --max-lag-seconds)
    1  observer stale (lag > --max-lag-seconds)
    2  could not measure (a control failed) - never reported as 0
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import urllib.error
import urllib.request

RAIL = "https://1f916.ai/api/rail"
PROVIDERS = [
    "https://mainnet.base.org",
    "https://base-rpc.publicnode.com",
]
UA = {"User-Agent": "railwalk/1.0 (+https://1f916.ai)"}
TIMEOUT = 30


def get_json(url: str):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.load(r)


def rpc(url: str, method: str, params: list):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(
        url, data=body, headers={**UA, "content-type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None
    if "error" in payload:
        raise RuntimeError(str(payload["error"])[:120])
    return payload.get("result")


def two_sources(method: str, params: list):
    """Return the value only when two providers return it identically.

    Control 0 lives here: if fewer than two providers answer, we raise rather
    than returning the one answer. A single voice is not a measurement of a
    thing two voices had to agree on.
    """
    answers = {}
    for url in PROVIDERS:
        try:
            answers[url] = rpc(url, method, params)
        except Exception as e:  # noqa: BLE001 - any failure is a non-answer
            answers[url] = f"ERR {e}"
    vals = [v for v in answers.values() if not (isinstance(v, str) and v.startswith("ERR "))]
    if len(vals) < 2:
        raise RuntimeError(f"only {len(vals)} of {len(PROVIDERS)} providers answered {method}")
    if not all(v == vals[0] for v in vals):
        raise RuntimeError(f"providers disagree on {method}")
    return vals[0]



def observed_stride(rows) -> int:
    """The widest block range actually served in last_range_*.

    The stride is a fact the registry publishes about itself (only written on
    the success path), so it is READ, never assumed. Falls back to 1,000 -- the
    unkeyed OBSERVER_BLOCKS_PER_CYCLE -- when no mark carries a range yet.
    """
    widest = 0
    for r in rows:
        fr, to = r.get("last_range_from"), r.get("last_range_to")
        if fr is not None and to is not None and to >= fr:
            widest = max(widest, to - fr + 1)
    return widest if widest > 0 else 1000


def block_time(number: int) -> int:
    block = two_sources("eth_getBlockByNumber", [hex(number), False])
    if not isinstance(block, dict) or "timestamp" not in block:
        raise RuntimeError(f"no block {number}")
    return int(block["timestamp"], 16)


def finalized_block() -> tuple[int, int]:
    """The finalized head, agreed on a FIXED block rather than on the head.

    Two providers do not publish the same 'finalized' number at the same
    instant - the head moves at 0.2 s per block and their views are a few
    seconds apart. Comparing their head numbers makes ordinary skew look like
    disagreement. So: take the lower of the two advertised finalized numbers,
    then require BOTH providers to serve the identical hash at that fixed
    block. A block below both finalized heads cannot be reorganised, and
    identical hashes at a fixed height is agreement about a fact.
    """
    heads = {}
    for url in PROVIDERS:
        try:
            b = rpc(url, "eth_getBlockByNumber", ["finalized", False])
            heads[url] = int(b["number"], 16)
        except Exception as e:  # noqa: BLE001
            heads[url] = f"ERR {e}"
    nums = [v for v in heads.values() if isinstance(v, int)]
    if len(nums) < 2:
        raise RuntimeError(f"only {len(nums)} of {len(PROVIDERS)} providers answered finalized head")
    num = min(nums)
    block = two_sources("eth_getBlockByNumber", [hex(num), False])
    if not isinstance(block, dict) or "timestamp" not in block:
        raise RuntimeError(f"no block {num}")
    return num, int(block["timestamp"], 16)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lag-seconds", type=int, default=3600)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rail = get_json(RAIL)
    marks = rail["observer"]["marks"]
    now_rail = rail["now"] / 1000

    fin_num, fin_ts = finalized_block()

    rows = []
    for m in marks:
        lb = m["last_block"]
        ts = block_time(lb)
        rows.append(
            {
                "funder": m["funder_address"],
                "last_block": lb,
                "mark_time": ts,
                "lag_seconds": fin_ts - ts,
                "blocks_behind": fin_num - lb,
                "rows_last_cycle": m.get("last_range_rows"),
                "updated_age_seconds": round(now_rail - m["updated_at"] / 1000),
                "error": m.get("last_error"),
                "last_range_from": m.get("last_range_from"),
                "last_range_to": m.get("last_range_to"),
            }
        )
    rows.sort(key=lambda r: r["lag_seconds"])

    lags = [r["lag_seconds"] for r in rows]
    advanced = [r for r in rows if (r["rows_last_cycle"] or 0) > 0]
    stale = max(lags) > args.max_lag_seconds

    if args.json:
        print(
            json.dumps(
                {
                    "rail_now": now_rail,
                    "finalized_block": fin_num,
                    "finalized_time": fin_ts,
                    "wallets": len(rows),
                    "lag_seconds_min": min(lags),
                    "lag_seconds_max": max(lags),
                    "written_last_cycle": len(advanced),
                    "stale": stale,
                    "rows": rows,
                },
                indent=2,
            )
        )
        return 1 if stale else 0

    print(f"registry now      {dt.datetime.fromtimestamp(now_rail, dt.UTC):%Y-%m-%d %H:%M:%SZ}")
    print(f"Base finalized    block {fin_num:,}  {dt.datetime.fromtimestamp(fin_ts, dt.UTC):%Y-%m-%d %H:%M:%SZ}")
    print()
    print(f"{'funder wallet':44}{'mark block':>12}{'mark time':>18}{'behind':>10}{'days':>7}")
    for r in rows:
        mt = dt.datetime.fromtimestamp(r["mark_time"], dt.UTC).strftime("%Y-%m-%d %H:%M")
        print(
            f"{r['funder']:44}{r['last_block']:>12,}{mt:>18}"
            f"{r['blocks_behind']:>10,}{r['lag_seconds'] / 86400:>7.1f}"
        )
    print()
    print(f"wallets: {len(rows)}   lag: {min(lags) / 86400:.1f}-{max(lags) / 86400:.1f} days")
    print(f"rows written in each wallet's last cycle: {len(advanced)} of {len(rows)}")
    print()
    # Per-wallet coverage, which is the quantity that decides whether the lag
    # can shrink. The cron runs every 5 minutes and walks ONE wallet per cycle
    # (observer.ts nextWallet: ORDER BY COALESCE(m.updated_at,0) ASC LIMIT 1),
    # so each wallet is asked 288/len(rows) times a day, NOT 288 times. Stating
    # 288 x stride as "the walk's capacity" is the aggregate of a walk that gets
    # every cycle for one wallet; it overstates each wallet by the wallet count.
    n = len(rows)
    per_wallet_cycles = 288.0 / n
    stride = observed_stride(rows)
    prod = 432_000  # blocks/day at the 0.2 s cadence measured 2026-11-05
    ceiling = per_wallet_cycles * stride
    print(f"rotation: {n} wallets, one per 5-min cycle -> {per_wallet_cycles:.2f} cycles/wallet/day")
    print(f"widest range actually walked: {stride:,} blocks (read from last_range_*, not assumed)")
    print(f"per-wallet ceiling at that stride: {ceiling:,.0f} blk/day = {ceiling / prod * 100:.1f}% of production")
    if ceiling < prod:
        print(f"=> even with every cycle agreeing, each wallet's lag grows "
              f"{(1 - ceiling / prod) * 24:.1f} h/day")
    print()
    if stale:
        print(f"STALE: worst mark is {max(lags) / 3600:.1f} h behind the finalized head "
              f"(threshold {args.max_lag_seconds / 3600:.1f} h).")
        print("A count of 0 observed payments on a listing whose funder wallet is marked")
        print("before the listing's posting block is not evidence of non-payment.")
        return 1
    print("CURRENT: every mark is inside the threshold.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"COULD NOT MEASURE: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)
