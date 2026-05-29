# Tutorial — a library micro-world

A guided walkthrough of the methodology on the smallest non-trivial
domain we could build. By the end you'll have seen each of the six
layers, run all three operations (Verify, Solve, Generate-equivalent),
and watched the Layer B rules chain together in Clingo's derivation
output.

The whole domain fits on one page. The Python verifier is ~250 lines.
The whole tutorial takes ~15 minutes to read and 30 seconds to run.

```sh
cd logic-first-design
uv sync                                        # one-time setup
uv run python tools/library_verify.py          # verify all 3 tasks
```

---

## 1. The scenario

A library lends physical Books to Borrowers. Two rules:

1. A borrower may have **at most 3 active loans** at a time.
2. A book must have **at least one available copy** to be loaned.

The agent's job: process borrow requests. Either approve (create a
loan) or refuse with a specific reason.

That's the whole domain. No payments, no fees, no due dates, no
holds, no privacy concerns. Three sorts, two rules, one action.

The point isn't to be realistic — it's to be small enough to hold in
your head while you watch the methodology work.

### The methodology in one picture

Six layers stacked on each other; each consumes the layers above.

```
┌────────────────────────────────────────────────────────────────┐
│  A — Ontology       sorts, attributes, closed enumerations     │
└────────────────────────────────────┬───────────────────────────┘
                                     │ vocabulary used by
                                     ▼
┌────────────────────────────────────────────────────────────────┐
│  B — World rules    integrity constraints + derivations (ASP)  │
└────────────────────────────────────┬───────────────────────────┘
                                     │ predicates consulted by
                                     ▼
┌────────────────────────────────────────────────────────────────┐
│  C — Actions        transition predicates (preconditions etc.) │
└────────────────────────────────────┬───────────────────────────┘
                                     │ gated by
                                     ▼
┌────────────────────────────────────────────────────────────────┐
│  D — Agent contract deontic rules (must / may / must not)      │
└────────────────────────────────────┬───────────────────────────┘
                                     │ instantiated against
                                     ▼
┌────────────────────────────────────────────────────────────────┐
│  E — Baseline DB    D₀ satisfying every A–C invariant          │
└────────────────────────────────────┬───────────────────────────┘
                                     │ pinned by
                                     ▼
┌────────────────────────────────────────────────────────────────┐
│  F — Tasks          (intent, expected D*) tuples               │
└────────────────────────────────────────────────────────────────┘
```

We'll walk through each layer in turn, then run all three operations
(Verify, Solve, Generate-equivalent) and see the results.

---

## 2. Layer A — Ontology

Layer A declares *what entities the world contains and what their
attributes are*. It's the vocabulary.

Three sorts: **Borrower**, **Book**, **Loan**. One closed enumeration
(`loan_status` ∈ {`active`, `returned`}). One numeric constant
(`max_active_loans_per_borrower = 3`).

[`domains/library/ontology.md`](../domains/library/ontology.md)
declares the predicates that Layer B will define — four of them:

| Predicate | Intuition |
|---|---|
| `active_loan_count(B, N)` | Borrower B holds N active loans. |
| `available_copies(K, N)` | Book K has N copies free. |
| `has_available_copy(K)` | True iff `available_copies(K, N)` with N ≥ 1. |
| `can_borrow(B, K)` | Composite — both branches must hold. |

**The Layer A discipline**: declare every predicate the rest of the
spec will reference, give it an arity and an English description,
and commit not to introduce new ones later without updating this
file. This is the "single source of truth for vocabulary" rule.

---

## 3. Layer B — World rules

Layer B encodes the policy as Answer Set Programming. The
[`rules.md`](../domains/library/rules.md) file has 4 derivation rules
+ 3 integrity constraints. Here are the load-bearing parts.

### 3.1 The two integrity constraints

```asp
% No borrower has more than 3 active loans.
:- borrower(B),
   #count{ L : loan_borrower(L, B), loan_status(L, active) } > 3.

% No book has more active loans than copies.
:- book(K), total_copies(K, T),
   #count{ L : loan_book(L, K), loan_status(L, active) } > T.
```

These are *invariants* — they describe what a valid DB state looks
like. Any D₀ or D* that violates them is invalid by definition. The
verifier will check both before reporting success.

### 3.2 The derivation chain

