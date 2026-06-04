# Nomos

**Nomos** (νόμος — Greek for "law / governing principle") is a
runnable benchmark and authoring environment for logic-first agent
tasks.

It packages a methodology for designing benchmark domains —
starting from a formal logical specification and projecting
natural-language prose, code, database state, and tasks from it —
together with the tooling to verify, run, and grade agents against
those domains.

This package is **self-contained**. It includes the methodology, a
fully worked example (retail returns & refunds), an airline retrofit
demonstrating generalization, two Clingo-based verifiers, a scenario
generator, a cross-validation harness that confirms the methodology
agrees with upstream tau2-bench tasks on 8 out of 8 cancellation
cases, and a local web UI (in progress) for authoring and running
benchmark tasks.

> See [`docs/benchmark.md`](docs/benchmark.md) for the v0.5 build
> we're working toward, and [`docs/open_decisions.md`](docs/open_decisions.md)
> for the architectural choices still being settled.

Five top-level docs, each available as both Markdown and standalone HTML:

| Doc | Purpose |
|---|---|
| [`docs/tutorial.md`](docs/tutorial.md) / [`.html`](docs/tutorial.html) | **Start here.** A library micro-world — six layers + three operations on the smallest non-trivial example. ~15 min read, 30 sec to run. |
| [`docs/methodology.md`](docs/methodology.md) / [`.html`](docs/methodology.html) | The framework — 5 principles, 6 layers, 3 operations |
| [`docs/findings.md`](docs/findings.md) / [`.html`](docs/findings.html) | The empirical writeup — what was built, what was proven, what bent |
| [`docs/next_steps.md`](docs/next_steps.md) / [`.html`](docs/next_steps.html) | The roadmap — 4 tiers of follow-up work with effort estimates |
| [`docs/lit_review.md`](docs/lit_review.md) / [`.html`](docs/lit_review.html) | Literature review — 42 related papers across 6 topic areas, with honest positioning. Bibliography in [`docs/references.bib`](docs/references.bib). |

The HTML versions are single self-contained files (no external CSS, no
CDN, no images) suitable for sharing as attachments or hosting as static
pages. To re-render after editing:

```sh
uv run python tools/render_doc.py tutorial methodology findings next_steps lit_review
```

```
nomos/
  README.md                       ← you are here
  docs/
    methodology.md                ← the methodology, 5 principles + 6 layers
  domains/
    retail_returns/               ← the worked example, authored end-to-end
      ontology.md                 ← Layer A: sorts, attributes, enumerations
      rules.md                    ← Layer B: integrity constraints + derivations (ASP)
      actions.md                  ← Layer C: transition predicates (9 actions)
      agent_contract.md           ← Layer D: deontic layer (38 rules)
      db.json                     ← Layer E: baseline D₀
      db_design.md                ← Layer E: rationale + self-verification
      tasks.json                  ← Layer F: 6 hand-authored benchmark tasks
      tasks_design.md             ← Layer F: per-task spec + uniqueness arguments
    airline_reference/
      policy_logic.md             ← reference: same methodology applied retroactively
                                    to tau2-bench's airline policy.md
  tools/
    verify_retail_returns.py      ← v0 verifier (Python, no Clingo dependency)
```

## Reading order

1. **[docs/methodology.md](docs/methodology.md)** — the methodology itself.
   Five principles, the A→F layer dependency map, the task model
   (`OperationalSpec` + `BehavioralSpec`), the three operations
   (Verify / Solve / Generate), known gaps. ~400 lines.

2. **[domains/retail_returns/ontology.md](domains/retail_returns/ontology.md)**
   onward, in alphabetical order matching Layer A → F. Each layer
   builds on the previous one only; cross-layer references are
   explicit. The design docs (`db_design.md`, `tasks_design.md`)
   explain the rationale; the data files (`db.json`, `tasks.json`)
   are the canonical artifacts.

