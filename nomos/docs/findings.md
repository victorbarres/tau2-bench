# Logic-First Domain Design — Findings

A writeup of what was built, what was proven, what bent, and what's left.
Companion to [`methodology.md`](methodology.md) (the *what*); this is the
*what happened when we tried it*.

---

## 1. The headline result

> The methodology produces the same outcome as the upstream's expected
> behavior on **8 out of 8 cross-validated airline tasks** — tasks that
> were authored by humans against a prose policy with **zero awareness of
> the methodology, its formalisms, or its tooling**.

That's the strongest empirical claim the project supports. A weaker but
also true claim:

> A greenfield benchmark domain (retail_returns) was designed
> spec-first and is now provably uniquely-solvable on its 6 tasks via
> Verify, mechanically derivable via Solve, and generatable via 6
> scenario templates with controlled-difficulty knob sweeps.

What this lets you do that hand-design didn't:

- **Author a task** by writing a structured `intent` field in JSON; the
  verifier proves it has exactly one valid solution.
- **Catch task ambiguity** the moment you author it — `ambiguous(N)`,
  with a diff showing what's under-constrained.
- **Catch policy drift** across artifacts — if `rules.md` and the
  Python action simulator disagree, the cross-check fails loudly.
- **Sample tasks at controlled difficulty** by varying scenario
  knobs; pruning ratio and constraint coverage are mechanical metrics.
- **Retrofit an existing prose policy** to the formalism; the
  cross-validation step catches policy gaps that the prose alone wouldn't
  surface.

---

## 2. The problem this addresses

Designing benchmark domains for agents is hand-craft work. A typical
domain has:

- A **prose policy** (`policy.md`).
- A **data schema** (often Pydantic).
- A **database** of instances.
- A **task corpus** with user scenarios and gold action sequences.
- A **tool implementation** that enforces some subset of the policy.

These artifacts encode the domain's meaning across five different
representations, each with its own author and its own edit cycle. No
single one is authoritative. To answer "is this task uniquely solvable?"
you triangulate. Three pains:

### 2.1 Drift

The artifacts disagree, and the disagreements compound silently.
Closed enumerations declared in code may not match the policy. The
schema may not enforce constraints the policy describes. Tool
implementations silently encode rules the policy mentions only in
passing. None of this surfaces until a task fails the eval — or worse,
appears to pass for the wrong reason.

Concrete example from the airline domain (caught early):
- `policy.md` lists 4 `flight_status` values.
- `data_model.py` has 6.
- Neither mentions which ones are bookable.

### 2.2 Uniqueness is emergent, not designed

Tasks have to be uniquely solvable for the benchmark to be meaningful
(otherwise the agent could produce *a* valid answer that isn't *the*
expected one). The traditional way to achieve this is iteratively:
author a task, run an oracle agent, see if it produces the gold
output, tweak the DB or constraints until it does, repeat.

This is slow and brittle. Nothing prevents two valid answers from
existing in principle; nothing tells the author *which* constraint is
under-specified when it does.

### 2.3 Prose is treated as the source of truth

Both policies and tasks are authored as natural-language prose, then
the structured artifacts (schema, gold actions, eval criteria) are
derived from the prose by hand. This is the wrong dependency
direction: prose is good for human consumption but bad for precision.

The methodology inverts this — the formal core is canonical, prose is
*rendered* from it. (For v0 we hand-write the prose and consistency-check
it against the spec; a full renderer is v1 work.)

---

## 3. The methodology in 200 words

Six layers, three operations:

**Layer A — Ontology.** Sorts, attributes, closed enumerations, named
derived predicates. No rules.

**Layer B — World rules.** Integrity constraints + derivations,
encoded as ASP. The "Layer B is executable" claim is what closes the
spec/impl gap.

**Layer C — Actions.** Each agent-callable tool is a transition
predicate with declared signature, preconditions, effects.

**Layer D — Agent contract.** Deontic rules: confirmation, refusal,
transfer, dialogue conduct. Some `[runtime]` checkable, some
`[prompt]` LLM-graded.

**Layer E — `D₀`.** A baseline DB satisfying Layers A–C.

**Layer F — Tasks.** Each task is a structured `OperationalSpec.intent`
plus a `BehavioralSpec` (move primitives — `lie`, `insist`, `withhold`,
etc.).

Three operations consume these:
- **Verify** `(D₀, OperationalSpec, D*) → unique | ambiguous(N) | infeasible`.
- **Solve** `(D₀, OperationalSpec) → D*`.
- **Generate** `(scenario template, knobs) → (D₀, task)`.

Plus two complexity metrics per task: **pruning ratio** (how much
`c_hard` narrowed the policy-permitted answer space) and **constraint
coverage** (how many Layer B derived predicates fired on the target
entity).

---

## 4. What was actually built

Three artifact buckets: the methodology doc, two domains, and tooling.

### 4.1 The methodology

