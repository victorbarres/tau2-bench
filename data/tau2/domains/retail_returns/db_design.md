# Retail Returns & Refunds — World Instantiation (Layer E)

This is **Layer E** of the logic-first design described in
[`docs/logic_first_design.md`](../../../../docs/logic_first_design.md). It
documents the **baseline database state `D₀`** for the retail_returns
worked example. The actual data lives in [`db.json`](db.json); this
document explains the design choices.

Layer E's contract with downstream layers:
- Every entity in `D₀` satisfies the ontology ([`ontology.md`](ontology.md))
  schema.
- `D₀` as a whole satisfies every integrity constraint in
  [`rules.md`](rules.md) §2.
- The derived predicates in [`rules.md`](rules.md) §3 evaluate correctly
  on `D₀`.
- The action surface in [`actions.md`](actions.md) is sufficient to
  reach interesting target states from `D₀`.

Layer F (tasks) is permitted to add per-task *deltas* — new customers,
new orders, new products — layered on top of `D₀` via the
`initial_state` field of a task. The shared baseline is fixed; tasks
expand it.

---

## 1. Frozen wall-clock

```
current_time = 2026-06-15T12:00:00Z
```

All temporal predicates (`days_since_fulfillment`, `within_window`) are
evaluated against this fixed reference. The choice of date is
arbitrary; what matters is that it positions our orders at meaningful
distances from various return-window thresholds:

| Window | Threshold | Earliest fulfillment_date still in window |
|---|---|---|
| Standard, change-of-mind, regular member | 30 days | 2026-05-16 |
| Standard, change-of-mind, plus member | 90 days | 2026-03-17 |
| Damaged-in-shipping | 14 days | 2026-06-01 |
| Defective / missing parts | 365 days | 2025-06-15 |
| Perishable (defect/shipping damage) | 2 days | 2026-06-13 |

D₀ contains at least one order in each row's "in-window" band and at
least one just outside, to exercise the boundary.

---

## 2. Customers

Six customers, chosen to cover the cross-product of
{regular, plus} × {has-store-credit, no-store-credit} ×
{purchaser-only, also-gift-recipient} that Layer F tasks will exercise.

| ID | Name | Tier | Store credit | Roles in D₀ |
|---|---|---|---|---|
| `cust_001` | Alice Chen | regular | $0 | self-purchaser, gift recipient on `ord_009` |
| `cust_002` | Bob Diaz | plus | $50.00 | self-purchaser, gift purchaser on `ord_005` |
| `cust_003` | Carla Wong | regular | $0 | self-purchaser with **invalid** original credit card |
| `cust_004` | David Park | plus | $0 | self-purchaser, gift purchaser on `ord_009`; has multiple credit cards |
| `cust_005` | Eva Singh | regular | $0 | self-purchaser, gift recipient on `ord_005` |
| `cust_006` | Frank Mueller | plus | $200.00 | self-purchaser of `ord_011` (old) and `ord_014` (fully returned) |

Design rationale per customer:

- **`cust_001`** — base case. Regular member, simple self-purchase
  flow. Also a gift recipient, so the gift-return flow can be
  exercised on the same customer.
- **`cust_002`** — base case for plus. Tests the 90-day extension. Has
  pre-existing store credit, so tasks involving "refund to store credit
  on a customer with existing balance" are easy to construct. Also acts
  as the purchaser in a gift order (purchaser ≠ recipient pattern).
- **`cust_003`** — the **invalid-card** scenario. Tests
  `payment_method_valid` failure and the resulting forced
  `eligible_refund_methods` collapse to `store_credit`.
- **`cust_004`** — multi-payment-method scenario. Lets tasks exercise
  the "which credit card was used on which order" disambiguation.
- **`cust_005`** — minimal regular customer; gift recipient. Tests the
  gift-return → store-credit pathway.
- **`cust_006`** — long-tail customer. Has an order from 2025-12-15
  (outside all windows except `defective` / `missing_parts`), and an
  already-fully-returned order. Tests both the "too old to return"
  refusal and the "nothing left to return" precondition.

