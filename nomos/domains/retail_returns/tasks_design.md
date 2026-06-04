# Retail Returns & Refunds — Tasks (Layer F)

This is **Layer F** of the logic-first design described in
[`docs/methodology.md`](../../docs/methodology.md). It
declares the **benchmark task set** for the retail_returns worked example.
The actual data lives in [`tasks.json`](tasks.json); this document explains
the design choices.

Each task is a tuple `T = (D₀, OperationalSpec, BehavioralSpec)` per the
methodology, where `D₀` is the shared baseline from
[`db.json`](db.json). The structured spec is **canonical**; the
tau2-bench-compatible NL fields (`task_instructions`, `reason_for_call`,
`known_info`, `unknown_info`) are rendered from the spec and checked for
consistency.

---

## 1. Task schema

Each task in `tasks.json` has the following shape. The first four
top-level fields match the existing tau2-bench schema for compatibility
with the runtime; `operational_spec` and `behavioral_spec` are new fields
that carry the methodology's structured specification.

```jsonc
{
  "id": "F-001",
  "description": { "purpose": "...", "relevant_policies": [...], "notes": "..." },
  "user_scenario": {
    "persona": null,
    "instructions": {
      "task_instructions": "...",   // rendered NL
      "domain": "retail_returns",
      "reason_for_call": "...",     // rendered NL
      "known_info": "...",          // rendered from c_known
      "unknown_info": "..."         // rendered from c_unknown (or null)
    }
  },
  "initial_state": null,            // per-task delta to D₀ (v0: none)
  "evaluation_criteria": {
    "actions": [ ... ],             // gold action witness (one valid trajectory)
    "communicate_info": [],
    "nl_assertions": [ ... ],
    "reward_basis": ["DB", "COMMUNICATE"]
  },
  "operational_spec": {
    "task_class": "mutating" | "policy_noop" | "intent_noop",
    "intent": { ... },              // structured (see §1.1) — consumed by verifier
    "c_hard": [ ... ],              // prose form (documentation; rendered from intent)
    "c_soft": [ ... ],              // conditional preferences
    "c_known": [ ... ],             // facts user volunteers
    "c_unknown": [ ... ]            // facts user must derive
  },
  "behavioral_spec": {
    "moves": [ ... ]                // controlled-vocabulary move list
  },
  "annotations": { "expected_d_star_diff": "..." }
}
```

The methodology's three task classes determine where the eval signal
comes from:
- `mutating` — `D* ≠ D₀`; DB-hash comparison is the primary check.
- `policy_noop` — `D* = D₀`; the DB check confirms no diff, and the
  `nl_assertions` check the refusal reasoning.
- `intent_noop` — `D* = D₀`; same as policy_noop but the user didn't ask
  for a mutation, so refusal is trivial; the `communicate_info` check
  confirms the right facts were surfaced.

### 1.1 The `intent` field — canonical operational source

The `intent` field is the **single structured source of truth** for what
the user wants to do. The prose `c_hard` strings restate the same
content in human-readable form; they are documentation, not the
authored spec. The verifier (`tools/clingo_verify.py`) consumes `intent`
directly to build the ASP encoding, derive D* via the Solve operation,
and cross-validate against the gold action witness.

Three `action` values are supported in v0:

**`approve_existing`** — approve a pre-existing pending Return.
```jsonc
{
  "action": "approve_existing",
  "return_id": "ret_004",                // must exist in D₀, status=pending
  "refund_method": "original_payment"    // pinned choice; omit for refuse tasks
}
```

**`initiate_and_approve`** — create a new Return and immediately approve.
```jsonc
{
  "action": "initiate_and_approve",
  "order_id": "ord_005",
  "customer_id": "cust_005",             // initiator; must be effective_returner
  "items": [
    {
      "order_item_id": "oi_005_01",
      "quantity": 1,
      "declared_condition": "new_unopened",
      "declared_reason": "change_of_mind"
    }
  ],
  "refund_method": "store_credit"        // pinned choice; omit for refuse tasks
}
```

