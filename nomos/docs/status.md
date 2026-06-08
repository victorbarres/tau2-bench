# Status — pick up here when you're back

> **What this is.** A point-in-time summary written for the human
> coming back to this project after time away. Tells you what's
> been done, where we actually stand, the decision currently
> blocking progress, and the longer roadmap. For deep detail,
> follow the links to the canonical docs.
>
> **Snapshot date**: 2026-06-08. If the doc you're reading is
> noticeably older than the latest `git log`, regenerate it before
> trusting the "Where we actually are" table.

## The arc, so far

The work since this branch began has unfolded in roughly six phases:

1. **Airline retrofit + cross-validation.** Took tau-bench's prose
   airline policy, re-expressed it as Layers A–F, validated against
   tau-bench's own hand-authored cancellation tasks. **Result:
   8/8 agree** (`tools/cross_validate_airline.py`). Humans wrote
   those tasks against the prose with zero awareness of our
   formalism; the formalism still produces the same verdict.

2. **Documentation pass.** [`methodology.md`](methodology.md),
   [`findings.md`](findings.md), [`next_steps.md`](next_steps.md),
   [`lit_review.md`](lit_review.md) (42 papers, BibTeX). All
   rendered to standalone HTML. Made the work shareable as an
   artifact rather than a working directory.

3. **Library tutorial.** Smallest non-trivial domain — 2 sorts,
   2 rules, 3 tasks — as a teaching example. Full A–F walkthrough
   with inline SVG diagrams of the derivation chain. ~15 minutes
   to read. See [`tutorial.md`](tutorial.md).

4. **Solo-mode runner prototype.** `tools/library_solo.py` —
   proof-of-concept agent runner. Oracle mode (deterministic
   perfect agent) passes 3/3, LLM mode wired via litellm, grader
   negative-tested on three deliberate bug shapes. Proved the
   `Ticket → World → Grader` pattern works end-to-end on the
   smallest domain.

5. **Repositioning as a runnable benchmark.** Named the project
   **Nomos** (νόμος, "law / governing principle"), renamed the
   directory, wrote [`benchmark.md`](benchmark.md) describing the
   full v0.5 vision (MCP server per domain, task authoring IDE,
   live agent runs, web UI). Added a web scaffold — FastAPI
   backend + React frontend — currently serving the docs but
   shaped to grow into the v0.5 UI.

6. **Extraction-readiness.** LICENSE (Apache-2.0), CONTRIBUTING.md,
   GitHub Actions CI, README rewritten for a fresh audience,
   hardcoded tau-bench path in cross-validator made configurable.
   The `nomos/` directory is structurally portable — one
   `git subtree split` away from being its own repo. See
   [`next_steps.md §4.4`](next_steps.md).

## Where we actually are

| Capability | Reality today |
|---|---|
| **Verify / Solve / Generate** | ✅ Works on all three domains. Mechanical, fast, negative-tested. |
| **Cross-validation against humans** | ✅ 8/8 on upstream airline cancel tasks. Needs tau-bench data — script handles via env var. |
| **Tutorial + methodology + lit review** | ✅ Polished, rendered, shareable. |
| **Authoring a task** | ⚠️ The methodology *enables* it (verifier proves your task is sound + unique). No UI — you edit JSON. |
| **Running an agent trajectory** | ⚠️ Library only, via `library_solo.py`. Not MCP. Doesn't generalize to retail / airline yet. |
| **Web UI** | ⚠️ Scaffold only — serves docs nicely, no benchmark functionality. |
| **Extraction readiness** | ✅ License, CI, CONTRIBUTING, no hardcoded paths. `git subtree split --prefix=nomos` produces a working repo. |

So today, Nomos is: **a verified methodology, three domain specs,
a working tutorial, a working agent-runner *demo* on one domain,
and a packaged-up directory ready to become its own repo.**

## The decision currently blocking next steps

What is Nomos *today*? Three coherent stances:

- **(a) Verification + authoring framework**, with a working
  agent-runner demo on the tutorial. Extract now. Honest about
  what it does, deliberately scoped. Verification work gets its
  own audience.

- **(b) Full runnable benchmark.** Build v0.5 first (MCP server,
  reference policy agent, retail/airline agent surfaces, live
  trajectory UI, task-authoring form). ~8–10 days of focused
  work. Extract once shipped.

- **(c) Middle path.** Extract now with explicit "v0: verification
  + authoring; v0.5: runnable benchmark (in progress)" framing.
  Lowest risk, lets verification ship while runner is built.

The assistant has been recommending (c). The human hasn't picked
yet. Pick before starting any next code — option (b) implies
weeks of focused work; (a) and (c) imply a fast extraction.

## The longer roadmap

In rough order of value (full details in
[`next_steps.md`](next_steps.md)):

- **v0.5 build** — generalize `library_solo.py`'s pattern via MCP:
  1. Extract a shared `bench/core/world.py` (simulator pattern)
  2. Build the MCP server (FastMCP shim per domain)
  3. Reference policy agent (Anthropic SDK + MCP client)
  4. Run lifecycle in `bench/server/` + live SSE to the React UI
  5. Task authoring form with live Solve preview
- **v0.6** — User simulator via MCP `ask_user` tool. Adds
  dialogue back in.
- **v0.7** — Port retail and airline to MCP. Cross-check against
  tau-bench's `LLMSoloAgent` on the cancel slice.
- **v0.8** — OpenTelemetry GenAI instrumentation; trace inspection
  in Phoenix.
- **v1** — Layer A–E editing in the UI; new-domain scaffolding.

Plus the **publishable angle** in tier 3 of next_steps: a
**counterfactual-world generator for benchmark-contamination
detection** (§3.6). Only this methodology enables it — rename
constants, permute thresholds while preserving structural
isomorphism, measure the LLM's performance gap on the variant.
That's a paper, not just a feature.

## Open architectural decisions

Documented in [`open_decisions.md`](open_decisions.md). The ones
upstream of any v0.5 code:

1. Repo extraction — extract `nomos/` to its own repo now, or
   keep it under `tau2-bench/` while prototyping?
2. Project layout — `src/bench/{core,server,mcp,agents}/`?
3. MCP server topology — one server with `--domain` arg, or per
   domain?

The other 7 are smaller (UI router choice, storage schema, etc.)
and don't block work starting.

## Where to look when you're back

| If you want… | Read |
|---|---|
| The vision for what Nomos becomes | [`benchmark.md`](benchmark.md) |
| What architectural choices are still in flight | [`open_decisions.md`](open_decisions.md) |
| The full roadmap with effort estimates | [`next_steps.md`](next_steps.md) |
| What "we proved" actually means concretely | [`findings.md`](findings.md) |
| The methodology itself | [`methodology.md`](methodology.md) |
| The micro-world walkthrough (if you've forgotten the layers) | [`tutorial.md`](tutorial.md) |
| The most recent commits | `git log --oneline -15` |

**Practical re-entry**: run the verifier suite to confirm nothing
has rotted while you were away:

```sh
cd nomos && make install
uv run python tools/verify_retail_returns.py       # 6/6
uv run python tools/clingo_verify.py               # 6/6
uv run python tools/library_solo.py --oracle       # 3/3
make dev                                           # browse the docs
```

If those pass, the methodology is still intact. Then make the
positioning call (a/b/c above) and move.
