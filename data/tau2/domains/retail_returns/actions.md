# Retail Returns & Refunds — Actions (Layer C)

This is **Layer C** of the logic-first design described in
[`docs/logic_first_design.md`](../../../../docs/logic_first_design.md). It
declares the **action surface**: the closed set of operations the agent can
invoke, each as a transition predicate.

Layer C describes **how the world changes** when an action fires. Layer B
([`rules.md`](rules.md)) describes **what is true** in any single DB state.
The two interlock: every action's post-state must satisfy every Layer B
invariant. If it can't, the action's preconditions are not strong enough — the
fix lives in Layer C, not in Layer B.

Layer C does **not** describe when the agent should or must invoke an action,
when confirmation is required, or what to say to the customer. Those are
Layer D (`agent_contract.md`) concerns.

---

## 0. Resolved Layer B questions

The 6 open questions from [`rules.md`](rules.md) §6 are resolved as follows
for v0:

| Q | Resolution | Mechanism |
|---|---|---|
| **Q-B-1** Multiple pending Returns per Order | **Forbidden.** At most one Return per Order with `status = pending`. | Precondition on `initiate_return`. |
| **Q-B-2** Single vs split approve+refund | **Single action.** `approve_return(R, refund_method)` performs the full `pending → refunded` transition atomically (sets refund method, refund amount, increments returned_quantity, applies store credit / replacement order if applicable). | Action design. |
| **Q-B-3** Exchange representation | **Paired Order, same SKU.** `refund_method = exchange` creates a new Order containing only the replacement item(s) with `unit_price_cents = 0`, owned by the same purchaser, `status = placed`. The original Order's `returned_quantity` increments normally; no monetary refund. | Effect of `approve_return` when refund_method = exchange. |
| **Q-B-4** Cancel-return as action | **Distinct action.** `cancel_return(R)` is its own thing; it does not share an entry point with `approve_return`. | Two separate actions. |
| **Q-B-5** Payment-method validity | **Layer B derivation, not external fact.** Defined in [`rules.md`](rules.md) §3.10 from ontology attributes (`valid` on credit_card, `balance_cents > 0` on gift_card). The encoder asserts only the underlying attribute facts; the predicate is derived. | Derivation rule in Layer B. |
| **Q-B-6** Cross-return consistency | **Precondition check.** `initiate_return` rejects if the requested quantity per OrderItem exceeds the unreturned remainder. Layer B's C-CARD-5 + C-BOOK-1 are the safety net; the precondition fails fast. | Precondition on `initiate_return`. |

**v0 design change (2026-05-26): `reject_return` removed from the action
surface.** The original design had `initiate_return` create a pending Return
regardless of eligibility, then `reject_return` move it to `rejected`. This
produced a DB diff (a `rejected` Return record) for what the methodology
calls a `policy_noop` task — contradicting the methodology's claim that
`D* = D₀` for policy_noop. The corrected design: the agent computes
eligibility from the request shape using read actions and, if ineligible,
refuses **in dialogue** without invoking `initiate_return`. This keeps the
DB unchanged for all policy_noop tasks. `initiate_return` retains its
structural-only preconditions; the *agent contract* (Layer D) is
responsible for not invoking it on ineligible requests. The
`rejection_reason` field on Return is preserved in the ontology for v1
compatibility but is unreachable in v0 (forbidden by C-STATE-R1).

---

## 1. Action surface

Nine actions total. Closed; no other operation is invocable.

| Action | Read or mutate | Used to |
|---|---|---|
| `get_customer_details(C)` | read | Look up a customer and their payment methods / store credit. |
| `get_order_details(O)` | read | Look up an order and its items. |
| `get_return_details(R)` | read | Look up an existing return. |
| `get_product_details(P)` | read | Look up a product's return class and category. |
| `search_customer_orders(C, filters)` | read | Find orders for a customer matching filters (date range, status, product). |
| `initiate_return(O, C, items)` | mutate | Create a `pending` Return on Order `O` initiated by Customer `C`. |
| `approve_return(R, refund_method)` | mutate | Move a `pending` Return to `refunded` with the chosen mechanism. |
| `cancel_return(R)` | mutate | Move a `pending` Return to `cancelled` (customer withdrawing). |
| `transfer_to_human_agent(reason)` | escalate | End the agent's session and hand off. No DB effect. |

---

## 2. ASP encoding conventions for actions

Each mutating action is encoded as a relation between a pre-state (`D₀`) and a
post-state (`D₁`). Two snapshots, not a time index.