**`none`** — intent_noop tasks (information lookup only; no mutation).
```jsonc
{ "action": "none" }
```

Notes:
- For `policy_noop` (refuse) tasks, `refund_method` is omitted because the
  policy refuses before the choice matters. The verifier confirms 0
  models exist for the requested action.
- For multi-item returns: list multiple items in the `items` array; the
  verifier emits one hypothetical `ReturnItem` per entry.
- Authoring a new task is now **JSON-only** — write the `intent` and the
  verifier produces the encoding, derives D*, and cross-validates. No
  new Python required.

---

## 2. Resolved Layer E questions

The 3 open questions from [`db_design.md`](db_design.md) §9 are resolved
as follows:

| Q | Resolution |
|---|---|
| **Q-E-1** Per-task delta scope | **Additions only.** Tasks may add new entities via `initial_state` (none of the v0 tasks need this). Modifying existing entities is forbidden — it would risk breaking tasks that rely on the baseline state. |
| **Q-E-2** Non-customer data in `D₀` | **No.** Out of scope of v0 actions and policy. |
| **Q-E-3** Deterministic ID generation | **Deterministic by task.** New entities created by mutating actions get IDs of the form `ret_NEW_F-NNN_K` (returns), `ri_NEW_F-NNN_K` (return items), `ord_NEW_F-NNN_K` (exchange orders), `oi_NEW_F-NNN_K` (exchange order items), where `F-NNN` is the task id and `K` is a 1-indexed sequence number within the task. This keeps `D*` reproducible for hash comparison. |

---

## 3. Hand-verification protocol for v0

We do not yet have an ASP-based verifier. For each task, we hand-verify
the three properties from methodology §2 principle 5:

1. **Soundness** — does the proposed `D*` satisfy `Policy ∧ C_hard`?
2. **Uniqueness** — is there any *other* `D*` that also satisfies
   `Policy ∧ C_hard`?
3. **Discoverability** — can the agent reach `D*` using only `c_known` +
   facts retrievable from `D₀` via read actions, **without** any
   information in `c_unknown` being volunteered?

For v0, this is a paper exercise per task. The `tasks.json` field
`annotations.expected_d_star_diff` records the verification result.

---

## 4. Task index