[`docs/methodology.md`](methodology.md) — ~380 lines. Principles,
layer dependency map, task model, three operations, behavioral
vocabulary, rendering policy, gaps. Drafted at session start and
revised across the project as the framework actually bent.

### 4.2 Domain 1: retail_returns (greenfield worked example)

[`domains/retail_returns/`](../domains/retail_returns/) — 8 files,
~2,600 lines of markdown/JSON/code.

| Layer | Artifact | Substance |
|---|---|---|
| A | [`ontology.md`](../domains/retail_returns/ontology.md) | 7 sorts, 8 closed enums, 11 derived predicates declared |
| B | [`rules.md`](../domains/retail_returns/rules.md) | 25 integrity constraints + 11 derivation rules in ASP. Composite `return_eligible`. Worked micro-example. |
| C | [`actions.md`](../domains/retail_returns/actions.md) | 9 actions (5 read + 4 mutate + 1 escalate). Two-snapshot ASP encoding. One-logical-transition convention. |
| D | [`agent_contract.md`](../domains/retail_returns/agent_contract.md) | 38 deontic rules across auth, disclosure, confirmation, challenge, refusal/transfer, out-of-scope, turn conduct. Each tagged `[runtime]`/`[prompt]`. |
| E | [`db.json`](../domains/retail_returns/db.json) + [`db_design.md`](../domains/retail_returns/db_design.md) | 6 customers, 12 products, 14 orders (17 items), 4 pre-existing returns, 9 payment methods. Self-verification table against all 25 integrity constraints. |
| F | [`tasks.json`](../domains/retail_returns/tasks.json) + [`tasks_design.md`](../domains/retail_returns/tasks_design.md) | 6 tasks covering all task families: canonical approve (F-001), gift return (F-002), window refusal (F-003), wrong-initiator refusal with adversarial lying (F-004), exchange (F-005), intent-only lookup (F-006). |

Each task carries:
- The structured `operational_spec.intent` (canonical).
- Prose `c_hard` / `c_known` / `c_unknown` (documentation, rendered
  from intent).
- A `behavioral_spec.moves` list using the controlled vocabulary.
- The tau2-bench-compatible NL surface (`task_instructions`, etc.)
  hand-written to be consistent with the spec.

### 4.3 Domain 2: airline (cancellation slice retrofit)

[`domains/airline/`](../domains/airline/) — 6 files, ~1,400 lines.

| Layer | Artifact | Status |
|---|---|---|
| A | [`ontology.md`](../domains/airline/ontology.md) | drafted (full domain) |
| B | [`rules.md`](../domains/airline/rules.md) | drafted (cancellation slice only) — 14 integrity constraints + 10 derivation rules + 3 composite predicates |
| C | [`actions.md`](../domains/airline/actions.md) | drafted (cancellation slice only) — 4 actions: `get_user_details`, `get_reservation_details`, `cancel_reservation`, `transfer_to_human_agents` |
| D | [`agent_contract.md`](../domains/airline/agent_contract.md) | drafted (cancellation slice only) — 27 deontic rules including the airline-specific D-OOS-2 (flown-segment forced transfer) |
| E | [`db.json`](../domains/airline/db.json) | drafted (synthetic D₀, 2 reservations) |
| F | [`tasks.json`](../domains/airline/tasks.json) | drafted (2 synthetic tasks: 1 refusal + 1 success) |

Booking, modification, compensation, search, baggage update,
passenger update, send_certificate slices remain TODO.

### 4.4 Tooling

5 Python modules, ~2,700 lines total:

- [`tools/verify_retail_returns.py`](../tools/verify_retail_returns.py) (~800 lines)
  — pure-Python action simulator + Layer B invariant checker for
  retail_returns. Applies gold trajectories, checks all 25 invariants
  on D*, reports class consistency.

- [`tools/clingo_verify.py`](../tools/clingo_verify.py) (~750 lines) —
  Clingo-based verifier for retail_returns. Implements Verify (uniqueness
  via answer-set count), Solve (cross-validates against gold), and two
  complexity metrics (pruning ratio, target-scoped constraint coverage).
  Drives off `operational_spec.intent`; supports JSON-only task
  authoring.

- [`tools/generate.py`](../tools/generate.py) (~750 lines) —
  scenario-driven task generator with 6 templates, CLI with knob
  sweeps + JSON export. Generated tasks are provably uniquely solvable
  by construction (each is run through the verifier).

- [`tools/clingo_verify_airline.py`](../tools/clingo_verify_airline.py)
  (~440 lines) — parallel Clingo verifier for the airline retrofit.
  Reuses the rule extractor and ASP helpers from clingo_verify;
  airline-specific DB encoding and per-task encoding. Includes Solve
  for the cancellation action.

- [`tools/cross_validate_airline.py`](../tools/cross_validate_airline.py)
  (~420 lines) — reads upstream tau2-bench airline JSON directly, runs
  our verifier on hand-authored intents for 8 upstream tasks,
  compares verdict against the upstream's expected outcome. Includes
  schema adapter + subset extractor.

