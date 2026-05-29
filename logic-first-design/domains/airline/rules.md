# Airline — World Rules (Layer B, cancellation slice)

This is **Layer B** of the airline retrofit, scoped to the
**cancellation + compensation policy slice** so we can drive one
end-to-end task verification before generalizing to bookings and
modifications.

What's here:
- **Integrity constraints** — domain-wide, structural invariants.
  Complete coverage of cardinality, uniformity, and referential rules.
- **Derivations** — cancellation- and compensation-specific.
  `recent_booking`, `has_flown_segment`, `has_airline_cancelled_segment`,
  `insurance_covers`, `cancellable`, `compensation_eligible`,
  `compensation_amount_cents`, and supporting helpers.

What's deferred (separate Layer B slices in later sessions):
- Booking validity (`valid_booking`, seat availability)
- Flight modification (`modifiable_flights`, replacement pricing)
- Cabin change (`cabin_changeable`, price differential)
- Baggage allowance computation (`free_baggage_per_passenger`)
- Insurance posture changes post-booking

Where an integrity constraint and an action's effect overlap, the
integrity constraint is authoritative. Actions (Layer C) are responsible
for preserving them; they are not allowed to define them.

---

## 0. Resolved ontology questions

The 12 open questions from [`ontology.md`](ontology.md) §8 are resolved
as follows. Items marked **deferred** affect non-cancellation slices
and will be resolved when those rules are authored.

| Q | Resolution | Rationale / mechanism |
|---|---|---|
| **Q1** Insurance coverage mapping | `insurance_covers/1` is an **external predicate** asserted by the encoder. Layer F's `intent.insurance_covers` (bool) drives whether the fact is emitted for a given reason. | Avoids forcing a closed enumeration on "health/weather" — the policy is genuinely open-vocabulary on covered reasons. |
| **Q2** "(basic) economy" parsing | `non_business_cabin/1` ≡ `cabin ∈ {basic_economy, economy}`. Encoded as two ground rules. | Cleanest reading of the upstream prose. |
| **Q3** Airline-cancelled flight detection | Derived from `flight_status(FN, D, cancelled)`; no separate user-asserted predicate. | `cancelled` is already in `flight_status` enum (ontology §2.5). |
| **Q4** "Business flight" in cancellation | `reservation_cabin(R, business)`. The C-UNIF-1 invariant guarantees a single cabin value per reservation. | Simplifies to a single attribute lookup. |
| **Q5** Compensation phrasings | Encode the **positive form** (silver/gold ∨ insurance ∨ business). Under Q2, this is logically equivalent to the negative form. | One source of truth in the ASP. |
| **Q6** Delayed compensation precondition | **Strict reading**: the modify/cancel must have actually been executed before compensation is offered. Layer C will gate this on a trajectory-level precondition; Layer B encodes the eligibility predicate only. | Honest to the policy text. |
| **Q7** Removing insurance post-booking | **Deferred** — not cancellation-relevant. Layer B (modification slice) will encode. | Affects `modify_reservation`, not `cancel_reservation`. |
| **Q8** Travel certificate gap | Reading (a): remaining cert balance after application is **lost**; cancellation refund of the cert portion is $0. | Locked. Affects refund computation (Layer C). |
| **Q9** Kept segments pricing | **Deferred** — not cancellation-relevant. | Affects `modify_reservation_flights` only. |
| **Q10** Recency window reference | Relative to `current_time` (the moment of the cancellation request). | `recent_booking/1` derived from `hours_since_creation/2` external. |
| **Q11** Membership for compensation | Only the `booking_user_id`'s `membership_tier` matters. | Encoded directly via `booking_user/2` + `membership_tier/2`. |
| **Q12** Status enum extension | `landed` and `cancelled` already added to `flight_status` (ontology §2.5). | Locked. |

---

## 1. ASP encoding conventions

Same conventions as
[`retail_returns/rules.md`](../retail_returns/rules.md) §1, with one
airline-specific addition:

- **Composite ids.** A `FlightInstance` is identified by
  `(flight_number, date)`. We do NOT mint a synthetic id; predicates
  carry the pair: `flight_status(FN, D, S)`, `flight_instance_seats(FN,
  D, C, N)`, etc.
- **Date / time / hour math** is external: the encoder computes
  `hours_since_creation(R, H)`, `days_since_creation(R, N)`,
  `current_time_iso(T)` etc., and emits them as ground facts.
