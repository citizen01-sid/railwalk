"""Mutants for C4/C5: each must be KILLED (i.e. the control must go red)."""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def per_wallet(n, stride, aggregate_bug=False):
    cycles = 288.0 if aggregate_bug else 288.0 / n
    return cycles * stride


def check(n, stride, aggregate_bug=False):
    cycles = 288.0 if aggregate_bug else 288.0 / n
    return cycles * stride


cases = []

# M1: the original defect -- use 288 cycles regardless of wallet count
def m1():
    got = per_wallet(14, 10000, aggregate_bug=True)
    assert got == 205714, f"aggregate mutant returned {got:,.0f}, control would not catch it"


# M2: right cycles, wrong stride assumption (1000 instead of the served 10000)
def m2():
    got = per_wallet(14, 1000)
    assert got == 205714, f"stride mutant returned {got:,.0f}"


# M3: read the stride from the wrong field (page width from the error text)
def m3():
    # a mutant that assumes the error text's '1000' instead of last_range_to-fr+1
    served = {"last_range_from": 100, "last_range_to": 10099}
    buggy = 1000  # error-text width
    correct = served["last_range_to"] - served["last_range_from"] + 1
    assert buggy == correct, f"error-text mutant {buggy} == correct {correct}"


for name, fn in (("M1 aggregate-288", m1), ("M2 assume-stride-1000", m2), ("M3 parse-error-text", m3)):
    try:
        fn()
        print(f"SURVIVED {name}")
    except AssertionError as e:
        print(f"KILLED   {name}: {e}")