```asp
active_loan_count(B, N) :-
  borrower(B),
  N = #count{ L : loan_borrower(L, B), loan_status(L, active) }.

available_copies(K, N) :-
  book(K),
  total_copies(K, T),
  M = #count{ L : loan_book(L, K), loan_status(L, active) },
  N = T - M.

has_available_copy(K) :- available_copies(K, N), N >= 1.

can_borrow(B, K) :-
  borrower(B), book(K),
  active_loan_count(B, N), N < 3,
  has_available_copy(K).
```

Read each rule as "to derive the head, the body must hold." The chain
goes: count active loans → compute available copies → check
availability → combine with the per-borrower cap → derive `can_borrow`.

**The Layer B discipline**: every derived predicate has exactly one
rule head (or one well-defined disjunction of heads). When a task
fails, you should be able to trace back which clause didn't fire.

---

## 4. Layer C — Actions

Layer C declares the agent's tool surface. The library has three
tools: two reads and one mutate.

[`actions.md`](../domains/library/actions.md) specifies `borrow_book`
in full:

> **Preconditions**: `borrower(B)`, `book(K)`, `can_borrow(B, K)`.
>
> **Effects**: Insert a new `Loan` with status `active`.
>
> **Failure modes**: `borrower_at_loan_cap` or `no_available_copies`,
> depending on which branch of `can_borrow` failed.

Three things to note:

1. **The action's precondition is `can_borrow/2` — a Layer B
   predicate.** Layer C doesn't restate the rules; it *consults* Layer
   B. If you change Layer B, Layer C updates automatically.

2. **The two failure modes correspond to the two branches of
   `can_borrow`.** When the verifier reports infeasibility, the agent
   can introspect to tell the user which branch failed.

3. **There's no choice surface.** Once `intent` pins the borrower and
   book, the action is fully determined. The verifier doesn't have to
   pick among options — it just checks whether the action is
   permitted.

---

## 5. Layer D — Agent contract

Layer D is the deontic layer — what the agent *must*, *may*, *must
not* do. For the library micro-world it's three rules
([`agent_contract.md`](../domains/library/agent_contract.md)):

- **D-AUTH-1**: must obtain the borrower id before any borrower-scoped
  action.
- **D-CONF-1**: must list the borrow request and obtain "yes" before
  invoking `borrow_book`.
- **D-REF-1**: must refuse in-band when `can_borrow/2` fails, citing
  the specific reason.

A real domain (retail, airline) would have 30+ rules covering
identity verification, disclosure scope, transfer logic,
challenge-on-incoherent-claim, etc. The library doesn't need them.
The methodology scales up without forcing every domain to scale up.

---

## 6. Layer E — The baseline DB

[`db.json`](../domains/library/db.json) is the world state the verifier
runs against.

```jsonc
{
  "constants": {"max_active_loans_per_borrower": 3},
  "borrowers": {
    "alice": {"borrower_id": "alice", "name": "Alice Chen"},
    "bob":   {"borrower_id": "bob",   "name": "Bob Diaz"}
  },
  "books": {
    "hamlet":  {"title": "Hamlet",     "total_copies": 2},
    "ulysses": {"title": "Ulysses",    "total_copies": 1},
    "iliad":   {"title": "The Iliad",  "total_copies": 1}
  },
  "loans": {
    "loan_001": {"borrower_id": "bob", "book_id": "hamlet",  "status": "active"},
    "loan_002": {"borrower_id": "bob", "book_id": "ulysses", "status": "active"},
    "loan_003": {"borrower_id": "bob", "book_id": "iliad",   "status": "active"}
  }
}
```

The choices matter:

- **Alice has 0 active loans** → she's available to borrow.
- **Bob has 3 active loans** → he's at the cap. Any borrow request
  from Bob must be refused on the cardinality branch.
- **Hamlet has 2 total copies; 1 is out** → 1 available.
- **Ulysses has 1 total copy; 1 is out (to Bob)** → 0 available. Any
  request for Ulysses must be refused on the availability branch.

These choices give us one happy path and two distinct refusal paths,
all reachable from the same baseline.

### D₀ at a glance

