# Nomos

**Nomos** (νόμος — Greek for "law / governing principle") is a
runnable benchmark and authoring environment for logic-first agent
tasks.

Each domain in Nomos is a *world governed by formally-stated laws*.
Tasks are written as structured intents whose correct answers are
*derived mechanically* from the laws, not hand-tuned by an author.
Agents are graded by comparing their final world state against the
derived ground truth — not against an LLM judge.

The goal: a benchmark you can debug, where soundness, uniqueness,
and difficulty are properties you can *prove* rather than properties
you have to take on faith.

## Status

| Working | Notes |
|---|---|
| Methodology, written end-to-end | 5 principles, 6 layers (A–F), 3 operations (Verify / Solve / Generate) |
| Three domains | `library/` (tutorial), `retail_returns/` (greenfield), `airline/` (retrofit, cancellation slice) |
| Pure-Python verifier | `verify_retail_returns.py` — 6/6 pass, catches 5/5 deliberate bugs |
| Clingo-based verifier + solver | `clingo_verify.py` — Verify, Solve, and metrics (pruning + coverage) |
| Scenario-driven generator | `generate.py` — 6 scenarios with knob sweeps + JSON export |
| Cross-validation harness | `cross_validate_airline.py` — **8/8 upstream tau-bench tasks agree** |
| Solo-mode runner prototype | `library_solo.py` — oracle passes 3/3, LLM mode wired |
| Local web UI scaffold | FastAPI + React serving the docs at `make dev` |

| In progress (see `docs/benchmark.md`) | |
|---|---|
| MCP server per domain | |
| Task authoring UI | with live Solve preview |
| Live agent runs | trajectory + grading streamed to UI |
| ASP + LLM-chat test queries | inside the IDE |

For the full empirical writeup: [`docs/findings.md`](docs/findings.md).
For what's next: [`docs/next_steps.md`](docs/next_steps.md).

## Quick start

Prerequisites: Python 3.10+, [`uv`](https://docs.astral.sh/uv/),
Node.js 16+.

```sh
git clone <repo-url>
cd nomos
make install            # uv sync + npm install
make dev                # backend :8000 + frontend :5173 — open localhost:5173
```

Verify the methodology passes its tests (no LLM calls,
~30 seconds total):

```sh
uv run python tools/verify_retail_returns.py       # 6/6 pure-Python
uv run python tools/clingo_verify.py               # 6/6 Clingo
uv run python tools/generate.py                    # 6/6 generated scenarios
uv run python tools/clingo_verify_airline.py       # 2/2 synthetic airline
uv run python tools/library_solo.py --oracle       # 3/3 solo-mode oracle
```

Optional, requires upstream tau-bench data
(see [Cross-validation](#cross-validation-with-tau-bench)):

```sh
uv run python tools/cross_validate_airline.py      # 8/8 upstream airline
```

## Reading order

1. **[`docs/tutorial.md`](docs/tutorial.md)** — 15-minute walkthrough
   of the library micro-world. Six layers + three operations on the
   smallest non-trivial example. Start here.
2. **[`docs/methodology.md`](docs/methodology.md)** — the framework.
   Five principles, the A→F dependency map, the three operations.
3. **[`docs/findings.md`](docs/findings.md)** — what was built, what
   was proven, what bent. The empirical writeup.
4. **[`docs/benchmark.md`](docs/benchmark.md)** — what we're building
   toward (v0.5 IDE + solo runner). Scope, deferred items, phasing.
5. **[`docs/lit_review.md`](docs/lit_review.md)** — 42 related papers
   across 6 topic areas with honest positioning.

## Layout

```
nomos/
  README.md, LICENSE, CONTRIBUTING.md    ← repo metadata
  pyproject.toml, uv.lock, Makefile      ← Python project + dev commands

  docs/                                  ← methodology, findings, tutorial,
                                            benchmark plan, decisions, lit review
  domains/                               ← Layer A–F specs per domain
    library/                             ← tutorial micro-world
    retail_returns/                      ← greenfield worked example
    airline/                             ← retrofit (cancellation slice)
    airline_reference/                   ← prose-to-spec extraction reference

  tools/                                 ← CLI utilities — verifiers, generator,
                                            solo-mode runner, doc renderer,
                                            cross-validation harness
  src/bench/                             ← Nomos Python package
    server/                              ← FastAPI app serving docs (v0);
                                            will host the full run API (v0.5+)
  web/                                   ← Vite + React frontend
  data/                                  ← runtime artifacts (gitignored)
```

Each domain directory holds the same six Layer files:
`ontology.md` (A), `rules.md` (B), `actions.md` (C),
`agent_contract.md` (D), `db.json` (E), `tasks.json` (F).
Design notes (`db_design.md`, `tasks_design.md`) sit alongside
where useful.

## Cross-validation with tau-bench

`tools/cross_validate_airline.py` validates the methodology's
outcomes against tau-bench's hand-authored airline tasks. It needs
a clone of the upstream airline data, which ships in the
[tau2-bench repo](https://github.com/sierra-research/tau2-bench),
not in Nomos. Point the script at it via:

```sh
# Option 1: CLI flag
uv run python tools/cross_validate_airline.py --upstream-data /path/to/airline

# Option 2: env var
NOMOS_UPSTREAM_AIRLINE_DATA=/path/to/airline \
    uv run python tools/cross_validate_airline.py
```

This is the **only** external data dependency in the project. Every
other verifier runs against data shipped in `domains/`.

## What this is for

- Building a benchmark domain for an agent (conversational,
  tool-using, or policy-grounded) where task soundness and uniqueness
  are **guaranteed by the verifier**, not tuned by hand.
- Designing a policy that needs to be coherent across multiple
  representations (prose, code, tests, runtime checks) without the
  multi-source-of-truth drift problem.
- Formalizing an existing prose policy with a structured extraction
  step (see `domains/airline_reference/`).

It is **not** a production policy engine, a verification system for
legal/regulatory text, or a Clingo wrapper. It's a discipline for
structuring how policy artifacts depend on one another, plus the
tooling to make that discipline operable.

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) for dev setup, coding
conventions, and how to propose a change.

## License

[Apache License 2.0](LICENSE). See `LICENSE` for the full text.