- **Pre-state predicates** carry no prefix and refer to `D₀`.
- **Post-state predicates** carry a `post_` prefix and refer to `D₁`.
- **Frame axioms** ("everything not touched stays the same") are implicit in
  the encoder and not written out in this doc.
- For each action, the body of the rule is the **precondition**; the head
  encodes the **effect** by asserting `post_*` facts.

In Layer C documentation we describe each action in prose + a relational
sketch, *not* full ASP. The actual ASP encoding is generated mechanically from
the spec. For v0, the encoder produces:
1. The `post_*` assertions for the action's effects.
2. A frame rule: `post_p(...) :- p(...), not modified_by(action, p, ...)`.
3. Re-runs all Layer B integrity constraints on the post-state.

---

## 3. Read actions

Read actions do not mutate `D₀`. They return data that the agent can use in
subsequent reasoning. For the verifier they're invisible (no state change);
for the discoverability check (methodology §11) they're load-bearing — they
define what the agent *can know*.

### 3.1 `get_customer_details(customer_id)`

**Returns**: `Customer` record + the list of `PaymentMethod` records owned by
that customer.

**Preconditions**: `customer(customer_id)` exists.

**Error**: customer not found → returns null; agent must handle.

### 3.2 `get_order_details(order_id)`

**Returns**: `Order` record (including `purchaser_customer_id`,
`recipient_customer_id`, `order_date`, `fulfillment_date`,
`payment_method_id`, `status`) + the list of its `OrderItem` records (each
with `product_id`, `quantity`, `fulfilled_quantity`, `returned_quantity`,
`unit_price_cents`).

**Preconditions**: `order(order_id)` exists.

**Discoverability note**: this is the canonical lookup for a return flow.
Without it, the agent cannot know what items are returnable. Most operational
tasks will require at least one call to this action.

### 3.3 `get_return_details(return_id)`

**Returns**: `Return` record + the list of its `ReturnItem` records.

**Preconditions**: `return(return_id)` exists.

### 3.4 `get_product_details(product_id)`

**Returns**: `Product` record (in particular `return_class`).

**Preconditions**: `product(product_id)` exists.

**Discoverability note**: required for any policy decision that depends on
`return_class` (window selection, exchange eligibility, restocking fee).

### 3.5 `search_customer_orders(customer_id, filters)`

**Returns**: list of `Order` records owned (purchased OR received as gift) by
`customer_id`, matching all supplied filters.

**Filters** (all optional, conjunctive):
- `date_from`, `date_to` — restricts on `order_date`.
- `status_in` — list of `order_status` values to include.
- `contains_product_id` — only orders containing at least one OrderItem of
  this product.

**Preconditions**: `customer(customer_id)` exists.

**Use case**: when the customer doesn't remember the order id but can
describe the order (e.g., "the one I bought last week with the blue widget").

---

## 4. Mutating actions

The three core transitions. Each is described as:

- **Signature** — name and parameters.
- **Preconditions** — must hold in `D₀` for the action to fire.
- **Effects** — diff applied to produce `D₁`.
- **Post-conditions** — implied by Layer B; cited for traceability.
- **Failure modes** — what happens when a precondition is violated.

### 4.1 `initiate_return(order_id, customer_id, items)`

Creates a new Return in `pending` status.

**Signature**:
- `order_id` — the Order being returned against.
- `customer_id` — the initiator. Must be the order's effective returner.
- `items: list[{order_item_id, quantity, declared_condition, declared_reason}]`
  — one entry per ReturnItem.

**Preconditions**:
- `order(order_id)` exists.
- `customer(customer_id)` exists.
- `eligible_to_initiate(customer_id, order_id)` (rules.md §3.5).
- `order_status(order_id, S)` with `S ∈ {delivered, partially_returned}`.
  (Cannot return against a fully_returned order — nothing left to return.)
- **No other Return on `order_id` has status `pending`** (Q-B-1).
- For each `items[i]`:
  - `order_item_of(items[i].order_item_id, order_id)` (the item is on this
    order).
  - `items[i].quantity ≥ 1` and `items[i].quantity ≤ unreturned remainder`
    of that OrderItem. Unreturned remainder = `fulfilled_quantity −
    returned_quantity` (in the pre-state; Layer B's C-BOOK-1 keeps this
    consistent across already-refunded returns).
  - `items[i].declared_condition ∈ item_condition` enum (closed enum check).
  - `items[i].declared_reason ∈ return_reason` enum.
- `items` is non-empty.

**Effects**:
- Allocate a fresh `return_id`. Allocate a fresh `return_item_id` per entry
  in `items`.
- Assert the new Return record: `return_of_order`, `return_initiator`,
  `return_status(return_id, pending)`, `created_date = current_time`.