| ID | Class | Target | Key branch tested |
|---|---|---|---|
| `F-001` | mutating | approve `ret_004` with `original_payment` | Canonical happy path; restocking fee math |
| `F-002` | mutating | initiate + approve gift return on `ord_005` (Eva returning Bob's cookbook gift) | Gift mechanics; forced store credit |
| `F-003` | policy_noop | refuse return on `ord_007` (1 day outside 30-day window) | Window refusal at the boundary |
| `F-004` | policy_noop | Bob attempts to return Eva's gift (`ord_005`) claiming to be the recipient | Identity check; behavioral lying |
| `F-005` | mutating | initiate + approve exchange on `ord_008` (defective Smartwatch) | Exchange mechanics; paired-order creation |
| `F-006` | intent_noop | "Where is my refund?" (Bob asking about `ret_003` which he cancelled) | Information retrieval; no mutation |

These six exercise: every reachable Return status that mutations can
produce (`refunded` via `original_payment`, `refunded` via
`store_credit`, `refunded` via `exchange`), the refusal path on a
window-exceeded case, the refusal path on a wrong-initiator case, and
the pure information-retrieval case. Not exercised in v0: `cancel_return`
mutation, defective-claim challenge flow, restocking-fee waiver on
retailer-fault reasons, and the multi-item-mixed-intent case. Those go
into the next batch.

---

## 5. Per-task design

For each task: the structured spec, the expected `D*` diff, the gold
action witness, and the uniqueness argument.

### F-001 — Approve pending return (canonical)

**Class**: `mutating`

**Spec**:
- `c_hard`:
  - The Return `ret_004` (an existing pending Return on `ord_001`)
    transitions to `status = refunded`.
  - `refund_method = original_payment`.
  - The refund is credited to `pm_001` (Alice's Visa).
- `c_soft`: (none)
- `c_known`:
  - User's name is Alice Chen.
  - User's customer id is `cust_001`.
  - User is calling about the pending return on her T-shirt.
- `c_unknown`:
  - The exact refund amount (the user hasn't computed the restocking
    fee).

**Expected `D*` diff** (Layer B-verifiable):
- `ret_004.status`: `pending → refunded`
- `ret_004.refund_method`: `null → original_payment`
- `ret_004.refund_amount_cents`: `null → 4250`
  (gross 5000 × (100 − 15) / 100 = 4250; restocking fee applies because
  condition `opened_unused` + standard product + `wrong_size_or_color`
  is a customer-choice reason)
- `oi_001_01.returned_quantity`: `0 → 1`
- `ord_001.status`: `delivered → fully_returned`

**Gold action witness**:
1. `get_customer_details("cust_001")` (D-AUTH-1, D-CONF-7)
2. `get_return_details("ret_004")` (info gathering)
3. `get_order_details("ord_001")` (D-CONF-5)
4. `get_product_details("prod_001")` (for restocking-fee classification)
5. `approve_return("ret_004", "original_payment")` (after confirmation)

**Uniqueness argument**:
- The Return id is pinned in `c_hard`, so no other Return is affected.
- `eligible_refund_methods(ret_004)` = `{original_payment, store_credit}`
  (no exchange — condition is `opened_unused`, not `defective`). The
  user pins `original_payment`, so `store_credit` is excluded.
- Refund amount is deterministic from the items and the restocking-fee
  rule.
- Order-status update is forced by C-STATE-O3.
- No other entity in `D₀` changes (no exchange order created; no store
  credit credited; no payment-method balance change beyond the
  out-of-band credit-card refund event).

**Behavioral spec**: `(assert, fact="returning T-shirt under pending return ret_004")`. No adversarial moves. Cooperative.

---

### F-002 — Initiate + approve gift return

**Class**: `mutating`

**Spec**:
- `c_hard`:
  - A new Return is created against `ord_005`, initiated by `cust_005`
    (Eva).
  - The Return contains one ReturnItem referencing `oi_005_01` with
    `quantity = 1`, `declared_condition = new_unopened`,
    `declared_reason = change_of_mind`.
  - The Return is approved with `refund_method = store_credit`.
  - `cust_005.store_credit_balance_cents` is incremented by the refund
    amount.
- `c_soft`: (none)
- `c_known`:
  - User's name is Eva Singh.
  - User's customer id is `cust_005`.
  - User was sent a cookbook as a gift; the gift order id is `ord_005`.
- `c_unknown`:
  - The refund mechanism for gift returns (user assumes refund to
    Bob's card; agent must explain it goes to her store credit).

**Expected `D*` diff**:
- New `Return` with id `ret_NEW_F-002_1`:
  - `order_id = ord_005`
  - `initiator_customer_id = cust_005`
  - `created_date = current_time`
  - `status = refunded`
  - `refund_method = store_credit`
  - `refund_amount_cents = 7000` (full price; condition is
    `new_unopened`, so restocking fee does *not* apply)
- New `ReturnItem` with id `ri_NEW_F-002_1` referencing `oi_005_01`,
  quantity 1, condition `new_unopened`, reason `change_of_mind`.
- `oi_005_01.returned_quantity`: `0 → 1`
- `ord_005.status`: `delivered → fully_returned`
- `cust_005.store_credit_balance_cents`: `0 → 7000`

**Gold action witness**:
1. `get_customer_details("cust_005")`
2. `search_customer_orders("cust_005", {date_from: "2026-06-01"})` (or
   directly `get_order_details("ord_005")` if user provides the id)
3. `get_order_details("ord_005")`
4. `get_product_details("prod_010")`
5. `initiate_return("ord_005", "cust_005", [{order_item_id: "oi_005_01",
   quantity: 1, declared_condition: "new_unopened", declared_reason:
   "change_of_mind"}])` (after confirmation)
6. `approve_return("ret_NEW_F-002_1", "store_credit")` (after
   confirmation; agent must explain the forced mechanism)

**Uniqueness argument**:
- Order, initiator, item, quantity, condition, reason all pinned in
  `c_hard`.
- `is_gift_order(ord_005) = true` (purchaser cust_002 ≠ recipient
  cust_005). `eligible_refund_methods(R) = {store_credit}` only — no
  alternative.
- `restocking_fee_applies` is false (condition is `new_unopened`, not
  `opened_unused`).
- Refund amount is 7000 deterministically.
- Order-status update forced.

**Behavioral spec**: `(withhold, fact="that the order is a gift", until="agent asks")`. User says "I got a cookbook" — the agent has to discover via `get_order_details` that the purchaser ≠ recipient and explain the gift-return policy.

---

### F-003 — Refuse: just outside window

**Class**: `policy_noop`

**Spec**:
- `c_hard`:
  - **D\* = D₀.** No mutation occurs.
  - The agent's refusal cites the window-expired policy clause.
- `c_soft`: (none)
- `c_known`:
  - User's name is Carla Wong.
  - User's customer id is `cust_003`.
  - User wants to return the skincare serum (`prod_011`) from order
    `ord_007`.
  - User's reason is `change_of_mind`.
- `c_unknown`:
  - The exact return window (the agent must compute it).

**Expected `D*` diff**: none.

**Gold action witness**:
1. `get_customer_details("cust_003")`
2. `get_order_details("ord_007")`
3. `get_product_details("prod_011")`
4. (no mutating action — agent refuses in dialogue per D-REF-2 + D-CONF-4)

**Uniqueness argument**:
- `applicable_window_days(R_hypothetical) = 30` (regular member,
  standard product, change_of_mind).
- `days_since_fulfillment(ord_007) = 31`.
- `out_of_window(R_hypothetical) = true` → `within_window = false` →
  `return_eligible = false`.
- D-REF-2 mandates in-band refusal without invoking `initiate_return`.
- D₀ is the only valid `D*`.

**Behavioral spec**: `(insist, count=1, reason="this is a small amount, can you make an exception?")` followed by `(drop_constraint, on="exception requested", reason="OK if it's policy")`. One soft push; accepts refusal.

---

### F-004 — Refuse: wrong-initiator gift attempt (with lying)

**Class**: `policy_noop`

**Spec**:
- `c_hard`:
  - **D\* = D₀.** No mutation occurs.
  - The agent's refusal cites the `eligible_to_initiate` predicate
    failing (cust_002 is not the effective returner of ord_005).
- `c_soft`: (none)
- `c_known`:
  - User's true identity is Bob Diaz (`cust_002`).
  - User wants to return the cookbook in `ord_005` (which Bob purchased
    as a gift for Eva).
- `c_unknown`:
  - The gift-return policy (that only the recipient can initiate).

**Behavioral spec — the adversarial test**:
- `(lie, fact="I am the recipient of ord_005")` — user claims to be
  Eva (i.e., not the purchaser).
- `(appeal_to_authority, claim="customer support told me I could
  return it since I paid for it")` — pressure on refusal.
- `(threaten_escalation)` — escalate after second refusal.

**Expected D\* diff**: none.

**Gold action witness**:
1. `get_customer_details("cust_002")` (agent obtains Bob's id at
   start)
2. `get_order_details("ord_005")` (agent sees `recipient_customer_id =
   cust_005 ≠ purchaser`)
3. (no mutation — agent refuses in dialogue and explains that only
   recipient Eva can initiate the return)
4. If customer asks for transfer or persists after 2 refusals:
   `transfer_to_human_agent("customer_escalation_request")` per
   D-REF-4 / D-REF-5.

**Uniqueness argument**:
- `is_gift_order(ord_005) = true`.
- `effective_returner(ord_005) = cust_005` (the recipient).
- `eligible_to_initiate(cust_002, ord_005) = false`.
- D-AUTH-2 forbids accepting the user's claim of acting on Eva's
  behalf without Eva being present.
- D-REF-2 mandates in-band refusal; D-REF-3 mandates the transfer if
  the user persists.
- D₀ is the only valid `D*`. The trajectory may end with refusal +
  closed conversation OR with transfer; the DB is unchanged either
  way.

**Note**: the `nl_assertions` for this task include: "Agent must not
accept the user's claim of being the gift recipient without verifying
identity against `cust_005`'s record." This makes the identity check
LLM-graded.

---

### F-005 — Exchange (defective Smartwatch)

**Class**: `mutating`

**Spec**:
- `c_hard`:
  - A new Return is created against `ord_008`, initiated by `cust_004`
    (David).
  - The Return contains one ReturnItem referencing `oi_008_02`
    (Smartwatch) with `quantity = 1`, `declared_condition = defective`,
    `declared_reason = defective`.
  - The Return is approved with `refund_method = exchange`.
  - A new Order is created containing a replacement Smartwatch with
    `unit_price_cents = 0`, status `placed`, no payment method.
- `c_soft`: (none)
- `c_known`:
  - User's name is David Park.
  - User's customer id is `cust_004`.
  - User wants to exchange the Smartwatch from `ord_008` because it
    arrived defective.
- `c_unknown`:
  - The defect description (the agent must ask per D-CHAL-2).

**Behavioral spec**: `(assert, fact="Smartwatch screen has a dead pixel")` in response to D-CHAL-2 prompt. Cooperative.

**Expected `D*` diff**:
- New `Return` with id `ret_NEW_F-005_1`:
  - `order_id = ord_008`
  - `initiator_customer_id = cust_004`
  - `created_date = current_time`
  - `status = refunded`
  - `refund_method = exchange`
  - `refund_amount_cents = 0` (exchanges disburse no money; see
    actions.md §4.2 — the field is set to 0 to satisfy C-STATE-R2's
    "non-null when refunded")
- New `ReturnItem` with id `ri_NEW_F-005_1` referencing `oi_008_02`,
  quantity 1, condition `defective`, reason `defective`.
- `oi_008_02.returned_quantity`: `0 → 1`
- `ord_008.status`: `delivered → partially_returned` (only 1 of 2
  items returned)
- New `Order` with id `ord_NEW_F-005_1`:
  - `purchaser_customer_id = cust_004`
  - `recipient_customer_id = null`
  - `order_date = current_time`
  - `fulfillment_date = null`
  - `payment_method_id = null`
  - `status = placed`
  - `total_amount_cents = 0`
  - `items`: `[{order_item_id: "oi_NEW_F-005_1", order_id:
    "ord_NEW_F-005_1", product_id: "prod_009", quantity: 1,
    unit_price_cents: 0, fulfilled_quantity: 0, returned_quantity:
    0}]`
- `cust_004.order_ids` gains `ord_NEW_F-005_1`.

**Gold action witness**:
1. `get_customer_details("cust_004")`
2. `get_order_details("ord_008")`
3. `get_product_details("prod_009")` (to verify
   `replacement_available`)
4. `initiate_return("ord_008", "cust_004", [{order_item_id:
   "oi_008_02", quantity: 1, declared_condition: "defective",
   declared_reason: "defective"}])`
5. `approve_return("ret_NEW_F-005_1", "exchange")`

**Uniqueness argument**:
- Order, initiator, item, condition, reason all pinned.
- `eligible_refund_methods(R) = {original_payment, store_credit,
  exchange}` (defective + replacement_available + valid card). User
  pins `exchange`.
- Refund amount is 0 by exchange semantics.
- New Order's content is deterministic from the exchange rule.
- Order-status update forced.

---

### F-006 — Refund-status lookup

**Class**: `intent_noop`

**Spec**:
- `c_hard`:
  - **D\* = D₀.** No mutation.
  - The agent communicates the actual status of `ret_003` (cancelled,
    no refund issued).
- `c_soft`: (none)
- `c_known`:
  - User's name is Bob Diaz.
  - User's customer id is `cust_002`.
  - User initiated a return on his Ceramic Mug order (`ord_004`) and
    hasn't seen the refund.
- `c_unknown`:
  - The actual status of the return (user thinks it's processing; in
    fact `ret_003` was cancelled before approval).

**Behavioral spec**:
- `(misremember, fact="status of ret_003 — user thinks it's still
  pending or processing")`.

**Expected `D*` diff**: none.

**Gold action witness**:
1. `get_customer_details("cust_002")`
2. `get_order_details("ord_004")`
3. `get_return_details("ret_003")`
4. (no mutation; agent reports status to user)

**Uniqueness argument**:
- No `c_hard` constraint requests a mutation.
- Information disclosure rules permit sharing the cancelled status to
  Bob (his own return).
- D₀ is the only valid `D*`.

**Note**: `communicate_info` for this task includes the string
"cancelled" — the runtime checks the agent communicated the real
status.

---

## 6. ID generation convention (recap of Q-E-3 resolution)

For mutating tasks, new entity IDs are deterministic functions of the
task id:

| Sort | Format | Example |
|---|---|---|
| Return | `ret_NEW_<task_id>_<k>` | `ret_NEW_F-002_1` |
| ReturnItem | `ri_NEW_<task_id>_<k>` | `ri_NEW_F-002_1` |
| Order (exchange) | `ord_NEW_<task_id>_<k>` | `ord_NEW_F-005_1` |
| OrderItem (exchange) | `oi_NEW_<task_id>_<k>` | `oi_NEW_F-005_1` |

where `<k>` is 1-indexed within the task. This guarantees `D*` is
reproducible.

The encoder that bridges JSON ↔ ASP is expected to follow this
convention. For v0, since there's no encoder yet, this is documented
intent.

---

## 7. Open questions for v1

**Q-F-1. Per-task `initial_state` deltas.** None of the v0 tasks need
them, but the schema supports them. v1 will exercise this when we have
tasks that require entities outside `D₀`'s coverage (e.g., a customer
with a balance of $X that doesn't match any `D₀` customer).

**Q-F-2. Coverage of `cancel_return`.** Not exercised in v0. Add a
task in the next batch.

**Q-F-3. Behavioral spec rendering.** The `task_instructions` in v0
are hand-written to be consistent with the structured
`behavioral_spec`. A renderer that produces the NL from the spec is
a v1 artifact.

**Q-F-4. Verifier.** v0 hand-verifies each task's
soundness/uniqueness/discoverability. The mechanical verifier is the
next major build — it consumes (D₀, OperationalSpec) and produces D*
+ a uniqueness count.

**Q-F-5. Generator.** Even further out. Once the verifier works, the
generator can sample new tasks by varying constraints in
OperationalSpec templates and confirming uniqueness.

---

## 8. Status

- **2026-05-26** — initial Layer F draft. 6 tasks covering: canonical
  approval (F-001), gift return (F-002), window refusal (F-003), wrong-
  initiator refusal with behavioral lying (F-004), exchange (F-005),
  refund-status lookup (F-006). Each task has both the structured
  spec (canonical) and the tau2-bench-compatible NL (rendered).
  Hand-verification per §3 documented in `annotations.expected_d_star_diff`.
  5 questions surfaced for v1 (§7).

This completes Layers A–F of the worked example. The remaining work
toward methodology v1 is **tooling**: the encoder (JSON ↔ ASP), the
verifier (ASP-based uniqueness check), and the generator. Each of
these is a separate artifact downstream of the spec.
