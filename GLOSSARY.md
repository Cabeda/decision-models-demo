# Glossary

**Decision model**: a model whose output is a typed value your code can branch on (a pick from a fixed set, a position on a scale, a yes/no probability), never free text.
_Avoid_: classifier (too narrow), chatbot.

**System One model**: another name for a decision model, after the fast, intuitive mode of thinking. Jev is the reference example.
_Avoid_: calling it an LLM; it does not generate text.

**Generative model**: a model that produces text token by token. In the demos it does the writing, while the decision model decides what happens next.

**State**: the content a question is asked about (a ticket, a weather summary, a database row). The caller decides what goes in, and less irrelevant detail gives better answers.

**Question**: one typed ask against a State. Several questions can be asked about the same State at once.

**Primitive**: one of the three kinds of Question, namely Choice, Score and Noul.

**Choice**: a Primitive that picks exactly one option from a closed set, with a probability per option.

**Score**: a Primitive that places the State on an ordered rubric, with a probability per level.

**Noul**: a Primitive that answers a yes/no statement with the probability that it is true.

**Probabilities**: the distribution a decision returns over its options or levels. They are the raw material for Confidence.

**Confidence**: one number from 0 to 1 summarising how concentrated the Probabilities are. High means a clear winner, low means no clear winner. It is not the same as the probability of the chosen option.

**Gate**: a threshold on Confidence that decides whether code acts automatically, escalates, or hands over to a human.

**Routing**: using a decision to select the next code path (a support queue, a handler, a bigger model).

**Cascade**: trying a cheaper model first and escalating to a stronger one only when the Gate says the answer is not trustworthy.

**Label**: a decision written back onto a data row, as in the DuckDB demo.

**Ground truth**: the field in a dataset that records what the right answer is, used to measure whether decisions are correct.

**Jev**: TypeSafe's hosted decision model and the origin of the System One category. In the demo it is the API contract (`typesafe-sdk`), not the engine.

**Ollaya**: a local server that implements the Jev wire API (`/v1/systemone`) on open decision models. The demo code is written against the TypeSafe SDK and points `TYPESAFE_BASE_URL` at Ollaya.
_Avoid_: calling it a Jev replacement; it is compatible at the API level only.

**Backend**: the Ollaya model that answers the Questions (`laya`, `kev`). Switching Backend means changing the `model` string and nothing else.

**Wire compatibility**: Ollaya accepts the same requests and returns the same response shape as Jev, so code written for Jev runs unchanged. The models and their quality differ.

**Context budget**: the token limit for State plus Questions (512 for `laya:en`, 8,192 for `kev`). `/v1/*` rejects a State that does not fit with `STATE_TRUNCATED` instead of answering from part of it.