---

## 3. Products

Twelve products, chosen to cover all five `product_return_class`
values plus enough variety within `standard` to make item-condition
distinctions interesting.

| ID | Name | Return class | Notes |
|---|---|---|---|
| `prod_001` | Cotton T-Shirt — Blue, M | standard | Common item; appears in self orders. |
| `prod_002` | Wireless Headphones | standard | Higher unit price; exchange-eligible. |
| `prod_003` | Ceramic Mug | standard | Low unit price; multi-quantity orders. |
| `prod_004` | Limited-Edition Necklace | final_sale | Non-returnable. |
| `prod_005` | Premium Coffee Beans | perishable | Two-day window for defect/shipping damage only. |
| `prod_006` | Ebook: Intro to Logic Programming | digital | Non-returnable. |
| `prod_007` | Industrial Cleaning Spray | hazmat | Non-returnable in v0. |
| `prod_008` | Wool Sweater — Gray, L | standard | Mid unit price; appears in gift order. |
| `prod_009` | Smartwatch Series 5 | standard | High unit price; appears in plus-member order; replacement available. |
| `prod_010` | Cookbook: Italian Classics | standard | Mid price. |
| `prod_011` | Skincare Serum | standard | Mid price; replacement NOT available (out of stock). |
| `prod_012` | Vinyl Record — The Album | standard | Mid price. |

The `replacement_available/1` predicate is true for all `standard`
products *except* `prod_011`, which models the "exchange requested but
no stock" case (forces `exchange` to drop out of
`eligible_refund_methods`).

---

## 4. Orders

Fourteen orders, positioned across the time grid and covering the
reachable Order statuses. `current_time = 2026-06-15`.

| ID | Purchaser | Recipient | Fulfillment | Days back | Status | Notes |
|---|---|---|---|---|---|---|
| `ord_001` | cust_001 | (self) | 2026-06-01 | 14 | delivered | well inside 30-day window |
| `ord_002` | cust_001 | (self) | 2026-04-01 | 75 | delivered | outside 30-day; in defective window only |
| `ord_003` | cust_002 | (self) | 2026-04-20 | 56 | delivered | inside plus 90-day window |
| `ord_004` | cust_002 | (self) | 2026-05-30 | 16 | delivered | inside any window; referenced by `ret_003` (cancelled) |
| `ord_005` | cust_002 | cust_005 | 2026-06-05 | 10 | delivered | **gift order**; recipient is cust_005 |
| `ord_006` | cust_003 | (self) | 2026-06-10 | 5 | delivered | invalid-card customer; inside window |
| `ord_007` | cust_003 | (self) | 2026-05-15 | 31 | delivered | **just outside 30-day** by one day |
| `ord_008` | cust_004 | (self) | 2026-06-12 | 3 | delivered | inside damaged-in-shipping window |
| `ord_009` | cust_004 | cust_001 | 2026-06-08 | 7 | delivered | **gift order**; recipient is cust_001 |
| `ord_010` | cust_005 | (self) | 2026-06-13 | 2 | delivered | very recent; perishable item |
| `ord_011` | cust_006 | (self) | 2025-12-15 | 182 | delivered | far outside all windows except defective |
| `ord_012` | cust_001 | (self) | (n/a) | — | processing | not yet fulfilled; not returnable |
| `ord_013` | cust_002 | (self) | 2026-05-20 | 26 | partially_returned | referenced by `ret_001` (refunded) |
| `ord_014` | cust_006 | (self) | 2026-05-25 | 21 | fully_returned | referenced by `ret_002` (refunded) |

Window positioning intent:

- `ord_001`, `ord_006`, `ord_008`, `ord_010`: clean happy-path returns.
- `ord_003`: tests plus-member extension (regular member would be out).
- `ord_002`, `ord_007`: just outside the standard window — refusal
  candidates.
- `ord_011`: outside all "common" windows. Tests the "only defective is
  in window" branch.
- `ord_005`, `ord_009`: gift-order flow with two different
  purchaser/recipient pairs.
