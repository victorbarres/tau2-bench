# Retail Returns & Refunds — Ontology (Layer A)

This is **Layer A** of the logic-first design described in
[`docs/methodology.md`](../../docs/methodology.md). It
declares the sorts (entity types), their attributes, the closed enumerations,
and the names of the derived predicates that downstream layers will define.

No rules and no constraints are stated here — those belong to Layer B
(`rules.md`). No actions or transitions are stated here — those belong to
Layer C (`actions.md`). No deontic claims — those belong to Layer D
(`agent_contract.md`).

This document is the **single source of truth** for what entities and
vocabulary the domain has. Any other artifact (code schema, DB instances,
NL prose) that disagrees with this document is wrong.

---

## 0. Scope of the domain

The domain models a single retailer's **post-purchase returns and refunds**
flow. A customer service agent handles requests of the form: "I want to
return X" or "where is my refund?". The agent has authority to approve or
deny returns, choose the refund mechanism (original payment / store credit /
exchange), and apply policy-prescribed adjustments (restocking fee, gift
return rules).

**In scope:**
- Identifying the order and items the customer wants to return.
- Verifying eligibility (window, product class, condition).
- Computing refund amount and refund mechanism.
- Executing the return + refund.
- Handling gift returns (recipient ≠ purchaser).
- Refusing ineligible returns with a clear reason.

**Out of scope (intentional):**
- Catalog browsing, search, recommendations.
- Order placement (new purchases).
- Shipment tracking before delivery.
- Fraud detection beyond the rule-based eligibility checks declared here.
- Cross-retailer returns or marketplace seller adjudication.
- Loyalty program enrollment.
- Inventory updates downstream of the return (treated as out-of-band).

---

## 1. Sorts

The closed list of entity types in the domain. Every fact in `D₀` is an
instance of exactly one of these.

| Sort | Description | Identifier |
|---|---|---|
| **Customer** | A person with an account. | `customer_id` |
| **Product** | A catalog entry. Determines return class and category. | `product_id` |
| **Order** | A completed purchase by a customer. | `order_id` |
| **OrderItem** | A line item on an Order: one product × quantity at a unit price. | `order_item_id` |
| **Return** | A return request initiated by a customer against an Order. | `return_id` |
| **ReturnItem** | A line item on a Return: a subset of an OrderItem being returned. | `return_item_id` |
| **PaymentMethod** | A credit card, gift card, or the customer's store credit account, attached to a Customer. | `payment_method_id` |

Notes:

- `Customer.store_credit_balance` is a numeric field, not a separate sort.
- Gift orders are modeled by an optional `recipient_customer_id` on `Order`;
  there is no separate `Gift` sort.
- The catalog is intentionally lean: `Product` carries only the policy-
  relevant attributes (`return_class`, `category`). No marketing fields.

---

## 2. Closed enumerations

Every enumerated attribute below is **closed and finite**. Values outside
these sets are invalid input.

### 2.1 `member_tier` (on Customer)
- `regular`
- `plus`

### 2.2 `product_return_class` (on Product)
Determines whether and how the product can be returned. Independent of
condition or reason.
- `standard` — normal return rules apply.
- `final_sale` — never returnable.
- `perishable` — never returnable for change-of-mind; returnable only if
  `defective` or `damaged_in_shipping` and reported within 48h of delivery.
- `digital` — never returnable (download/access already granted at purchase).
- `hazmat` — cannot be shipped back; refunds available only with
  product-disposal certification (out of scope for v0; treated as
  non-returnable in v0).

### 2.3 `order_status` (on Order)
- `placed`
- `processing`
- `shipped`
- `delivered`
- `partially_returned`
- `fully_returned`
- `cancelled`

### 2.4 `item_condition` (on ReturnItem, declared by customer)
- `new_unopened` — original packaging, seals intact.
- `opened_unused` — opened for inspection but not used.
- `used` — used for its intended purpose.
- `damaged_in_use` — used and damaged by the customer.
- `defective` — flaw attributable to manufacturing/QC.
- `damaged_in_shipping` — flaw attributable to shipping.
- `missing_parts` — incomplete on arrival.

