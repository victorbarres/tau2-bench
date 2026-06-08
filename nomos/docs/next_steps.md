# Next Steps

A structured roadmap for extending this work. Items are grouped by
*payoff shape* rather than ranked by importance — different goals
prioritize different tiers.

The four tiers:

- **Tier 1 — Mechanical / immediate.** Small commits, well-defined,
  low risk. Each is a single focused session.
- **Tier 2 — Coverage extension.** Multi-session but tractable.
  Adds breadth without methodology changes.
- **Tier 3 — Methodologically interesting.** Research-y. Each item
  could be a paper or a substantial extension.
- **Tier 4 — Productionization.** Integration work to make the
  methodology operable in a real benchmark pipeline.

Each item lists:
- **Why it matters** — what becomes possible / cheaper / safer.
- **Dependencies** — what has to exist first.
- **Effort estimate** — sessions of focused work.

A **decision guide** at the bottom suggests where to start based on
specific goals.

---

## Tier 1 — Mechanical / immediate

### 1.1 Multi-payment refund allocation (airline Q-D-A1 v1)

**Status**: known v0 gap. Currently airline's Solve assumes one
payment method per reservation and refunds the full amount to it.
Real upstream tasks routinely use compositions (1 cert + 1 card + 2
gift cards).

**Why it matters**: unblocks cross-validation of multi-cancel
upstream tasks (7, 39, 42). Closes the most concrete gap in the
airline retrofit.

**Dependencies**: none.

**Effort**: ~1 session.

**Sketch**:
- Extend the upstream-to-our adapter to preserve `payment_history`
  with `(payment_id, amount)` tuples.
- Add `payment_amount(R, PM, A)` to the Reservation attributes
  (ontology.md §3.5).
- Update `apply_cancel_reservation()` to dispatch per-payment refund
  using the stored amounts rather than the segment-sum approximation.
- Verify the same 8 cross-val tasks still pass (they should — they
  all happen to be single-payment).

### 1.2 Insurance / baggage fee allocation in refund totals

**Status**: known v0 gap. Refund totals are computed as segment-sum ×
passengers. Insurance ($30/passenger) and extra baggage ($50 each)
aren't included. The $30 discrepancy on task 29's Solve output is
this gap surfacing.

**Why it matters**: makes Solve diffs match upstream payment_history
exactly. Cosmetic for cross-validation pass/fail; useful for any
benchmark integration where the refund amount is checked.

**Dependencies**: 1.1 (per-payment allocation) is a natural
prerequisite.

**Effort**: ~30 minutes after 1.1 is done.

**Sketch**:
- In `reservation_total_cents()`, add insurance cost iff
  `has_travel_insurance` and extra-baggage cost based on
  `nonfree_baggages`.
- Constants are already in ontology.md §5.

### 1.3 Unify the two Clingo verifiers

**Status**: `clingo_verify.py` and `clingo_verify_airline.py` share a
lot — rule extraction, ASP atom formatting, solve wrapper — but
diverge on DB encoding and per-task encoding. Currently they're
parallel with one import.

**Why it matters**: every new domain currently requires duplicating
the verifier scaffold (~400 lines). A unified verifier would let
each new domain plug in just an `encode_db` + `encode_task` pair.
Makes the methodology *deployable* to new domains, not just
demonstrable.

**Dependencies**: none.

**Effort**: ~1 session.

**Sketch**:
- Extract a `tools/lp/` package:
  - `lp/extract.py` — rules.md → ASP source (already domain-agnostic).
  - `lp/solve.py` — Clingo wrapper, model parsing.
  - `lp/coverage.py` — constraint coverage metric.
  - `lp/verify.py` — Verify orchestration.
- Each domain provides:
  - `domains/<X>/encoder.py` — `encode_db(db) → str`, `encode_task(task, db) → TaskEncoding`.
  - `domains/<X>/simulator.py` — Python action functions for Solve.
- `tools/verify.py <domain>` becomes the single entry point.

### 1.4 Negative-test mode for Generate

**Status**: Generate currently produces valid tasks only. There's no
mode to confirm "the verifier catches deliberately bad specs."

**Why it matters**: regression protection. If a Layer B rule
silently weakens (e.g., a typo'd predicate name that makes
`cancellable` always true), the existing test suite wouldn't catch
it because all our test tasks expect success.

**Dependencies**: none.

