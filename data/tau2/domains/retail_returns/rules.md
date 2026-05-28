# Retail Returns & Refunds — World Rules (Layer B)

This is **Layer B** of the logic-first design described in
[`docs/logic_first_design.md`](../../../../docs/logic_first_design.md). It
declares:

- **Integrity constraints** — properties any valid DB state must satisfy.
- **Derivations** — definitions of the predicates declared by name in
  [`ontology.md`](ontology.md) §6.

Layer B describes **what is true in any single DB state**. It does **not**
describe how state evolves — that belongs to Layer C (`actions.md`). It does
**not** describe deontic obligations on the agent — that belongs to Layer D
(`agent_contract.md`).

Where an integrity constraint and an action's effect overlap (e.g., the
invariant "OrderItem.returned_quantity equals the sum of refunded
ReturnItem.quantities" vs. the action effect "approving a return increments
returned_quantity"), the integrity constraint is authoritative. Actions are
responsible for preserving the invariant; they are not allowed to define it.

---

## 0. Resolved ontology questions

The 6 open questions from [`ontology.md`](ontology.md) §8 are resolved as
follows for v0:

| Q | Resolution | Rationale |
|---|---|---|
| **O1** Split shipments | **Not modeled.** `fulfilled_quantity ∈ {0, quantity}` per OrderItem. | Simplifies returnability checks. v1 can add partial fulfillment. |
| **O2** Exchange representation | **Atomic, same-SKU only.** `refund_method = exchange` swaps for a replacement of the same `product_id`. Different-SKU exchanges are out of scope for v0 (must be handled as return + new order). | Keeps action surface bounded. Real exchanges involve catalog browsing, which is out of scope. |
| **O3** Gift return refund destination | **Always store credit to recipient.** The `gift_return_to_purchaser_threshold_cents` constant is declared but unused in v0. | Avoids needing purchaser consent flow. |
| **O4** Defective inspection | **Not gated in v0.** Agent may approve `defective` returns on customer declaration. `requires_inspection(RI)` is exposed for v1 use. | Real inspection workflow is out of band. |
| **O5** Store credit dual representation | **Collapse to Customer field only.** `store_credit` is removed from `payment_type`; `Customer.store_credit_balance_cents` is the single source. | Eliminates redundancy. v1 can re-introduce as a PaymentMethod if forward orders need it. |
| **O6** Reason/condition coherence | **Layer D concern.** No Layer B invariant forbids incoherent declarations (e.g., `change_of_mind` + `defective`). The agent contract layer is responsible for challenging incoherence. | Customers do declare incoherently; this is dialogue-shape, not world-shape. |

**Consequence of O5:** `payment_type` (ontology.md §2.8) becomes
`{ credit_card, gift_card }` only in v0. Update consumers accordingly.

**Consequence of v0 simplification:** of the 6 declared `return_status`
values, only `{ pending, refunded, cancelled }` are reachable in v0.
`approved`, `received`, and `rejected` are declared in the ontology for
forward compatibility but are forbidden by integrity constraint C-STATE-R1
(§2). The reason `rejected` is excluded from v0: the `reject_return`
action has been removed from the action surface; refusals of ineligible
requests are handled in dialogue (Layer D) without invoking
`initiate_return`, so a `rejected` Return never appears in the DB. See
[`actions.md`](actions.md) §0 for the cascade.

---

## 1. ASP encoding conventions

Conventions used by all rules below. These are not normative — they're the
shorthand this document adopts.

- **Predicates are lowercase snake_case.** Identifiers from the ontology
  appear as constants.
- **Sort guards** are typed predicates (`customer/1`, `order/1`, etc.).
  Asserted as facts in `D₀`.
- **Attributes** are encoded as 2-ary predicates: `member_tier(C, plus)`,
  `return_class(P, standard)`, `unit_price_cents(OI, 4999)`.
- **Optional attributes** (e.g., `recipient_customer_id`) are simply absent
  if not present. No null sentinel.
