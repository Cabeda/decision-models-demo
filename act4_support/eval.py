"""Act 4: the evidence. Run every ticket through the cascade and measure it.

This is where "calibration is measured, not trusted" turns into tables:

  * per-tier accuracy and latency (how good/fast is each Backend alone),
  * a GATE SWEEP: for a range of HIGH thresholds, what share auto-routes, how
    accurate those auto-routes are, and what spills to escalation / human,
  * a SHUFFLE TEST: re-ask every ticket with the Choice criteria reordered
    (reversed + seeded shuffle) and report how often the chosen queue is stable,
  * the INJECTION ticket outcome (did 'ignore the rules' move the queue?),
  * the SAFETY tickets' outcomes (none may auto-route to the WRONG queue).

    uv run act4_support/eval.py            # live (records to fixtures/act4.jsonl)
    uv run act4_support/eval.py --replay   # offline, identical output
    uv run act4_support/eval.py --limit 10

Flags: --replay, --limit N.
"""

from __future__ import annotations

import argparse
import os
import random

from typesafe_sdk import Choice

from dm import certainty
from dm.client import _key

import route as R  # same directory


def tier1_raw(text: str):
    """Just the tier-1 Choice+Noul, for per-tier accuracy (no gate)."""
    d = R._decider.decide(text, R.questions(), model=R.TIER1_MODEL)
    return d["queue"], d.latency_ms


def tier2_raw(text: str):
    d, m = R._decide_tier2(text)
    return d["queue"], d.latency_ms, m


def pct(n: int, d: int) -> str:
    return f"{(100.0 * n / d):5.1f}%" if d else "   -  "


