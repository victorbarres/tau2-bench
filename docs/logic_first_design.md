# Logic-First Domain Design

A methodology for designing tau-bench-style benchmark domains by starting from a
formal logical specification and projecting natural language, code, database
state, and tasks from it — rather than authoring those artifacts independently
and reconciling them by hand.

This document is the **methodology**. The accompanying **worked example** lives
under [`data/tau2/domains/retail_returns/`](../data/tau2/domains/retail_returns/)
and instantiates each layer described here.

This is **not** a fill-in-the-blank template. Templates encode commitments
(required fields, grammar, optionality) that we have not yet earned the right
to make. A worked example does most of the same job — showing what "good"
looks like — without prematurely freezing the format. A template, if and when
we write one, comes after we have used this methodology to build at least one
fresh domain end-to-end and retrofitted at least one existing one.

---

## 1. Why we are doing this

The airline domain is the reference point. Its current artifact stack is:

- `policy.md` — natural-language policy.
- `data_model.py` — Pydantic schemas.
- `db.json` — instances.
- `tasks.json` — natural-language user scenarios + gold action sequences.
- Tool implementations — enforcement logic for the parts of the policy that
  happen to be machine-checkable.

Each of these encodes part of the domain's meaning. None of them is
authoritative. To answer a simple question like "is this booking valid?" you
have to triangulate across all five. Three concrete consequences fall out of
that:

1. **Drift.** Closed enumerations exist in code (`FlightDateStatus` has 6
   cases) that are not present in policy (`policy.md` lists 4). The policy's
   "(basic) economy" idiom is not enforced by any schema. Tool implementations
   silently encode rules that policy mentions only in passing.
2. **Uniqueness of task solutions is emergent, not designed.** The DB and the
   user scenarios were iteratively tuned by hand until the gold action
   sequence happened to be the only one that passed the eval. No machine-
   checkable proof exists that another DB state could not also have satisfied
   the user's stated constraints under the policy.
3. **Natural language is treated as input.** Policy is authored in prose;
   tasks are authored in prose. The structured artifacts (schema, gold
   actions, tests) are derived by hand from the prose. This is the wrong
   direction of dependency: prose is good for human consumption but bad for
   precision, and we are using it as the precision-bearing source.

This methodology inverts those dependencies. The formal core is authoritative;
everything else — code, DB, prose, tasks — is downstream.

---

## 2. Five principles

1. **One source of truth per layer.** No prose policy that drifts from code,
   no code schema that drifts from policy, no DB that violates declared
   invariants. Each artifact has exactly one upstream source. Where two
   artifacts overlap (e.g., the policy mentions cardinalities and the schema
   enforces them), one is generated from the other; never both hand-written.

2. **Closed enumerations are declared, finite, and authoritative.** Cabin
   classes, statuses, action types, payment kinds — declared once, in a single
   place, with no implicit additions. If the encoding needs a `landed` status
   in addition to the four documented ones, the closed enumeration changes,
   not the consumer code.

3. **Actions are first-class transition predicates.** Each agent-callable
   tool corresponds to one action with a declared signature, preconditions,
   effects, and validity rules. The Pydantic schema, the policy clause, and
   the tool implementation are *all three* derived from the action spec; they
   are not parallel sources to be reconciled.

4. **Policy is layered, not monolithic.** The current `policy.md` fuses three
   kinds of rule that have different audiences and different formal homes:

   - **World invariants** — properties the world satisfies whether the agent
     does anything or not (`|passengers| ≤ 5`). Never violable.
   - **Action validity** — preconditions on transitions (`can't cancel basic
     economy mid-flight`). The agent could attempt the action; the world
     refuses it.
   - **Agent contract** — deontic, dialogue-shape rules (`must confirm before
     mutating`, `deny vs transfer`). The world doesn't refuse; the agent
     refuses.

   These three layers are kept separate.

5. **Tasks are queries with provable preconditions.** A task is a constraint
   set over the final DB state, starting from a given DB. Three preconditions
   are required of every task:

   - **Soundness** — the intended answer satisfies policy ∧ constraints.
   - **Uniqueness** — no other answer also satisfies them.
   - **Discoverability** — the agent can reach the intended answer using only
     the information the user volunteers plus information retrievable from
     the DB by available tools.

   These properties are *machine-checkable* outputs of the methodology, not
   aspirations we approach by hand-tuning.