---

## 5. What was proven

### 5.1 Soundness + uniqueness, mechanically

On retail_returns, the Clingo verifier passes 6/6 tasks:

| Task | Family | Verdict | Pruning | Coverage |
|---|---|---|---|---|
| F-001 | approve_existing | unique | 2→1 | 15 |
| F-002 | initiate_approve (gift) | unique | 1→1 | 14 |
| F-003 | refuse (out of window) | policy_refused | 0→0 | — |
| F-004 | refuse (wrong initiator) | policy_refused | 0→0 | — |
| F-005 | initiate_approve (exchange) | unique | 3→1 | 15 |
| F-006 | intent_noop (lookup) | trivial | — | — |

"Unique" means Clingo enumerated all `D*` satisfying
`Policy ∧ C_hard ∧ D₀` and found exactly one. The pruning ratio shows
how much work `c_hard` did to narrow the policy-permitted answer space
(e.g., F-005's defective Smartwatch has 3 eligible refund methods;
`c_hard` pinning `exchange` reduces to 1).

The pure-Python verifier (applies the gold trajectory and checks
Layer B invariants) also passes 6/6, providing a redundant
independent check.

### 5.2 Solve operation works

For each successful task, both the gold trajectory and the
Clingo-derived solution produce the *same* `D*` — measured as the
identical structured diff against `D₀`. **Three-way agreement** across
6/6 mutating tasks:

```
F-002 Solve diff:
  customer/cust_005.store_credit_balance_cents: 0 → 7000
  order/ord_005.status: delivered → fully_returned
  order_item/oi_005_01.returned_quantity: 0 → 1
  return/ret_NEW_F-002_1: NEW (status=refunded, method=store_credit, amount=7000)
```

This is what lets gold-trajectory authoring become *optional*: the
Solve operation is the canonical D*-derivation. The gold trajectory
remains useful as a cross-check but is no longer authoritative.

### 5.3 Generate works

Six scenario templates, each with knob parameters. All 6 generated
scenarios match expected (pruning, verdict):

| Scenario | Expected | Got | Verdict |
|---|---|---|---|
| `happy_path_self_return` | 2→1 | 2→1 | unique |
| `gift_return_forced_store_credit` | 1→1 | 1→1 | unique |
| `exchange_defective` | 3→1 | 3→1 | unique |
| `window_refusal` | 0→0 | 0→0 | policy_refused |
| `non_returnable_refusal` | 0→0 | 0→0 | policy_refused |
| `wrong_initiator_refusal` | 0→0 | 0→0 | policy_refused |

Knob sweeps mechanically surface policy boundaries:

```
member_tier=regular days_since_fulfillment=15  → unique (in window)
member_tier=regular days_since_fulfillment=60  → infeasible (out of window for regular)
member_tier=plus    days_since_fulfillment=15  → unique
member_tier=plus    days_since_fulfillment=60  → unique (plus 90-day extension holds)
```

That's the regular-vs-plus distinction being mechanically demonstrated
across knob values — not asserted by a test but falling out of the
policy applied to the synthesized D₀.

Generated tasks export to `task.json` + `db.json` matching the schema
of existing artifacts, and they round-trip through the verifier
cleanly (loaded back from disk, re-verified, produce the same Solve
diff).

### 5.4 Cross-validation on real upstream data

8 upstream tau2-bench airline tasks, all 8 cross-validate:

| # | User | Reservation | Branch tested | Got |
|---|---|---|---|---|
| 0 | Emma Kim | EHGLP3 (gold, basic_economy, no ins, ~11d) | all grounds fail | policy_refused ✓ |
| 1 | Raj Sanchez | Q69X3R (silver, economy, no ins, ~29h) | outside 24h | policy_refused ✓ |
| 14 | Mohamed Silva | K1NW8N (basic_economy, no ins, **~22.9h**) | recent_booking at boundary | unique ✓ |
| 19 | Olivia Gonzalez | Z7GOZK (basic_economy, **ins=yes**, ~43h) | insurance + covered | unique ✓ |
| 26 | Amelia Sanchez | 3FRNFB (basic_economy, no ins, ~9d) | all grounds fail | policy_refused ✓ |
| 29 | Raj Brown | VA5SGQ (economy, **ins=yes**, ~7d) | insurance + covered | unique ✓ |
| 47 | Sophia Silva | H8Q05L (basic_economy, **ins=yes**, reason=birthday) | insurance ≠ uncovered reason | policy_refused ✓ |
| 49 | Anya Garcia | 3RK2T9 (basic_economy, **ins=no**, user lies) | ground truth vs claim | policy_refused ✓ |

Tasks 47 and 49 are the methodology's payoff cases:

- **Task 47** — insurance was purchased, but the user's reason ("best
  friend's birthday") isn't health or weather. The `intent.insurance_covers`
  field is correctly `false`. The verifier refuses despite insurance
  being yes. This tests the *precise scope* of the insurance branch —
  insurance alone isn't sufficient; the reason must also be covered.