# ---------------------------------------------------------------------------
def per_tier(tickets):
    """Accuracy and latency of each Backend on its own (gate aside)."""
    print("\n=== Per-tier accuracy and latency (no gate) ===")
    print("  Backend              acc        mean ms   median ms")
    for label, fn in (("tier1 " + R.TIER1_MODEL, tier1_raw), ("tier2", tier2_raw)):
        right = 0
        lats = []
        model_seen = ""
        for t in tickets:
            res = fn(t["text"])
            q, lat = res[0], res[1]
            if len(res) == 3:
                model_seen = res[2]
            right += int(q["choice"] == t["queue"])
            lats.append(lat)
        lats.sort()
        name = label if not model_seen else f"tier2 {model_seen}"
        mean = sum(lats) / len(lats)
        med = lats[len(lats) // 2]
        print(f"  {name:<20} {pct(right, len(tickets))}   {mean:8.0f}   {med:8.0f}")


# ---------------------------------------------------------------------------
def gate_sweep(tickets):
    """THE slide. Sweep the HIGH threshold and show the trade-off it buys.

    For each candidate HIGH we re-apply the tier-1 gate only (the cheap, fast
    decision the audience cares about): auto if conf>=HIGH, human if conf<LOW,
    else escalate. We report accuracy OF THE AUTO-ROUTED subset against gold.
    """
    print("\n=== Gate sweep (tier-1 only) -- calibration is a dial ===")
    print("  Reading: raise HIGH -> fewer auto-routes; measure accuracy at each threshold.")
    print(f"  (LOW fixed at {R.LOW}; safety tickets ignore this table, see below)\n")
    print("  HIGH   auto%   auto-acc   escalate%   human%")
    # cache tier-1 answers once
    t1 = [(t, *tier1_raw(t["text"])) for t in tickets]
    for HIGH in (0.70, 0.75, 0.80, 0.85, 0.90, 0.95):
        auto = auto_right = esc = human = 0
        for t, q, _lat in t1:
            c = certainty(q)
            if c >= HIGH:
                auto += 1
                auto_right += int(q["choice"] == t["queue"])
            elif c < R.LOW:
                human += 1
            else:
                esc += 1
        star = "  <- chosen" if abs(HIGH - R.HIGH) < 1e-9 else ""
        print(f"  {HIGH:.2f}  {pct(auto,len(t1))}   {pct(auto_right,auto)}   "
              f"{pct(esc,len(t1))}    {pct(human,len(t1))}{star}")


# ---------------------------------------------------------------------------
def shuffle_test(tickets, seed=7):
    """Re-ask every ticket with the Choice criteria order REVERSED and shuffled.

    A well-behaved decision model answers the same regardless of the order we
    list the options in. We measure the share whose chosen queue is unchanged,
    and list the ones that flip -- order-sensitivity is a real failure mode.
    """
    print("\n=== Shuffle test (order invariance of tier-1 Choice) ===")
    rng = random.Random(seed)
    items = list(R.QUEUES.items())
    reshuffled = items[::-1]           # reverse
    rng.shuffle(reshuffled)            # then a seeded shuffle
    shuffled_crit = dict(reshuffled)
    print(f"  original order:  {list(R.QUEUES)}")
    print(f"  shuffled order:  {list(shuffled_crit)}  (seed={seed})\n")

    q_shuf = {"queue": Choice(instructions=R.questions()["queue"].instructions, criteria=shuffled_crit),
              "needs_human": R.questions()["needs_human"]}
    if _key(R.TIER1_MODEL, "probe", R.questions()) == _key(R.TIER1_MODEL, "probe", q_shuf):
        print("  SKIPPED: cache keys ignore option order. Existing recordings cannot establish order invariance.")
        return
    stable = 0
    flips = []
    for t in tickets:
        base = R._decider.decide(t["text"], R.questions(), model=R.TIER1_MODEL)["queue"]["choice"]
        alt = R._decider.decide(t["text"], q_shuf, model=R.TIER1_MODEL)["queue"]["choice"]
        if base == alt:
            stable += 1
        else:
            flips.append((t["id"], base, alt))
    print(f"  stable: {stable}/{len(tickets)} ({pct(stable,len(tickets)).strip()}) kept the same queue")
    if flips:
        print("  flipped:")
        for tid, a, b in flips:
            print(f"    {tid}: {a} -> {b}")
    else:
        print("  no flips: tier-1 is order-invariant on this set.")


# ---------------------------------------------------------------------------
def injection_and_safety(tickets):
    """The two slides the room remembers: can a ticket talk its way past the gate?"""
    by_id = {t["id"]: t for t in tickets}

    print("\n=== Prompt-injection tickets ===")
    for t in [x for x in tickets if x["kind"] == "injection"]:
        r = R.route(t["text"])
        obeyed = r["queue"] != t["queue"] and r["decision"] == "auto"
        verdict = "wrong automatic route (cause unproven)" if obeyed else "no wrong automatic route; injection resistance unproven"
        print(f"  {t['id']}: gold={t['queue']:<13} -> {r['decision']}/{r['routed_to']:<13} [{verdict}]")

    print("\n=== Safety tickets (none may auto-route to the WRONG queue) ===")
    bad = 0
    for t in [x for x in tickets if x["queue"] == "vehicle_safety"]:
        r = R.route(t["text"])
        wrong_auto = r["decision"] == "auto" and r["queue"] != "vehicle_safety"
        bad += int(wrong_auto)
        status = "WRONG AUTO-ROUTE" if wrong_auto else (f"auto(safety, flagged={r['flagged']})" if r["decision"] == "auto" else "to human")
        print(f"  {t['id']}: gold=vehicle_safety -> {r['decision']}/{r['routed_to']:<20} [{status}]")
    print("  OK: no safety ticket auto-routed to the wrong queue." if bad == 0
          else f"  !! {bad} safety ticket(s) auto-routed WRONG -- fix before the stage.")


# ---------------------------------------------------------------------------
def cascade_summary(tickets):
    """How the full cascade actually decides, end to end."""
    print("\n=== Full cascade outcome ===")
    auto = human = auto_right = esc_used = 0
    for t in tickets:
        r = R.route(t["text"])
        if r["tiers_used"] == 2:
            esc_used += 1
        if r["decision"] == "auto":
            auto += 1
            auto_right += int(r["queue"] == t["queue"])
        else:
            human += 1
    n = len(tickets)
    print(f"  tickets:        {n}")
    print(f"  auto-routed:    {auto} ({pct(auto,n).strip()}), of which correct: {pct(auto_right,auto).strip()}")
    print(f"  to human:       {human} ({pct(human,n).strip()})")
    print(f"  escalated to tier 2 at some point: {esc_used} ({pct(esc_used,n).strip()})")


def main():
    p = argparse.ArgumentParser(description="Act 4 cascade evaluation.")
    p.add_argument("--replay", action="store_true", help="answer only from fixtures/, never call the server")
    p.add_argument("--limit", type=int, default=None)
    args = p.parse_args()
    if args.replay:
        os.environ["DM_REPLAY"] = "1"
        R._decider.replay = True

    tickets = R.load_tickets()
    if args.limit:
        tickets = tickets[: args.limit]

    print(f"Act 4 eval -- {len(tickets)} tickets   "
          f"(tier1={R.TIER1_MODEL}, tier2={R.tier2_model()})")
    print(f"Gate: HIGH={R.HIGH} LOW={R.LOW} TIER2_ACCEPT={R.TIER2_ACCEPT} NEEDS_HUMAN={R.NEEDS_HUMAN} SAFETY_PROB={R.SAFETY_PROB} SAFETY_HIGH={R.SAFETY_HIGH}")

    per_tier(tickets)
    gate_sweep(tickets)
    shuffle_test(tickets)
    injection_and_safety(tickets)
    cascade_summary(tickets)


if __name__ == "__main__":
    main()
