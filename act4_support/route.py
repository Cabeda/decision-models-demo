"""Act 4: customer-support ticket routing as a confidence-gated Cascade.

A ticket comes in. A fast, cheap Backend (laya) answers two typed Questions:
which queue, and whether a human is needed. A Gate on Confidence decides what
happens: route automatically, escalate to a stronger Backend (kev), or hand to
a human. Safety tickets get a stricter gate. Nothing here generates text.

    uv run act4_support/route.py "the app crashes when I open my invoice"   # live, one ticket
    uv run act4_support/route.py --all                                      # whole fixture set
    uv run act4_support/route.py --all --replay                             # offline, from fixtures/

Flags: --replay (never touch the network), --limit N (first N fixture tickets).
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from typesafe_sdk import Choice, Noul

from dm import Decider, DecisionError, certainty
from dm.show import bar

# ---------------------------------------------------------------------------
# Thresholds. These are the whole point of the act: calibration is a dial, not
# a guess. The numbers below were TUNED from the Gate sweep in eval.py (see the
# final report), not picked by feel.
# ---------------------------------------------------------------------------
HIGH = 0.85   # confidence >= HIGH  -> trust the answer, auto-route
LOW = 0.55    # confidence <  LOW   -> no clear winner, send to a human
              # LOW <= confidence < HIGH -> escalate to the stronger Backend

# The needs_human Noul is a vague question, and the Backends read it loosely.
# Measured on this set: laya sits near 0.05 for most tickets but still gave 0.81
# on a plain duplicate-charge ticket, and kev:4b sits near 0.5 for EVERYTHING
# (clear tickets median 0.46, ambiguous 0.54). At the obvious 0.5 line it is a
# coin flip, so it may only VETO an auto-route when the model is really sure.
# Lesson: a Gate is only as good as the question it reads.
NEEDS_HUMAN = 0.90

# Confidence scales differ per Backend. kev:4b was right 37/40 times, yet its
# Choice confidence is lower than laya's (6 options, so top-class 0.5 is already
# a clear winner). Its 3 wrong answers sat at 0.29-0.41, and every answer at 0.5
# or above was right. So tier 2 gets its own line, read off the data, not
# borrowed from tier 1. (40 tickets is a small sample, and tuned on the same 40.)
# KNOWN FAILURE: the 4 wrong auto-routes all come from TIER 1. laya is confidently
# wrong (0.86-0.99) on ambiguous and multi-intent tickets. Its docs say the raw
# checkpoints are over-confident; the fix is to refit calibration on labelled data.
TIER2_ACCEPT = 0.50

# vehicle_safety is special: the cost of mis-routing a brake/fire/steering
# ticket is a crash, not a slow reply. So we never let it slip through quietly.
SAFETY_PROB = 0.15    # if vehicle_safety has even this much probability, treat the ticket as safety-suspect
SAFETY_HIGH = 0.90    # a safety ticket only auto-routes if BOTH tiers agree this strongly...
                      # ...and even then we still flag it for a human to eyeball.

HERE = Path(__file__).resolve().parent
TICKETS = HERE / "tickets.json"

# The six queues, described the way a new support agent would be briefed.
QUEUES = {
    "billing": "Payments, invoices, subscriptions, refunds and charges",
    "app_technical": "The Zephyra phone app: crashes, login, bugs, notifications, sync",
    "charging": "Charging the car: speed, range, home and public chargers, charging errors",
    "vehicle_safety": "Physical safety of the car: brakes, steering, smoke or fire, warning lights, tyres",
    "privacy_gdpr": "Personal data, consent, GDPR access or deletion, data sharing",
    "general": "Anything else, or too vague to place: hours, manuals, hello, 'it is broken'",
}

TIER1_MODEL = "laya"            # router: English -> laya:en, other languages -> laya:multilingual
TIER2_MODEL = "kev:4b"          # stronger, slower
TIER2_FALLBACK = "kev:0.8b"     # used when kev:4b is not pulled on this machine


def questions() -> dict:
    """The two typed Questions every tier asks about a ticket."""
    return {
        "queue": Choice(
            instructions="Which support queue should handle this ticket? Pick the PRIMARY issue.",
            criteria=QUEUES,
        ),
        "needs_human": Noul(
            instructions=(
                "This ticket needs a human agent rather than an automated reply: the customer "
                "is angry, threatens legal or regulatory action, or the request is too unclear to act on."
            ),
        ),
    }


# One available Decider, resolved once (so --replay / live is decided up front).
_decider = Decider("act4", model=TIER1_MODEL)
_tier2_cache: dict[str, str] = {}


def tier2_model() -> str:
    """Which tier-2 Backend to use: kev:4b if available, else kev:0.8b.

    Live: ask `ollaya list`. Replay: we cannot shell out, so we trust whatever
    the fixture RECORDED -- if a kev:4b response was recorded live, replay must
    use kev:4b too, otherwise live and --replay would diverge. This keeps the
    two paths byte-identical instead of guessing a possibly-different fallback.
    """
    if "m" in _tier2_cache:
        return _tier2_cache["m"]
    model = TIER2_FALLBACK
    if os.environ.get("DM_REPLAY") == "1":
        # Did the recorded fixture use the stronger model? Then so do we.
        recorded = {rec.get("requested_model") for rec in _decider._cache.values()}
        model = TIER2_MODEL if TIER2_MODEL in recorded else TIER2_FALLBACK
    else:
        try:
            import subprocess

            out = subprocess.run(["ollaya", "list"], capture_output=True, text=True, timeout=10).stdout
            names = {line.split()[0] for line in out.splitlines() if line.strip() and not line.startswith("NAME")}
            model = TIER2_MODEL if TIER2_MODEL in names else TIER2_FALLBACK
        except Exception:
            model = TIER2_FALLBACK
    _tier2_cache["m"] = model
    return model


def _decide_tier2(text: str):
    """Tier-2 decision, tolerant of a missing kev:4b in both live and replay."""
    model = tier2_model()
    try:
        return _decider.decide(text, questions(), model=model), model
    except (LookupError, DecisionError):
        # replay miss or server refusal on the preferred tier-2 model: try the fallback
        if model != TIER2_FALLBACK:
            return _decider.decide(text, questions(), model=TIER2_FALLBACK), TIER2_FALLBACK
        raise


# ---------------------------------------------------------------------------
# The cascade itself. Returns a dict trace that route --all and eval.py share.
# ---------------------------------------------------------------------------
def route(text: str) -> dict:
    """Run the confidence-gated cascade on one ticket. Pure data out, no printing."""
    steps: list[dict] = []

    # --- Tier 1: fast Backend ------------------------------------------------
    d1 = _decider.decide(text, questions(), model=TIER1_MODEL)
    q1, nh1 = d1["queue"], d1["needs_human"]
    conf1 = certainty(q1)
    safety_p1 = q1["probabilities"].get("vehicle_safety", 0.0)
    steps.append({
        "tier": 1, "backend": d1.model, "queue": q1["choice"], "confidence": round(conf1, 3),
        "needs_human": round(nh1["noul"], 3), "safety_prob": round(safety_p1, 3),
        "latency_ms": round(d1.latency_ms, 1), "probs": q1["probabilities"],
    })

    # Is this a safety-suspect ticket? Either tier 1 picked vehicle_safety, or
    # vehicle_safety carries non-trivial probability even if it did not win.
    safety_suspect = q1["choice"] == "vehicle_safety" or safety_p1 >= SAFETY_PROB

    # Tier-1 Gate. A human is also forced when the Noul says so.
    if nh1["noul"] >= NEEDS_HUMAN:
        return _finish(text, steps, "human", q1["choice"], "tier-1 flagged needs_human", safety_suspect, flag=True)

    if not safety_suspect and conf1 >= HIGH:
        return _finish(text, steps, "auto", q1["choice"], f"tier-1 confidence {conf1:.2f} >= HIGH", safety_suspect)
    if conf1 < LOW and not safety_suspect:
        return _finish(text, steps, "human", q1["choice"], f"tier-1 confidence {conf1:.2f} < LOW", safety_suspect)

    # --- Tier 2: stronger Backend (escalation) ------------------------------
    # We escalate when tier 1 is in the grey band, OR the ticket is safety-suspect
    # (we want a second strong opinion before anything near safety auto-routes).
    why = "safety-suspect: second opinion required" if safety_suspect else f"tier-1 confidence {conf1:.2f} in grey band"
    d2, m2 = _decide_tier2(text)
    q2, nh2 = d2["queue"], d2["needs_human"]
    conf2 = certainty(q2)
    safety_p2 = q2["probabilities"].get("vehicle_safety", 0.0)
    steps.append({
        "tier": 2, "backend": m2, "queue": q2["choice"], "confidence": round(conf2, 3),
        "needs_human": round(nh2["noul"], 3), "safety_prob": round(safety_p2, 3),
        "latency_ms": round(d2.latency_ms, 1), "probs": q2["probabilities"], "why_escalated": why,
    })

    if nh2["noul"] >= NEEDS_HUMAN:
        return _finish(text, steps, "human", q2["choice"], "tier-2 flagged needs_human", safety_suspect, flag=True)

    # Safety gate: auto-route only if BOTH tiers pick vehicle_safety with high
    # confidence -- and even then we flag it so a human still eyeballs it.
    if safety_suspect:
        both_safety_high = (
            q1["choice"] == "vehicle_safety" and q2["choice"] == "vehicle_safety"
            and conf1 >= SAFETY_HIGH and conf2 >= SAFETY_HIGH
        )
        if both_safety_high:
            return _finish(text, steps, "auto", "vehicle_safety",
                           "both tiers agree vehicle_safety with high confidence", safety_suspect, flag=True)
        return _finish(text, steps, "human", "vehicle_safety",
                       "safety-suspect without strong two-tier agreement", safety_suspect, flag=True)

    # Normal tier-2 Gate.
    if conf2 >= TIER2_ACCEPT:
        return _finish(text, steps, "auto", q2["choice"], f"tier-2 confidence {conf2:.2f} >= {TIER2_ACCEPT}", safety_suspect)
    return _finish(text, steps, "human", q2["choice"], f"tier-2 confidence {conf2:.2f} below {TIER2_ACCEPT}", safety_suspect)


def _finish(text, steps, decision, queue, why, safety_suspect, flag=False):
    final_queue = "vehicle_safety_HUMAN" if (decision == "human" and queue == "vehicle_safety") else queue
    return {
        "text": text,
        "decision": decision,          # auto | human
        "queue": queue,                # the queue the cascade believes in
        "routed_to": "human" if decision == "human" else queue,
        "why": why,
        "flagged": flag or (decision == "auto" and safety_suspect),
        "safety_suspect": safety_suspect,
        "tiers_used": len(steps),
        "steps": steps,
    }


# ---------------------------------------------------------------------------
# Printing (stage-friendly: probability bars, one ticket at a time).
# ---------------------------------------------------------------------------
def print_trace(r: dict, verbose: bool) -> None:
    print(f"\nticket: {r['text']}")
    for s in r["steps"]:
        head = (f"  tier {s['tier']} [{s['backend']}]  queue={s['queue']}  "
                f"conf={s['confidence']:.2f}  needs_human={s['needs_human']:.2f}  "
                f"safety_p={s['safety_prob']:.2f}  {s['latency_ms']:.0f} ms")
        if "why_escalated" in s:
            head += f"\n          escalated: {s['why_escalated']}"
        print(head)
        if verbose:
            for label, p in sorted(s["probs"].items(), key=lambda kv: -kv[1]):
                mark = "<-" if label == s["queue"] else "  "
                print(f"          {label:<15} {bar(p, 18)} {p:5.1%} {mark}")
    flag = "  [FLAGGED for human review]" if r["flagged"] else ""
    print(f"  => {r['decision'].upper()} -> {r['routed_to']}   ({r['why']}){flag}")


def load_tickets() -> list[dict]:
    return json.loads(TICKETS.read_text())["tickets"]


def main() -> None:
    p = argparse.ArgumentParser(description="Act 4 support-ticket cascade router.")
    p.add_argument("ticket", nargs="?", help="a single free-text ticket to route live")
    p.add_argument("--all", action="store_true", help="route the whole fixture set")
    p.add_argument("--replay", action="store_true", help="answer only from fixtures/, never call the server")
    p.add_argument("--limit", type=int, default=None, help="only the first N fixture tickets")
    args = p.parse_args()
    if args.replay:
        os.environ["DM_REPLAY"] = "1"
        _decider.replay = True

    print(f"Gate: HIGH={HIGH}  LOW={LOW}  TIER2_ACCEPT={TIER2_ACCEPT}  NEEDS_HUMAN={NEEDS_HUMAN}  SAFETY_PROB={SAFETY_PROB}  SAFETY_HIGH={SAFETY_HIGH}")
    print(f"tier 1: {TIER1_MODEL}   tier 2: {tier2_model()} (configured {TIER2_MODEL}, fallback {TIER2_FALLBACK})")

    if args.all:
        tickets = load_tickets()
        if args.limit:
            tickets = tickets[: args.limit]
        counts = {"auto": 0, "human": 0}
        for t in tickets:
            r = route(t["text"])
            counts[r["decision"]] += 1
            gold = f"  gold={t['queue']}" + (f"/{t.get('secondary')}" if t.get("secondary") else "")
            print(f"\n[{t['id']} {t['lang']} {t['kind']}]{gold}")
            print_trace(r, verbose=False)
        print(f"\n--- {len(tickets)} tickets: {counts['auto']} auto-routed, {counts['human']} to human ---")
    elif args.ticket:
        print_trace(route(args.ticket), verbose=True)
    else:
        p.error("give a ticket in quotes, or --all")


if __name__ == "__main__":
    main()