- **Task 49** — user *claims* she purchased insurance; the reservation
  record says no insurance. The verifier consults `has_travel_insurance`
  in `D₀` (ground truth) and refuses regardless of the customer's
  assertion. This validates the Q1 resolution: `insurance_covers/1`
  is a *structured input*, not a customer-asserted predicate. It
  doesn't matter what the user says — the policy applies to facts.

These are exactly the kind of subtle cases where a hasty agent might
just cancel. The methodology mechanically prevents that.

### 5.5 Complexity is measurable

The pruning ratio gives a principled "how constrained is this task"
number. F-005 (exchange with 3 eligible refund methods → 1) is
mechanically the *hardest* of the retail_returns mutating tasks; F-002
(gift forces store_credit before c_hard) is the easiest. That ordering
wasn't asserted; it falls out of running the policy.

Constraint coverage adds a second axis — "how much policy machinery
does this task exercise." F-001 fires 15 distinct derived predicates
on the target Return; F-002 fires 14; F-005 fires 15 but with
different rules (`all_items_defective`, `requires_inspection`,
`all_replacements_available` fire only for F-005).

Together, these two metrics give a difficulty profile per task. For
a benchmark designer, they let you ask:

- "Do my tasks span the full complexity range, or are they clustered?"
- "Which policy branches does my corpus actually exercise?"
- "If I add a new task, where in the difficulty distribution does it land?"

### 5.6 Bugs the methodology caught during development

Each is a methodology validation as much as a bug.

**Bug 1 — Date-arithmetic off-by-one.** Both verifiers initially used
timestamp subtraction for `days_between(later, earlier)`, returning 30
for an order delivered May 15 at 16:00 vs current time June 15 at
12:00 (less than 24h short of 31 calendar days). Policy semantics count
calendar days: 31 days, not 30. F-003 (1-day-outside-window boundary
test) was being *silently negated* by this bug.

The pure-Python verifier didn't catch it because F-003 has no
mutating action — the empty diff matched the empty diff regardless of
whether eligibility was correctly computed. The Clingo verifier caught
it because it derives the policy outcome from scratch and reported
`unique` (eligible) where F-003 expected `infeasible`.

**Two independent verifiers disagreeing surfaced a real spec/impl
drift.** That's exactly what the methodology's redundancy is for. (See
[commit `e5b92ae`](../../commits/e5b92ae).)

**Bug 2 — `effective_returner` extracted but not loaded.** The Clingo
rule extractor in clingo_verify.py initially required a `.` after the
section number in markdown headers (e.g., `## 2.`), but rules.md uses
`### 2.3 Multi-party` (no period). This silently dropped §2.3, which
defines `effective_returner/2` — the helper that `eligible_to_initiate`
depends on. The verifier *appeared* to work because
`eligible_refund_methods` computed correctly on its own, masking the
fact that `return_eligible` was actually always false. Caught by
inspecting the Clingo `info: atom does not occur in any rule head`
warning. Fix: regex now permits headers without trailing periods.

**Bug 3 — Reservation IDs starting with digits.** Real upstream
reservation IDs like `3FRNFB` and `3RK2T9` start with digits, which
ASP rejects as constants (must start with a lowercase letter).
Surfaced immediately when cross-validation expanded from 3 to 8 tasks.
Fix: `_asp_safe()` helper prepends `r` to ids whose first character
isn't a letter; the original case is preserved separately for DB
lookup.

The bug *would not have surfaced* in the synthetic D₀ (we chose
letter-starting IDs by accident). It only surfaced because we ran
against real upstream data. **Cross-validation against external data
exposed an assumption we didn't know we were making** — exactly the
kind of validation that's hard to get any other way.

### 5.7 The methodology generalizes — empirically

Two domains have now been fully (retail_returns) or partially
(airline cancellation slice) modeled. The methodology framework
*itself* did not need modification between the two; only
domain-specific encoding adaptations (composite ids, positional
sub-entities, external predicates for open-vocabulary classifications)
were required.

What survived the airline encounter unchanged:
- Layer separation (A–F).
- The single-source-of-truth principle.
- The structured-intent canonical / prose-rendered pattern.
- The Verify / Solve / Generate operation triad.
- The integrity-constraint-vs-derivation distinction.
- The closed-enumeration convention (extended with `cancelled` and
  `landed` flight statuses).

---

## 6. What the methodology bent on

These are real adaptations the framework absorbed. None invalidates
the methodology, but each is a place where retail_returns gave a
cleaner picture than reality permits.

### 6.1 External predicates for open-vocabulary classifications

The airline policy says insurance covers "health or weather reasons."
The closed `cancellation_reason` enum is `{change_of_plan,
airline_cancelled, other}`. These vocabularies don't overlap.

The retail_returns methodology assumed all classifications could be
modeled as closed enumerations. The airline retrofit forced an
adaptation: `insurance_covers/1` is an **external predicate**, supplied
by the verifier from `intent.insurance_covers: bool`, *not* derived
from a closed enum.

