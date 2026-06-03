# Open decisions

Things we haven't settled yet. Each entry: question, my current
leaning + why, the trade-off. Crossed off as we pick.

## 1. Name

**Question**: what do we call the runnable benchmark?

**Current leaning**: `logic-first-bench` — descriptive, sells the
angle, distinguishes from `logic-first-design` (the methodology
package).

**Alternatives**: `policy-bench`, `asp-bench`, something punchier.
Naming is reversible cheaply; can punt until we're closer to a
public ship.

## 2. Repository structure

**Question**: stay under `tau2-bench/logic-first-design/`, rename
in place, or carve out into a new top-level repository?

**Current leaning**: rename in place to `logic-first-bench/` for
now. Keep parent `tau2-bench/` repo as the umbrella while we
prototype. Carve out into its own repo when we're ready to ship
publicly — at that point the tau-bench-coupling story is "we
cross-validated against it once; we don't depend on it."

**Trade-off**: separate repo would force the no-coupling discipline
sooner; in-place is faster and we already have the cross-validation
proof.

## 3. Project layout inside the benchmark dir

**Question**: how do we organize Python code?

```
Option A (packages/ subdirs):
  packages/bench_core/         shared: World, solve, grader
  packages/bench_server/       FastAPI app
  packages/bench_mcp/          MCP server base + per-domain modules
  packages/bench_agents/       reference policy agents

Option B (flatter):
  bench/core/, bench/server/, bench/mcp/, bench/agents/
  (single src/bench package, submodules)

Option C (no packages, just dirs):
  server/, mcp/, agents/  alongside existing tools/
```

**Current leaning**: Option B. Single `bench/` package with clear
submodules. Less ceremony than packages/, more structure than
loose dirs.

## 4. MCP server topology

**Question**: one MCP server per domain (`library_server`,
`retail_server`, `airline_server`), or one server with a `--domain`
argument?

**Current leaning**: **one server with `--domain`**. Less code
duplication. Domain-specific tools registered conditionally based
on the loaded domain. Spawned as `python -m bench.mcp --domain
library --task-id LIB-T-001 ...`.

**Trade-off**: per-domain would be cleaner for eventual Harbor
packaging (one Docker image per domain). One-with-arg is fewer
moving parts now; refactor to per-domain when we package for
distribution.

## 5. Reference policy agent

**Question**: which agents do we ship as reference clients?

**Current leaning**: **Anthropic SDK only for v0**. It has the
cleanest native MCP integration. Add a litellm variant in v0.1 for
multi-provider coverage (OpenAI, DeepSeek, etc.).

**Trade-off**: Anthropic-only means OpenAI/etc. evaluators can't
run out of the box until v0.1. But shipping two agents in v0 means
debugging two MCP shims simultaneously — more friction for less
v0 signal.

## 6. Run-state persistence

**Question**: do active runs survive a server restart, or die with
the process?

**Current leaning**: **memory-only for v0**. Active runs die with
the server. Completed runs persist (SQLite + JSONL).

**Trade-off**: PID-tracking + reattach on restart is doable but
fiddly and not load-bearing for v0. Add it when we hit the first
"a run was lost" frustration.

## 7. Telemetry: OTEL now or later

**Question**: do we instrument with OpenTelemetry GenAI spans in
v0, or wait until v0.5?

**Current leaning**: **wait**. The UI shows the trajectory live
from our JSONL stream; OTEL would be duplicate work for v0. Wire
OTEL in v0.5 when we want trace inspection in Phoenix/Langfuse
(per-token replay, latency attribution, cost analytics across runs).

**Trade-off**: instrumenting later is slightly more refactoring than
instrumenting from the start. Worth it: we lock in our event
schema first, then map to OTEL.

## 8. UI: route library or URL-based switching?

**Question**: react-router or hand-rolled URL-based view switching
(matches `web/leaderboard`)?

**Current leaning**: **hand-rolled, like the leaderboard**. The
page set is small (~7 routes); a router library is overkill and
we get consistency with the existing leaderboard code.

## 9. Storage: SQLite or just JSONL

**Question**: do we need SQLite at all, or are flat JSONL files
enough?

**Current leaning**: **SQLite for run metadata, JSONL for
trajectories**. Query patterns ("all runs of LIB-T-001 with
haiku-4-5") want an index; JSONL alone scans badly. SQLite is
zero-config Python-builtin.

## 10. Headless CLI alongside the UI

**Question**: do we have a CLI for headless runs (no browser
needed), or is the UI the only way to run?

**Current leaning**: **both**. A `make run domain=… task=…` CLI
that writes the same trajectory artifacts the UI consumes. Useful
for CI, batch sweeps, and people who don't want the UI.

## 11. License

**Question**: when we ship publicly, what license?

**Current leaning**: Apache-2.0 (matches tau-bench, friendly for
benchmark adoption). Decide closer to ship.

---

## Things explicitly NOT open

These came up in conversation and were decided:

- **MCP for tools** — yes
- **User sim is LLM-driven** — yes
- **User sim accessed via MCP `ask_user` tool, not A2A** — yes
- **Build server + UI together** — yes
- **Local-only for v0** — yes
- **A2A deferred** — yes, premature
- **Harbor packaging deferred** — yes, when public
- **Inspect AI adapter** — optional, not on v0 critical path
- **No tau-bench dependencies** — non-negotiable