<svg viewBox="0 0 720 320" xmlns="http://www.w3.org/2000/svg"
style="font-family:-apple-system,BlinkMacSystemFont,Inter,Segoe UI,sans-serif; max-width:100%; height:auto; display:block; margin:1.5rem auto;">
<defs>
<marker id="lib-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
<path d="M 0 0 L 10 5 L 0 10 z" fill="#d97706"/>
</marker>
</defs>
<text x="22" y="22" font-size="11" font-weight="700" fill="#6b7280" letter-spacing="0.08em">BORROWERS</text>
<text x="442" y="22" font-size="11" font-weight="700" fill="#6b7280" letter-spacing="0.08em">BOOKS</text>
<rect x="20" y="40" width="200" height="70" rx="8" fill="#d1fae5" stroke="#059669" stroke-width="2"/>
<text x="120" y="65" text-anchor="middle" font-size="17" font-weight="700" fill="#1a1a1a">alice</text>
<text x="120" y="86" text-anchor="middle" font-size="12" fill="#374151">0 active loans</text>
<text x="120" y="100" text-anchor="middle" font-size="11" fill="#059669" font-weight="600">▲ available to borrow</text>
<rect x="20" y="145" width="200" height="70" rx="8" fill="#fef3c7" stroke="#d97706" stroke-width="2"/>
<text x="120" y="170" text-anchor="middle" font-size="17" font-weight="700" fill="#1a1a1a">bob</text>
<text x="120" y="191" text-anchor="middle" font-size="12" fill="#374151">3 active loans</text>
<text x="120" y="205" text-anchor="middle" font-size="11" fill="#d97706" font-weight="600">⚠ at loan cap</text>
<rect x="440" y="40" width="260" height="65" rx="8" fill="#fafafa" stroke="#1f2937" stroke-width="1.5"/>
<text x="570" y="62" text-anchor="middle" font-size="15" font-weight="700" fill="#1a1a1a">Hamlet</text>
<text x="570" y="78" text-anchor="middle" font-size="10" fill="#6b7280">2 copies total</text>
<rect x="455" y="84" width="115" height="14" rx="3" fill="#fef3c7" stroke="#d97706"/>
<text x="513" y="95" text-anchor="middle" font-size="10" fill="#92400e">1 lent</text>
<rect x="575" y="84" width="115" height="14" rx="3" fill="#d1fae5" stroke="#059669"/>
<text x="633" y="95" text-anchor="middle" font-size="10" fill="#065f46" font-weight="600">1 available</text>
<rect x="440" y="125" width="260" height="55" rx="8" fill="#fafafa" stroke="#1f2937" stroke-width="1.5"/>
<text x="570" y="148" text-anchor="middle" font-size="15" font-weight="700" fill="#1a1a1a">Ulysses</text>
<text x="570" y="163" text-anchor="middle" font-size="10" fill="#6b7280">1 copy total</text>
<rect x="510" y="168" width="120" height="9" rx="3" fill="#fef3c7" stroke="#d97706"/>
<rect x="440" y="200" width="260" height="55" rx="8" fill="#fafafa" stroke="#1f2937" stroke-width="1.5"/>
<text x="570" y="223" text-anchor="middle" font-size="15" font-weight="700" fill="#1a1a1a">The Iliad</text>
<text x="570" y="238" text-anchor="middle" font-size="10" fill="#6b7280">1 copy total</text>
<rect x="510" y="243" width="120" height="9" rx="3" fill="#fef3c7" stroke="#d97706"/>
<path d="M 220 165 Q 330 75 437 70" fill="none" stroke="#d97706" stroke-width="1.5" marker-end="url(#lib-arr)"/>
<text x="280" y="108" font-size="10" fill="#92400e">loan_001</text>
<path d="M 220 180 Q 330 165 437 155" fill="none" stroke="#d97706" stroke-width="1.5" marker-end="url(#lib-arr)"/>
<text x="290" y="170" font-size="10" fill="#92400e">loan_002</text>
<path d="M 220 195 Q 330 240 437 230" fill="none" stroke="#d97706" stroke-width="1.5" marker-end="url(#lib-arr)"/>
<text x="290" y="215" font-size="10" fill="#92400e">loan_003</text>
<g transform="translate(20, 275)">
<rect width="14" height="14" rx="3" fill="#d1fae5" stroke="#059669"/>
<text x="22" y="11" font-size="11" fill="#6b7280">available / can act</text>
<rect x="180" width="14" height="14" rx="3" fill="#fef3c7" stroke="#d97706"/>
<text x="202" y="11" font-size="11" fill="#6b7280">at limit / in use</text>
<line x1="370" y1="7" x2="395" y2="7" stroke="#d97706" stroke-width="1.5" marker-end="url(#lib-arr)"/>
<text x="403" y="11" font-size="11" fill="#6b7280">active loan</text>
</g>
</svg>