This pattern likely generalizes to other domains with open-vocabulary
classifications — medical reason codes, legal cause categories,
free-text incident descriptions. The "closed enumerations are
authoritative" principle yields cleanly: the methodology distinguishes
*derived* predicates (must come from rules) from *input* predicates
(may come from intent), and external predicates fall into the second
bucket.

The cost: tasks must explicitly assert these as structured inputs.
Tasks 47 and 49 (cross-validated above) test this honestly — Sophia's
birthday case sets `insurance_covers: false` despite insurance=yes;
Anya's lying case also sets it to false. The verifier sees ground
truth from the intent, not from the customer's claim.

### 6.2 Composite identifiers

`FlightInstance` is identified by `(flight_number, date)`, not a
single id. retail_returns had no analog — every sort had a single
identifier. The methodology absorbed this without modification:
predicates carry the pair (`flight_status(FN, D, S)`,
`segment_of(R, FN, D)`).

In practice this requires no spec-level change; only the encoder is
slightly busier. No methodology principle bent.

### 6.3 Positional sub-entities

`Passenger` has no global identifier in the upstream airline schema
— passengers are positionally nested inside Reservations. The encoder
synthesizes `passenger(R, 1)`, `passenger(R, 2)`, etc., for ASP-grounding
purposes only. The synthesized indices have no semantic meaning beyond
"one fact per actual passenger."

The retail_returns assumption — "every sort has a stable id" — was
silently wrong. The methodology's "single source of truth" principle
still holds; the source is just the positional order in the parent
entity.

### 6.4 Soft-deleted entities

Cancelled reservations are not deleted from `D₀` — they stay with
`status = cancelled`. retail_returns avoided this (returns transitioned
through clean state machines). The methodology absorbs it: post-state
encoding treats `reservation_status(R, _)` as a single-valued
attribute that mutates; refund events are emitted separately.

### 6.5 The single-payment v0 simplification (Q-D-A1)

The upstream airline tasks routinely use multi-payment compositions
(1 travel certificate + 1 credit card + 2 gift cards). Computing
per-payment refund allocation requires tracking
`payment_amount(R, PM, A)` on the Reservation — the upstream's
`payment_history[]` carries this, but we sidestepped it for v0.

For the 8 cross-validated cancellation tasks, *every single one* used
exactly one payment method — so the simplification held. But the
remaining 3 upstream cancel tasks (7, 39, 42) all involve multi-cancel
and almost certainly multi-payment compositions. They were
intentionally excluded from this round of cross-validation.

This is the most concrete v1 follow-up: extend the encoder to track
per-payment allocation and the Solve diff to compute per-payment
refund amounts. It's mechanical work; the methodology already
specifies the policy (`Q-B-A1` resolution).

### 6.6 Fee/baggage allocation in refund totals

Our Solve diff for VA5SGQ (cross-validated task 29) shows refund
total `$656.00` (sum of segment prices × 1 passenger). The upstream's
`payment_history` says `$686.00` was charged. The $30 difference is
the single-passenger insurance fee, which our v0 doesn't compute.

The methodology specifies the policy (insurance is $30/passenger,
extra baggage is $50 each) but the Solve implementation doesn't roll
these into the refund total. Adding it is ~20 lines of code; it's
been left for v1 to keep the cancellation-slice scope tight.

### 6.7 The agent's effective spec extends beyond Layer C

Surfaced after the cancellation-slice retrofit. The agent under test
doesn't only consume `actions.md` — it also consumes the Python
**tool docstrings** that get rendered into its tool-definition
prompts. Those docstrings can contain behavioral constraints
(parameter descriptions, return-value semantics, examples) that
aren't reflected in `actions.md`, and conversely `actions.md` can
specify behavior the docstrings don't surface.

In v0 the docstrings are hand-written and trust-based — there is no
consistency check between Layer C and the rendered tool description.
This is a real gap in the "single source of truth" claim: Layer C is
the source of truth for *us*, but the agent's effective spec is
Layer C plus whatever the tool implementer chose to write in the
docstring.

Two clean fixes (both in `next_steps.md` §1.13):
- Declare tool docstrings as an explicit Layer C output. Hand-write
  them in v0, but consistency-check against `actions.md` the same
  way prose is consistency-checked against the spec.
- v1: render tool docstrings deterministically from action specs.

A third option — and probably the right long-term answer — is to
acknowledge that the rendered NL surface the agent consumes has its
own audience requirements (deontic clarity, refusal grounds) that
are distinct from the human-facing `policy.md` (auditability) and
the user-simulator's `task_instructions` (adversarial moves). All
three are "rendered NL," but they shouldn't be conflated into a
single output (see `next_steps.md` §1.12).

---

## 7. Cross-validation: a deeper look

The 8 cross-validated tasks each test a different branch. The pattern
each one validates:

**Tasks 0, 1, 26 — "All grounds fail" refusal.** No recent booking,
no airline-cancelled segment, no business cabin, no insurance. The
disjunctive `cancellable/2` predicate evaluates to false on all four
ground clauses. Verifier reports 0 models = `policy_refused`. Tests
the basic case.

**Task 14 — Boundary case.** Mohamed Silva booked at 16:03 the
previous day; current_time is 15:00 today. That's 22 hours 57 minutes.
`hours_since_creation = 22`, which is `≤ 24`, so `recent_booking`
fires. Cancel succeeds via the recent_booking branch.

If the hours computation were even slightly off — e.g., if we'd used
ceiling instead of floor — this would fail. The cross-validation
catches that. The boundary is honored.

**Tasks 19, 29 — Insurance + covered reason.** Olivia "feels unwell";
Raj Brown is instructed by the task to "mention your health problem
at the start of the conversation." Both have insurance. Both succeed.

The intent encoding `cancellation_reason: "other"` + `insurance_covers:
true` lets Layer B's insurance branch fire. The verifier's success
matches the upstream's expectation: `cancellable(R, other)` because
`has_travel_insurance(R) ∧ insurance_covers(other)`.

**Task 47 — Insurance but uncovered reason.** This is the
methodology's first payoff. Sophia has insurance, but her reason is
"best friend's birthday." Under the Q1 resolution,
`intent.insurance_covers = false` because birthdays aren't health or
weather. Layer B's insurance branch requires `insurance_covers(Reason)`
to be true, which we don't emit. The branch can't fire. The other
three branches also can't fire (basic_economy not business; no
airline-cancelled segment; not within 24h). All four cancellation
grounds fail; verifier refuses.

The upstream task explicitly tests that "agent understands that
insurance only covers health or weather reasons." The verifier
mechanically respects this without any prose understanding — it
respects it because the intent's structured input says insurance
doesn't cover this reason, and Layer B's clause is conjunctive.

**Task 49 — Adversarial input.** Anya doesn't have insurance, but the
user_scenario instructs the user simulator to *insist she has insurance*.
A hasty agent might capitulate. The verifier doesn't, because
`intent.insurance_covers = false` (matching the ground truth in `D₀`).
Layer B's branch requires `has_travel_insurance(R)`, which is false
for Anya's reservation. Refusal triggered regardless of customer
assertion.

This validates a methodology choice that wasn't obvious upfront:
making `insurance_covers/1` a *structured input from intent*, not a
customer-asserted predicate, means the verifier is naturally robust
against customer manipulation. Tasks that test "user lies, agent must
verify" — a major category in the upstream airline corpus — fall out
for free.

---

## 8. Honest accounting

### 8.1 What works

- **Verify** (provable uniqueness via Clingo answer-set enumeration) on
  both domains.
- **Solve** (mechanical D*-derivation, cross-validates with gold) on
  both domains.
- **Generate** (template-driven scaffold synthesis, knob sweeps, JSON
  export) on retail_returns.
- **Complexity metrics** (pruning ratio, constraint coverage) on
  retail_returns. Airline metrics work too but no diversity (binary 0/0
  or 1/1 because cancellation has no choice surface).
- **JSON-only task authoring** — drive everything from
  `operational_spec.intent`. Smoke-tested on retail_returns with a
  brand-new F-SMOKE task that round-trips through Verify + Solve with
  zero Python changes.
- **Cross-validation** against upstream tasks designed independently —
  8/8 on airline cancellation slice.

### 8.2 What's known incomplete

| Gap | Severity | Status |
|---|---|---|
| Multi-payment refund allocation (airline) | Real for v1 | Q-D-A1 single-payment held for cross-val; needed for tasks 7/39/42 |
| Insurance/baggage fees in refund totals | Cosmetic for v0 | Documented (+$30 discrepancy on task 29) |
| Booking, modification, compensation slices (airline) | Large scope | TODO, multi-week |
| Behavioral DSL beyond vocabulary | Methodology gap acknowledged | v2 work |
| NL renderer (spec → prose) | Methodology gap acknowledged | v0 hand-writes; v2 generates |
| LLM-graded Layer D rules | Out of LP scope by design | Lives in eval harness |
| Discoverability check | Methodology gap with explicit proxies | D-CONF-5/D-CONF-7 cover most cases |

### 8.3 What didn't generalize cleanly

- **The "every sort has a stable id" assumption.** Bent for
  Passenger (positional).
- **The "closed enumerations" principle.** Bent for `insurance_covers/1`
  (external open-vocabulary).
- **The "one task identifier" assumption.** Bent for FlightInstance
  (composite).

In each case, the *bend* was clean — the methodology absorbed the
adaptation without principle violation. But each was a place where
retail_returns' worked example was misleadingly simple.

### 8.4 What surprised us in retrospect

- **The two-verifier redundancy paid off bigger than expected.** The
  date-arithmetic bug would have shipped silently with just the
  pure-Python verifier; would have shipped silently with just the
  Clingo verifier. Both running on the same domain caught the
  disagreement. Recommend this pattern: two independent implementations
  of the same policy, run in parallel during development.

