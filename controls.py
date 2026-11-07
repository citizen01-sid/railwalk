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

print()
print("all controls:", "PASS" if all(results) else "FAIL")
sys.exit(0 if all(results) else 1)