### 2.5 `return_reason` (on ReturnItem, declared by customer)
- `change_of_mind`
- `wrong_size_or_color`
- `wrong_item_received`
- `defective`
- `damaged_in_shipping`
- `arrived_late`
- `not_as_described`

### 2.6 `return_status` (on Return)
- `pending` — created, not yet approved/rejected by the agent.
- `approved` — agent approved; awaiting receipt of physical items.
- `rejected` — agent denied with reason.
- `received` — items physically received (out-of-band step).
- `refunded` — refund issued.
- `cancelled` — customer withdrew before approval.

(For v0, the `received` → `refunded` transition is treated as automatic at
approval time, since the agent is not modeling physical receipt. v1 may
split.)

### 2.7 `refund_method` (on Return)
- `original_payment` — back to the payment method used on the Order.
- `store_credit` — credited to the customer's `store_credit_balance`.
- `exchange` — no monetary refund; a new Order is created for the replacement
  item.

### 2.8 `payment_type` (on PaymentMethod)
- `credit_card`
- `gift_card`

(`store_credit` was considered as a third payment type but resolved in
[`rules.md`](rules.md) §0 (O5) to live solely as `Customer.store_credit_balance_cents`.
A future version that supports new purchases inside the agent dialogue may
re-introduce it.)

---

## 3. Attributes per sort

Attributes are fields that must be present on every instance unless marked
optional. All identifiers are strings; all monetary amounts are integer cents
(no floats); all dates are ISO 8601 UTC.

### 3.1 Customer
- `customer_id` (id)
- `name` (string)
- `email` (string)
- `addresses` (list of Address; v0 carries one shipping address)
- `member_tier` (enum, §2.1)
- `payment_methods` (list of PaymentMethod ids; ≥ 0)
- `store_credit_balance_cents` (int, ≥ 0)
- `order_ids` (list of Order ids)

### 3.2 Product
- `product_id` (id)
- `sku` (string)
- `name` (string)
- `category` (string; not enumerated in v0 — it's a label, not a rule-bearing
  field)
- `return_class` (enum, §2.2)
- `manufacturer` (string)

### 3.3 Order
- `order_id` (id)
- `purchaser_customer_id` (Customer id) — who paid.
- `recipient_customer_id` (Customer id, optional) — who received. If absent
  or equal to `purchaser_customer_id`, this is a self-purchase. If different,
  this is a gift order.
- `order_date` (datetime)
- `fulfillment_date` (datetime, optional) — when the order was delivered.
  Required for any returnable order.
- `payment_method_id` (PaymentMethod id, optional) — the payment used. Required
  for all customer-purchased orders. Absent for system-generated exchange
  orders (see [`actions.md`](actions.md) §4.2).
- `items` (list of OrderItem; ≥ 1)
- `total_amount_cents` (int) — sum of items.
- `status` (enum, §2.3)

### 3.4 OrderItem
- `order_item_id` (id)
- `order_id` (Order id)
- `product_id` (Product id)
- `quantity` (int, ≥ 1)
- `unit_price_cents` (int)
- `fulfilled_quantity` (int, 0 ≤ … ≤ quantity)
- `returned_quantity` (int, 0 ≤ … ≤ fulfilled_quantity)

### 3.5 Return
- `return_id` (id)
- `order_id` (Order id)
- `initiator_customer_id` (Customer id) — who started the return. May equal
  `Order.purchaser_customer_id` (self-return) or `Order.recipient_customer_id`
  (gift return).
- `created_date` (datetime)
- `items` (list of ReturnItem; ≥ 1)
- `status` (enum, §2.6)
- `refund_method` (enum, §2.7; non-null iff `status = refunded`)
- `refund_amount_cents` (int; non-null iff `status = refunded`)
- `rejection_reason` (string; non-null iff `status = rejected`. Unreachable
  in v0 — `rejected` is forbidden by Layer B C-STATE-R1, kept for v1
  forward-compatibility when `reject_return` may be reintroduced.)