**Effort**: ~1 session.

**Sketch**:
- Per scenario, define a small set of "this should fail" mutants
  (e.g., happy_path with `c_hard.refund_method = nonsense`).
- Generator emits the mutant; verifier should report
  `infeasible`/`ambiguous`/`error`; CI fails if any mutant *passes*.

### 1.5 Methodology version bump + changelog discipline

**Status**: the methodology doc has a changelog at the bottom but
isn't versioned. No way to refer to "methodology v0.1.0".

**Why it matters**: if anyone external picks up the methodology,
they need a stable version number to reference. Also useful
internally when retrofit decisions change (e.g., Q1 was resolved
one way; if v1 resolves it differently, we want to point to the
previous resolution by version).

**Dependencies**: none.

**Effort**: ~30 minutes.

**Sketch**:
- Add `VERSION` constant (`v0.1.0`) to methodology.md header.
- Each substantive methodology change bumps the patch version.
- Cross-link from findings.md and README.md.

### 1.6 More retail_returns Generate scenarios

**Status**: 6 scenarios cover the main task families. There are
specific edge cases worth adding: defective-claim-without-replacement,
opened-unused-non-standard, perishable-defect-48h-boundary, etc.

**Why it matters**: more variety in the synthesized benchmark
corpus; tests more policy branches.

**Dependencies**: none.

**Effort**: ~30 minutes per scenario; ~1-2 sessions for 5-10
scenarios.

### 1.7 Render `next_steps.md` to HTML and link from README

**Status**: this doc. Should be rendered like findings.md and
methodology.md.

**Why it matters**: same as the others — single-file shareable HTML.

**Dependencies**: none (already in `render_doc.py`).

**Effort**: 1 command.

**Action**:
```sh
uv run python tools/render_doc.py next_steps
```

### 1.8 Solo-mode / direct-task runner

**Status**: prototype done for the library micro-world
([`tools/library_solo.py`](../tools/library_solo.py)). Oracle mode
passes 3/3, grader negative-tested on 3 deliberate bug shapes
(success-claim on refusal task, wrong refusal reason, refuse on happy
path). LLM mode wired via litellm (`uv sync --extra solo`) and
import-verified; live evaluation pending an API-keyed run.

**What's still open**:
- Generalize to retail_returns (9 actions, multi-payment refunds,
  c_hard structural checks). Reuses the same `Ticket → World → Grader`
  shape; the World class grows but the grader contract is identical:
  compare final DB to Solve-derived D*.
- Cross-check against tau²-bench's existing `LLMSoloAgent` so the two
  agree on which tasks are "solo-solvable" (the airline cancel slice
  is the obvious cohort, since cross_validate_airline already proves
  D*-equivalence).
- Difficulty signal: report per-model pruning ratio + tool-call count
  alongside pass/fail, so a model that brute-forces (reads everything)
  vs. one that plans (reads only what `can_borrow` needs) is
  distinguishable.

**Why it matters**: lets you measure the *policy-reasoning* difficulty
of a task independent of the dialogue. Given a structured intent, the
agent already has enough information to solve directly. tau²-bench
already has a "solo" mode but only for telecom; this generalizes.

### 1.9 Discriminating-atom output when Verify reports ambiguous

**Status**: Verify reports `ambiguous_<N>plus` when N>1 models exist
but doesn't say *what* discriminates them.

**Why it matters**: turns ambiguity from an opaque error into a
constructive hint. The author can see "models differ on
`picked_refund_method`; pin it to resolve" and immediately know what
to add to `c_hard`. Supports iterative spec authoring: write the
spec → see what's free → tighten → re-verify.

**Dependencies**: none. The information is already in the answer sets;
just needs surfacing.

**Effort**: ~1 session.

**Sketch**:
- After Clingo returns N models, compute the per-predicate symmetric
  difference between them.
- Report: "Models differ on these atoms: {…}. Pin one of them in
  `intent` to disambiguate."

### 1.10 Policy-consistency self-check

**Status**: the verifier checks tasks against `rules.md`. It does not
check `rules.md` against itself for internal contradictions.

**Why it matters**: if `rules.md` is internally inconsistent (two
derivation rules with mutually exclusive heads, an integrity
constraint that no D₀ can satisfy), the verifier reports `infeasible`
on every task without saying *why*. The dev should be told the policy
is broken, not that their task is wrong.

**Dependencies**: none.