- `ord_012`: not-yet-delivered. Tests `not return_class_returnable`
  refusal? No — tests the order-status refusal (C-STATE-O1).
- `ord_013`, `ord_014`: pre-existing returns; test discoverability of
  "this has already been partially/fully returned" state.

Order items are listed in [`db.json`](db.json); the variety roughly
maps to:
- Single-item orders (most of them).
- One multi-item order (`ord_008`, with both a clothing and an
  electronics item) for tasks that test mixed-intent or partial-return
  flows.
- One order containing a `final_sale` item (`ord_006` includes
  `prod_004`) to test the "agent refuses this item but offers to
  process the others" path.

---

## 5. Existing Returns

Four pre-existing Returns in `D₀`:

| ID | Order | Status | Refund method | Notes |
|---|---|---|---|---|
| `ret_001` | ord_013 | refunded | original_payment | Drives `ord_013`'s `partially_returned` status. |
| `ret_002` | ord_014 | refunded | store_credit | Drives `ord_014`'s `fully_returned` status. |
| `ret_003` | ord_004 | cancelled | — | Customer withdrew before approval. |
| `ret_004` | ord_001 | pending | — | Awaiting agent action. Used as a target for the canonical "approve a pending return" task. |

Notes:
- `ret_001` and `ret_002` are necessary by C-STATE-O3 / C-BOOK-1: an
  order with `status = fully_returned` must have its
  `returned_quantity` sums equal to total quantity, which means there
  must be `refunded` returns accounting for that.
- `ret_004` provides a ready-made approval target for the simplest
  mutating tasks.
- A `rejected` return would be needed if `reject_return` existed; per
  [`actions.md`](actions.md) §0, it does not, so this status is
  unreachable in v0.

---

## 6. Payment Methods

Nine payment methods:

| ID | Owner | Type | Notes |
|---|---|---|---|
| `pm_001` | cust_001 | credit_card | Visa, valid |
| `pm_002` | cust_002 | credit_card | Mastercard, valid |
| `pm_003` | cust_002 | gift_card | $75 balance |
| `pm_004` | cust_003 | credit_card | Visa, **invalid** (closed) |
| `pm_005` | cust_003 | gift_card | $200 balance |
| `pm_006` | cust_004 | credit_card | Amex, valid |
| `pm_007` | cust_004 | credit_card | Visa, valid |
| `pm_008` | cust_005 | credit_card | Mastercard, valid |
| `pm_009` | cust_006 | credit_card | Visa, valid |

Coverage:
- At least one **invalid credit card** (cust_003) — exercises
  `payment_method_valid` derivation false branch.
- At least one **gift card with balance** (cust_002, cust_003) —
  exercises `payment_method_valid` derivation true branch on gift cards.
- Multiple cards per customer (cust_002, cust_003, cust_004) — tests
  disambiguation when the policy says "to the order's original payment
  method."

---

## 7. Self-verification against Layer B

A run-through of each integrity constraint in
[`rules.md`](rules.md) §2 and where `D₀` satisfies it:

| Constraint | Where satisfied |
|---|---|
| C-CARD-1 (orders have ≥ 1 OrderItem) | All 14 orders have ≥ 1 item. |
| C-CARD-2 (returns have ≥ 1 ReturnItem) | All 4 returns have ≥ 1 item. |
| C-CARD-3 (`fulfilled ∈ {0, quantity}`) | Delivered orders have `fulfilled = quantity`; `ord_012` (processing) has `fulfilled = 0`. |
| C-CARD-4 (`0 ≤ returned ≤ fulfilled`) | All OrderItem `returned_quantity` values are in range. |
| C-CARD-5 (return quantity bounds) | Encoder asserts `valid_return_quantity` for each ReturnItem. |
| C-REF-1 through C-REF-9 (referential) | All FK references in JSON point to existing entities. |
| C-MP-1 (initiator is effective_returner) | Gift returns (none in `D₀`); self returns have initiator = purchaser. |
| C-MP-2 (gift order has distinct purchaser/recipient) | `ord_005`, `ord_009` both have distinct purchaser ≠ recipient. |
| C-STATE-O1 (return only against delivered+) | All return-bearing orders are `delivered` / `partially_returned` / `fully_returned`. |
| C-STATE-O2 (fulfillment_date set when status ≥ shipped) | `ord_012` has no fulfillment_date and is `processing`; all others do. |
| C-STATE-O3 (status matches derivation) | `ord_013` partially_returned: 1 of 2 items returned. `ord_014` fully_returned: all items returned. |
| C-STATE-R1 (only 3 reachable statuses) | All 4 returns are `pending` / `refunded` / `cancelled`. |
| C-STATE-R2 / R3 (terminal data presence) | `refunded` returns have `refund_method` + `refund_amount`; others don't. |
| C-BOOK-1 (returned_quantity matches sum) | `ord_013.oi_001.returned_quantity = 1` matches `ret_001.ri_001.quantity = 1`. `ord_014.oi_001.returned_quantity = 1` matches `ret_002.ri_001.quantity = 1`. |
| C-TIME-1 through C-TIME-3 (chronology) | All dates ordered correctly. |
| C-MONEY-1 / C-MONEY-2 (balances ≥ 0) | All store credit and gift card balances ≥ 0. |
| C-MONEY-3 (refund amount = sum) | `ret_001.refund_amount_cents` and `ret_002.refund_amount_cents` computed from item amounts. |

`D₀` is self-consistent. A v1 verifier would mechanize this table.

---

## 8. What `D₀` enables (preview of Layer F)

The deliberate variety supports task shapes including:

**Mutating tasks (`mutating`):**
- Approve `ret_004` with `original_payment` (Alice's pending return,
  valid card).
- Initiate-and-approve a return on `ord_006` (Carla, invalid card →
  forced to `store_credit`).
- Initiate-and-approve a gift return on `ord_005` (Bob → Eva, must go
  to Eva's store credit).
- Initiate-and-approve an exchange on `ord_009` (defective item,
  `prod_002` headphones with `replacement_available = true`).
- Cancel `ret_004` (customer changes their mind).

**Policy-no-op tasks (`policy_noop`):**
- Attempt return on `ord_007` (1 day outside window).
- Attempt return on `ord_011` for non-defective reason.
- Attempt return on any item from `prod_004` (final_sale) or `prod_006`
  (digital).
- Attempt gift return where purchaser tries to initiate (purchaser ≠
  recipient).
- Attempt exchange of `prod_011` (no replacement available).
- Attempt return on `ord_012` (not yet delivered).
- Attempt return on `ord_014` (fully returned, nothing left).

**Intent-no-op tasks (`intent_noop`):**
- Lookup of `ret_001` refund status.
- Lookup of `ord_013` partial return state.
- Lookup of Bob Diaz's store credit balance.
- "Can I still return this?" — informational eligibility check
  without follow-through.

---

## 9. Open questions for Layer F

**Q-E-1. Per-task delta scope.** Tasks may add new orders / customers
to `D₀`. May they also *modify* existing entities (e.g., bump a
store credit balance)? v0 leaning: deltas are additions only; existing
entities are immutable across tasks. Modifying them risks breaking
other tasks that rely on the baseline.

**Q-E-2. Should `D₀` contain non-customer data the agent might need?**
For example, holiday schedules, business hours, store locations. v0
answer: no. Out of scope of the current actions and policy.

**Q-E-3. Random ID generation.** Should new IDs allocated by mutating
actions (`initiate_return`'s fresh `return_id`) be deterministic? For
the verifier to compare DB hashes, yes — D* must be reproducible. v0
leaning: use a hash of (action name, sorted arguments, current_time)
as the seed, computed by the encoder.

---

## 10. Status

- **2026-05-26** — initial Layer E draft. 6 customers, 12 products,
  14 orders (~30 order items), 4 existing returns, 9 payment methods.
  All Layer B integrity constraints satisfied by construction (§7
  self-verification table). 3 questions surfaced for Layer F (§9).
