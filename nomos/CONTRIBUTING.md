# Contributing to Nomos

Thanks for your interest in Nomos. This document covers the
practical bits: how to get a local dev environment up, where to
look in the code, the conventions we keep, and how to propose
changes.

## Quick start

Prerequisites:
- Python 3.10+
- [`uv`](https://docs.astral.sh/uv/) for Python dependency
  management (`brew install uv` on macOS, `pipx install uv`
  elsewhere)
- Node.js 16+ for the web UI (`brew install node`)
- Clingo is installed automatically via `uv sync` (the Python
  bindings ship with the binary)

Setup:

```sh
git clone <repo-url>
cd nomos
make install     # uv sync + npm install
make dev         # backend :8000 + frontend :5173
```

Verify the methodology still passes its tests (no LLM calls,
~30 seconds total):

```sh
make oracle                                        # library solo-mode oracle
uv run python tools/verify_retail_returns.py       # 6/6 pure-Python
uv run python tools/clingo_verify.py               # 6/6 Clingo
uv run python tools/generate.py                    # 6/6 generated scenarios
uv run python tools/clingo_verify_airline.py       # 2/2 synthetic airline tasks
```

Optional, requires upstream tau-bench data
(see [the cross-validation section](#cross-validation-with-tau-bench)):

```sh
uv run python tools/cross_validate_airline.py      # 8/8 upstream airline
```

## Where things live

```
nomos/
  README.md, LICENSE, CONTRIBUTING.md    ← repo metadata
  pyproject.toml, uv.lock, Makefile      ← Python project + dev commands

  docs/                                  ← the methodology, findings, lit review,
                                            tutorial, benchmark plan, decisions log
  domains/                               ← Layer A–F specs per domain
    library/                             ← tutorial micro-world (start here)
    retail_returns/                      ← greenfield worked example
    airline/                             ← retrofit (cancellation slice)

  tools/                                 ← standalone CLI utilities — verifiers,
                                            generator, solo-mode runner, doc renderer
  src/bench/                             ← Nomos Python package (web server today;
                                            core/mcp/agents to follow)
  web/                                   ← Vite + React frontend
  data/                                  ← runtime artifacts (gitignored)
```

For a deeper tour of the methodology and the artifacts:
- [`docs/tutorial.md`](docs/tutorial.md) — 15-minute walkthrough of
  the smallest non-trivial domain
- [`docs/methodology.md`](docs/methodology.md) — the framework
- [`docs/benchmark.md`](docs/benchmark.md) — what we're building
  toward (v0.5 scope, deferred items)
- [`docs/open_decisions.md`](docs/open_decisions.md) — architectural
  questions still in flight
- [`docs/next_steps.md`](docs/next_steps.md) — roadmap with effort
  estimates

## Cross-validation with tau-bench

The script `tools/cross_validate_airline.py` validates the
methodology's outcomes against tau-bench's hand-authored airline
tasks. It needs a clone of the upstream airline data (which ships
in the [tau2-bench repo](https://github.com/sierra-research/tau2-bench),
not in Nomos). Point the script at it via:

```sh
# Option 1: CLI flag
uv run python tools/cross_validate_airline.py --upstream-data /path/to/airline

# Option 2: env var
NOMOS_UPSTREAM_AIRLINE_DATA=/path/to/airline \
    uv run python tools/cross_validate_airline.py
```

Default: looks at `../data/tau2/domains/airline/` relative to the
Nomos root (works when Nomos is co-located with a tau2-bench clone).

This is the **only** external data dependency in the project. All
other verifiers run with no internet access and no external clones.

## Coding conventions

- **Editing existing files over creating new ones.** Most additions
  fit somewhere in the current structure; check before adding new
  top-level dirs or modules.
- **Comments explain *why*, not *what*.** If a comment restates what
  the code already says, delete it. Comments earn their place by
  explaining hidden constraints, subtle invariants, workarounds, or
  surprising behavior.
- **Verifiers must catch deliberate bugs.** A new verifier or grader
  passes a test suite *and* is negative-tested against deliberate
  mutations (see the bug-injection pattern in
  `tools/verify_retail_returns.py` and `tools/library_solo.py`).
- **No backwards-compatibility shims unless asked.** This is a
  research artifact; we move fast and refactor in place.
- **Tasks and ontologies live in JSON/Markdown, not Python.** When
  in doubt, prefer declarative formats so the verifier can be the
  source of truth.

## Markdown / docs

- Re-render HTML after editing prose docs:
  `uv run python tools/render_doc.py <slug> [<slug>...]`
- Inline `<svg>` in markdown: indent freely and add HTML comments;
  the renderer flattens both before passing to the markdown parser
  (see `src/bench/server/docs.py::_flatten_inline_svg`).

## Proposing a change

For small fixes (typos, doc clarifications, obvious bug fixes), open
a PR directly. For larger changes (new layers, new domains, new
verifier features, anything touching the methodology), open an issue
first so we can align on direction — see
[`docs/open_decisions.md`](docs/open_decisions.md) for what's
actively up for debate.

Before opening a PR:
1. Run the verifier suite above and confirm everything still passes.
2. If you added a new doc, add it to the `DOC_META` dict in
   `src/bench/server/docs.py` so the web UI lists it.
3. Squash WIP commits; aim for one or two clean commits per logical
   change.

## License

By contributing, you agree your contributions are licensed under
the [Apache License 2.0](LICENSE), the project's license.