Read off the three tasks directly from the picture:

- **Alice → Hamlet**: green source, available slot on Hamlet. Borrow approved.
- **Bob → Hamlet**: amber source, capped. Refused before we even look at the book.
- **Alice → Ulysses**: green source — but Ulysses has no available copies. Refused on the book side.

The whole point of the verifier is to mechanize that visual reasoning.

---

## 7. Layer F — Tasks

[`tasks.json`](../domains/library/tasks.json) has three tasks, each with
a structured `operational_spec.intent`:

| Task | Intent | Expected | Tests which branch |
|---|---|---|---|
| LIB-T-001 | `alice` borrows `hamlet` | `unique` (cancel succeeds) | both branches hold |
| LIB-T-002 | `bob` borrows `hamlet` | `policy_refused` | cardinality (N=3, fails `N < 3`) |
| LIB-T-003 | `alice` borrows `ulysses` | `policy_refused` | availability (`has_available_copy(ulysses)` = false) |

Each task's `c_hard` is a one-line description of the expected D\*
diff (or "D\* = D₀" for refusals). `c_known` and `c_unknown` are
omitted — the micro-world doesn't need them.

---

## 8. Running Verify

Now we run the verifier and watch the chain fire.

```sh
uv run python tools/library_verify.py
```

The output:

```
ID           task_class     verdict            models   ok
──────────────────────────────────────────────────────────
LIB-T-001    mutating       unique             1        ✓
LIB-T-002    policy_noop    policy_refused     0        ✓
LIB-T-003    policy_noop    policy_refused     0        ✓

SUMMARY: 3/3 library tasks verified.
```

Each row tells you a real thing:

- **`unique` with 1 model** → exactly one D\* satisfies the policy. The
  borrow is well-posed.
- **`policy_refused` with 0 models** → no D\* satisfies the policy. The
  borrow is correctly forbidden.

The detail panel for LIB-T-001 shows the derivation chain:

```
LIB-T-001:
  intent: {'action': 'borrow_book', 'borrower_id': 'alice', 'book_id': 'hamlet'}
  verdict: unique (1 model(s))
  derivation:
    • active_loan_count(alice,0)         ← Alice has 0 loans
    • active_loan_count(bob,3)           ← Bob has 3 (irrelevant here)
    • available_copies(hamlet,1)         ← 2 total − 1 out = 1
    • available_copies(iliad,0)          ← (irrelevant)
    • available_copies(ulysses,0)        ← (irrelevant)
    • can_borrow(alice,hamlet)           ← both branches hold
    • target_borrow(alice,hamlet)        ← what the task pinned
```

This is what "mechanically proven" means in practice. Clingo derived
`active_loan_count(alice, 0)` by counting. It derived
`available_copies(hamlet, 1)` by subtracting. It composed both to
derive `can_borrow(alice, hamlet)`. The chain is visible.

### The derivation chain, drawn