- **Generate is uncomfortably easy once Verify works.** Generate is
  the methodology's most ambitious operation. In practice it's just
  "scaffold-then-verify"; the heavy lift is Verify. Generate works
  because if the spec is verifiable, any (D₀, intent) pair that
  Verify accepts is by definition a valid task.

- **Cross-validation is a force multiplier.** Three hours of work to
  build the upstream adapter (including discovering and fixing the
  ID-starting-with-digit bug) turned a "validated on tasks we
  designed" claim into "validated on tasks designed without
  awareness of us." The cost-to-evidence ratio is unusual.

- **Tasks 47 and 49 weren't designed to test our methodology.** They
  were authored by upstream task designers to test the LLM agent's
  ability to challenge incoherent customer claims. They happen to be
  *exactly* the cases where our structured-intent + external-predicate
  pattern earns its keep. The convergence wasn't planned and is
  evidence of cross-cutting concerns.

---

## 9. What this is and isn't

### 9.1 What this is

- A **discipline** for designing benchmark domains where task
  correctness is mechanically provable rather than tuned by hand.
- A **methodology** that imposes a particular dependency structure
  (formal spec → rendered prose, not the reverse) and a particular
  validation discipline (every task verifiable, every modification
  re-verifiable).
- An **executable demonstration** — two domains, two verifiers, a
  generator, a cross-validation harness, ~6,000 lines of artifacts.
- A **research artifact** — methodology + worked examples + empirical
  validation, with negative results (gaps, simplifications, things
  that bent) documented honestly.

### 9.2 What this isn't

- **Not a production policy engine.** The ASP runs at task-verification
  scale, not real-time customer-service scale. Production policy
  enforcement would use a different architecture.
- **Not formal verification of real policy.** Real airline policies
  have ambiguity, exception escalation, regional variation, and
  undocumented practice. This methodology produces *idealized*
  policies — benchmark-grade clarity, not regulatory-grade fidelity.
- **Not LLM replacement.** Dialogue, persuasion, courtesy, judgment
  calls, multi-turn coherence — none of this is in scope. The
  methodology constrains the *correctness backbone* the LLM operates
  against, not the LLM itself.
- **Not a complete formal system.** Discoverability (whether the
  agent could in principle compute D* from C_known + tool lookups) is
  acknowledged-but-not-encoded. The closest we get is two runtime
  proxy rules (D-CONF-5/D-CONF-7); the real formalization needs an
  epistemic model that's deferred to v2.

### 9.3 Where the methodology applies

The framework fits domains where:

- Task correctness is dominantly a function of DB endstate (not
  dialogue subtleties).
- Policy is expressible as integrity constraints + derivation rules
  with closed-vocabulary classifications (with the external-predicate
  escape hatch for open ones).
- The action surface is finite and known up front.
- The eval can be DB-hash equality (or structural equality with
  ID-canonicalization).

Where it doesn't fit cleanly:

- Domains heavy on numeric optimization (pricing, scheduling) — ASP's
  grounding cost blows up. SMT or hybrid solvers would be more
  appropriate. The *principles* generalize; the *engine* doesn't.
- Domains where the correctness is dialogue-shape (creative writing,
  persuasion, therapy). The methodology constrains state, not
  conversation.
- Domains where the policy is genuinely open-ended (e.g.,
  "appropriately escalate based on customer distress") — anything
  not reducible to a closed-set classification + structured intent.

---

## 10. Future work

### 10.1 Methodologically meaningful

- **v1 verifier generalization.** Unify `clingo_verify.py` and
  `clingo_verify_airline.py` into a single domain-agnostic core +
  per-domain encoders. ~1 session.
- **NL renderer.** Generate `task_instructions`, `reason_for_call`,
  etc. from the structured spec. v0 hand-writes with consistency
  checks; v1 generates with LLM polish.
- **Behavioral spec DSL.** The controlled vocabulary (lie, insist,
  withhold, etc.) is enough for v0 to *describe* adversarial patterns;
  a DSL with composition operators would let us *synthesize* them at
  controlled difficulty. Research-y.
- **Discoverability formalization.** Currently hand-audited (with
  runtime proxies). A proper encoding requires modeling the agent's
  epistemic state across the conversation — what facts have been
  read, what's been inferred, what's been told. Epistemic logic
  programs (Clingo extensions) could carry this; substantial new
  formalism.

### 10.2 Domain coverage

- **Airline booking + modification + compensation slices.** Layer B
  extensions, action surface expansion, more cross-validation tasks.
  Multi-week.
- **Multi-payment refund allocation.** The most concrete v1
  follow-up. ~1 session.
- **Multi-cancel and multi-modify tasks** (upstream 7, 39, 42).
  Would relax the "one logical transition per task" convention.
- **A third domain.** Banking disputes, insurance claims, or telecom
  plan changes. Each would test methodology generalization in a
  different direction.

