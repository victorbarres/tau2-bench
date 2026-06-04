# Airline — Ontology (Layer A)

This is **Layer A** of the logic-first design described in
[`docs/methodology.md`](../../docs/methodology.md), applied as a **retrofit**
to the existing tau2-bench airline domain. It declares the sorts (entity
types), their attributes, the closed enumerations, and the names of the
derived predicates that downstream layers will define.

Companion files: Layer B (`rules.md`), Layer C (`actions.md`), Layer D
(`agent_contract.md`), Layer E (`db.json` + `db_design.md`), Layer F
(`tasks.json` + `tasks_design.md`) — to be authored in subsequent passes.

Source of this extraction: the upstream tau2-bench airline `policy.md`
(prose policy). An earlier extraction draft lives at
[`../airline_reference/policy_logic.md`](../airline_reference/policy_logic.md);
this Layer A document is the first formal artifact of the retrofit.

This document is the **single source of truth** for what entities and
vocabulary the airline domain has. Any other artifact (code schema, DB
instances, NL prose, tool definitions) that disagrees with this document
is wrong.

---

## 0. Scope of the domain

The domain models a single airline's **reservation lifecycle** for a
customer service agent: bookings, modifications (flights / cabin /
baggage / passenger info), cancellations, refunds, and compensation
gestures. The agent has authority to execute bookings on behalf of an
authenticated user, apply policy-prescribed adjustments (baggage
allowance, restocking-like rules for cabin changes), and refuse
ineligible requests.

**In scope:**
- Searching flights (direct and one-stop).
- Booking a new reservation against available flight instances.
- Modifying an existing reservation (flights / cabin / baggage /
  passenger info).
- Cancelling an existing reservation.
- Issuing refunds to the original payment methods.
- Offering compensation certificates as a policy-prescribed gesture.
- Transferring to a human agent when the request is out of scope.

**Out of scope (intentional for the LP encoding):**
- Catalog or fare-class browsing beyond what the flight search tools
  return.
- Frequent flier point accrual / redemption (membership is treated only
  as a tier that gates policy branches).
- Loyalty status changes mid-trip.
- Multi-airline / interline / codeshare logic.
- Tax breakdowns, fuel surcharges, fare buckets.
- Seat assignment beyond cabin class (no row/seat numbering).
- "Don't provide outside knowledge" / "one tool call per turn" / the
  transfer message string literal — these are dialogue-shape concerns
  that live in Layer D (agent contract), not Layer A.

---

## 1. Sorts

The closed list of entity types in the domain. Every fact in `D₀` is an
instance of exactly one of these.

| Sort | Description | Identifier |
|---|---|---|
| **User** | A person with an airline account; may be the booking user of a reservation. | `user_id` |
| **PaymentMethod** | A credit card, gift card, or travel certificate, attached to a User. | `payment_method_id` |
| **Flight** | An abstract route operated by the airline (origin, destination, scheduled times). | `flight_number` |
| **FlightInstance** | A specific operation of a Flight on a specific date. Bookability and seat availability live here, not on Flight. | `(flight_number, date)` composite |
| **Reservation** | A booking record: User + flights + passengers + payment + baggage + insurance. | `reservation_id` |
| **Passenger** | A person on a reservation. Need not be a User. | per-reservation index (no global id) |

Notes:

- `FlightInstance` is identified by a `(flight_number, date)` composite.
  We treat it as a sort because bookability, seat counts, and per-cabin
  prices are per-instance, not per-flight.
- `Passenger` has no global identifier — passengers are nested inside a
  Reservation. This matches the upstream data model and the tau-bench
  task schema.
- The set of `Action`s the agent can invoke is *not* a Layer A sort —
  it's a Layer C concern (the action surface). Layer A declares the
  entities the world contains; Layer C declares how those entities
  transition.

---

## 2. Closed enumerations

Every enumerated attribute below is **closed and finite**. Values outside
these sets are invalid input.

### 2.1 `membership_tier` (on User)
- `regular`
- `silver`
- `gold`

A total order is implicit: `regular < silver < gold`. Used by the
compensation eligibility rule and the baggage allowance table.

### 2.2 `payment_type` (on PaymentMethod)
- `credit_card`
- `gift_card`
- `travel_certificate`

### 2.3 `cabin_class` (on Reservation, on FlightInstance per-cabin attributes)
- `basic_economy`
- `economy`
- `business`

**Important:** `basic_economy` is a separate class from `economy`. They
share no rules unless a rule explicitly names both. The upstream policy's
"(basic) economy" idiom for compensation refusal is interpreted as
"`basic_economy` OR `economy`" — i.e., non-`business`. (See §8 Q2.)