- **Numeric constants** (ontology §5) are exposed as ground facts:
  `const(recent_booking_window_hours, 24)`, etc.
- **Closed enumerations** are exposed as ground facts for grounding
  convenience: e.g., `cancellation_reason_value(change_of_plan)`,
  `complaint_type_value(cancelled_flight_complaint)`. The encoder emits
  them automatically.

---

## 2. Integrity constraints (domain-wide)

Hard invariants. Any DB state that violates one of these is invalid by
definition. Constraint IDs are stable for cross-references from other
layers.

### 2.1 Cardinality

- **C-CARD-1.** Every Reservation has 1 ≤ |passengers| ≤ 5.
  ```
  :- reservation(R), #count{ Idx : passenger(R, Idx) } < 1.
  :- reservation(R), #count{ Idx : passenger(R, Idx) } > 5.
  ```
- **C-CARD-2.** Every Reservation has at least one flight segment.
  ```
  :- reservation(R), #count{ FN, D : segment_of(R, FN, D) } = 0.
  ```
- **C-CARD-3.** Payment composition caps (§4.2 of ontology):
  ```
  :- reservation(R),
     #count{ PM : payment_used(R, PM), payment_method_type(PM, travel_certificate) } > 1.
  :- reservation(R),
     #count{ PM : payment_used(R, PM), payment_method_type(PM, credit_card) } > 1.
  :- reservation(R),
     #count{ PM : payment_used(R, PM), payment_method_type(PM, gift_card) } > 3.
  ```

### 2.2 Referential

- **C-REF-1.** `booking_user(R, U) → user(U)`.
- **C-REF-2.** `payment_used(R, PM) → payment_method(PM)`.
- **C-REF-3.** Payment methods used by a reservation are owned by the
  booking user:
  ```
  :- reservation(R), booking_user(R, U), payment_used(R, PM),
     not payment_method_owner(PM, U).
  ```
- **C-REF-4.** Every flight segment references an existing FlightInstance:
  ```
  :- segment_of(R, FN, D), not flight_instance(FN, D).
  ```

### 2.3 Uniformity

- **C-UNIF-1.** Cabin class is uniform across all segments of a
  reservation. Since `cabin_class` is a single attribute on the
  Reservation (per ontology §3.5), this is enforced by the data model.
  Declared here so consumers can assume it without re-checking.

### 2.4 State machine: Reservation

- **C-STATE-RES-1.** A `cancelled` reservation does not gain new
  segments / passengers / payment methods. (Encoder enforces; declared
  for completeness.)
- **C-STATE-RES-2.** A `cancelled` reservation's `cancellation_reason`
  must be present and ∈ `cancellation_reason_value`:
  ```
  :- reservation(R), reservation_status(R, cancelled),
     not reservation_cancellation_reason_set(R).
  ```

### 2.5 Booking-time

- **C-BOOK-1.** At creation time (`created_time`), every segment of
  the reservation had `flight_status = available`. Verified by encoder
  using historical snapshots; not re-derivable from current state.
  Documented here for traceability.

### 2.6 Monetary

- **C-MONEY-1.** `gift_card.balance_cents ≥ 0`.
- **C-MONEY-2.** `travel_certificate.balance_cents ≥ 0`.
- **C-MONEY-3.** Insurance: `has_travel_insurance(R)` is non-increasing
  after creation. (Q7 — once added, can be removed only by cancellation;
  cannot be added post-creation. Encoder enforces; declared for
  completeness; full encoding deferred to modification-slice rules.)

### 2.7 Time consistency

- **C-TIME-1.** For every Reservation segment, the FlightInstance's
  `date` is on or after the Reservation's `created_time` date.
- **C-TIME-2.** A Reservation's `created_time` is at or before
  `current_time`.

(Both verified by encoder.)

---

## 3. Derivation rules (cancellation slice)

Definitions for the predicates declared by name in
[`ontology.md`](ontology.md) §6, restricted to those needed for
cancellation and compensation.

### 3.1 `non_business_cabin(R)` (Q2)

```
non_business_cabin(R) :- reservation(R), reservation_cabin(R, basic_economy).
non_business_cabin(R) :- reservation(R), reservation_cabin(R, economy).
```