3. **[tools/verify_retail_returns.py](tools/verify_retail_returns.py)** —
   the working v0 verifier. Read after the layer files; it makes the
   most sense once you've seen what it's verifying.

4. **[domains/airline_reference/policy_logic.md](domains/airline_reference/policy_logic.md)** —
   shows what the methodology's extraction step looks like when
   applied *retroactively* to an existing prose policy, as opposed
   to authored forward. Useful for understanding the retrofit case.

## Running the verifier

Requires only Python 3.10+ (uses standard library only — `json`, `pathlib`,
`datetime`, `dataclasses`). No external dependencies.

```sh
python tools/verify_retail_returns.py
```

Expected output: `D₀` baseline passes all 25 Layer B integrity constraints,
then each of the 6 tasks in `tasks.json` is verified end-to-end (gold
trajectory applied to `D₀`, preconditions checked, Layer B re-checked on
`D*`, diff printed, task-class consistency confirmed). Final line:
`SUMMARY: 6/6 passed.`

To see that the verifier actually catches bugs (rather than rubber-
stamping), inject one — e.g., change a task's `refund_method` to an
ineligible value in `tasks.json` — and re-run.

## Solo-mode runner (library micro-world)

A prototype runner that evaluates an agent on the structured `intent`
directly — no user simulator. Tests *policy-reasoning* difficulty
isolated from dialogue navigation.

```sh
# Deterministic oracle — no LLM, validates the harness end-to-end.
uv run python tools/library_solo.py --oracle

# Live LLM mode — requires API key for the chosen provider.
uv sync --extra solo
OPENAI_API_KEY=... uv run python tools/library_solo.py --model gpt-4o-mini
ANTHROPIC_API_KEY=... uv run python tools/library_solo.py \
    --model anthropic/claude-haiku-4-5-20251001
```

Oracle currently passes 3/3 library tasks. The grader compares the
agent's final DB state against `Solve(D₀, intent)`; for `policy_noop`
tasks it also requires a refusal with the exact reason mandated by
Layer D D-REF-1. Generalization to retail_returns is the next step
(see [docs/next_steps.md §1.8](docs/next_steps.md)).

## What's working, what's not

**Working:**
- The methodology, written down end-to-end.
- A worked example through Layers A–F covering a non-trivial domain
  (6 sorts, ~25 integrity constraints, 11 derivations, 9 actions,
  38 deontic rules, 14 orders, 6 tasks).
- A v0 verifier that mechanizes all Layer B and Layer C and the
  runtime-checkable subset of Layer D, and passes 6/6 tasks while
  catching 5/5 deliberate bug injections.
- **An LP-based verifier + solver** (`tools/clingo_verify.py`)
  implementing three operations from the methodology:

  - **Verify**: proves soundness + uniqueness for all 6 tasks. Per-task:
    | ID | family | verdict | pruning | cov |
    |---|---|---|---|---|
    | F-001 | approve_existing | unique | 2→1 | 15 |
    | F-002 | initiate_approve | unique | 1→1 | 14 |
    | F-003 | refuse | policy_refused | 0→0 | 0 |
    | F-004 | refuse | policy_refused | 0→0 | 0 |
    | F-005 | initiate_approve | unique | 3→1 | 15 |
    | F-006 | noop | trivial | — | — |

  - **Solve**: derives D* from `(D₀, OperationalSpec)` alone — no gold
    action witness needed. Cross-validates against the gold trajectory:
    6/6 Solve-derived D* match the gold-trajectory D*.

  - **Metrics**: pruning ratio + constraint coverage per task (filtered
    by target entities for task-specific complexity).

  - **JSON-only task authoring.** Each task's
    `operational_spec.intent` field is the canonical source. The
    verifier consumes it directly — no per-task Python encoder.
    Adding a new task is a JSON edit; Verify and Solve both work
    immediately. See `domains/retail_returns/tasks_design.md` §1.1
    for the intent schema.

  Extracts Layer B rules from rules.md so the markdown stays the single
  source of truth; reuses the pure-Python action simulator from
  `verify_retail_returns.py` for the deterministic post-state computation.