---

## 3. The layer dependency map

Six layers, each producing one artifact, each consuming only upstream layers.

| Layer | Name | Output | Depends on |
|---|---|---|---|
| **A** | Ontology | Sorts, attributes, derived predicates, closed enumerations | — |
| **B** | World rules | Integrity constraints and derivations (ASP rules) | A |
| **C** | Actions | Transition predicates: signature + pre + effect + validity, per action | A, B |
| **D** | Agent contract | Deontic layer: confirmation, refusal, transfer, dialogue-shape rules | A, B, C |
| **E** | World instantiation | A baseline DB (`D₀`) that satisfies A–C | A, B |
| **F** | Tasks | `(D₀, OperationalSpec, BehavioralSpec)` tuples with proven uniqueness | A–E |

Downstream artifacts (generated, never hand-authored if avoidable):

- **Data model code** (e.g., Pydantic) — generated from A.
- **Tool stubs + validators** — generated from A + C.
- **NL `policy.md`** — rendered from A + B + C + D.
- **NL `task_instructions`** — rendered from F's OperationalSpec + BehavioralSpec.
- **Evaluation criteria** (`actions[]`, `nl_assertions`, `communicate_info`) —
  derived from F.

Rendering is hand-written for v0 (see §6 on rendering ambition), but the spec
is treated as authoritative: any divergence between prose and spec is a bug in
the prose, not in the spec.

---

## 4. Task model

A task is a tuple `T = (D₀, OperationalSpec, BehavioralSpec)`.

### `OperationalSpec`

The structured intent. Four sub-bags:

- `C_hard` — properties the final DB state must have. (User wants a return for
  order X with items {a, b}, refund to original payment, on 2026-05-20.)