<svg viewBox="0 0 720 360" xmlns="http://www.w3.org/2000/svg"
style="font-family:-apple-system,BlinkMacSystemFont,Inter,Segoe UI,sans-serif; max-width:100%; height:auto; display:block; margin:1.5rem auto;">
<defs>
<marker id="deriv-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
<path d="M 0 0 L 10 5 L 0 10 z" fill="#1d4ed8"/>
</marker>
<marker id="deriv-arr-dim" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
<path d="M 0 0 L 10 5 L 0 10 z" fill="#9ca3af"/>
</marker>
</defs>
<text x="22" y="14" font-size="11" font-weight="700" fill="#6b7280" letter-spacing="0.08em">CONCLUSION</text>
<text x="22" y="124" font-size="11" font-weight="700" fill="#6b7280" letter-spacing="0.08em">DERIVED PREDICATES</text>
<text x="22" y="254" font-size="11" font-weight="700" fill="#6b7280" letter-spacing="0.08em">FROM D₀ FACTS + COUNTING</text>
<rect x="220" y="25" width="280" height="60" rx="8" fill="#1d4ed8" stroke="#1d4ed8" stroke-width="2"/>
<text x="360" y="49" text-anchor="middle" font-size="15" font-weight="700" fill="white">can_borrow(alice, hamlet)</text>
<text x="360" y="68" text-anchor="middle" font-size="11" fill="#dbeafe">✓ Clingo proves both bodies hold</text>
<rect x="40" y="135" width="280" height="70" rx="6" fill="#dbeafe" stroke="#1d4ed8" stroke-width="1.5"/>
<text x="180" y="160" text-anchor="middle" font-size="13" font-weight="700" fill="#1a1a1a">active_loan_count(alice, N)</text>
<text x="180" y="180" text-anchor="middle" font-size="12" fill="#1e3a8a">N = 0</text>
<text x="180" y="196" text-anchor="middle" font-size="11" fill="#059669" font-weight="600">0 &lt; 3 ✓</text>
<rect x="400" y="135" width="280" height="70" rx="6" fill="#dbeafe" stroke="#1d4ed8" stroke-width="1.5"/>
<text x="540" y="160" text-anchor="middle" font-size="13" font-weight="700" fill="#1a1a1a">has_available_copy(hamlet)</text>
<text x="540" y="180" text-anchor="middle" font-size="12" fill="#1e3a8a">available_copies(hamlet, 1)</text>
<text x="540" y="196" text-anchor="middle" font-size="11" fill="#059669" font-weight="600">1 ≥ 1 ✓</text>
<line x1="220" y1="135" x2="280" y2="88" stroke="#1d4ed8" stroke-width="1.5" marker-end="url(#deriv-arr)"/>
<line x1="500" y1="135" x2="440" y2="88" stroke="#1d4ed8" stroke-width="1.5" marker-end="url(#deriv-arr)"/>
<rect x="20" y="265" width="200" height="68" rx="6" fill="#fafafa" stroke="#6b7280" stroke-width="1"/>
<text x="120" y="284" text-anchor="middle" font-size="11" font-weight="600" fill="#4b5563">count loans where</text>
<text x="120" y="300" text-anchor="middle" font-size="11" fill="#4b5563">borrower = alice ∧</text>
<text x="120" y="314" text-anchor="middle" font-size="11" fill="#4b5563">status = active</text>
<text x="120" y="328" text-anchor="middle" font-size="12" font-weight="700" fill="#059669">→ 0</text>
<rect x="240" y="265" width="220" height="68" rx="6" fill="#fafafa" stroke="#6b7280" stroke-width="1"/>
<text x="350" y="284" text-anchor="middle" font-size="11" font-weight="600" fill="#4b5563">total_copies(hamlet) = 2</text>
<text x="350" y="300" text-anchor="middle" font-size="11" fill="#4b5563">active loans on hamlet = 1</text>
<text x="350" y="328" text-anchor="middle" font-size="12" font-weight="700" fill="#059669">→ 2 − 1 = 1</text>
<rect x="480" y="265" width="220" height="68" rx="6" fill="#fafafa" stroke="#6b7280" stroke-width="1"/>
<text x="590" y="284" text-anchor="middle" font-size="11" font-weight="600" fill="#4b5563">has_available_copy(K) :-</text>
<text x="590" y="300" text-anchor="middle" font-size="11" fill="#4b5563">  available_copies(K, N),</text>
<text x="590" y="314" text-anchor="middle" font-size="11" fill="#4b5563">  N ≥ 1.</text>
<line x1="140" y1="265" x2="170" y2="208" stroke="#9ca3af" stroke-width="1" stroke-dasharray="3 3" marker-end="url(#deriv-arr-dim)"/>
<line x1="350" y1="265" x2="490" y2="208" stroke="#9ca3af" stroke-width="1" stroke-dasharray="3 3" marker-end="url(#deriv-arr-dim)"/>
<line x1="590" y1="265" x2="560" y2="208" stroke="#9ca3af" stroke-width="1" stroke-dasharray="3 3" marker-end="url(#deriv-arr-dim)"/>
</svg>

Read it bottom-up: from the D₀ facts (gray boxes), counting and
arithmetic produce intermediate derived predicates (blue boxes), and
the top `can_borrow` derivation requires both of them to hold. If
either lower-tier check fails — Alice at the cap, Hamlet at zero
copies — the chain doesn't reach the top, no model exists, and the
verifier reports `policy_refused`. That's all that "0 models" means.