- **A scenario-driven generator** (`tools/generate.py`) implementing
  the methodology's third operation: synthesize `(D₀, task)` pairs
  from scenario templates. Six templates cover the main task families
  (happy-path / gift / exchange / window-refusal / non-returnable /
  wrong-initiator). Each generates a minimal D₀ with just the entities
  needed to support the intent, then runs the generated task through
  Verify + Solve to confirm uniqueness. 6/6 generated scenarios match
  expected pruning ratios:

  | scenario | task_class | expected pruning |
  |---|---|---|
  | happy_path_self_return | mutating | 2→1 |
  | gift_return_forced_store_credit | mutating | 1→1 |
  | exchange_defective | mutating | 3→1 |
  | window_refusal | policy_noop | 0→0 |
  | non_returnable_refusal | policy_noop | 0→0 |
  | wrong_initiator_refusal | policy_noop | 0→0 |

  **CLI for benchmark authoring**:

  ```sh
  # All scenarios, default knobs.
  uv run python tools/generate.py

  # One scenario, override one knob.
  uv run python tools/generate.py happy_path_self_return member_tier=plus

  # Knob sweep — cartesian product of comma-separated values.
  # Surfaces policy regime boundaries (in-window → out-of-window).
  uv run python tools/generate.py --summary happy_path_self_return \
      member_tier=regular,plus days_since_fulfillment=15,30,60,90,120

  # Export each variant to a separate task.json + db.json under DIR/.
  # Exported files match the schema of domains/retail_returns/{tasks,db}.json
  # and round-trip through the verifier.
  uv run python tools/generate.py --export out/ happy_path_self_return \
      days_since_fulfillment=5,15,28,31,85
  ```

  Sweeps report "regime crossings" when variants cross a policy
  boundary (e.g. a mutating scenario becomes policy-refused when knobs
  push it past the return window). These are informative, not errors.

  Requires `uv sync` to install the `clingo` Python bindings.
  See `pyproject.toml` for the dependency.

**Not yet working:**
- **Solve** operation (derive D* from `(D₀, OperationalSpec)` alone,
  without a gold trajectory).
- **Generate** operation (synthesize D₀ such that a given
  OperationalSpec template has exactly one solution).
- **Clingo integration**. The ASP code in `rules.md` is intended for
  Clingo but has not been executed; the v0 verifier reimplements the
  rules in Python. ASP integration matters for uniqueness search; the
  verifier compares against a single hand-written gold D*.
- **Structural `c_hard` checking**. The structured `c_hard` constraints
  in `tasks.json` are currently documentation; the verifier checks
  the diff against the gold trajectory only.
- **LLM-graded Layer D rules**. The `[prompt]`-tagged rules in
  `agent_contract.md` need a judge model to score, not a static checker.
- **Renderer** (spec → NL prose). The methodology commits that rendering
  *is possible* from the spec; v0 does it by hand and checks for
  consistency.

See [docs/methodology.md §9](docs/methodology.md#9-what-this-methodology-does-not-solve)
for the full gap list.

## What this is for

This methodology is intended for situations where:

- You're building a benchmark domain for an agent (conversational,
  tool-using, or policy-grounded), and you want task soundness and
  task uniqueness to be *guaranteed* rather than tuned by hand.
- You're designing a policy that needs to be coherent across multiple
  representations (prose, code, tests, runtime checks) and you want
  to avoid the multi-source-of-truth drift problem.
- You're trying to formalize an existing policy and want a structured
  extraction step before committing to an encoding (the
  `airline_reference/` example shows what that looks like).

It is *not* a production policy engine, a verification system for
real-world legal/regulatory text, or a Clingo wrapper. It is a
discipline for structuring how policy artifacts depend on one another
and a worked demonstration that the discipline pays off.

## License

(To be set by the project owner before shipping.)