- `C_soft` — preferences with explicit fallback. ("Refund to original card if
  possible; otherwise accept store credit.")
- `C_known` — facts the user volunteers without being asked.
- `C_unknown` — facts the user does not know but the agent must derive
  (typically through DB lookups: "I forget which item I want to return, but
  it's the one I bought last week").

### `BehavioralSpec`

Dialogue-shape directives, in semi-structured NL using a controlled vocabulary
of move primitives (see §7). Things like:

- `(insist, count=3)` — escalate three times before backing off.
- `(lie, claim="I'm a Plus member")` — assert a false fact.
- `(misremember, fact="purchase date")` — be wrong about something.
- `(fallback, condition="price > X", action="drop second item")` — branch on
  what the agent reveals.
- `(appeal_to_authority, claim="customer support told me ...")` — pressure
  pattern.

The BehavioralSpec carries dialogue dynamics; it does **not** affect what the
correct final DB state is. The OperationalSpec carries the world-shape
constraints; it does **not** prescribe the dialogue.

### The three task classes

Every task gets the same structure. The verifier classifies each as one of:

- **`intent_noop`** — `C_hard` requests no mutation. `D* = D₀` trivially.
- **`policy_noop`** — `C_hard` requests a mutation, but policy denies it under
  `D₀`. `D* = D₀` with a *reason trace* (which rules fired the refusal).
- **`mutating`** — `D* ≠ D₀`, derivable from `(D₀, Policy, C_hard)`.

`policy_noop` is the most LP-valuable: it's where the formal layer proves the
correct answer is a refusal *and* tells us why.

---

## 5. The three operations the system performs

| Operation | Input | Output | Purpose |
|---|---|---|---|
| **Verify** | `(D₀, OperationalSpec, D*)` | answer-set count + diff for any extras | confirm a hand-authored task is well-posed |
| **Solve** | `(D₀, OperationalSpec)` | the unique `D*` (or `ambiguous` / `infeasible`) | derive ground-truth DB state from spec |
| **Generate** | `(OperationalSpec template, knobs)` | a `D₀` (possibly a delta over a shared baseline) such that the task has a unique solution | sample the task space at controlled difficulty |

Verify is the cheapest and gives the highest immediate ROI on existing
corpora. Solve replaces the "gold actions as ground truth" pattern with
"solver output as ground truth." Generate is the hardest and where the
methodology's design risk lives.

Generate, for v0, is implemented as **generate-then-verify**: enumerate
candidate `D₀`s subject to the spec, then run Verify on each. Slow but
conceptually clean. A more efficient **witness + perturbation** encoding is a
follow-up.

---

## 6. Where logical reasoning lives, and where it doesn't

The formal core is ASP (Clingo). It handles:

- Closed enumerations and finite-domain constraints.
- Cardinality bounds (`≤ N`, `≥ N`, `= N`).
- Defaults with exceptions (the canonical ASP strength).
- Integrity constraints (`:- bad_state`).
- Choice rules (for action selection and DB generation).

External (host-language) predicates handle:

- **Money arithmetic.** Prices, totals, refund amounts. Computed once and
  asserted as facts.
- **Date/time arithmetic.** "Within N days of …" is a host predicate that
  emits a boolean fact (`recent_purchase(O)`). Calendar reasoning does not
  live in ASP.
- **Status classification.** "Any item already shipped" is a host predicate
  that surfaces a single boolean fact.

This avoids ASP's grounding blow-up on numeric domains. The cost is one extra
layer (the encoder); the benefit is decidability and a small grounding.

For domains where numeric/temporal reasoning is the *core* of the policy (e.g.,
finance, scheduling), this methodology applies but the formal core may swap
out (SMT, hybrid). The *principles* generalize; the *engine* is a design
choice per domain.

---

## 7. Behavioral layer — vocabulary, not DSL

The behavioral layer (adversarial dialogue, manipulation, refusal, fallback)
is not formalized in v0. Instead we maintain a **controlled vocabulary** of
move primitives that authors tag in NL `task_instructions`:

| Primitive | Meaning |
|---|---|
| `assert(fact)` | State a fact (assumed true unless flagged). |
| `lie(fact)` | State a fact known to be false in `D₀`. |
| `misremember(fact)` | State a wrong value for a fact the user genuinely doesn't know precisely. |
| `insist(count=N)` | Repeat a request N times after pushback before backing off. |
| `fallback(condition, action)` | Conditional plan: do X if condition, else Y. |
| `appeal_to_authority(source)` | Cite a third party to override agent judgment. |
| `threaten_escalation` | Threaten to ask for a supervisor. |
| `drop_constraint(c)` | Voluntarily relax constraint `c` if pressed. |
| `change_topic(new_intent)` | Pivot to an unrelated request. |
| `withhold(fact, until=condition)` | Don't reveal a fact unless asked or condition met. |

This vocabulary is enough to *describe* and *sample* adversarial patterns
without committing to a grammar. A DSL with composition operators is a v2
artifact. The vocabulary is the v0 contract.

---

## 8. Rendering: spec is canonical, prose is hand-written

For v0, NL prose (policy.md, task_instructions, tool descriptions) is
**hand-written** but **consistency-checked** against the spec. The check:

- Every machine-checkable claim in the prose traces to a rule or fact in the
  spec.
- Every rule in the spec that is user-facing is mentioned in some prose
  artifact.

A renderer (spec → prose) is a v2 artifact built only if hand-rendering
becomes the bottleneck. The methodology commits that rendering *is* possible
from the spec; it does not commit that we build the renderer now.

---

## 9. What this methodology does not solve

Honest accounting of the gaps:

1. **Dialogue quality.** A task with a logically-correct OperationalSpec can
   still be a bad benchmark task if the rendered NL is robotic, ambiguous, or
   stilted. Style is not formalizable.

2. **Real-world policy fidelity.** Real policies (insurance, banking,
   healthcare) have ambiguity, exception escalation, regional variation, and
   undocumented practice. This methodology produces *idealized* policies. The
   tradeoff is intentional — benchmark domains are simulated worlds, and
   logical clarity beats realism in that setting — but it should not be
   confused with formal verification of an actual production policy.

3. **Adversarial behavior generation.** The Behavioral vocabulary lets us
   describe adversarial patterns; it does not let us synthesize them at
   controlled difficulty. That is a separate research thread.

4. **Multi-turn world dynamics.** This methodology assumes the world state
   evolves only through agent actions. Domains where the world changes
   independently mid-conversation (real-time inventory, live pricing) need a
   richer model.

---

## 10. Phasing

A reasonable build order, given a fresh domain:

1. **Layers A–B**: ontology + world rules. ASP encoding.
2. **Layer C**: actions. Transition predicates. Generate the Pydantic schema
   and tool stubs from this.
3. **Layer D**: agent contract. Deontic layer. Render the human-facing
   `policy.md` from A + B + C + D.
4. **Layer E**: instantiate `D₀`. Either author by hand and verify, or sample
   a valid model from A + B.
5. **Verifier first, solver next**: prove that Verify works on a single
   hand-authored task. Then drop the `D*` ground truth and recover it from
   `(D₀, OperationalSpec)` via Solve.
6. **Layer F + Generate**: task generation at controlled difficulty.
7. **Render**: hand-write NL prose for the first ~5 tasks. Use those to
   stress-test the BehavioralSpec vocabulary.
8. **Retrofit airline**: with the methodology proven on a greenfield, fold the
   airline domain back in. This will surface methodology gaps that
   greenfielding doesn't (because greenfielding has no legacy to honor).

---

## 11. Open methodology questions

These are interpretive choices we have not yet committed to. They will be
resolved during the worked example and folded back into v2 of this doc.

- **Per-task D₀ vs shared D₀.** Airline uses a shared D₀. The retail worked
  example will use a shared baseline with per-task *deltas* (added orders,
  added customers) layered on top.
- **Soft constraint resolution.** `C_soft` with conditional fallback ("if
  price > $X, drop the item") can be resolved at solve time (compute against
  `D₀`'s actual prices) or pre-resolved at authoring time. We default to
  solve-time and revisit if it causes pain.
- **Discoverability check — known gap.** Principle 5 lists discoverability
  as a machine-checkable precondition, but v0 does not actually check it
  formally. Encoding it would require modeling the agent's information state
  (what facts the agent has read so far in the conversation), which is a
  richer formalism than constraints over `D*`. v0 falls back to two coarser
  proxies: (a) Layer D rules (D-CONF-5 and D-CONF-7 in
  [`agent_contract.md`](../data/tau2/domains/retail_returns/agent_contract.md))
  require the agent to have called `get_order_details` and
  `get_customer_details` before mutating, and (b) a hand-audit at
  task-authoring time. Full discoverability is a v1 artifact. The principle
  remains in the methodology because the long-term commitment matters; the
  v0 gap is explicit rather than hidden.

**Locked since v0.1 (no longer open):**
- ~~Multi-action tasks~~ — locked to "at most one mutating action per task"
  in [`actions.md`](../data/tau2/domains/retail_returns/actions.md) §6.

---

## 12. Worked example

See [`data/tau2/domains/retail_returns/`](../data/tau2/domains/retail_returns/)
for the worked-example domain. The current state of the worked example, by
layer:

| Layer | File | Status |
|---|---|---|
| A — Ontology | [`ontology.md`](../data/tau2/domains/retail_returns/ontology.md) | drafted |
| B — World rules | [`rules.md`](../data/tau2/domains/retail_returns/rules.md) | drafted |
| C — Actions | [`actions.md`](../data/tau2/domains/retail_returns/actions.md) | drafted |
| D — Agent contract | [`agent_contract.md`](../data/tau2/domains/retail_returns/agent_contract.md) | drafted |
| E — `D₀` | [`db.json`](../data/tau2/domains/retail_returns/db.json) + [`db_design.md`](../data/tau2/domains/retail_returns/db_design.md) | drafted |
| F — Tasks | `tasks.json` | TODO |

The methodology's success criterion is: by the time all six layers are
populated for retail_returns, we should be able to (a) verify a hand-authored
task, (b) solve a task from spec alone, (c) generate a new task with proven
uniqueness, and (d) hand-write the rendered NL with the consistency check
catching at least one mismatch we would have missed by eye.

---

## 13. Status and changelog

- **2026-05-22** — initial methodology draft. Decisions locked: methodology +
  worked example (no template); behavioral layer as vocabulary (no DSL);
  rendering hand-written with consistency check (no generator). Worked
  example domain: retail returns and refunds. See conversation log.
- **2026-05-26** — §11 updated: "multi-action tasks" item moved to "Locked
  since v0.1" (per actions.md §6); "discoverability check" reframed as a
  known v0 gap with explicit proxies (D-CONF-5 and D-CONF-7), rather than
  a deferred ambition. The principle stays; the v0 limitation is now in
  the open rather than implicit.