### 3.6 ReturnItem
- `return_item_id` (id)
- `return_id` (Return id)
- `order_item_id` (OrderItem id)
- `quantity` (int, ≥ 1; ≤ unreturned quantity on the underlying OrderItem)
- `declared_condition` (enum, §2.4)
- `declared_reason` (enum, §2.5)

### 3.7 PaymentMethod
- `payment_method_id` (id)
- `customer_id` (Customer id) — owner.
- `type` (enum, §2.8)
- `display_label` (string; e.g., `"Visa •••• 1234"`)
- For `gift_card`: `balance_cents` (int, ≥ 0).
- For `credit_card`: `valid` (bool) — whether the card is currently usable
  for refunds. Used by Layer B's `payment_method_valid/1` predicate.

---

## 4. Multi-party relationships

The presence of `Order.recipient_customer_id` distinct from
`Order.purchaser_customer_id` is the **only** multi-party construct in the
domain.

A return is:

- **Self-return** — `Return.initiator_customer_id = Order.purchaser_customer_id`
  AND no recipient (or `recipient = purchaser`).
- **Gift return** — `Return.initiator_customer_id = Order.recipient_customer_id`
  AND `recipient ≠ purchaser`.
- **Invalid** — any other combination. (E.g., a third party cannot return
  someone else's order. Enforced as a Layer B integrity constraint.)

This split matters because the refund mechanism differs (gift returns cannot
refund to the purchaser's card without the purchaser's consent, which the
agent does not have authority to obtain in this domain).

---

## 5. Numeric constants

Values that the rules in Layer B will reference. Declared here so that all
artifacts use the same symbolic name.

| Symbol | Value | Notes |
|---|---|---|
| `current_time` | (set per `D₀`) | Frozen wall-clock for this benchmark instantiation. |
| `standard_return_window_days` | 30 | Applies to most cases. |
| `plus_member_extension_days` | 60 | Plus members get 30 + 60 = 90 day window. |
| `defective_return_window_days` | 365 | Window when reason ∈ {defective, missing_parts}. |
| `damaged_in_shipping_window_days` | 14 | Tight reporting window. |
| `perishable_defect_report_hours` | 48 | Perishable items: only window. |
| `restocking_fee_percent` | 15 | Applies to `opened_unused` standard items. |
| `gift_return_to_purchaser_threshold_cents` | 5000 | Below this, gift returns auto-issue store credit (no purchaser contact required). v0 always issues store credit for gift returns — this threshold is parameterized for future use. |

All monetary thresholds and percentages are configurable per `D₀`; the values
above are defaults.

---

## 6. Derived predicates (names only; defined in Layer B)

These will be defined as ASP rules in Layer B. Listed here so other layers
can reference them and downstream artifacts (Pydantic, NL prose) have a
single vocabulary to use.

| Predicate | Arity | Intuition |
|---|---|---|
| `is_gift_order(O)` | 1 | True iff `recipient ≠ purchaser`. |
| `effective_returner(O, C)` | 2 | The customer who is entitled to initiate a return on order `O`. |
| `applicable_window_days(RI, D)` | 2 | The return window in days that applies to ReturnItem `RI`, given the product's return class, declared reason, and the purchaser's member tier. |
| `within_window(R)` | 1 | True iff every ReturnItem of Return `R` has elapsed-since-fulfillment ≤ its applicable window. |
| `return_class_returnable(P)` | 1 | True iff the product's return_class permits returns at all. |
| `eligible_to_initiate(C, O)` | 2 | True iff customer `C` is the order's effective returner. |
| `restocking_fee_applies(RI)` | 1 | True iff `opened_unused` ∧ `return_class = standard` ∧ reason ∈ {change_of_mind, wrong_size_or_color}. |
| `refund_amount_for(RI, A)` | 2 | The per-line monetary refund amount `A`, after any restocking fee. |
| `eligible_refund_methods(R, M)` | 2 | Multi-valued: each fact asserts that refund method `M` is a valid choice for Return `R`. |
| `eligible_refund_to_original_payment(R)` | 1 | Convenience: true iff `eligible_refund_methods(R, original_payment)`. |
| `payment_method_valid(PM)` | 1 | True iff `PM` is currently usable as a refund destination. |
| `requires_inspection(RI)` | 1 | True iff declared_condition = `defective`. Declared for v1; not gated in v0. |
| `return_eligible(R)` | 1 | Composite: true iff the return is eligible for approval. |

---

## 7. Out of scope (intentionally)

For each, a brief rationale so future contributors don't re-litigate:

- **Multi-currency.** Single currency (USD cents). Adds complexity without
  stressing the methodology.
- **Promotions, discounts, coupons.** A return's refund amount is based on
  what was paid; we don't unwind promotion logic. The order's
  `total_amount_cents` is taken as ground truth.
- **Partial-quantity nuance for bundles.** OrderItems are independent line
  items. Bundle logic is out of scope.
- **Address verification, fraud signals.** No fraud-scoring rules. Refusals
  come from declared eligibility rules only.
- **Tax recalculation.** Refunds are pro-rata on the line item total; we do
  not model sales tax separately.
- **Carrier-side return shipping logistics.** The agent confirms a return is
  approved; the physical handoff is out-of-band.

---

## 8. Open ontological questions

Items we deferred. Each will get a decision before Layer B can be written.

**O1. Should `OrderItem.fulfilled_quantity` ever be less than
`OrderItem.quantity`?** I.e., do we model split shipments and partial
fulfillments? v0 default: no. `fulfilled_quantity ∈ {0, quantity}` only. If
0, the item is not yet fulfilled and is not returnable.

**O2. Should we model exchange as an atomic action, or as
return-plus-new-order?** v0 default: atomic — `refund_method = exchange`
creates a paired Order automatically. Simpler for tasks; loses some realism
(exchanges normally involve catalog browsing).

**O3. Gift return refund destination.** Always store credit to the recipient
in v0. The `gift_return_to_purchaser_threshold_cents` constant is declared
but unused in v0 rules. Confirm.

**O4. Defective claims and inspection.** Should the agent be allowed to
approve a `defective` return without an inspection step? Real retail varies.
v0 default: yes, agent can approve on the customer's declaration, but the
`requires_inspection` predicate is exposed so downstream layers can choose
to gate behavior on it.

**O5. `store_credit` as PaymentMethod or as Customer field.** Both are
represented in this ontology (PaymentMethod with `type = store_credit`
references back to Customer). This is intentional but slightly redundant.
Confirm we want both views or collapse to one.

**O6. Return reason vs. condition consistency.** A customer declares both a
reason (`defective`) and a condition (`new_unopened`). Some combinations are
incoherent (`change_of_mind` + `defective`). Do we enforce coherence as a
world invariant (Layer B), or treat incoherent declarations as an agent-
contract issue (Layer D, "agent should challenge")? v0 default: Layer D —
the customer is allowed to declare incoherently; the agent is expected to
catch it.

---

## 9. Status

- **2026-05-22** — initial draft. Sorts, enumerations, attributes, and the
  vocabulary of derived predicates declared. Awaiting Layer B (rules) and
  resolution of the 6 open questions in §8.
- **2026-05-26** — reconciliation pass. §3.3 `payment_method_id` marked
  optional (exchange-order accommodation). §6 derived-predicates table
  reconciled with Layer B actual definitions: `applicable_window_days`
  signature corrected to `(RI, D)`; `refund_amount_for` arity corrected to
  2; orphan `refund_method_for` removed; `eligible_refund_methods`,
  `payment_method_valid`, `effective_returner`, and `return_eligible`
  added.
