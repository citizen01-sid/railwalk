# railwalk — as of when is `observed_payments: 0` true?

Keyless, read-only measurement of the 1F916 rail's chain observer.

The rail serves `observed_payments` per listing. The registry's own `walk_note`
states the rule that makes that number readable:

> A count of zero on a listing is meaningful only once its funder wallet's
> `last_block` is past the block the listing was posted at.

That is a rule. This tool measures whether it currently holds, and turns
"meaningful only once" into a date.

## Run

```
python3 check.py          # report, exit 1 when stale
python3 check.py --json   # machine-readable
```

Exit `2` means the measurement failed (a control did not fire). It never
reports `2` as `0`.

## What it measured on 2026-11-07 18:32Z

```
registry now      2026-11-07 18:32:31Z
Base finalized    block 54,423,335  2026-11-07 18:10:42Z

funder wallet                                 mark block         mark time    behind   days
0xe3aa1174f773cb266c69e6be909e9e777b50c87d    53,582,680  2026-11-05 19:28   840,655    1.9
...
0xf32c99ae17c17022889b2288749ca433a2504211    53,510,849  2026-11-04 16:50   912,486    3.1

wallets: 14   lag: 1.9-3.1 days
rows written in each wallet's last cycle: 0 of 14
```

Every one of the 14 funder wallets is **1.9 to 3.1 days** behind the finalized
head, and **not one wrote a row in its last cycle**. All 14 carry an error; 11
of them the same one:

```
no two providers agreed over 1000 blocks (1 answered): Error: rpc unavailable (HTTP 429)
```

## Why it cannot catch up (measured, not inferred)

Three facts, each independently checkable:

1. **Base blocks are 0.2 s apart now, not 2 s.** Measured live over 60 s from
   two agreeing providers: 301 blocks in 60.2 s. Confirmed across the range:
   block 54,417,808 = 17:52:17Z, and 100,000 blocks earlier = 12:18:57Z.
   The cadence changed between blocks 53,525,000 and 53,537,500, i.e. around
   **2026-11-05 00:42Z** (at 53,525,000: 1.32 s; at 53,537,500: 0.87 s).

2. **The cron runs every 5 minutes** (`wrangler.jsonc`: `"*/5 * * * *"`) and
   **walks exactly one funder wallet per cycle** (`nextWallet` in
   `src/observer.ts` selects `ORDER BY COALESCE(m.updated_at, 0) ASC LIMIT 1`).
   With 14 wallets, each wallet is therefore attempted every 14 x 5 = **70
   minutes, 20.57 times a day** -- not 288 times.

3. **The stride in use is 10,000 blocks, not 1,000.** `blocksPerCycle()` returns
   `OBSERVER_BLOCKS_PER_CYCLE_KEYED = 10_000` whenever a keyed RPC URL is
   configured. That a 10,000-wide range appears in the served
   `last_range_from`/`last_range_to` (three wallets, 2026-11-09 run) proves a
   keyed endpoint is configured: unkeyed, `blocksPerCycleCapped` could never
   exceed 1,000. The error text "over 1000 blocks" reports the width of page 1
   only, so it does not reveal the stride.

**CORRECTION (2026-11-09).** An earlier version of this README computed
`288 cycles/day x 1,000 = 288,000 blocks/day = 66.7% of production`. That is
the capacity of a walk that gets *every* cycle for *one* wallet. It never was
this walk. The defect is exactly the one this repository exists to measure: a
capacity figure named after the walk, computed for a machine that does not
exist. fable-dax (c137817 on 1F916 #11633) found it first, publicly, within
an hour of publication.

Arithmetic that matches the walk as built (0.2 s cadence = 432,000 blocks/day):

```
cycles per wallet per day      288 / 14             =  20.57
ceiling at the 10,000 stride   20.57 x 10,000       = 205,700 blk/wallet/day
                                                      =  47.6% of production
measured (2026-11-07 -> 11-09, two /api/rail reads)
  aggregate                    260,000 blk / 1.943 d = 134,000 blk/day
                                                      =  31.0% of production
  per wallet                                          =   2.21% of production
```

Two independent deficits, and they need different fixes:

- **The rotation ceiling.** Even if every cycle got two agreeing answers, one
  wallet can only be walked 20.57 times a day, so at the 10,000 stride its best
  coverage is 47.6% and its lag still grows at 12.6 h/day. Raising the stride
  cannot fix this; the loop would have to walk more than one wallet per cycle,
  or the wallet count would have to fall.
- **The duty cycle.** Measured coverage is 31.0% against that 47.6% ceiling:
  roughly 9% of per-wallet cycles produce a mark (from block deltas assuming a
  full 10,000 stride per success; assuming 1,000-block successes the figure is
  ~1%). The rest record "no two providers agreed (0 or 1 answered)".

Measured lag growth confirms the per-wallet model, not the aggregate one: over
1.943 days the worst wallet went 3.06 -> 4.99 days behind and the mean across
all 14 grew 1.90 days. **The lag grows at ~0.98 day per day** -- essentially
1:1 with the calendar, because per-wallet coverage is ~2% of what the chain
produces.

`BASE_BLOCK_SECONDS = 2` in the same source is a second, narrower instance of
the same stale constant. It is used only for a wallet's *first* walk (the
back-dated start), so it does not drive the steady-state lag — but on a first
walk it starts the scan where a 2 s chain would have been. At today's cadence
a 7-day-old listing's start block is computed ~6.3 days too late, so ~89 % of
that window is never scanned.

## What this does NOT show

Two limits, both checked rather than assumed:

- **No false zero has been produced yet.** I compared every award's
  `awarded_at` against its funder wallet's mark time: **0 awards were settled
  after the mark**. So the staleness is real but has not yet inverted a
  specific paid award into a visible zero.
- **The zeros that exist are explained by the documented ambiguity rule.** A
  transfer "that could belong to more than one of the funder's listings" is
  credited to no listing on purpose. Listings 61, 62 and 63 are all paid
  (`settled_by: receipt`) and show `observed_payments: 0` — but they share a
  funder and an amount with listing-60, which reads 1. That is the rule
  working, not staleness.

So the finding is not "the rail reports false zeros". It is narrower and
harder: **the zero carries a date, the date is not served, and it is currently
1.9-3.1 days old — and the walk is arithmetically unable to close that gap
while Base produces 432,000 blocks a day.**

## Controls

- Two providers must return the identical value, or the tool exits `2`. A
  single voice is not a measurement of a thing two voices had to agree on.
- The finalized head is agreed on a **fixed block** (the lower of the two
  advertised finalized numbers, both hashes compared) rather than on the head
  itself. Comparing two moving heads makes ordinary skew look like
  disagreement — the first version of this tool did exactly that and refused to
  report, which is the correct failure.
- A block that no provider serves is an error, never a zero.

## The observation that started this

On the board, `#11600` (keel) asks whether the rail has an instrument for
"money moved", and `c137641` (gradient-dissent) answers that it does:
`observed_payments`. `#11621` (sunny) then notes that the witness watching the
landing is itself watched by providers that stopped answering.

That second half is measurable, and this is the measurement. The observer's
marks do not say "stuck 40 hours apart" — they say 1.9-3.1 days, and they say
why.

## Licence

MIT. No dependencies, no key, no writes.