### 2.4 `trip_type` (on Reservation)
- `one_way`
- `round_trip`

### 2.5 `flight_status` (on FlightInstance, per-date)
- `available` — bookable; seats and prices are listed.
- `on_time` — not yet departed but **not bookable**.
- `delayed` — not yet departed but **not bookable**.
- `flying` — departed, not landed; **not bookable**.
- `landed` — past; **not bookable**. Required by the cancellation rule
  to detect "any portion already flown" (introduced in this retrofit;
  see §8 Q12).
- `cancelled` — flight was cancelled by the airline. Required by the
  cancellation eligibility rule "the flight is cancelled by airline"
  (see §8 Q3).

### 2.6 `cancellation_reason` (asserted by user, on a cancellation request)
- `change_of_plan`
- `airline_cancelled`
- `other`

The upstream policy lists these three. Insurance coverage ("health or
weather reasons") does not align with these three reasons as written;
see §8 Q1 for the v0 plan to introduce `insurance_covers/1` as an
external predicate.

### 2.7 `complaint_type` (compensation only)
- `cancelled_flight_complaint`
- `delayed_flight_complaint_with_change_or_cancel`

These are the only two grounds for which the agent may issue
compensation, per the upstream policy. No other complaint type permits
compensation.

### 2.8 `compensation_outcome` (on the result of `offer_compensation`)
- `issued` — a certificate was sent.
- `denied` — no compensation given (e.g., user not eligible).

(Helper enum used by Layer C action effects, declared here for closure.)

---

## 3. Attributes per sort

Attributes are fields that must be present on every instance unless
marked optional. All identifiers are strings; all monetary amounts are
integer cents (no floats); all dates are ISO 8601 in the timezone the
upstream data uses (UTC for the new retrofit DB, EST for the upstream
flight times — see §5 on the timezone convention).

### 3.1 User
- `user_id` (id)
- `name` (FirstLast struct: first_name, last_name)
- `email` (string)
- `addresses` (list of Address; v0 carries one)
- `date_of_birth` (date)
- `payment_method_ids` (list of PaymentMethod ids; ≥ 0)
- `membership_tier` (enum, §2.1)
- `reservation_ids` (list of Reservation ids)
- `saved_passengers` (list of Passenger structs — used during booking
  flow to pre-fill passenger info; not a referential FK)

### 3.2 PaymentMethod
- `payment_method_id` (id)
- `customer_id` (User id) — owner.
- `type` (enum, §2.2)
- `display_label` (string; e.g., `"Visa •••• 1234"`)
- For `gift_card`: `balance_cents` (int, ≥ 0)
- For `travel_certificate`: `balance_cents` (int, ≥ 0)
- For `credit_card`: no balance carried in DB (out-of-band billing)

### 3.3 Flight
- `flight_number` (id)
- `origin` (string — IATA code)
- `destination` (string — IATA code)
- `scheduled_departure_time` (time-of-day; local at origin)
- `scheduled_arrival_time` (time-of-day; local at destination)

### 3.4 FlightInstance
A FlightInstance is a `(flight_number, date)` pair with per-date
attributes:
- `flight_number` (Flight id)
- `date` (date, YYYY-MM-DD)
- `status` (enum, §2.5)
- For each `cabin_class` value (basic_economy / economy / business):
  - `available_seats` (int, ≥ 0)
  - `unit_price_cents` (int, ≥ 0)
- Optional: `actual_departure_time`, `actual_arrival_time` (datetime,
  populated once flying / landed)

### 3.5 Reservation
- `reservation_id` (id)
- `booking_user_id` (User id) — the authenticated booker.
- `trip_type` (enum, §2.4)
- `origin` (string — IATA code; equal to first segment's origin)
- `destination` (string — IATA code; equal to last segment's destination
  for one_way, or original origin for round_trip)
- `cabin_class` (enum, §2.3) — uniform across all segments. This is a
  Layer B invariant; see C-UNIF-1.
- `flight_segments` (ordered list of FlightInstance references, each a
  `(flight_number, date)` pair)
- `passengers` (list of Passenger; 1 ≤ size ≤ 5)
- `payment_method_ids_used` (list of PaymentMethod ids; bounded — see §5
  for cardinalities)
- `created_time` (datetime) — used by the 24h cancellation eligibility
  branch.
- `total_baggages` (int, ≥ 0)
- `nonfree_baggages` (int, ≥ 0; ≤ total_baggages)
- `has_travel_insurance` (bool)
- `status` (enum: { active, cancelled }) — soft state. Cancelled
  reservations are retained in the DB with a status flag (not deleted),
  matching the upstream data model.

### 3.6 Passenger
- `first_name` (string)
- `last_name` (string)
- `date_of_birth` (date)

(No id — passengers are positionally nested in a Reservation.)

---

## 4. Multi-party / structural relationships

Three structural relationships matter for Layer B:

### 4.1 Reservation → FlightInstances (ordered)
Each Reservation references a sequence of FlightInstances by
`(flight_number, date)`. The ordering matters for itinerary semantics
(first segment's origin = trip origin; last segment's destination =
trip destination for `one_way`).

### 4.2 Reservation → PaymentMethods (multi, with cardinality caps)
A Reservation can use **at most**:
- 1 `travel_certificate`
- 1 `credit_card`
- 3 `gift_card`s

(Layer B integrity constraints; declared in rules.md.)

### 4.3 User → Passengers (passenger ≠ user)
A Passenger is *not* a User. The booking user provides passenger info
manually (or via `saved_passengers`). A reservation may have passengers
none of whom is the booking user.

(No multi-tenant / corporate booking flows in v0.)

---

## 5. Numeric constants

Values that the rules in Layer B will reference. Declared here so all
artifacts use the same symbolic name. Sourced from the upstream
`policy.md`.

| Symbol | Value | Origin clause |
|---|---|---|
| `current_time` | `2024-05-15T15:00:00 EST` | policy.md L3 (per-D₀) |
| `max_passengers_per_reservation` | 5 | "at most five passengers" |
| `max_travel_certificates` | 1 | payment section |
| `max_credit_cards` | 1 | payment section |
| `max_gift_cards` | 3 | payment section |
| `extra_baggage_cost_cents` | 5000 | "each extra baggage is 50 dollars" |
| `insurance_cost_per_passenger_cents` | 3000 | "travel insurance is 30 dollars per passenger" |
| `recent_booking_window_hours` | 24 | "booking was made within the last 24 hrs" |
| `compensation_cancelled_per_passenger_cents` | 10000 | refunds section |
| `compensation_delayed_per_passenger_cents` | 5000 | refunds section |
| `refund_business_days_min` | 5 | "5 to 7 business days" |
| `refund_business_days_max` | 7 | "5 to 7 business days" |

**Timezone convention.** The upstream policy and flight schedules use
EST (no DST handling). The retrofit DB will adopt UTC for `created_time`
and ISO datetime fields; flight schedule times remain in EST and are
treated as local-at-origin for arithmetic.

### 5.1 Free baggage allowance table

Per passenger, by `membership_tier × cabin_class`:

| membership | basic_economy | economy | business |
|---|---|---|---|
| regular | 0 | 1 | 2 |
| silver  | 1 | 2 | 3 |
| gold    | 2 | 3 | 4 |

Will be encoded as 9 ground ASP facts in rules.md (driving the
`free_baggage_per_passenger/3` predicate, §6).

---

## 6. Derived predicates (names only; defined in Layer B)

These will be defined as ASP rules in Layer B. Listed here so other
layers can reference them and downstream artifacts (Pydantic, NL prose,
verifier) have a single vocabulary.

| Predicate | Arity | Intuition |
|---|---|---|
| `bookable(FI)` | 1 | True iff FlightInstance `FI` is in `available` status. |
| `valid_booking(R)` | 1 | Composite: a candidate Reservation satisfies all booking validity rules. |
| `free_baggage_per_passenger(U, C, N)` | 3 | Free baggage count `N` for user `U` flying cabin `C` (from the table in §5.1). |
| `free_baggage_total(R, N)` | 2 | Per-reservation free baggage total. |
| `extra_baggages(R, N)` | 2 | `max(0, total_baggages − free_baggage_total)`. |
| `modifiable_flights(R)` | 1 | True iff Reservation `R`'s flight segments may be modified (not basic_economy, not fully flown). |
| `cabin_changeable(R)` | 1 | True iff no segment of `R` is flying or landed yet. |
| `recent_booking(R)` | 1 | True iff `current_time − created_time ≤ 24h`. |
| `has_flown_segment(R)` | 1 | True iff any segment of `R` is in `flying` or `landed` status. |
| `has_airline_cancelled_segment(R)` | 1 | True iff any segment of `R` is in `cancelled` status. |
| `insurance_covers(reason)` | 1 | True iff the cancellation reason is covered by travel insurance (external — see §8 Q1). |
| `cancellable(R, Reason)` | 2 | True iff Reservation `R` may be cancelled with the given `Reason`. |
| `compensation_eligible(R, ComplaintType)` | 2 | True iff `R`'s booking user + cabin + insurance posture entitles them to a compensation gesture for the given complaint. |
| `compensation_amount_cents(R, ComplaintType, A)` | 3 | The amount `A` due as compensation. |
| `payment_method_valid(PM)` | 1 | True iff the payment method is usable as a refund destination (e.g., gift card balance > 0). |
| `payment_composition_valid(R)` | 1 | True iff the Reservation's `payment_method_ids_used` satisfies the cardinality caps (§4.2). |

---

## 7. Out of scope (intentionally)

For each, a brief rationale so future contributors don't re-litigate:

- **Frequent flier miles / point redemption.** Not in the upstream
  policy; membership tier is the only loyalty signal needed.
- **Seat selection within a cabin.** Cabin class is the only seat-level
  policy lever; row/seat numbering is unmodeled.
- **Multi-airline interline.** All segments operate on the same airline.
- **Currency conversion.** Single currency (USD cents).
- **Tax / fee breakdowns.** The reservation's payment total is the
  ground truth; we do not decompose into fare components.
- **Per-segment cabin class.** Layer B will enforce uniform cabin
  across all segments (C-UNIF-1).
- **Dialogue-shape rules** (one tool call per turn, transfer message
  text, no-outside-knowledge). These belong to Layer D.

---

## 8. Open ontological questions (carried from `policy_logic.md`)

The 12 ambiguities surfaced in the original extraction. Each is
proposed for a default resolution; final commitment lives in Layer B
(`rules.md`) §0.

**Q1. Insurance coverage mapping.** Policy lists three
`cancellation_reason` values (`change_of_plan`, `airline_cancelled`,
`other`) but says insurance covers "health or weather." Default
resolution: introduce `insurance_covers/1` as an **external predicate**
asserted by the encoder based on a side-channel reason classification.
Layer F tasks will carry the classification in `intent.insurance_covers:
bool` so the verifier can encode the fact directly.

**Q2. "(basic) economy" parsing in compensation rule.** Default
resolution: read as `basic_economy OR economy` (i.e., non-`business`).
Confirm and encode.

**Q3. Airline-cancelled flight detection.** Default resolution: add
`cancelled` as a `flight_status` value (already done in §2.5); the
`has_airline_cancelled_segment(R)` predicate is derived from segment
status.

**Q4. "Business flight" in cancellation rules.** Default resolution:
read as `cabin_class(R) = business`, leveraging the C-UNIF-1
uniform-cabin invariant.

**Q5. Compensation rule equivalent phrasings.** Default resolution:
under Q2's reading, the negative and positive phrasings are
logically equivalent by De Morgan. Encode one (the positive form is
clearer for derivation).

**Q6. Delayed-flight compensation precondition.** Default resolution:
strict reading — the modify/cancel must have actually been executed
before the agent issues compensation. Encode `compensation_eligible`
to require a prior `modify_*` or `cancel_reservation` action in the
same task.

**Q7. Removing insurance post-booking.** Default resolution: forbidden
symmetrically. (Policy forbids adding; we treat removing as also
forbidden.) Encode as Layer B integrity constraint.

**Q8. Travel certificate gap.** Default resolution: reading (a) —
remaining balance on the certificate after application is lost; refund
of cert portion at cancellation is $0. The reservation locks the
applied amount, not the cert face value.

**Q9. Flight segment modification — kept vs replaced pricing.**
Default resolution: kept segments retain their original-booking unit
price; replacement segments use the current `FlightInstance` price.

**Q10. Recency window reference time.** Default resolution: relative
to `current_time` (i.e., the moment of the cancellation request).

**Q11. Membership for compensation.** Default resolution: only the
`booking_user_id`'s `membership_tier` matters, not any passenger's.

**Q12. Status enum extension.** Default resolution: added `landed` and
`cancelled` to `flight_status` (§2.5). Confirm.

---

## 9. Status

- **2026-05-29** — initial Layer A draft. Migrated from
  `../airline_reference/policy_logic.md` §1, §2, §5 into the standard
  retail_returns-style structure. 6 sorts, 8 closed enumerations, 12
  numeric constants, 1 free-baggage table, 16 derived predicates
  named. 12 open questions surfaced for Layer B resolution (§8).

Layers B–F remain TODO. The next session should author Layer B
(`rules.md`) covering at least the cancellation-related integrity
constraints + derivations, which is the smallest subset that supports
a first end-to-end airline retrofit task verification.