(`reservation_cabin(R, business)` produces no fact for
`non_business_cabin/1`; defaults to false by negation as failure.)

### 3.2 `payment_method_valid(PM)`

A PaymentMethod is **valid** as a refund destination iff usable.
Mirrors retail_returns rules.md §3.10.

```
payment_method_valid(PM) :-
  payment_method_type(PM, credit_card),
  payment_method_credit_card_valid(PM).

payment_method_valid(PM) :-
  payment_method_type(PM, gift_card),
  payment_method_balance_cents(PM, B),
  B > 0.

payment_method_valid(PM) :-
  payment_method_type(PM, travel_certificate),
  payment_method_balance_cents(PM, B),
  B > 0.
```

Encoder asserts `payment_method_credit_card_valid/1` and
`payment_method_balance_cents/2` from the ontology attributes.

### 3.3 `recent_booking(R)` (Q10)

True iff the reservation was created within the last 24 hours of
`current_time`. Driven by the external predicate
`hours_since_creation/2`.

```
recent_booking(R) :-
  reservation(R),
  hours_since_creation(R, H),
  const(recent_booking_window_hours, W),
  H <= W.
```

### 3.4 `has_flown_segment(R)` (cancellation precondition)

```
has_flown_segment(R) :-
  segment_of(R, FN, D),
  flight_status(FN, D, flying).

has_flown_segment(R) :-
  segment_of(R, FN, D),
  flight_status(FN, D, landed).
```

A reservation with a flown segment cannot be cancelled by the agent —
the upstream policy requires transfer to a human (Layer D will gate).

### 3.5 `has_airline_cancelled_segment(R)` (Q3)

```
has_airline_cancelled_segment(R) :-
  segment_of(R, FN, D),
  flight_status(FN, D, cancelled).
```

This is the "the flight is cancelled by airline" condition in the
upstream policy. Triggered by the airline's status update on a
FlightInstance, not by the user's claim.

### 3.6 `insurance_covers(Reason)` (Q1, external)

`insurance_covers/1` is an **external predicate** asserted by the
encoder based on the task's `intent.insurance_covers` flag (or, for
generated tasks, the scenario's insurance assumption). It is NOT
derived from `cancellation_reason` because the upstream policy's
"health or weather" vocabulary does not align with the three
`cancellation_reason` values.

The encoder emits zero or one fact:
- `insurance_covers(Reason).` if the task asserts coverage.
- (nothing) — the predicate is false by negation as failure.

No Layer B rule head for this predicate; it's a pure input.

### 3.7 `cancellable(R, Reason)` (composite)

Per the upstream policy:

> The flight can be cancelled if **any** of the following is true:
> - The booking was made within the last 24 hrs
> - The flight is cancelled by the airline
> - It is a business flight
> - The user has travel insurance and the reason for cancellation is
>   covered by insurance
>
> If any portion of the flight has already been flown, the agent cannot
> help and transfer is needed.

Encoded:

```
% Top-level: requires no flown segment.
cancellable(R, Reason) :-
  cancellation_reason_value(Reason),
  reservation(R),
  not has_flown_segment(R),
  cancellation_ground(R, Reason).

% Grounds (any of):
cancellation_ground(R, Reason) :-
  cancellation_reason_value(Reason),
  reservation(R),
  recent_booking(R).

cancellation_ground(R, Reason) :-
  cancellation_reason_value(Reason),
  reservation(R),
  has_airline_cancelled_segment(R).

cancellation_ground(R, Reason) :-
  cancellation_reason_value(Reason),
  reservation(R),
  reservation_cabin(R, business).

cancellation_ground(R, Reason) :-
  reservation(R),
  has_travel_insurance(R),
  insurance_covers(Reason).
```

Note the four `cancellation_ground` clauses correspond to the four
policy bullets, in order. The first three are reason-agnostic (they
hold for any `Reason` in the enum); the fourth requires the specific
`Reason` to be covered by insurance.

### 3.8 `num_passengers(R, N)`

```
num_passengers(R, N) :-
  reservation(R),
  N = #count{ Idx : passenger(R, Idx) }.
```

The `passenger/2` predicate is asserted by the encoder, one fact per
positional passenger index on the reservation. (Per ontology §3.6,
passengers have no global id; the encoder synthesizes a positional
index for ASP-grounding purposes only.)