- **Multi-valued collections** (e.g., a Customer's order list) are
  represented by the inverse relation: `order_purchaser(O, C)` rather than
  embedding the order list in the customer.
- **Numeric constants** from ontology.md §5 are exposed as ground facts:
  `const(standard_return_window_days, 30)`.
- **Arithmetic and date math** are computed by the encoder and asserted as
  ground facts. Predicates like `days_since_fulfillment(O, D)` are inputs to
  ASP, not computed by it.

---

## 2. Integrity constraints

Hard invariants. Numbered for traceability. Any DB state that violates one of
these is invalid by definition; no rule, action, or agent behavior can produce
it.

### 2.1 Cardinality

- **C-CARD-1.** Every Order has ≥ 1 OrderItem.
  ```
  :- order(O), #count{ OI : order_item_of(OI, O) } = 0.
  ```
- **C-CARD-2.** Every Return has ≥ 1 ReturnItem.
  ```
  :- return(R), #count{ RI : return_item_of(RI, R) } = 0.
  ```
- **C-CARD-3.** For each OrderItem: `fulfilled_quantity ∈ {0, quantity}`.
  (O1: no split shipments.)
  ```
  :- order_item(OI), quantity(OI, Q), fulfilled_quantity(OI, F),
     F != 0, F != Q.
  ```
- **C-CARD-4.** For each OrderItem: `0 ≤ returned_quantity ≤ fulfilled_quantity`.
  ```
  :- order_item(OI), returned_quantity(OI, R), R < 0.
  :- order_item(OI), returned_quantity(OI, R), fulfilled_quantity(OI, F), R > F.
  ```
- **C-CARD-5.** For each ReturnItem `RI` of Return `R` referencing OrderItem
  `OI`: `1 ≤ ReturnItem.quantity ≤ unreturned_count(OI, R_creation_time)`.
  *Computed by encoder; asserted as a check fact `valid_return_quantity(RI)`.*
  ```
  :- return_item(RI), not valid_return_quantity(RI).
  ```

### 2.2 Referential

- **C-REF-1.** `order_item_of(OI, O)` implies `order(O)`.
- **C-REF-2.** Every OrderItem references an existing Product:
  `product_of(OI, P) → product(P)`.
- **C-REF-3.** `order_purchaser(O, C) → customer(C)`.
- **C-REF-4.** `order_recipient(O, C) → customer(C)`.
- **C-REF-5.** When an order has a payment method, it is owned by the
  purchaser. (`order_payment_method/2` is optional — absent for
  system-generated exchange orders, per [`actions.md`](actions.md) §4.2.)
  ```
  :- order(O), order_payment_method(O, PM), order_purchaser(O, C),
     not payment_method_owner(PM, C).
  ```
- **C-REF-6.** `return_of_order(R, O) → return(R), order(O)`.
- **C-REF-7.** `return_initiator(R, C) → customer(C)`.
- **C-REF-8.** Every ReturnItem references an OrderItem of the Return's
  Order:
  ```
  :- return_item_of(RI, R), return_item_references(RI, OI),
     return_of_order(R, O), not order_item_of(OI, O).
  ```
- **C-REF-9.** `payment_method_owner(PM, C) → customer(C)`.

### 2.3 Multi-party

- **C-MP-1.** Return initiator is the effective returner of the order:
  ```
  effective_returner(O, C) :- order_recipient(O, C), is_gift_order(O).
  effective_returner(O, C) :- order_purchaser(O, C), not is_gift_order(O).

  :- return_of_order(R, O), return_initiator(R, C), not effective_returner(O, C).
  ```
- **C-MP-2.** A gift order has a recipient distinct from the purchaser
  (definitional; if recipient equals purchaser, it's a self-order):
  ```
  is_gift_order(O) :- order_recipient(O, R), order_purchaser(O, P), R != P.
  ```

### 2.4 State machine: Order

- **C-STATE-O1.** A returnable Order has been delivered:
  ```
  :- return_of_order(R, O), not order_status(O, delivered),
     not order_status(O, partially_returned), not order_status(O, fully_returned).
  ```
- **C-STATE-O2.** Status implies fulfillment_date is set for the relevant
  cases:
  ```
  :- order_status(O, S), S != placed, S != processing, S != cancelled,
     not fulfillment_date_set(O).
  ```
- **C-STATE-O3.** `partially_returned` ↔ some but not all fulfilled units
  have been returned. `fully_returned` ↔ all fulfilled units have been
  returned. Encoded as a derivation in §3.6 and an integrity check that
  status matches the derivation.

### 2.5 State machine: Return

- **C-STATE-R1.** Return status is one of the 3 reachable v0 values:
  ```
  :- return_status(R, approved).
  :- return_status(R, received).
  :- return_status(R, rejected).
  ```
  (`pending`, `refunded`, `cancelled` are allowed in v0.)
- **C-STATE-R2.** Terminal-status data presence:
  ```
  :- return_status(R, refunded), not refund_method_set(R).
  :- return_status(R, refunded), not refund_amount_set(R).
  ```
- **C-STATE-R3.** Conversely, non-`refunded` returns have null refund fields:
  ```
  :- return_status(R, S), S != refunded, refund_method_set(R).
  :- return_status(R, S), S != refunded, refund_amount_set(R).
  ```

  (The `rejection_reason` field exists in the ontology for v1
  compatibility but is unreachable in v0 because `rejected` is
  forbidden by C-STATE-R1. The corresponding integrity constraint
  returns in v1 when `reject_return` is reintroduced.)

### 2.6 Returned-quantity bookkeeping

This is the central state invariant tying Returns back to Orders.

- **C-BOOK-1.** For each OrderItem, `returned_quantity` equals the sum of
  ReturnItem quantities over all `refunded` Returns referencing it:
  ```
  expected_returned_qty(OI, Total) :-
    order_item(OI),
    Total = #sum{ Q, RI :
                  return_item_references(RI, OI),
                  return_item_quantity(RI, Q),
                  return_item_of(RI, R),
                  return_status(R, refunded) }.

  :- order_item(OI), returned_quantity(OI, X), expected_returned_qty(OI, Y), X != Y.
  ```

### 2.7 Time consistency

- **C-TIME-1.** Fulfillment after order: `fulfillment_date ≥ order_date`.
  *Verified by encoder.*
- **C-TIME-2.** Returns initiated after fulfillment:
  `Return.created_date ≥ Order.fulfillment_date`. *Verified by encoder.*
- **C-TIME-3.** Returns initiated no later than now:
  `Return.created_date ≤ current_time`. *Verified by encoder.*

### 2.8 Monetary

- **C-MONEY-1.** `Customer.store_credit_balance_cents ≥ 0`.
- **C-MONEY-2.** For `gift_card` PaymentMethod: `balance_cents ≥ 0`.
- **C-MONEY-3.** For `refunded` Returns: `refund_amount_cents = ∑ refund_amount_for(RI)`.
  ```
  expected_refund_amount(R, Total) :-
    return(R),
    Total = #sum{ A, RI :
                  return_item_of(RI, R),
                  refund_amount_for(RI, A) }.

  :- return_status(R, refunded), refund_amount(R, X),
     expected_refund_amount(R, Y), X != Y.
  ```

---

## 3. Derivation rules

Definitions for the predicates declared by name in
[`ontology.md`](ontology.md) §6.

### 3.1 `is_gift_order(O)`

Already defined in C-MP-2:
```
is_gift_order(O) :- order_recipient(O, R), order_purchaser(O, P), R != P.
```
If no `order_recipient/2` fact exists for `O`, `is_gift_order(O)` is false
(negation as failure).

### 3.2 `applicable_window_days(RI, D)`

The applicable return window in days for ReturnItem `RI`, given the product's
return class, the declared reason, and the purchaser's member tier.

```
% Non-returnable classes — window = 0.
applicable_window_days(RI, 0) :-
  return_item(RI),
  return_item_references(RI, OI),
  product_of(OI, P),
  return_class(P, C),
  C != standard, C != perishable.

% Perishable — defect/shipping damage only, very short window (48h = 2 days
% for v0; sub-day granularity not modeled).
applicable_window_days(RI, 2) :-
  return_item(RI),
  return_item_references(RI, OI),
  product_of(OI, P),
  return_class(P, perishable),
  return_item_reason(RI, R),
  perishable_eligible_reason(R).

applicable_window_days(RI, 0) :-
  return_item(RI),
  return_item_references(RI, OI),
  product_of(OI, P),
  return_class(P, perishable),
  return_item_reason(RI, R),
  not perishable_eligible_reason(R).

perishable_eligible_reason(defective).
perishable_eligible_reason(damaged_in_shipping).

% Standard — branch on reason.
applicable_window_days(RI, 365) :-
  standard_item(RI), return_item_reason(RI, R),
  long_window_reason(R).

applicable_window_days(RI, 30) :-
  standard_item(RI), return_item_reason(RI, R),
  retailer_fault_reason(R).

applicable_window_days(RI, D) :-
  standard_item(RI), return_item_reason(RI, R),
  customer_choice_reason(R),
  return_item_of(RI, Ret), return_of_order(Ret, O),
  order_purchaser(O, C),
  tier_window(C, D).

% Helpers.
standard_item(RI) :-
  return_item(RI), return_item_references(RI, OI),
  product_of(OI, P), return_class(P, standard).

long_window_reason(defective).
long_window_reason(missing_parts).

retailer_fault_reason(damaged_in_shipping).
retailer_fault_reason(wrong_item_received).
retailer_fault_reason(arrived_late).
retailer_fault_reason(not_as_described).

customer_choice_reason(change_of_mind).
customer_choice_reason(wrong_size_or_color).

tier_window(C, 90) :- member_tier(C, plus).
tier_window(C, 30) :- member_tier(C, regular).
```

### 3.3 `within_window(R)`

A Return is within window iff every ReturnItem's elapsed-time-since-fulfillment
is within its applicable window. The elapsed time is computed by the encoder
and asserted as `days_since_fulfillment(O, N)`.

```
out_of_window(RI) :-
  return_item(RI), return_item_of(RI, Ret), return_of_order(Ret, O),
  applicable_window_days(RI, D),
  days_since_fulfillment(O, N),
  N > D.

within_window(R) :-
  return(R), not exists_out_of_window_item(R).

exists_out_of_window_item(R) :-
  return_item_of(RI, R), out_of_window(RI).
```

**Semantic caveat.** For non-returnable products (`return_class ∈ {final_sale,
digital, hazmat}`), `applicable_window_days` is 0, and the day-0 case
(`N = 0`) leaves `out_of_window` false. So `within_window(R)` would return
*true* for a same-day return of a non-returnable item, which is misleading
in isolation. This is harmless in practice because `return_eligible` (§4)
composes `within_window` with `all_items_returnable`, which catches the
non-returnable case independently. Read `within_window` as "the time gate
specifically," not "the return is overall acceptable."

### 3.4 `return_class_returnable(P)`

True iff the product's return class permits any returns at all.

```
return_class_returnable(P) :- return_class(P, standard).
return_class_returnable(P) :- return_class(P, perishable).
```

(`final_sale`, `digital`, `hazmat` produce no facts → false by negation as
failure.)

### 3.5 `eligible_to_initiate(C, O)`

True iff the customer is the order's effective returner (per C-MP-1).

```
eligible_to_initiate(C, O) :- effective_returner(O, C).
```

### 3.6 Order status derivation (consistency with C-STATE-O3)

```
order_total_quantity(O, Total) :-
  order(O), Total = #sum{ Q, OI : order_item_of(OI, O), quantity(OI, Q) }.

order_total_returned(O, Total) :-
  order(O), Total = #sum{ R, OI : order_item_of(OI, O), returned_quantity(OI, R) }.

derived_order_status(O, fully_returned) :-
  order(O), order_total_quantity(O, T), order_total_returned(O, T), T > 0.

derived_order_status(O, partially_returned) :-
  order(O), order_total_quantity(O, T), order_total_returned(O, R),
  R > 0, R < T.

% Integrity check: stored status matches derivation when a return has occurred.
:- order(O), derived_order_status(O, S), order_status(O, S2), S != S2.
```

(The `placed`/`processing`/`shipped`/`delivered`/`cancelled` statuses are set
by upstream order-lifecycle actions and not derived here.)

### 3.7 `restocking_fee_applies(RI)`

```
restocking_fee_applies(RI) :-
  return_item(RI),
  return_item_condition(RI, opened_unused),
  return_item_references(RI, OI),
  product_of(OI, P), return_class(P, standard),
  return_item_reason(RI, R),
  customer_choice_reason(R).
```

The fee is the **only** reduction applied. No other deductions.

### 3.8 `refund_amount_for(RI, A)`

```
gross_amount(RI, A) :-
  return_item(RI), return_item_references(RI, OI),
  return_item_quantity(RI, Q), unit_price_cents(OI, U),
  A = Q * U.

refund_amount_for(RI, A) :-
  gross_amount(RI, G), not restocking_fee_applies(RI), A = G.

refund_amount_for(RI, A) :-
  gross_amount(RI, G), restocking_fee_applies(RI),
  const(restocking_fee_percent, P),
  A = G * (100 - P) / 100.
```

Integer division — restocking fee is rounded down. (Acceptable rounding for
v0; a Layer C action assertion can normalize to cents.)

### 3.9 `eligible_refund_methods(R, M)`

The set of refund methods the return is eligible for. Multi-valued:
multiple facts may be derived for the same `R`.

```
% Gift returns: store credit only.
eligible_refund_methods(R, store_credit) :-
  return(R), return_of_order(R, O), is_gift_order(O).

% Self-returns with valid original payment: original_payment + store_credit
% are both eligible.
eligible_refund_methods(R, original_payment) :-
  return(R), return_of_order(R, O), not is_gift_order(O),
  order_payment_method(O, PM), payment_method_valid(PM).

eligible_refund_methods(R, store_credit) :-
  return(R), return_of_order(R, O), not is_gift_order(O).

% Self-returns with invalid original payment: store_credit only (already
% covered by the previous rule).

% Exchange is eligible iff:
%   - Not a gift return.
%   - All ReturnItems are defective.
%   - Replacement is available for each (same SKU, in stock).
% (Stock check is an external predicate; for v0, a single fact
% `replacement_available(P)` per product.)
eligible_refund_methods(R, exchange) :-
  return(R), return_of_order(R, O), not is_gift_order(O),
  all_items_defective(R),
  all_replacements_available(R).

all_items_defective(R) :-
  return(R), not exists_non_defective_item(R).
exists_non_defective_item(R) :-
  return_item_of(RI, R), return_item_condition(RI, C), C != defective.

all_replacements_available(R) :-
  return(R), not exists_unavailable_replacement(R).
exists_unavailable_replacement(R) :-
  return_item_of(RI, R), return_item_references(RI, OI),
  product_of(OI, P), not replacement_available(P).
```

`payment_method_valid(PM)` is defined in §3.10.

### 3.10 `payment_method_valid(PM)`

A PaymentMethod is **valid** as a refund destination iff it is currently
usable. Encoded directly from the ontology attributes:

```
% credit_card: valid iff its `valid` attribute is true.
payment_method_valid(PM) :-
  payment_method_type(PM, credit_card),
  payment_method_credit_card_valid(PM).

% gift_card: valid iff it has a non-zero balance.
payment_method_valid(PM) :-
  payment_method_type(PM, gift_card),
  payment_method_balance_cents(PM, B),
  B > 0.
```

`payment_method_credit_card_valid/1` is asserted as a ground fact by the
encoder (it reflects the `valid` boolean attribute on the credit_card
PaymentMethod — see [`ontology.md`](ontology.md) §3.7).
`payment_method_balance_cents/2` is similarly a ground fact for gift cards.

### 3.11 `eligible_refund_to_original_payment(R)`

Convenience predicate for the common case:

```
eligible_refund_to_original_payment(R) :- eligible_refund_methods(R, original_payment).
```

### 3.12 `requires_inspection(RI)`

```
requires_inspection(RI) :- return_item_condition(RI, defective).
```

(Declared for v1 — Layer D may choose to gate behavior on this; v0 does not.)

---

## 4. Eligibility composition

The composite predicate that consumers (Layer C, Layer D, the verifier) will
reach for most often: **`return_eligible(R)`**.

A return is **eligible** iff all of the following hold:

```
return_eligible(R) :-
  return(R),
  return_of_order(R, O),
  return_initiator(R, C),
  eligible_to_initiate(C, O),                 % §3.5
  within_window(R),                            % §3.3
  all_items_returnable(R),
  return_status(R, S), eligible_status(S).

all_items_returnable(R) :-
  return(R), not exists_non_returnable_item(R).

exists_non_returnable_item(R) :-
  return_item_of(RI, R),
  return_item_references(RI, OI),
  product_of(OI, P),
  not return_class_returnable(P).

eligible_status(pending).
eligible_status(refunded).
```

A return that is `cancelled` is never eligible (by status). In v0, the
agent never creates a Return for which `return_eligible(R)` would be
false — the eligibility check happens in dialogue (Layer D D-REF-2), and
ineligible requests result in an in-band refusal without invoking
`initiate_return`. So in practice the only way `return_eligible(R)` is
false on an existing Return is if state has changed between initiation
and approval (e.g., the customer cancelled it). `approve_return`'s
precondition enforces this safety net.

---

## 5. Worked micro-example

For concreteness, a fully ground micro-instance that exercises the rules. Not
a benchmark task — just a sanity check that the rules typecheck and produce
the expected predicates.

```
% --- D₀ facts ---

% Constants.
const(restocking_fee_percent, 15).
const(standard_return_window_days, 30).
const(plus_member_extension_days, 60).
current_time(2026-05-23).

% Customer.
customer(c1).
member_tier(c1, regular).
payment_method_owner(pm1, c1).
payment_method_type(pm1, credit_card).
payment_method_valid(pm1).

% Product.
product(p_widget).
return_class(p_widget, standard).
replacement_available(p_widget).

% Order.
order(o1).
order_purchaser(o1, c1).
order_payment_method(o1, pm1).
order_status(o1, delivered).
fulfillment_date_set(o1).
days_since_fulfillment(o1, 12).

% OrderItem (1 widget, $50, fulfilled).
order_item(oi1).
order_item_of(oi1, o1).
product_of(oi1, p_widget).
quantity(oi1, 1).
fulfilled_quantity(oi1, 1).
returned_quantity(oi1, 0).
unit_price_cents(oi1, 5000).

% Return (pending, change-of-mind, opened_unused).
return(ret1).
return_of_order(ret1, o1).
return_initiator(ret1, c1).
return_status(ret1, pending).

return_item(ri1).
return_item_of(ri1, ret1).
return_item_references(ri1, oi1).
return_item_quantity(ri1, 1).
return_item_condition(ri1, opened_unused).
return_item_reason(ri1, change_of_mind).
valid_return_quantity(ri1).
```

Expected derived facts (sketched, not run):

| Predicate | Value |
|---|---|
| `is_gift_order(o1)` | false |
| `applicable_window_days(ri1, _)` | 30 (regular member, standard, change_of_mind) |
| `out_of_window(ri1)` | false (12 ≤ 30) |
| `within_window(ret1)` | true |
| `return_class_returnable(p_widget)` | true |
| `eligible_to_initiate(c1, o1)` | true |
| `restocking_fee_applies(ri1)` | **true** (opened_unused + standard + change_of_mind) |
| `gross_amount(ri1, _)` | 5000 |
| `refund_amount_for(ri1, _)` | 4250 (5000 × 0.85) |
| `eligible_refund_methods(ret1, _)` | `original_payment`, `store_credit` (no exchange — not defective) |
| `return_eligible(ret1)` | true |

A solver run on this state should non-deterministically choose between
`refund_method = original_payment` and `refund_method = store_credit` —
unless the OperationalSpec for a task pins one of them.

---

## 6. Open questions for Layer C

Items surfaced while writing Layer B that affect the action layer. Listed for
resolution at Layer C, not now.

**Q-B-1. Can a customer initiate multiple `pending` Returns against the same
Order simultaneously?** v0 likely answer: no — only one `pending` Return per
Order at a time. Enforce as a Layer C precondition on `initiate_return`.

**Q-B-2. What is the canonical action that performs the
`pending → refunded` transition?** Single action `approve_return` that takes
the refund method as input? Or split into `approve_return` +
`issue_refund`? v0 leaning: single action; refund method is a parameter.

**Q-B-3. Exchange semantics.** When `refund_method = exchange`, what
exactly changes? A new OrderItem is added to the original Order with
`unit_price_cents = 0`? Or a new Order is created? Either is consistent with
the Layer A schema; Layer C must pick one.

**Q-B-4. Cancellation of a `pending` Return.** Triggered by the customer
asking to cancel the return request, *not* the underlying purchase. Should
this be a distinct action `cancel_return`, or a parameter on
`approve_return` (refund_method = null + status = cancelled)? v0 leaning:
distinct action.

**Q-B-5. Original payment method validity.** `payment_method_valid(PM)` is
an external fact. What is its definition in v0? Likely: credit_card is
valid iff not flagged closed (a fact carried on the PaymentMethod);
gift_card is valid iff `balance_cents > 0`. Confirm at Layer C.

**Q-B-6. Cross-return consistency at Layer C.** When a new Return is being
approved, we must check that the sum of (already-returned + this-return)
quantities does not exceed fulfilled_quantity. This is C-BOOK-1 as a Layer C
precondition. Confirm enforcement mechanism (run integrity constraints
post-action vs. precondition check).

---

## 7. Status

- **2026-05-23** — initial Layer B draft. All 6 ontology questions resolved
  (§0). 25 integrity constraints (§2). 11 derivation predicates (§3). Composite
  `return_eligible` predicate (§4). Worked micro-example (§5). 6 questions
  surfaced for Layer C (§6).
- **2026-05-26** — reconciliation pass. §0 v0-narrowing updated: 6 (not 7)
  declared `return_status` values, only 3 (not 4) reachable in v0;
  `rejected` removed as reachable since `reject_return` action is dropped
  (see actions.md §0). C-STATE-R1 extended to forbid `rejected`;
  C-STATE-R2/R3 dead `rejected` integrity lines removed. C-REF-5 made
  conditional with note about exchange orders lacking `payment_method`.
  §3.3 `within_window` semantic caveat added (composition with
  `all_items_returnable` handles non-returnable-product edge case). §3.10
  `payment_method_valid` derivation added (moved from Q-B-5 resolution
  table). §3.11/§3.12 renumbered.
