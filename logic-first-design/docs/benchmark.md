# Benchmark — what we're building

A standalone, runnable benchmark for evaluating LLM agents on
policy-grounded conversational tasks, built on top of the logic-first
methodology already in this package.

The methodology gives us provably-correct task specifications
(`Solve(D₀, intent) = D*`). The benchmark is the harness that lets any
modern agent actually *run* against those specifications, with a
useful UI for watching and debugging.

## Why a new benchmark, not an extension of tau-bench

- **tau-bench couples evaluation to its own `Agent`/`Environment`
  classes.** External agents — Claude Code, custom LangGraph
  agents, anyone's MCP-speaking client — can't easily plug in. We
  want zero coupling.
- **Our grading is objective.** `Solve(D₀, intent)` derives the
  ground-truth D* mechanically. Pass/fail with a specific reason,
  not "did the LLM-judge say it looked right."
- **Our user simulator can be made structured.** The customer's
  persona is generated from task fields (`c_known`, `c_unknown`,
  goal) the verifier already uses — so the simulator's behavior is
  constrained by the same spec the agent is being graded against.
- **Modern protocol substrate.** MCP for tools; whatever standardizes
  next (OpenTelemetry GenAI for traces, Harbor for packaging,
  eventually A2A) composes cleanly on top.

## How it works

### Agent under test

Talks MCP. Connects to a per-domain MCP server. The server exposes
Layer C actions as tools, plus two extras:

- `ask_user(message)` — sends a message to the simulated customer
- `done(refusal_reason?)` — ends the trial

The agent's task: satisfy the structured `intent` while obeying
the Layer D policy. The policy text is available as an MCP resource.

### User simulator

Runs **inside** the MCP server. When the agent calls `ask_user`,
the server invokes an LLM with the customer's persona built from
the task. Returns the reply through the MCP tool boundary. The
agent never sees a separate user channel — it's just another tool.

Not A2A. Not scripted. **LLM-driven from day one.**

### Grading

Offline, after `done`:

- Compare the server's final World state to `Solve(D₀, intent)`.
- For `policy_noop` tasks, also check the refusal reason matches.
- For `intent_noop` tasks, check DB unchanged + no refusal.

Result: pass / fail with a specific reason and a structured diff.

### UI

Local web app:
- **Backend**: FastAPI. Owns run lifecycle, storage, the event stream.
- **Frontend**: Vite + React (same stack as `web/leaderboard`).
- **Live**: SSE stream from backend to UI; trajectory renders as it
  happens (dialogue, tool calls, state mutations).
- **History**: SQLite + JSONL for run records and event logs.

What you can do from the UI:
- Browse domains and tasks.
- Inspect a task (ticket, intent, D₀, expected D*).
- Kick off a run interactively (pick policy model + user-sim model).
- Watch a run unfold live.
- Inspect any past run — same view, just static.
- See a leaderboard of pass rates by model × task class.

## Key design decisions (made)

| Decision | Choice | Why |
|---|---|---|
| Tool protocol | **MCP** | Standard; any MCP-speaking agent works |
| User sim transport | **MCP tool (`ask_user`)** | Sim is environment, not peer agent |
| User sim behavior | **LLM-driven** | That's the actual benchmark |
| Grading | **`Solve(D₀, intent)` vs final state** | Objective and automatic |
| UI | **Local web (FastAPI + React)** | Live runs need a backend |
| Coupling to tau-bench | **None** | Standalone is the goal |
| Multi-agent / A2A | **Deferred** | Premature for v0 |
| Outer packaging (Harbor) | **Deferred** | When we ship publicly |
| Observability (OTEL) | **Deferred to v0.5** | JSONL + SSE cover v0 |

## v0 scope (what we actually build)

1. **One MCP server: `library`** with 3 Layer C tools + `ask_user` +
   `done`.
2. **LLM-driven user simulator** built from task fields (persona,
   `c_known`, `c_unknown`).
3. **One reference policy agent** (Anthropic SDK + MCP client).
4. **Web server** (FastAPI): REST + SSE, SQLite + JSONL storage,
   per-run subprocess orchestration.
5. **React UI** with the page set above (domains, task detail,
   run launcher, live trajectory view, leaderboard).
6. **Grader** reusing `library_verify.solve_task`.
7. **Headless CLI** for batch runs without the UI.

When library is end-to-end working — server, agent, UI, grading
— we know the architecture holds. Then we port retail_returns and
airline as new servers, same shape.

## Deferred (explicitly)

- Retail returns and airline servers (after library proves out)
- litellm reference agent (after Anthropic SDK works)
- OpenTelemetry instrumentation
- A2A multi-agent variants
- Harbor packaging
- Inspect AI adapter
- Public leaderboard / submission workflow
- Resumable runs across server restarts
- Adversarial user-sim profiles
- Structured `c_hard` checking beyond DB equality
- Required-read declaration (Victor's notes #11)

## How this relates to what's already here

Already built in this package and **reused as-is**:
- All Layer A–F domain specs (`domains/library/`, `domains/retail_returns/`, `domains/airline_reference/`)
- The Clingo-based Solve operation in `tools/clingo_verify.py` and `tools/library_verify.py`
- The methodology and tutorial docs

The benchmark wraps these in a runnable harness; it doesn't replace
any of them.

## What the working v0 looks like

Concretely, when v0 ships:

```sh
# One command starts everything
make dev

# Browser opens to localhost:5173
# Pick library/LIB-T-001, pick policy model, pick user-sim model, click "Run"
# Watch the agent and customer talk, watch tool calls fire,
# watch the World state mutate, see the grading verdict at the end.
```

Plus a headless mode:

```sh
make run domain=library task=LIB-T-001 \
    policy=anthropic/claude-haiku-4-5-20251001 \
    sim=anthropic/claude-haiku-4-5-20251001
# Prints PASS/FAIL with reason; writes the trajectory under data/runs/.
```

That's the target.