### 3.9 `compensation_eligible(R, ComplaintType)` (Q5 positive form, Q11)

A reservation's booking user is entitled to compensation iff **any** of:
- `membership_tier(booking_user) ∈ {silver, gold}`, OR
- `has_travel_insurance(R) = true`, OR
- `reservation_cabin(R) = business`

(Q11: only the booking user's tier matters, not any passenger's. Q5:
positive form encoded.)

```
member_eligible_for_compensation(R) :-
  reservation(R), booking_user(R, U), membership_tier(U, silver).
member_eligible_for_compensation(R) :-
  reservation(R), booking_user(R, U), membership_tier(U, gold).

% Composite eligibility — reason-agnostic.
compensation_grounds(R) :- member_eligible_for_compensation(R).
compensation_grounds(R) :- reservation(R), has_travel_insurance(R).
compensation_grounds(R) :- reservation(R), reservation_cabin(R, business).

compensation_eligible(R, ComplaintType) :-
  complaint_type_value(ComplaintType),
  reservation(R),
  compensation_grounds(R).
```

### 3.10 `compensation_amount_cents(R, ComplaintType, A)`

Per the upstream policy:
- Cancelled flight complaint: `$100 × num_passengers`
- Delayed flight complaint + change/cancel: `$50 × num_passengers`

```
compensation_amount_cents(R, cancelled_flight_complaint, A) :-
  compensation_eligible(R, cancelled_flight_complaint),
  num_passengers(R, N),
  const(compensation_cancelled_per_passenger_cents, C),
  A = N * C.

compensation_amount_cents(R, delayed_flight_complaint_with_change_or_cancel, A) :-
  compensation_eligible(R, delayed_flight_complaint_with_change_or_cancel),
  num_passengers(R, N),
  const(compensation_delayed_per_passenger_cents, C),
  A = N * C.
```

Q6 strict reading is a **Layer C** precondition on the
`offer_compensation` action for the delayed case (the modify/cancel
must have actually been executed). Layer B's
`compensation_eligible/2` is necessary but not sufficient on its own
for the delayed branch.

---

## 4. Composite predicates

The handful of composites that Layer C and the verifier reach for
most often.

### 4.1 `cancellable_with_some_reason(R)`

For "this reservation could be cancelled if the user supplies the right
reason." Used by Verify in the existence direction.

```
cancellable_with_some_reason(R) :-
  reservation(R),
  cancellation_reason_value(Reason),
  cancellable(R, Reason).
```

### 4.2 `payment_composition_valid(R)`

