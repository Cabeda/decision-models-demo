"""Act 1, step 3: where decision models break, and what to do about it.

    uv run act1_primitives/03_where_it_breaks.py
    uv run act1_primitives/03_where_it_breaks.py --replay
"""

from typesafe_sdk import Choice, Noul

from dm import Decider, DecisionError, certainty, common_parser, parse

args = parse(common_parser(__doc__))
decider = Decider("act1_breaks", model=args.model)

QUEUES = Choice(
    instructions="Which team should handle this ticket?",
    criteria={
        "billing": "Payments, invoices and refunds",
        "technical": "App bugs, errors and outages",
        "account": "Login, profile and settings",
    },
)


def section(title: str) -> None:
    print(f"\n=== {title} ===")


# 1. Language: each checkpoint answers a Portuguese ticket, and they do not all agree.
section("1. Same ticket, different checkpoints")
PT = "Cobraram-me duas vezes a mensalidade da app e quero o reembolso."
print(f"state: {PT}")
for model in ("laya:en", "laya:multilingual", "laya:typed-decisions", "kev:0.8b"):
    try:
        d = decider.decide(PT, {"queue": QUEUES}, model=model)
    except (DecisionError, Exception) as exc:  # a model that is not pulled yet
        print(f"  {model:<22} unavailable ({str(exc)[:50]})")
        continue
    a = d["queue"]
    print(f"  {model:<22} {a['choice']:<10} confidence {a['confidence']:.2f}  {d.latency_ms:6.0f} ms")
print("-> the answer is only as good as the checkpoint. Measure on your own data.")

# 2. Length: laya:en has a 512-token window and refuses rather than guess.
section("2. A state that does not fit")
LONG = " ".join(
    "The infotainment screen froze again on the motorway and I had to restart the car twice."
    for _ in range(60)
)
print(f"state: {len(LONG.split())} words")
for model in ("laya:en", "kev:0.8b"):
    try:
        d = decider.decide(LONG, {"queue": QUEUES}, model=model)
        print(f"  {model:<10} {d['queue']['choice']} ({d['queue']['confidence']:.2f}) in {d.latency_ms:.0f} ms")
    except DecisionError as exc:
        print(f"  {model:<10} refused: {str(exc)[:90]}")
    except Exception as exc:
        print(f"  {model:<10} unavailable ({str(exc)[:50]})")
print("-> a refusal beats a silent truncation. Pick a model whose window fits your data.")

# 3. Numbers: keep arithmetic in code and hand the model words.
section("3. Numbers: let code do the maths")
pairs = [(7, 10), (12, 10), (9, 10), (10, 9), (3, 30), (31, 30)]
right = 0
for temp, limit in pairs:
    q = Noul(instructions=f"{temp} is less than {limit}.")
    p = decider.decide("Compare the two numbers.", {"less": q})["less"]["noul"]
    ok = (p > 0.5) == (temp < limit)
    right += ok
    print(f"  {temp:>2} < {limit:<2}  model says {p:5.1%}   truth {temp < limit!s:<5}  {'ok' if ok else 'WRONG'}")
print(f"  {right}/{len(pairs)} right. In code this is `temp < limit`: bucket numbers first, ask the model about the bucket.")
