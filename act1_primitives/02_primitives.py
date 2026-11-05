"""Act 1, step 2: the three primitives through the Jev SDK.

Same ticket, three kinds of question. Nothing here generates text.

    uv run act1_primitives/02_primitives.py
    uv run act1_primitives/02_primitives.py --model kev:0.8b
    uv run act1_primitives/02_primitives.py --replay
"""

import time

from typesafe_sdk import Choice, Noul, Score

from dm import Decider, common_parser, parse
from dm.show import show_answer

args = parse(common_parser(__doc__))
decider = Decider("act1", model=args.model)

TICKET = (
    "I was charged twice for my subscription this month and the app keeps crashing "
    "when I open the invoice. Please refund the second charge today."
)

# TICKET = (
#     "I want to cancel my account and request right to be forgotten from California privacy law."
# )

questions = {
    # Choice: pick exactly one from a closed set.
    "queue": Choice(
        instructions="Which team should handle this ticket?",
        criteria={
            "billing": "Payments, invoices and refunds",
            "technical": "App bugs, errors and outages",
            "account": "Login, profile and settings",
        },
    ),
    # Score: place it on an ordered rubric.
    "urgency": Score(
        instructions="How urgent is this ticket?",
        criteria=["Can wait", "Needs attention this week", "Needs attention today"],
    ),
    # Noul: a yes/no statement, answered as a probability.
    "wants_refund": Noul(instructions="The customer asks for money back."),
}

print(f"model: {args.model}\nticket: {TICKET}\n")
start = time.perf_counter()
d = decider.decide(TICKET, questions)
elapsed_ms = (time.perf_counter() - start) * 1000
for name, ans in d.answers.items():
    show_answer(name, ans)
print(f"\nanswered by {d.model}, {d.input_tokens} input tokens, 0 output tokens")
print(f"current call ({'cached' if d.cached else 'live'}): {elapsed_ms:.2f} ms")
print(f"original model request: {d.latency_ms:.0f} ms")