The reservation's payment_method usage satisfies the cardinality caps
(C-CARD-3). Convenience predicate — the underlying caps are integrity
constraints (so a violating DB doesn't exist), but Layer C wants a
positive predicate to consult.

```
payment_composition_valid(R) :-
  reservation(R),
  #count{ PM : payment_used(R, PM),
         payment_method_type(PM, travel_certificate) } <= 1,
  #count{ PM : payment_used(R, PM),
         payment_method_type(PM, credit_card) } <= 1,
  #count{ PM : payment_used(R, PM),
         payment_method_type(PM, gift_card) } <= 3.
```

### 4.3 `requires_transfer_for_cancellation(R)`

True iff the cancellation request must transfer to a human (rather than
be refused in-band or executed). The single case in v0 is "a portion
of the flight has already been flown":

```
requires_transfer_for_cancellation(R) :-
  reservation(R), has_flown_segment(R).
```

Layer D will gate the `transfer_to_human_agents` invocation on this
predicate.

---

## 5. Worked micro-example

A small ground instance exercising the cancellation rules. Not a
benchmark task — a sanity check that the rules typecheck and produce
the expected predicates.

```
% --- D₀ facts ---

% Constants.
const(recent_booking_window_hours, 24).
const(compensation_cancelled_per_passenger_cents, 10000).
const(compensation_delayed_per_passenger_cents, 5000).

% Enums.
cancellation_reason_value(change_of_plan).
cancellation_reason_value(airline_cancelled).
cancellation_reason_value(other).
complaint_type_value(cancelled_flight_complaint).
complaint_type_value(delayed_flight_complaint_with_change_or_cancel).

% User: Alice, silver member.
user(u_alice).
membership_tier(u_alice, silver).
payment_method(pm_card).
payment_method_type(pm_card, credit_card).
payment_method_owner(pm_card, u_alice).
payment_method_credit_card_valid(pm_card).

% Flight: HAT001 SFO→JFK on 2024-05-20, status=available, business cabin.
flight_instance(hat001, "2024-05-20").
flight_status(hat001, "2024-05-20", available).

% Reservation: Alice, business cabin, 2 passengers, no insurance,
% created 8h ago.
reservation(r_001).
booking_user(r_001, u_alice).
reservation_cabin(r_001, business).
reservation_status(r_001, active).
segment_of(r_001, hat001, "2024-05-20").
payment_used(r_001, pm_card).
passenger(r_001, 1).
passenger(r_001, 2).
hours_since_creation(r_001, 8).
% has_travel_insurance(r_001) NOT asserted → false by NAF.
```

Expected derived facts:

| Predicate | Value |
|---|---|
| `non_business_cabin(r_001)` | false (cabin = business) |
| `recent_booking(r_001)` | true (8h ≤ 24h) |
| `has_flown_segment(r_001)` | false |
| `has_airline_cancelled_segment(r_001)` | false |
| `cancellable(r_001, change_of_plan)` | true — via recent_booking AND via business cabin |
| `cancellable(r_001, airline_cancelled)` | true — same |
| `cancellable(r_001, other)` | true — same |
| `num_passengers(r_001, _)` | 2 |
| `compensation_grounds(r_001)` | true — silver member AND business cabin |
| `compensation_amount_cents(r_001, cancelled_flight_complaint, _)` | 20000 (= 2 × 10000) |
| `compensation_amount_cents(r_001, delayed_flight_complaint_with_change_or_cancel, _)` | 10000 (= 2 × 5000) |
| `requires_transfer_for_cancellation(r_001)` | false |

A second scenario worth tracing: Alice with insurance covering only
`other`, no recent booking, economy cabin. Cancellable for `other` but
not for `change_of_plan` or `airline_cancelled` (unless the flight is
also airline-cancelled).

---

## 6. Open questions for Layer C

Items surfaced while writing the cancellation slice. Listed for
resolution at Layer C, not now.

**Q-B-A1. Refund mechanics for travel certificates (Q8 follow-up).**
On a successful cancellation that refunds a travel certificate, what
happens to the cert's `balance_cents`? Reading (a) says the remaining
balance is lost; does the *applied* amount go anywhere? v0 leaning:
applied amount disappears (cert is consumed at booking time); no
refund event is emitted. Layer C `cancel_reservation` action will
codify.

**Q-B-A2. Refund mechanics for credit cards.** Refund "to the
original payment method" — for credit_card, what fact gets emitted?
Mirroring retail_returns: a `refund_to_card(PM, A)` event fact, no
in-DB balance mutation. Confirm.

**Q-B-A3. Compensation as a separate action vs. cancel side-effect?**
Two readings of the upstream policy:
(a) `offer_compensation` is its own action invoked after a cancel /
    modify when the customer complains and is eligible.
(b) The cancel itself emits the compensation if applicable.
v0 leaning: (a). The agent contract layer requires the customer to
*ask* for compensation; it's not automatic.

**Q-B-A4. Multi-reservation cancellation in a single task.** Not
allowed under retail_returns' "one logical transition per task"
convention. Confirm same convention for airline.

**Q-B-A5. Partial cancellation.** Can a customer cancel one segment
of a round-trip reservation without cancelling the whole reservation?
The upstream policy does not address this directly. v0 leaning: no —
cancel applies to whole reservations only. Multi-segment cancellation
becomes a modify_flights operation.

**Q-B-A6. Insurance evidence threshold.** `insurance_covers(Reason)`
is an external predicate. What gates the encoder's assertion of this
fact? In Layer F, the task's `intent.insurance_covers: bool` will carry
it. For Generate, the scenario template specifies it. No further
threshold (e.g., medical documentation) is modeled in v0.

---

## 7. Status

- **2026-05-29** — initial Layer B draft, cancellation + compensation
  slice only. 10 of 12 ontology Qs resolved (Q7, Q9 deferred). 14
  integrity constraints. 10 derivation rules. 3 composite predicates.
  Worked micro-example. 6 questions surfaced for Layer C.

Booking validity, flight modification, cabin change, and baggage
allowance rules remain TODO; they will be added in subsequent Layer B
sessions before broadening the action surface in Layer C.