**Effort**: ~30 minutes.

**Sketch**:
- New verifier mode: run Clingo on (closed-enum facts, D₀, Layer B)
  with no intent and no choice rule.
- If 0 models: policy contradicts itself or D₀. Report which integrity
  constraint fails.
- Run as a precondition before any task verification; fail fast.

### 1.11 Required-read declaration in intent schema

**Status**: `intent_noop` tasks check that the agent communicated the
right facts but don't require specific *read actions* (e.g., the
agent must have authenticated by calling `get_user_details`).

**Why it matters**: tau-bench tasks often require authentication or
other read actions *before* the response is valid even if no DB
change happens. Currently we only enforce read-before-mutate via
D-CONF-5/D-CONF-7 for mutating tasks.

**Dependencies**: none.

**Effort**: ~1 session.

**Sketch**:
- Add `intent.required_reads: list[{action, args}]` to the schema.
- Verifier's trajectory check confirms each required read appeared
  before the agent's response.

### 1.12 Methodology §8 — split into three rendered-NL audiences

**Status**: methodology §8 treats prose as a single rendered artifact.
In practice there are three:
- `task_instructions` for the *user simulator* (adversarial moves,
  withholds, lies, fallbacks).
- `system_prompt` / tool descriptions for the *agent under test*
  (deontic clarity, refusal grounds, escalation rules).
- `policy.md` for *humans inside the company* (auditability, citation
  to regulations, training material).

**Why it matters**: each has a different audience and consistency
requirement. Conflating them makes the consistency check vague.

**Dependencies**: none.

**Effort**: ~30 minutes of doc revision.

**Sketch**:
- Split methodology.md §8 into 8.1 / 8.2 / 8.3 — one per audience.
- For each, the relevant Layer to render from + the consistency check
  applicable.

### 1.13 Tool docstring as canonical Layer C output

**Status**: the agent sees Python tool docstrings as part of its tool
definitions. Those docstrings can contain content not reflected in
`actions.md`, and conversely, `actions.md` can specify behavior the
docstring doesn't surface. Currently no consistency check.

**Why it matters**: the tool docstring is *de facto* part of the
domain spec — it's what the agent actually consumes. Should be in
Layer C as a generated artifact, or at minimum declared as the
rendered NL surface of an action and consistency-checked.

**Dependencies**: none.

**Effort**: ~1 session for the convention; longer to actually
generate docstrings from action specs.

**Sketch**:
- Add to methodology §3 (downstream artifacts table): "tool docstrings
  rendered from Layer C."
- v0: hand-write docstrings, consistency-check against `actions.md`.
- v1: render docstrings from action specs deterministically.

---

## Tier 2 — Coverage extension

### 2.1 Cross-validate remaining airline cancel tasks

**Status**: 8/11 upstream cancel tasks cross-validated. The
remaining 3 (tasks 7, 39, 42) all have multiple `cancel_reservation`
gold actions per task — they violate the one-logical-transition
convention.

**Why it matters**: completes cross-validation coverage of the
cancellation slice; strengthens the empirical claim from 8/8 to
11/11.

**Dependencies**: 1.1 (multi-payment refund) and either:
- Relax the one-logical-transition convention to allow multi-cancel,
  OR
- Split each upstream task into N sub-tasks (one per cancel) and
  cross-validate each.

**Effort**: ~1 session (mostly hand-authoring intents and edge-case
debugging).

### 2.2 Airline booking slice

**Status**: TODO. The largest remaining airline workstream. Covers
~10 of the ~37 non-cancel upstream tasks.

**Why it matters**: booking is the airline domain's modal action.
Without it the retrofit covers only a slice; with it the retrofit
becomes a real second domain.

**Dependencies**:
- Layer B extension covering booking validity (valid_booking,
  seat availability, payment composition cardinalities — partially
  drafted in rules.md §2).
- Layer C extension: `book_reservation`, `search_direct_flight`,
  `search_onestop_flight`, `list_all_airports`, `calculate`.
- Layer D extension: confirmation contents for booking, payment
  composition disclosure, calculation-helper conduct.
- Verifier extension to handle booking's free-variable surface
  (which flights to pick when multiple match user constraints).
- Multi-payment composition handling (depends on 1.1).

**Effort**: 3-4 sessions for the layer authoring + 1-2 for the
verifier work. Cross-validation against upstream tasks expands the
total time.

