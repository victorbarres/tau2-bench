# Nomos — what we're building

**Nomos** (νόμος, "law / governing principle") is a standalone,
runnable benchmark **and authoring environment** for logic-first
agent tasks, built on top of the methodology already in this
package.

The name foregrounds what we evaluate — policy-following with
provable consequences — and signals that each domain is governed
by formally-stated laws, not by hand-tuned prose. The underlying
methodology is *logic-first design* (see `docs/methodology.md`);
*Nomos* is what that methodology becomes when it's made runnable.

Two halves:
- **An IDE for designing domains** — explore the six layers, test
  queries against the logic, author tasks, see expected behavior
  before any LLM is involved.
- **A runner for evaluating agents** — kick off a model against an
  authored task, watch tool calls land and state mutate live,
  grade against `Solve(D₀, intent)` automatically.

The IDE and runner share the same data model and live in one app.
Authoring a task and immediately running an agent against it is one
flow.

## Why a new benchmark, not an extension of tau-bench

- **tau-bench couples evaluation to its own `Agent`/`Environment`
  classes.** External agents — Claude Code, custom LangGraph
  agents, anyone's MCP-speaking client — can't easily plug in. We
  want zero coupling.
- **Our grading is objective.** `Solve(D₀, intent)` derives the
  ground-truth D* mechanically. Pass/fail with a specific reason,
  not "did the LLM-judge say it looked right."
- **The methodology is interactive when given a UI.** Test queries,
  live integrity-constraint checks, and `Solve` previews turn the
  design loop from "edit file → run verifier → squint" into
  something you actually iterate in.
- **Modern protocol substrate.** MCP for tools; whatever standardizes
  next (OpenTelemetry GenAI for traces, Harbor for packaging,
  eventually A2A for multi-agent flows) composes cleanly on top.

## How the runner side works (v0.5: solo-only)

### Agent under test

Talks MCP. Connects to a per-domain MCP server. The server exposes
Layer C actions as tools, plus `done(refusal_reason?)` to end the
trial. The agent's task: satisfy the structured `intent` while
obeying the Layer D policy. The policy text is available as an MCP
resource the agent can read.

**No `ask_user`, no user simulator in v0.5.** The agent receives the
ticket in its initial instruction and solves end-to-end via tool
calls. This is exactly what `tools/library_solo.py` already does —
v0.5 wraps that pattern in MCP + a UI.

### Grading

Offline, after `done`:

- Compare the server's final World state to `Solve(D₀, intent)`.
- For `policy_noop` tasks, also check the refusal reason matches.
- For `intent_noop` tasks, check DB unchanged + no refusal.

Result: pass / fail with a specific reason and a structured diff.

## How the authoring side works (v0.5: tasks only)

### Browse all six layers

Read-only views of Layer A (ontology), B (rules), C (actions),
D (agent contract), E (D₀). Source edits stay in the filesystem
(VS Code, your editor of choice) — the UI shows the current state
and live-validates it.

### Test queries against the logic (two modes)

**ASP query mode** — type an atom like `can_borrow(alice, hamlet)`
into a Clingo-powered query panel; see whether it's derivable, the
derivation chain, or the constraint that blocks it. This is the
formal "is this true under the rules" tool.

**Policy chat mode** — chat panel with an LLM that has the Layer C
action specs and Layer D agent contract as context. Ask
"if alice already has three books, can she borrow another?" or
"what conditions need to hold for a borrow to succeed?" in natural
language. The LLM acts as an informal policy interpreter; useful for
sanity-checking that the prose policy says what you think it does.

Read-only Q&A in v0.5 — the chat panel doesn't invoke actions
against a sandbox. (That's the agent-run view's job.)

### Author tasks (Layer F only)

Structured form:
- Pick intent action (`borrow_book`, etc.) from the domain's tool
  surface.
- Fill arguments.
- Set task class (`mutating` / `policy_noop` / `intent_noop`).
- For policy_noop tasks, set expected refusal reason.

Live preview shows `Solve(D₀, intent)` as you fill the form — you
see the expected D* (or the policy refusal) before saving.

Save writes a new task to `tasks.json` with a fresh id. **Edits to
existing tasks create a new id** (`LIB-T-001-v2`) — the original is
preserved so run history stays attached to a stable spec.

### Run an authored task against an agent

From the task page, click "Run agent." The benchmark runner spawns
the MCP server + reference policy agent (Anthropic SDK), streams the
trajectory back to the UI, grades at the end. Same as running any
existing task.

## Key design decisions (made)