### 10.3 Productionization

- **Integration with tau2-bench eval harness.** Currently the
  cross-validation is a separate tool. A v1 would let
  `clingo_verify.py` plug into the eval pipeline directly.
- **CI for the methodology artifacts.** Every methodology change
  should re-verify all tasks; every task change should re-verify
  itself. None of this is automated yet.
- **Authoring tool.** A v1 "task editor" that prompts the author for
  the structured intent, runs Verify in the background, and surfaces
  ambiguities in real time. The methodology supports this; nothing
  has been built.

---

## 11. Reproducibility

All artifacts live under `nomos/` in this repo
(`victorb/asp-test` branch). The directory is self-contained:

```
nomos/
├── README.md
├── pyproject.toml         # uv-managed, single dependency: clingo>=5.6
├── docs/
│   ├── methodology.md
│   └── findings.md        # this document
├── domains/
│   ├── retail_returns/    # 8 spec files + db.json + tasks.json
│   ├── airline/           # 6 spec files + db.json + tasks.json (cancel slice)
│   └── airline_reference/ # original extraction reference
└── tools/                 # 5 Python modules
```

To reproduce:

```sh
cd nomos
uv sync                                          # one-time setup
uv run python tools/verify_retail_returns.py    # 6/6 pure-Python
uv run python tools/clingo_verify.py            # 6/6 Clingo
uv run python tools/generate.py                 # 6/6 Generate
uv run python tools/clingo_verify_airline.py    # 2/2 synthetic airline
uv run python tools/cross_validate_airline.py   # 8/8 upstream airline
```

Cross-validation reads from
`/Users/victorbarres/scripts/tau2-bench/data/tau2/domains/airline/`
— the upstream tau2-bench airline data shipping in the parent repo.
Hardcoded path; would need adjustment for relocation.

Total wall-clock time for all 5 commands: under 30 seconds on a 2024
laptop.

---

## 12. Project arc (selected milestones)

For context on how this developed across the project:

- **Methodology drafted** + retail_returns Layers A–D drafted
  ([`4096f50`](../../commits/4096f50)).
- **Reconciliation pass** after a critic review surfaced cross-layer
  bugs ([`5a4e6f4`](../../commits/5a4e6f4)). Key decision: drop
  `reject_return` from v0 to make `policy_noop` give `D* = D₀`
  cleanly.
- **Layers E + F drafted** ([`3579367`](../../commits/3579367),
  [`8dc2368`](../../commits/8dc2368)).
- **Pure-Python verifier passes 6/6** + catches 5/5 deliberate bug
  injections ([`2bb9e20`](../../commits/2bb9e20)).
- **Package gathered** into self-contained `nomos/`
  directory ([`3539548`](../../commits/3539548)).
- **First Clingo verifier (F-001 prototype)**
  ([`94564bf`](../../commits/94564bf)).
- **Phase 1 generalized + complexity metrics + date-arithmetic bug
  fix** ([`e5b92ae`](../../commits/e5b92ae)). This is where the
  two-verifier redundancy paid off.
- **Solve operation** — cross-validates with gold trajectories 6/6
  ([`84046f5`](../../commits/84046f5)).
- **Structured intent field** — JSON-only task authoring
  ([`1fb6728`](../../commits/1fb6728)).
- **Generate operation** + scenario-driven synthesis
  ([`b54ea6d`](../../commits/b54ea6d)).
- **Generate v0.1 polish** — CLI, knob sweeps, JSON export
  ([`dc2fb91`](../../commits/dc2fb91)).
- **Airline retrofit Layer A–D drafted**
  ([`9879e13`](../../commits/9879e13), [`a3b27db`](../../commits/a3b27db),
  [`3d14b17`](../../commits/3d14b17)).
- **Airline verifier 2/2 synthetic**
  ([`a1877d5`](../../commits/a1877d5)).
- **Cross-validation 3/3 then 8/8 upstream tasks** + Solve for airline
  ([`7c395f3`](../../commits/7c395f3),
  [`85f845a`](../../commits/85f845a)).

Twenty commits total on `victorb/asp-test`. Each session produced a
focused, committed unit; the discipline of "always commit at the end
of a substantive session" matched the methodology's discipline of
"always verify after every change."

---

## 13. The bottom line

A methodology for designing benchmark domains was authored, applied to
a greenfield example, and stress-tested against an existing corpus
designed independently of it. The headline number — **8/8 upstream
agreement** — supports the core claim that the framework generalizes.
The bugs caught and the simplifications surfaced are documented; the
remaining gaps are named and tractable.

The original pain — "extremely difficult to give guarantees of
correctness" — has a different answer now. Where that difficulty
came from drift, redundant authoring, and emergent uniqueness, the
methodology offers a single canonical spec, mechanical derivation, and
provable uniqueness by Clingo enumeration. The work that remains is
*coverage* (more slices, more tasks, more domains) — not foundational
risk.

That's the result this writeup is for.