### 2.3 Airline modification slice

**Status**: TODO. Covers ~10 of the ~37 non-cancel upstream tasks.

**Why it matters**: modification rules are the airline policy's
most complex section (basic-economy restrictions, kept-vs-replaced
pricing, cabin uniformity invariant, no-origin-destination-change
rule).

**Dependencies**: 2.2 (booking slice) is a soft prerequisite —
modification reads + writes the booking state.

**Effort**: 3-4 sessions.

### 2.4 Airline compensation slice

**Status**: TODO. Smaller than booking/modification but interlocks
with cancel + modify (compensation is conditional on those having
fired in the same task).

**Why it matters**: compensation logic is *only* expressible as
deontic + temporal (the modify/cancel must have happened first;
the customer must have asked). Tests whether our methodology
handles cross-action ordering constraints.

**Dependencies**: 2.2 (booking) and 2.3 (modification) for the
preconditions to be exercisable. Also: deciding whether to relax
the one-logical-transition convention.

**Effort**: 2 sessions.

### 2.5 Behavioral / adversarial cross-validation

**Status**: cross-validation so far has been on the DB-endstate axis
only. Many upstream tasks are about *behavioral* correctness — the
agent must refuse to be manipulated, must double-check claims, must
not capitulate to pressure.

Tasks 4, 24, 37, 43, 44, 45 from the upstream are explicitly
behavioral. Our verifier checks the DB; the behavioral component
is `[prompt]`-tagged Layer D rules.

**Why it matters**: validates that the methodology's two-axis split
(LP for state, controlled vocabulary + LLM judge for behavior)
captures the full eval signal.

**Dependencies**: none formally; benefits from an LLM judge being
wired up.

**Effort**: 1-2 sessions to set up; longer to actually run if it
involves LLM calls.

### 2.6 A third domain

**Status**: only retail_returns (greenfield) and airline (retrofit)
done so far. A third domain would test generalization in a new
direction.

**Why it matters**: two domains is suggestive; three is
convincing. Candidates:
- **Banking disputes** — Reg E rules, time windows, evidence
  documentation, multi-party flows (merchant + bank + customer).
  Regulatorily plausible without being regulation-accurate.
- **Insurance claims** — coverage applicability, deductibles,
  exclusions, statute of limitations. Tests our external-predicate
  pattern even harder than airline (every classification is
  open-vocabulary).
- **Telecom plan changes** — proration, mid-cycle upgrades/downgrades,
  contract terms. Tests numeric heavy logic where ASP grounding gets
  awkward.
- **Healthcare prior auth** — formulary rules, step therapy. Compliance
  risk but very rule-rich.

**Dependencies**: 1.3 (unified verifier) would make this much
cheaper. Without it, each new domain duplicates ~400 lines of
scaffold.

**Effort**: 1-2 weeks for a domain-1-equivalent (Layers A–F, ~10
tasks, verifier integration).

---

## Tier 3 — Methodologically interesting

### 3.1 NL renderer (spec → prose)

**Status**: deferred by design. v0 hand-writes prose and
consistency-checks against the spec.

**Why it matters**: closes the methodology's "spec is canonical;
prose is rendered" loop. Currently the prose lives in
`tasks_design.md` / `policy.md` and has to be regenerated by hand
each time the spec changes. A renderer makes the dependency
formal.

**Why it's hard**: auto-generated prose tends to read like
compliance text. The methodology commits that rendering *is
possible*; the renderer would need a style template + LLM polish
pass + a frozen-pass-to-prevent-regeneration mechanism.

**Dependencies**: stable spec format (mostly true today).

**Effort**: ~1-2 sessions for a v0 renderer (basic templating); v1
that's actually usable for benchmark prose is multi-session and
needs LLM integration.

### 3.2 Behavioral spec DSL

**Status**: v0 uses a controlled vocabulary (`lie`, `insist`,
`withhold`, etc.) as tags in NL `task_instructions`. There's no
grammar; no composition operators.