- Assert each new ReturnItem record: `return_item_of`,
  `return_item_references`, `return_item_quantity`,
  `return_item_condition`, `return_item_reason`.

**Post-conditions** (Layer B):
- `valid_return_quantity` holds for every new ReturnItem (encoder asserts).
- All Layer B integrity constraints continue to hold (`pending` Returns
  don't increment `returned_quantity` yet, so C-BOOK-1 is undisturbed).

**Failure modes**: agent receives an error result with a specific reason
code. Layer D specifies how the agent communicates the failure to the
customer.

### 4.2 `approve_return(return_id, refund_method)`

The single action that performs the full `pending → refunded` transition
(per Q-B-2). All side effects of approval — quantity bookkeeping, monetary
refund, store credit credit, exchange-order creation — happen atomically.

**Signature**:
- `return_id` — the Return to approve.
- `refund_method ∈ {original_payment, store_credit, exchange}`.

**Preconditions**:
- `return(return_id)` exists.
- `return_status(return_id, pending)`.
- `return_eligible(return_id)` (rules.md §4).
- `eligible_refund_methods(return_id, refund_method)` (rules.md §3.9).
- If `refund_method = exchange`: gift orders excluded (already in
  `eligible_refund_methods`); all ReturnItems are `defective`; replacements
  available (also already in `eligible_refund_methods`).

**Effects**:
- `return_status(return_id, refunded)`.
- `refund_method(return_id, refund_method)`.
- Compute total refund: `A = ∑ refund_amount_for(RI, _)` over the Return's
  ReturnItems (rules.md §3.8). Assert `refund_amount(return_id, A)`.
- For each ReturnItem `RI` referencing OrderItem `OI` with quantity `q`:
  increment `returned_quantity(OI)` by `q`.
- Recompute and update `order_status(O)` for each affected Order using the
  derivation in rules.md §3.6 (`delivered → partially_returned` or
  `fully_returned` as appropriate).
- Branch on `refund_method`:
  - `original_payment`: credit the Order's original PaymentMethod by `A`.
    - For `gift_card`: increment `balance_cents` by `A`.
    - For `credit_card`: emit a `refund_to_card(PM, A)` event fact (no
      in-DB balance to mutate). Treated as out-of-band by the system but
      recorded in the answer set.
  - `store_credit`: increment `Customer.store_credit_balance_cents` of the
    Return's initiator by `A`.
  - `exchange`: do **not** disburse any money. Create a new Order:
    - Fresh `order_id`.
    - Same `purchaser_customer_id` as the original.
    - No `recipient_customer_id` (the exchange replacement goes to the
      effective returner, regardless of original gift status).
    - `order_date = current_time`.
    - One OrderItem per original ReturnItem, with the same `product_id` and
      `quantity` as the ReturnItem, and `unit_price_cents = 0`,
      `fulfilled_quantity = 0`.
    - `status = placed`.
    - `payment_method_id = null` (no payment associated with exchanges).

**Post-conditions** (Layer B):
- All integrity constraints hold. Specifically:
  - C-BOOK-1: `returned_quantity` arithmetic matches.
  - C-STATE-R2: terminal-status data is present (refund_method,
    refund_amount).
  - C-STATE-O3: `order_status` matches the derived status.
- For `exchange`, the new Order satisfies all Order invariants (it has at
  least one OrderItem, has a status from the allowed set, etc.).

**Failure modes**: precondition violations are surfaced as specific error
codes. Layer D specifies whether the agent retries, refuses, or transfers.

### 4.3 `cancel_return(return_id)`

Customer withdraws a return they previously initiated.

**Signature**:
- `return_id`.

**Preconditions**:
- `return(return_id)` exists.
- `return_status(return_id, pending)`.

(No eligibility check — the customer can always cancel a pending return.)

**Effects**:
- `return_status(return_id, cancelled)`.
- No quantity, order-status, or monetary side effects.

**Failure modes**: trying to cancel a non-pending return → no-op with a
specific error code.

---

## 5. Escalation

### 5.1 `transfer_to_human_agent(reason)`

Hand off the conversation to a human. No DB effect.

**Signature**:
- `reason: string` — short label citing why escalation is needed (e.g.,
  `"refund_to_closed_card_purchaser"`, `"hazmat_disposal"`).

**Preconditions**: none in v0.

**Effects**: emits a `transfer(reason)` event fact. The system terminates the
agent session.

**Layer D will gate** when this is appropriate (out-of-scope requests,
authority limits exceeded, dialogue irreconcilable). Layer C just declares
the operation exists.

---

## 6. The "one logical transition per task" convention

For v0, every task may contain **at most one logical state transition**
between `D₀` and `D*`. The verifier's contract is `valid_transition(D₀, D₁)`
as a single step.

What this allows:
- A task with **zero** mutating tool calls (intent_noop / policy_noop).
- A task with **one** mutating tool call on a pre-existing entity (e.g.,
  `approve_return` on a pending Return that already exists in `D₀`, or
  `cancel_return` on a pending Return).
- A task with **the `initiate_return` + `approve_return` pair** on a single
  new Return — these compose into one logical transition (a Return is
  created and immediately finalized). Two tool calls, one logical
  transition.

What this forbids:
- Multiple mutations on **different entities**. E.g., "cancel return A and
  also initiate return B" is two logical transitions and must be split
  into two tasks.
- The `initiate_return` + `approve_return` pair on **different** Returns
  in the same task — that's the same kind of multi-entity mutation, just
  obfuscated.

Read actions are unlimited.

This convention is declared here at Layer C because it constrains the
action surface; it is also referenced in Layer F (task model) as a hard
constraint on `OperationalSpec`. Multi-transition tasks are deferred to
v1.

---

## 7. Generated artifacts (downstream of Layer C)

Per the methodology, three artifacts are generated from Layers A + C:

1. **Pydantic data model** — one class per sort (Layer A), one method per
   action (Layer C). For mutating actions, the method body is generated as a
   small driver that runs precondition checks, applies effects, then re-runs
   Layer B invariants as an assertion.
2. **Tool stubs** — one tool per action. The tool description is generated
   from the action's prose (signature, preconditions, error semantics).
   Hand-written prose may be polished after generation but the spec is
   authoritative.
3. **Action validators** — code-level checks that mirror the Layer B
   integrity constraints. Used as defense in depth at runtime; the
   "ground truth" of validity is still Layer B.

In v0 we hand-author all three to validate the methodology; in v1 we'd
generate them.

---

## 8. Open questions for Layer D

Surfaced while writing Layer C. Listed for resolution at Layer D, not now.

**Q-C-1. When can the agent invoke `approve_return` without confirming the
refund mechanism with the customer?** Default: never. The agent must list
the refund method and amount and get explicit "yes" before approve fires.
Layer D will codify.

**Q-C-2. What's the agent's authority to refuse?** With `reject_return`
removed (§0), refusal is a dialogue act, not an action. The agent may
refuse in-band on policy-derivable grounds (window expired, product
non-returnable, customer not the order's effective returner). Softer
grounds (suspected fraud, etc.) require transfer. Layer D codifies the
exact rules.

**Q-C-3. Required reads before each mutation.** Discoverability check:
should we require that the agent has called `get_order_details` and
`get_customer_details` before any mutation on that Order/Customer? It's
implicit because the agent needs the data, but Layer D could make it
explicit. Default: implicit.

**Q-C-4. Refund method when customer is silent.** If the agent says "I can
refund this either to your original card or as store credit — which would
you prefer?" and the customer doesn't choose, what does the agent do?
Default: cannot proceed; must re-ask. Encode as a Layer D rule, not a
Layer C precondition.

**Q-C-5. Exchange when not all items are defective.** A customer wants to
exchange one item and refund another. Under O2 (atomic same-SKU exchange),
this requires two separate returns, conflicting with §6's "one mutating
action per task." v0: either bundle into one Return with `refund_method`
disagreement (rejected by §3.9 — refund_method is per-Return, not per-item),
or split into two tasks. Default: split.

**Q-C-6. Idempotency.** What happens if the agent calls `approve_return`
twice with the same arguments? The second call's preconditions fail (return
is no longer `pending`). Whether the agent handles that gracefully is Layer
D. Default: error to customer, no DB change.

---

## 9. Status

- **2026-05-23** — initial Layer C draft. All 6 Layer B questions resolved
  (§0). 10 actions declared (§1). 4 mutating actions specified in full
  (§4–§5). One-mutation-per-task convention declared (§6). 6 questions
  surfaced for Layer D (§8).
- **2026-05-26** — reconciliation pass. `reject_return` removed from the
  action surface to make `policy_noop` give `D* = D₀` cleanly (in-band
  refusal handled by Layer D D-CONF-4 instead). Action count: 10 → 9.
  Mutating actions: 4 → 3. Q-B-5 resolution updated to point to Layer B
  derivation (rules.md §3.10). Q-C-2 reframed: refusal is a dialogue act,
  not a tool call.

The action surface is now closed for v0. Any new operation requires updating
this document, which cascades to Layers A (if it introduces a new sort or
attribute), B (if it changes what's a valid state), the generated Pydantic
schema, and the tool stubs.