For LIB-T-002 and LIB-T-003 the chain stops at the mid tier and no
model exists, so the verifier reports `policy_refused`.

---

## 9. Solve — derive D\* directly

For LIB-T-001 the verifier also runs Solve. The Python action simulator
applies `borrow_book(alice, hamlet)` and computes the structured diff:

```
Solve-derived D* diff:
  → loan/loan_NEW_LIB-T-001: NEW (borrower=alice, book=hamlet, status=active)
  → borrower/alice.active_loan_count: 0 → 1
  → book/hamlet.available_copies: 1 → 0
```

Three changes. The new loan record. Alice's active count incremented.
Hamlet's available copies decremented. **Nothing else changes.** That's
the canonical D\* — and we got it from the spec alone, without writing
gold actions.

For the refusal tasks (T-002, T-003), Solve reports `D* = D₀` — no
mutation, by definition. The verifier confirms this matches the
declared `policy_noop` class.

---

## 10. What a "Generate" variant looks like

The methodology's third operation — Generate — synthesizes new tasks at
controlled difficulty by varying scenario knobs. The library is too
small for a real scenario library, but here's the idea applied
manually.

Take LIB-T-001 (Alice borrows Hamlet). Vary one knob: how many loans
does Alice already have?

| Variant | Alice's loans | Hamlet available | Expected | Pruning |
|---|---|---|---|---|
| 0 active | 0 | 1 | `unique` | 1→1 |
| 2 active | 2 | 1 | `unique` (just inside cap) | 1→1 |
| 3 active | 3 | 1 | `policy_refused` (at cap) | 0→0 |

The boundary is mechanical: `N < 3` is the condition; at `N = 3` the
borrow is refused. The verifier respects the boundary exactly,
without any human deciding what counts as "at the cap."

In the real `tools/generate.py` (for retail_returns), this knob-sweep
pattern is what powers the difficulty calibration:
```sh
uv run python tools/generate.py happy_path_self_return \
    member_tier=regular,plus days_since_fulfillment=15,30,60,90
```
produces eight variants spanning the policy boundary, each
mechanically verified.

---

## 11. What you just saw, in methodology terms

You read six layers of spec, all internally consistent. You ran a
verifier that:

1. Loaded `rules.md` and parsed the ASP code.
2. Encoded `db.json` as ground facts.
3. For each task, asked Clingo: "given (D₀, Policy, intent), how many
   answer sets exist?"
4. Reported `unique` (1) / `policy_refused` (0) / `ambiguous` (>1) /
   `infeasible` (0 for a mutating task).
5. For the `unique` case, applied a Python action simulator to
   produce the structured D* diff.

**No hand-tuned database.** The D₀ was authored to make all three
tasks well-posed; the verifier confirmed that mechanically.

**No hand-authored gold actions.** Solve derived D* from the
spec alone.

**No prose ambiguity.** The cap of 3 is in `rules.md`; the boundary
is enforced exactly by Clingo's evaluation. If you change the rule to
`N < 4`, every task re-verifies under the new policy.

This is what the methodology does. The library micro-world is the
smallest place to see it; the
[retail_returns worked example](../domains/retail_returns/) is the same
machinery scaled up to 6 sorts, 25 invariants, 38 deontic rules, and
6 tasks. The
[airline retrofit](../domains/airline/) is the same machinery applied
to a corpus that wasn't designed for the methodology — 8/8 upstream
cross-validation.

---

## 12. Where to go next

If you want to **see the methodology at scale**, read
[`methodology.md`](methodology.md) (the framework) or
[`findings.md`](findings.md) (the empirical writeup with results).

If you want to **understand where the methodology came from and where
it sits in the landscape**, read [`lit_review.md`](lit_review.md) (42
papers across six topic areas).

If you want to **build something new on top**, read
[`next_steps.md`](next_steps.md) (a tiered roadmap with effort
estimates).

If you want to **see this same pattern on a real domain**, the
retail_returns tutorial is the entire `domains/retail_returns/`
directory plus `tools/clingo_verify.py`. Open
[`retail_returns/ontology.md`](../domains/retail_returns/ontology.md)
and follow the same six-layer structure you just saw here.

The library is a teaching artifact. Everything you see here scales
up; nothing here doesn't generalize. That's the point of the
methodology.
