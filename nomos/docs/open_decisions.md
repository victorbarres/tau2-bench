# Open decisions

Things we haven't settled yet. Each entry: question, current
leaning + why, the trade-off. Crossed off as we pick.

## Still open

### 1. Repository extraction

**Status**: directory renamed to `nomos/` and made self-contained.
The remaining question: do we carve `nomos/` out into its own
top-level repository now, or keep it under `tau2-bench/` as a
prototype until we're closer to shipping?

**Current leaning**: keep under `tau2-bench/` for now. The dir is
structurally ready to move (no hardcoded references in or out
beyond `cross_validate_airline.py`'s upstream-data path, which is
a known follow-up). Carve out when there's a reason — first
external collaborator, or first public release.

**Trade-off**: separate repo forces no-coupling discipline immediately
and gives the brand its own front door; in-place keeps the
prototype iteration cheap.

### 2. Project layout inside the benchmark dir

**Question**: how do we organize Python code?

```
Option A: packages/{bench_core,bench_server,bench_mcp,bench_agents}/
Option B: src/bench/{core,server,mcp,agents}/  (single package)
Option C: top-level dirs (server/, mcp/, agents/, ...)
```

**Current leaning**: Option B. Single `bench/` package with clear
submodules. Less ceremony than packages/, more structure than
loose dirs.

### 3. MCP server topology

**Question**: one MCP server per domain (`library_server`,
`retail_server`, `airline_server`), or one server with a `--domain`
argument?

**Current leaning**: **one server with `--domain`**. Less code
duplication. Domain-specific tools registered conditionally.

**Trade-off**: per-domain would be cleaner for eventual Harbor
packaging (one image per domain). One-with-arg is fewer moving
parts now; refactor when we package for distribution.

### 4. Run-state persistence

**Question**: do active runs survive a server restart, or die with
the process?

**Current leaning**: **memory-only for v0.5**. Active runs die with
the server. Completed runs persist (SQLite + JSONL).

**Trade-off**: PID-tracking + reattach on restart is doable but
fiddly. Add it when we hit the first "a run was lost" frustration.

### 5. UI: route library or URL-based switching?

**Question**: react-router or hand-rolled URL-based view switching
(matches `web/leaderboard`)?

**Current leaning**: **hand-rolled, like the leaderboard**. The
page set is small (~7 routes); a router library is overkill and
we get consistency with existing leaderboard code.

### 6. ASP query panel: derivation chain display

**Question**: when an ASP query returns derivable, do we show just
the answer, or visualize the derivation chain (which rules fired,
in what order)?

**Current leaning**: **show the chain**. We already display this
in `library_verify.py`'s output; the UI rendering is essentially
parsing Clingo's `--show` output into a tree.

**Trade-off**: chain rendering is more frontend work but is the
whole point of "test queries" — answer alone is less informative
than seeing why.

### 7. Policy-chat panel model

**Question**: do we let the user pick the chat-mode LLM, or hardcode
one?

**Current leaning**: **make it configurable, default to a small
fast Claude (haiku-4-5)**. Chat is informal — we don't want token
cost to discourage exploration. User can swap to a bigger model if
they want stricter interpretation.

### 8. Task-edit history surface

**Question**: when editing a task creates a new id (`LIB-T-001-v2`),
do we surface the lineage in the UI ("this is v2 of LIB-T-001") or
treat each id as independent?

**Current leaning**: **surface lineage**, with a "previous version"
link. Comparison view across versions is useful for "did this edit
break anything."

### 9. Headless CLI scope

**Question**: does the CLI cover authoring too, or only runs?

**Current leaning**: **runs only for v0.5**. Authoring via CLI
means a separate config DSL; not worth it. Edit JSON in your editor,
run from CLI.

### 10. License

**Question**: when we ship publicly, what license?

**Current leaning**: Apache-2.0 (matches tau-bench, friendly for
benchmark adoption). Decide closer to ship.

---

## Decided

These came up in conversation and have answers:

- **Name: Nomos** — Greek νόμος, "law/custom/governing principle".
  Foregrounds what we evaluate (policy-following with provable
  consequences). The underlying methodology is "logic-first design"
  (see `docs/methodology.md`); Nomos is its runnable form.
- **Directory renamed** to `nomos/` — self-contained, ready to move
  out of `tau2-bench/` when there's a reason.
- **MCP for tools** — yes
- **User sim is LLM-driven (when it exists)** — yes, deferred to v0.6
- **User sim accessed via MCP `ask_user` tool, not A2A** — yes
- **Solo only for v0.5** — yes, no `ask_user` and no dialogue in
  v0.5 trajectory rendering
- **Build server + UI together** — yes
- **Jump to v0.5 (skip read-only v0.0)** — yes
- **Local-only for v0.5** — yes
- **A2A deferred** — yes, premature
- **Harbor packaging deferred** — yes, when public
- **Inspect AI adapter** — optional, not on v0 critical path
- **No tau-bench dependencies** — non-negotiable
- **Test query panel has two modes: ASP and LLM chat** — yes
- **LLM chat is read-only Q&A in v0.5** — yes, no tool-invocation
  from chat panel
- **Authoring scope: tasks (Layer F) only for v0.5** — yes
- **Editing a task creates a new id** — yes, preserves run history
- **Reference agent: Anthropic SDK only for v0.5** — yes, litellm
  later
- **Telemetry: structured JSONL + SQLite for v0.5, OTEL later** — yes
- **Storage: SQLite for run metadata, JSONL for trajectories** — yes
- **Editor: Monaco for ASP/code, structured forms for JSON/D₀** — yes
