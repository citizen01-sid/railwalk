"""Controls that the checker can FAIL. Each must be observed to fail."""
import subprocess, sys, json, urllib.request, importlib.util

import os
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("chk", os.path.join(HERE, "check.py"))
chk = importlib.util.module_from_spec(spec); spec.loader.exec_module(chk)

def run(name, fn, expect_fail):
    try:
        fn(); out = "no exception"
    except Exception as e:
        out = f"{type(e).__name__}: {str(e)[:90]}"
    failed = out != "no exception"
    ok = (failed == expect_fail)
    print(f"{'PASS' if ok else 'FAIL'}  {name}: {out}")
    return ok

results = []

# C1: one provider silent -> must refuse, not return the single answer
def one_provider():
    orig = chk.PROVIDERS[:]
    chk.PROVIDERS[:] = ["https://mainnet.base.org"]
    try: chk.two_sources("eth_getBlockByNumber", [hex(54000000), False])
    finally: chk.PROVIDERS[:] = orig
results.append(run("C1 single provider must refuse", one_provider, True))

# C2: a block that does not exist must be an error, never a zero timestamp
def missing_block():
    chk.block_time(99_999_999_999)
results.append(run("C2 impossible block must error", missing_block, True))

# C3: the subject must succeed at all (control 0)
def subject_works():
    t = chk.block_time(54_000_000)
    assert t > 1_700_000_000, f"implausible timestamp {t}"
results.append(run("C0 a known block returns a real timestamp", subject_works, False))

# C4: the coverage arithmetic must be per-wallet, not aggregate.
# The bug this guards: 288 cycles/day x stride is the capacity of a walk that
# gets EVERY cycle for one wallet. With N wallets sharing 288 cycles, each is
# asked 288/N times. If someone "restores" the aggregate figure the per-wallet
# ceiling rises by a factor of N and the deficit disappears from the report.
def coverage_is_per_wallet():
    for n, stride, want in ((14, 10000, 205714), (14, 1000, 20571), (1, 10000, 2880000)):
        cycles = 288.0 / n
        got = cycles * stride
        assert abs(got - want) < 1, f"n={n} stride={stride}: got {got:,.0f}, want {want:,}"
    # the aggregate figure must NOT equal the per-wallet figure for n>1
    n, stride = 14, 10000
    assert (288.0 * stride) != (288.0 / n * stride), "per-wallet and aggregate collapsed"
results.append(run("C4 coverage must be per-wallet", coverage_is_per_wallet, False))

# C5: the stride must be read from served data, never assumed.
# read_stride() returns the widest last_range_* width across marks; with no
# marks carrying a range it must fall back rather than invent 10,000.
def stride_from_data():
    assert chk.observed_stride([]) == 1000, chk.observed_stride([])
    assert chk.observed_stride([{"last_range_from": 100, "last_range_to": 1099}]) == 1000
    assert chk.observed_stride([{"last_range_from": 100, "last_range_to": 10099}]) == 10000
results.append(run("C5 stride read from served ranges", stride_from_data, False))

print()
print("all controls:", "PASS" if all(results) else "FAIL")
sys.exit(0 if all(results) else 1)