| Decision | Choice | Why |
|---|---|---|
| Tool protocol | **MCP** | Standard; any MCP-speaking agent works |
| User sim transport (later) | **MCP tool (`ask_user`)** | Sim is environment, not peer agent |
| User sim in v0.5 | **Out entirely** | Solo only; sim added in v0.6 |
| User sim behavior (when added) | **LLM-driven** | That's the actual benchmark |
| Grading | **`Solve(D₀, intent)` vs final state** | Objective and automatic |
| Authoring scope | **Layer F (tasks) only in v0.5** | A–E change rarely; iterate where it matters |
| Test queries | **Both ASP and LLM chat** | Formal + informal sanity checks |
| Task edits | **Create new id, preserve history** | Run records stay attached to stable specs |
| UI | **Local web (FastAPI + React)** | Live runs need a backend |
| Coupling to tau-bench | **None** | Standalone is the goal |
| Multi-agent / A2A | **Deferred** | Premature for v0 |
| Outer packaging (Harbor) | **Deferred** | When we ship publicly |
| Observability (OTEL) | **Deferred to later phase** | JSONL + SSE cover v0 |

## v0.5 scope (what we actually build)

### Backend
1. **MCP server: `library`** with 3 Layer C tools + `done`. No `ask_user`.
2. **Reference policy agent** (Anthropic SDK + MCP client).
3. **Grader** reusing `library_verify.solve_task`.
4. **Web server** (FastAPI): REST + SSE, SQLite + JSONL storage,
   per-run subprocess orchestration.
5. **Authoring backend**: task validation, Solve-preview endpoint,
   task save with new-id generation.
6. **Query backend**: Clingo query endpoint, policy-chat LLM endpoint.

### Frontend (React + Vite, same stack as `web/leaderboard`)
1. **Domain home** — browse A–F as read-only; D₀ as cards; task list.
2. **Layer B page** — ASP source view + two query tabs (ASP + chat).
3. **Task authoring page** — form with live Solve preview; save +
   "Run agent" button.
4. **Run view** — live trajectory (tool calls + state mutations),
   grading at end.
5. **Leaderboard** — pass rates by model × task class across runs.

### Headless CLI
- `make run domain=library task=LIB-T-001 model=...` for batch /
  CI use. Writes the same artifacts the UI consumes.

## Phasing roadmap

| Phase | New surface | Effort estimate |
|---|---|---|
| **v0.5** | Solo runner + task authoring + LLM-chat queries | ~8–10 days |
| **v0.6** | User simulator via MCP `ask_user` tool; dialogue rendering in trajectory view | ~5–7 days |
| **v0.7** | Port retail_returns and airline as additional MCP servers | ~3–5 days each |
| **v0.8** | OpenTelemetry GenAI instrumentation + Phoenix integration | ~3 days |
| **v1** | Editing for Layer A–E in browser; new-domain scaffolding | ~2 weeks |
| **later** | A2A multi-agent variants, Harbor packaging, Inspect AI adapter, public leaderboard | open |

## Deferred (explicitly)

- User simulator + `ask_user` tool (v0.6)
- Dialogue rendering in trajectory view (v0.6)
- Retail returns and airline MCP servers (v0.7)
- litellm reference agent for non-Anthropic models (v0.7)
- OpenTelemetry instrumentation (v0.8)
- Layer A–E editing in the UI (v1)
- New-domain creation in the UI (v1)
- A2A multi-agent variants
- Harbor packaging
- Inspect AI adapter
- Public leaderboard / submission workflow
- Resumable runs across server restarts
- Adversarial user-sim profiles
- Structured `c_hard` checking beyond DB equality
- Required-read declaration (Victor's notes #11)

## How this relates to what's already here

Reused as-is:
- All Layer A–F domain specs (`domains/library/`, `domains/retail_returns/`, `domains/airline_reference/`)
- The Clingo-based Solve operation in `tools/clingo_verify.py` and `tools/library_verify.py`
- The solo-mode harness in `tools/library_solo.py`
- The methodology and tutorial docs

The benchmark wraps these in a runnable harness + a UI; it doesn't
replace any of them. Existing `tools/*.py` keep working as CLI
utilities even after the UI exists.

## What v0.5 looks like when it ships

```sh
# One command starts everything
make dev

# Browser opens to localhost:5173
# - Browse the library domain; click "Test queries" and ask ASP or chat
# - Author a new task: pick borrow_book, fill in alice + hamlet, see expected D*
# - Click "Save + Run"; pick claude-haiku-4-5
# - Watch tool calls fire, watch alice's loan count tick up, see PASS at the end
```

Plus a headless mode:

```sh
make run domain=library task=LIB-T-001 \
    policy=anthropic/claude-haiku-4-5-20251001
# Prints PASS/FAIL with reason; writes the trajectory under data/runs/.
```

That's the target.