**Why it matters**: would let us *sample* adversarial patterns at
controlled difficulty (e.g., "give me a refusal task with
appeal_to_authority depth 3 + threat_escalation"). Currently
behavioral specs are hand-authored.

**Why it's hard**: defining the operator algebra is research-y.
What does "lie composed with insist" mean? When does the simulated
user back off?

**Dependencies**: a user simulator that can interpret the DSL.

**Effort**: research project. Months.

### 3.3 Discoverability formalization

**Status**: methodology Principle 5 lists discoverability as
machine-checkable. v0 falls back to two coarse proxies (D-CONF-5,
D-CONF-7 read-before-mutate rules).

**Why it matters**: closes the methodology's most-flagrant gap.
Without discoverability, a task could be uniquely-solvable but
require facts the agent has no way to learn.

**Why it's hard**: requires modeling the agent's epistemic state
across the conversation — what facts have been read, what's been
inferred. Epistemic logic programs (Clingo extensions like
`elp`) carry this; substantial new formalism.

**Dependencies**: Clingo with epistemic extensions. Possibly
moving from `clingo` to something like `clingo` + `elps2asp`.

**Effort**: research-grade. Multi-month if done seriously; a small
fragment could be done in 1-2 sessions.

### 3.4 Multi-transition task support

**Status**: forbidden by the one-logical-transition convention.
The convention exists because Verify's transition relation is
`valid_transition(D₀, D₁)` — single-step.

**Why it matters**: real benchmarks have multi-step tasks. The
upstream airline corpus has tasks that cancel one reservation,
book another, and offer compensation — all in one dialogue.

**Why it's hard**: multi-step changes the verifier shape. Two
options:
- Chain: `valid_chain(D₀, D₁, D₂, …)` — pure unrolling.
- Plan: `reachable(D₀, D_final)` — the agent's planning problem.

Plan-style needs more formalism but is more methodologically
honest.

**Dependencies**: 3.3 (discoverability) overlaps — both need
richer state.

**Effort**: 1-2 sessions for chain unrolling; substantial for
proper planning.

### 3.5 Difficulty calibration via constraint inversion

**Status**: pruning ratio and constraint coverage exist as
descriptive metrics. There's no way to *target* a difficulty
level when generating.

**Why it matters**: enables corpus design at a specific difficulty
profile. "Give me 20 tasks with pruning ratio between 3 and 5,
covering at least 12 distinct predicates."

**Why it's hard**: requires inverting the generator — instead of
"given knobs, what pruning?", you ask "given target pruning, what
knobs?" Search problem; may need different ASP encoding.

**Dependencies**: existing Generate + Metrics.

**Effort**: 2-3 sessions.

### 3.6 Counterfactual-world generator (benchmark-contamination detector)

**Status**: doesn't exist. Probably the most novel single application
of the methodology.

**Why it matters**: benchmark contamination is the dominant
methodological problem in LLM eval. If a model was trained on
tau-bench, it can pattern-match against canonical entity names,
canonical 24-hour thresholds, canonical refund-method-by-condition
mappings, etc.

If the policy is *purely logical*, we can mechanically construct an
**isomorphic counterfactual**: rename constants, permute numeric
thresholds within sound bounds, shuffle the closed-enum vocabulary,
and verify the resulting domain has the same structural properties.
The LLM should score equivalently on both. **Performance gap on the
counterfactual = contamination signal.**

This is a publishable contribution on its own. It's the kind of
thing only the methodology enables — you cannot do this with a
prose policy or a hand-coded checker.

**Why it's hard**: maintaining isomorphism is the constraint. Threshold
permutations must respect orderings (plus's extended window must
remain longer than regular's); enum renaming must be consistent across
Layer A/B/C/D; the resulting `D₀` must satisfy all integrity
constraints. None of this is intractable but it's careful work.

**Dependencies**: existing methodology + verifier. Optionally 3.5
(difficulty calibration) to control variant difficulty.

**Effort**: 2-3 sessions for a v0 counterfactual generator; the eval
campaign comparing LLM performance on original vs counterfactual is
an additional research project.

**Sketch**:
- Symbol-renaming pass over a verified domain (Layer A + B + E + F
  consistently renamed).
- Threshold-permutation pass with ordering constraints.
- Verify the result is structurally isomorphic (same rule-firing
  pattern on each task in the corpus).
- Eval LLM on original vs variants; large gap = strong evidence
  the original was in training data.

### 3.7 Adaptive / fluid benchmarking via rule-level weakness tracking

**Status**: doesn't exist. The methodology's *unique* enabler is
rule-level granularity — we know which Layer B predicates fired on
each task.

**Why it matters**: traditional benchmarking gives task-level
pass/fail signals. With rule-level tracking we can ask which *policy
branches* the LLM fails on (e.g., "fails on the insurance + covered
branch 70% of the time, fine elsewhere"). With Generate already
working, the next move is to *target* failing branches with the next
batch of tasks.

This is the fluid-benchmarking pattern (Rodriguez et al. and
descendants) applied to LLM policy reasoning specifically. The
methodology specifically enables it because we have a rule firing
trace per task.

**Why it's hard**: requires (a) per-task rule-firing instrumentation
in the eval, (b) failure attribution to specific rules, (c) generator
that conditions on which rules to exercise. Each is a small piece;
together they're a coherent system.

**Dependencies**: 3.5 (constraint inversion) helps. The metrics work
(pruning + coverage) is already in place.

**Effort**: ~3-4 sessions for a v0 adaptive loop.

**Sketch**:
- Eval logs which Layer B predicates fired on each task and whether
  the agent's response was correct.
- Aggregation: per-predicate failure rate across the corpus.
- Generator extension: "produce a task that exercises rules R₁ ∧ R₂"
  where R₁, R₂ are the worst-performing rules.
- Closed loop: eval → analyze → generate → eval → ...

### 3.8 Logic-driven user simulator

**Status**: the user simulator is an LLM following NL
`task_instructions`. Its responses are entirely model-generated.

**Why it matters**: the user has structured goals (intent),
constraints (c_hard), and fallback logic (c_soft). Each could be
*computed* rather than generated. The LLM's role would shrink to:
"render the computed response as natural language."

This is a cleaner separation between *what* the user would say (a
logical derivation from their goals + conversation state) and *how*
they say it (surface NL). It also makes adversarial moves more
controllable — `lie` becomes a structured action, not a prompt-tuned
behavior.

**Why it's hard**: requires modeling the user's belief state across
the conversation. Connects to discoverability (3.3).

**Dependencies**: 3.3 (discoverability formalization) is a soft
prerequisite.

**Effort**: research project. Months for a real implementation.

### 3.9 Dialogue logic (dialogue acts beyond moves)

**Status**: v0 has a controlled vocabulary of moves (`lie`,
`insist`, `withhold`). There's no grammar.

**Why it matters**: real customer-service conversations have a
structured pattern — opening, identification, problem statement,
clarification, resolution proposal, confirmation, close. Each turn
has a *dialogue act* (greeting, request, clarification-question,
counter-proposal). A formalism for dialogue acts would let us:
- Detect when the user simulator deviates from a coherent pattern.
- Guide the agent through standard customer-service stages.
- Test compliance with dialogue conduct rules (D-TURN-1 etc.) more
  rigorously.

Connects to Walton-style argumentation dialogue games and to BDI
agent theory.

**Why it's hard**: dialogue act formalisms are well-studied but
fragmented. Picking the right granularity is research.

**Dependencies**: 3.2 (behavioral DSL) overlaps.

**Effort**: research project.

---

## Tier 4 — Productionization

### 4.1 Eval harness integration

**Status**: cross-validation reads upstream tasks.json directly
but doesn't plug into the upstream evaluator. The eval still runs
the gold action sequence; our verifier is separate.

**Why it matters**: makes our verifier *part of* the benchmark
pipeline, not a check on it. Lets the benchmark verify task
correctness automatically before running.

**Dependencies**: 1.3 (unified verifier) is a soft prerequisite.

**Effort**: 2-3 sessions of integration + debugging.

**Sketch**:
- Hook into tau2-bench's `evaluator/evaluator_env.py`.
- Before evaluating an agent trajectory, run Verify on the task
  spec; flag tasks that don't have a unique solution.
- Optionally: replace gold-action-derived D* with Solve-derived D*
  as the source of truth.

### 4.2 CI for methodology artifacts

**Status**: no automation. Every methodology / spec / task
change should trigger re-verification.

**Why it matters**: prevents regressions during ongoing
development. Catches spec/impl drift the moment it happens.

**Dependencies**: none beyond standard CI infra.

**Effort**: ~1 session.

**Sketch**:
- GitHub Actions config running all 5 verifiers on PR.
- Cache the uv venv between runs.
- Fail the build on any verifier reporting non-zero exit.

### 4.3 Authoring tool

**Status**: doesn't exist. Authors edit JSON files by hand and run
the verifier from the CLI.

**Why it matters**: a real-time authoring loop (verifier runs in
the background as you edit; surfaces ambiguity / infeasibility
immediately) would dramatically lower the cost of authoring a new
task.

**Dependencies**: 1.3 (unified verifier) for clean integration.

**Effort**: 1-2 weeks for a polished interactive tool; ~3 days
for a minimal LSP-style "verifier-as-you-save" file watcher.

### 4.4 Public repository extraction

**Status**: extraction-ready as of 2026-06-08. Co-located under
`tau2-bench/` but structurally portable:

- LICENSE present (Apache-2.0).
- CONTRIBUTING.md present with dev setup + cross-validation
  instructions.
- README rewritten for a fresh standalone audience.
- `tools/cross_validate_airline.py` no longer has a hardcoded path
  to tau-bench; uses `--upstream-data` CLI flag, or
  `NOMOS_UPSTREAM_AIRLINE_DATA` env var, or the sibling default.
- GitHub Actions CI added (`.github/workflows/ci.yml`) — runs the
  full verifier suite + a React build on every push/PR. No upstream
  data needed (cross-validation is excluded from CI; runs locally
  when the data is present).
- Smoke-tested: all 6 verifier suites pass, missing-data error is
  user-friendly.

**Why it matters**: if shipping as an independent artifact, a
separate repo is cleaner. Easier to license / contribute / depend
on.

**Dependencies**: none remaining.

**Effort**: ~15 minutes for `git subtree split` + push.

**Action**:
```sh
git subtree split --prefix=nomos -b nomos-extracted
# then push the branch to a new repo:
#   git remote add nomos <new-repo-url>
#   git push nomos nomos-extracted:main
```

### 4.5 License + contributing docs

**Status**: done. Apache-2.0 LICENSE + CONTRIBUTING.md added
2026-06-08. README's license section now points at LICENSE.

---

## Decision guide — where to start

Pick the row matching your goal:

| If you want to… | Start with | Then maybe |
|---|---|---|
| Strengthen the empirical claim | 2.1 (rest of airline cancel) → 2.5 (behavioral cross-val) | 2.6 (third domain) |
| Make the methodology *usable* by others | 1.3 (unified verifier) → 4.4 (extract repo) → 4.5 (license) | 4.3 (authoring tool) |
| Make the methodology *cheaper to use* | 1.8 (solo mode) + 1.9 (ambiguity hints) + 1.13 (tool docstrings) | 4.3 (authoring tool) |
| Ship a publishable result | 3.6 (counterfactual contamination detection) — likely the single most novel application | 1.5 (version) + 4.4 (extract) |
| Get coverage of the airline corpus | 1.1 (multi-payment) → 2.1 → 2.2 (booking) → 2.3 (modify) → 2.4 (compensation) | 4.1 (eval integration) |
| Demonstrate methodology limits | 3.3 (discoverability) or 3.4 (multi-transition) | 3.2 (behavioral DSL) |
| Build a generator for benchmark corpora | 3.5 (difficulty calibration) + 3.7 (adaptive benchmarking) | 1.4 (negative test mode) |
| Detect benchmark contamination | 3.6 (counterfactual world generator) | 3.5 (difficulty calibration) for matched-difficulty variants |
| Just clean up loose ends before stopping | 1.1, 1.2, 1.5, 1.7, 1.10 | 1.12, 1.13 (doc polish) |

Most productive next individual session, ranked by ROI:
1. **1.3 (unify verifiers)** — unlocks every Tier 2 / Tier 4 item.
2. **1.1 + 1.2 (multi-payment + fees)** — closes the documented v0
   gaps and unblocks 2.1.
3. **2.1 (finish cancel cross-val)** — 11/11 is much stronger than 8/8.
4. **3.6 (counterfactual contamination detector)** — most "wow" /
   most likely publishable single contribution.
5. **2.6 (third domain)** — strong methodology-generalization result
   if 1.3 is already done.
6. **1.8 (solo mode)** + **1.9 (ambiguity hints)** — cheap, immediate
   usability wins for any author.

---

## Status

- **2026-05-29** — initial roadmap. 4 tiers, ~25 items each with effort
  estimate + dependency notes + payoff. Decision guide at bottom for
  goal-directed entry.

This is a living document. Items completed should be moved to a
`done.md` (or tagged ✓) with the commit hash; items that turn out to
be wrong or untractable should be moved to an `abandoned.md` with the
reason.
