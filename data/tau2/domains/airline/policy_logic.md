# Airline Policy — Logical Structure (extraction for ASP)

This document is the **natural-language extraction layer** for the airline policy
defined in [policy.md](policy.md). Its purpose is to enumerate, in plain English,
every concept, instance, rule, and constraint that the policy implies, in a form
that maps cleanly onto an Answer Set Programming (Clingo) encoding.

It does **not** introduce any new policy: every clause below either restates
something in `policy.md` or makes an interpretive choice that is flagged in the
"Open Questions / Ambiguities" section at the end.

The target downstream artifact is a Clingo program in which:
- **Sorts** become typed constants / domain predicates.
- **Instances** become facts (closed enumerations).
- **Rules** become normal rules (with negation-as-failure for defaults/exceptions).
- **Constraints** become integrity constraints (`:- …`) or cardinality bounds.
- Arithmetic and temporal checks that would blow up grounding (dates, prices)
  are kept as **external predicates** supplied by a host program.

---

## 1. Sorts / Concepts

These are the entity types in the domain. Each will become a one-place predicate
(or a typed constant in a multi-sorted encoding).

### 1.1 User
A person who holds an account and can be the booker of a reservation.
Attributes:
- `user_id` (identifier)
- `email`
- `addresses` (collection)
- `date_of_birth`
- `payment_methods` (collection — see PaymentMethod)
- `membership_level` — see §2.2
- `reservation_numbers` (collection — see Reservation)

### 1.2 PaymentMethod
A means of payment associated with a user.
Attributes:
- `payment_method_id`
- `owner_user_id`
- `type` — see §2.3
- `balance` (only meaningful for `gift_card` and `travel_certificate`)

### 1.3 Flight
An abstract route operated by the airline.
Attributes:
- `flight_number`
- `origin`
- `destination`
- `scheduled_departure_time` (local time at origin)
- `scheduled_arrival_time` (local time at destination)

### 1.4 FlightInstance
A specific operation of a Flight on a specific date. (Bookability lives here,
not on Flight.)
Attributes:
- `flight_number`
- `date`
- `status` — see §2.4
- For each CabinClass: `available_seats`, `price`

### 1.5 Reservation
A booking record tying a User to a sequence of FlightInstances for a set of
Passengers.
Attributes:
- `reservation_id`
- `booking_user_id`
- `trip_type` — see §2.5
- `flight_segments` (ordered list of FlightInstance references)
- `cabin_class` (single value, uniform across segments — see §4)
- `passengers` (list of Passenger; 1 ≤ size ≤ 5)
- `payment_methods_used` (list — see §4 for cardinalities)
- `created_time` (timestamp)
- `baggage_count` (integer per passenger)
- `has_travel_insurance` (boolean)
- `total_paid` (monetary amount)

### 1.6 Passenger
A person who flies on a reservation. Need not be a User.
Attributes:
- `first_name`
- `last_name`
- `date_of_birth`

### 1.7 Action
A request the agent may take. Models the deontic structure of the policy.
Instances: see §2.6.

### 1.8 CancellationReason
Reason supplied by the user for a cancellation request.
Instances: see §2.7.

### 1.9 Derived concepts (will be defined by rules in §3, not asserted as facts)
- `bookable(FlightInstance)`
- `free_baggage_allowance(User, CabinClass)` — per passenger
- `modifiable(Reservation)` — flights aspect
- `cabin_changeable(Reservation)`
- `cancellable(Reservation, CancellationReason)`
- `compensation_eligible(User, Reservation)`
- `compensation_amount(Reservation, ComplaintType)`
- `requires_confirmation(Action)`

---

## 2. Instances / Closed Enumerations

These are the closed sets. Any value outside these sets is invalid input.

### 2.1 (none — User is open)

### 2.2 `membership_level`
- `regular`
- `silver`
- `gold`

(Total order for some rules: `regular < silver < gold`. Useful for the
compensation rule.)

### 2.3 `payment_type`
- `credit_card`
- `gift_card`
- `travel_certificate`

### 2.4 `flight_status`
- `available` — bookable; seats and prices are listed
- `on_time` — not yet departed but **not bookable**
- `delayed` — not yet departed but **not bookable**
- `flying` — departed, not landed; **not bookable**
- (Implied) `landed` / `completed` — past; **not bookable**. Needed for the
  "any portion already flown" check in §3.4.

### 2.5 `trip_type`
- `one_way`
- `round_trip`

### 2.6 `action`
- `book`
- `modify_flights`
- `modify_cabin`
- `modify_baggage`
- `modify_passenger_info`
- `cancel`
- `offer_compensation`
- `transfer_to_human`

The first six are **DB-mutating** and therefore require explicit user
confirmation (§5).

### 2.7 `cancellation_reason`
- `change_of_plan`
- `airline_cancelled`
- `other`

(See ambiguity Q1 below — the policy's "covered by insurance (health or
weather)" clause does not align with this three-way split as written.)

### 2.8 `cabin_class`
- `basic_economy`
- `economy`
- `business`

**Important:** `basic_economy` is a separate class from `economy`. They share no
rules unless a rule explicitly names both.

### 2.9 `complaint_type` (compensation only)
- `cancelled_flight_complaint`
- `delayed_flight_complaint_with_change_or_cancel`

### 2.10 Numeric constants
| Symbol | Value | Source clause |
|---|---|---|
| `current_time` | `2024-05-15T15:00:00 EST` | policy.md L3 |
| `max_passengers_per_reservation` | 5 | "at most five passengers" |
| `max_travel_certificates` | 1 | payment section |
| `max_credit_cards` | 1 | payment section |
| `max_gift_cards` | 3 | payment section |
| `extra_baggage_cost_usd` | 50 | "each extra baggage is 50 dollars" |
| `insurance_cost_per_passenger_usd` | 30 | "travel insurance is 30 dollars per passenger" |
| `recent_booking_window_hours` | 24 | "booking was made within the last 24 hrs" |
| `compensation_cancelled_per_passenger_usd` | 100 | refunds section |
| `compensation_delayed_per_passenger_usd` | 50 | refunds section |
| `refund_business_days_min` | 5 | "5 to 7 business days" |
| `refund_business_days_max` | 7 | "5 to 7 business days" |

### 2.11 Free baggage allowance table (per passenger, by member × cabin)
| membership | basic_economy | economy | business |
|---|---|---|---|
| regular | 0 | 1 | 2 |
| silver  | 1 | 2 | 3 |
| gold    | 2 | 3 | 4 |

This is a 9-fact table in ASP.

---

## 3. Rules (derivations, permissions, obligations)

These will become Clingo rules. Default/exception structure is called out
because that is where ASP's negation-as-failure shines.

### 3.1 Bookability
- **R-BOOK-1**: A FlightInstance `f` is `bookable` iff `status(f) = available`.
  (Equivalently: `delayed`, `on_time`, `flying`, and any past status are
  non-bookable.)

### 3.2 Valid booking
A proposed Reservation `r` is a **valid booking** iff **all** of the following
hold:
- **R-BOOK-2**: The booking user's `user_id` was provided.
- **R-BOOK-3**: Trip type, origin, destination were provided.
- **R-BOOK-4**: 1 ≤ |passengers(r)| ≤ 5.
- **R-BOOK-5**: Every passenger has first_name, last_name, date_of_birth.
- **R-BOOK-6**: All flight segments in `r` have a single, uniform cabin class.
- **R-BOOK-7**: All passengers fly all segments. (No per-passenger itineraries.)
- **R-BOOK-8**: Every FlightInstance in `r` is `bookable` (§3.1).
- **R-BOOK-9**: Payment composition satisfies §4 cardinalities and every
  payment method used is in `payment_methods(booking_user)`.
- **R-BOOK-10**: `total_paid(r) = Σ flight_price(segment, cabin) × |passengers|
  + extra_baggage_cost × extra_bag_count(r)
  + insurance_cost × |passengers| · 𝟙[has_insurance(r)]`.
  (Arithmetic delegated to host predicate.)

### 3.3 Free baggage allowance
- **R-BAG-1**: `free_baggage_per_passenger(u, c) = T[membership(u), c]` where
  `T` is the table in §2.11.
- **R-BAG-2**: `free_baggage_total(r) = free_baggage_per_passenger(booking_user,
  cabin) × |passengers|`.
- **R-BAG-3**: `extra_bags(r) = max(0, requested_bags(r) − free_baggage_total(r))`.
- **R-BAG-4 (obligation, soft)**: "Do not add checked bags that the user does
  not need." — This is an agent-behavior rule (§5), not a DB integrity rule.

### 3.4 Modification — flight segments
- **R-MOD-1 (hard exclusion)**: `modify_flights(r)` is forbidden if
  `cabin_class(r) = basic_economy`.
- **R-MOD-2**: A flight modification may **not** change `origin(r)`,
  `destination(r)`, or `trip_type(r)`. (Where origin/destination refer to the
  overall trip endpoints.)
- **R-MOD-3**: Kept segments retain their **original price**; replacement
  segments use the **current price**.
- **R-MOD-4**: After modification, R-BOOK-6 (uniform cabin) must still hold.
- **R-MOD-5**: Replacement segments must be `bookable` (§3.1).
- **R-MOD-6 (payment)**: A flight modification's price-difference payment uses
  **exactly one** payment method, which is either a `credit_card` or a
  `gift_card` already in the user's profile.

### 3.5 Modification — cabin
- **R-CABIN-1**: `cabin_changeable(r)` iff **no** segment of `r` has status
  `flying` or `landed`.
- **R-CABIN-2**: Cabin change applies to **all** segments uniformly.
- **R-CABIN-3**: If new total price > old total price, user pays the difference
  via R-MOD-6 method.
- **R-CABIN-4**: If new total price < old total price, user is refunded the
  difference via R-MOD-6 method.
- **R-CABIN-5**: Unlike R-MOD-1, cabin change **is** allowed even on
  `basic_economy` reservations.

### 3.6 Modification — baggage and insurance
- **R-BAG-MOD-1**: Baggage count may be increased, never decreased.
- **R-INS-MOD-1**: `has_travel_insurance(r)` may **not** be set to true after
  initial booking. (Removing insurance is not addressed by the policy and
  should be treated as forbidden by default — flagged as Q7.)

### 3.7 Modification — passenger info
- **R-PAX-MOD-1**: Individual passenger identities (name, dob) may be edited.
- **R-PAX-MOD-2**: `|passengers(r)|` may **not** change. (Explicitly: not even
  a human agent can change it.)

### 3.8 Cancellation eligibility
- **R-CANCEL-PRE-1**: Agent must obtain `user_id`, `reservation_id`,
  `cancellation_reason` before invoking cancel.
- **R-CANCEL-HARD**: If any segment of `r` has status `flying` or `landed`,
  the agent **cannot** cancel and must transfer (§5).
- **R-CANCEL-OK**: Otherwise, `cancellable(r, reason)` iff **any** of:
  1. `created_time(r) ≥ current_time − 24 hours` (recent booking), **or**
  2. Some segment of `r` has been cancelled by the airline (interpretation
     of "the flight is cancelled by airline" — see Q3), **or**
  3. `cabin_class(r) = business`, **or**
  4. `has_travel_insurance(r) = true` **and** `insurance_covers(reason)` (see
     Q1 for the definition of `insurance_covers`).
- **R-REFUND-1**: On cancellation, refund goes to the **original payment
  methods** within 5–7 business days.
- **R-REFUND-2**: Any unused balance remaining on a travel certificate is
  **not** refundable (it was non-refundable to begin with — the certificate
  itself can be returned, but the gap between cert value and reservation cost
  is lost).

### 3.9 Compensation
Default stance: **do not** offer compensation; only offer when explicitly
requested and eligible.

- **R-COMP-DEFAULT**: `offer_compensation(u, r)` is forbidden unless requested
  by the user.
- **R-COMP-ELIGIBLE**: `compensation_eligible(u, r)` iff **at least one** of:
  - `membership(u) ∈ {silver, gold}`, **or**
  - `has_travel_insurance(r) = true`, **or**
  - `cabin_class(r) = business`.
  Equivalently (and equivalent per the policy's two phrasings): **NOT**
  (`regular` AND `¬insurance` AND `cabin ∈ {basic_economy, economy}`).
- **R-COMP-AMOUNT-CANCELLED**: For a `cancelled_flight_complaint` on `r`:
  amount = 100 × |passengers(r)|. Confirm the cancellation facts first.
- **R-COMP-AMOUNT-DELAYED**: For a `delayed_flight_complaint_with_change_or_cancel`
  on `r`: amount = 50 × |passengers(r)|. The change/cancel must actually be
  performed (it is a precondition of this compensation, not just a request).
- **R-COMP-CLOSED**: No other compensation reasons are permitted.

### 3.10 Agent behavior (deontic / procedural)
- **R-AGENT-CONFIRM**: Any action in {book, modify_flights, modify_cabin,
  modify_baggage, modify_passenger_info, cancel} requires the agent to list
  the action details and obtain an explicit "yes" before executing the
  database-mutating tool.
- **R-AGENT-SCOPE**: The agent must not provide information, knowledge, or
  procedures absent from the user's input or available tools; no subjective
  recommendations.
- **R-AGENT-INTERLEAVE**: A single turn must either be (a) one tool call with
  no user-facing response, or (b) one user-facing response with no tool call.
  Never both at once.
- **R-AGENT-DENY**: Requests that violate any rule above must be denied (not
  silently refused or partially fulfilled).
- **R-AGENT-TRANSFER**: Transfer to human agent iff and only if the request
  is out of scope. Mechanism: call `transfer_to_human_agents`, then send the
  exact string `"YOU ARE BEING TRANSFERRED TO A HUMAN AGENT. PLEASE HOLD ON."`

---

## 4. Constraints (hard invariants — `:- …` in Clingo)

These are integrity constraints. A model is invalid if any of them is violated.
They restate, in inviolable form, things that some rules in §3 already imply,
plus a few cross-cutting invariants.

### 4.1 Cardinality
- **C-CARD-1**: `|passengers(r)| ≤ 5`.
- **C-CARD-2**: `|{m ∈ payment_methods_used(r) : type(m) = travel_certificate}| ≤ 1`.
- **C-CARD-3**: `|{m ∈ payment_methods_used(r) : type(m) = credit_card}| ≤ 1`.
- **C-CARD-4**: `|{m ∈ payment_methods_used(r) : type(m) = gift_card}| ≤ 3`.

### 4.2 Uniformity
- **C-UNIF-1**: All segments of a reservation share a single cabin class.
- **C-UNIF-2**: All passengers of a reservation are ticketed on all segments
  of that reservation.

### 4.3 Integrity / referential
- **C-REF-1**: Every `payment_method` used in `r` is owned by `booking_user(r)`.
- **C-REF-2**: Every `reservation_id` referenced by a user's
  `reservation_numbers` actually exists.

### 4.4 Bookability
- **C-BOOK-1**: Every `FlightInstance` in a created reservation had
  `status = available` at booking time.

### 4.5 Immutability under modification
- **C-IMM-1**: `origin`, `destination`, `trip_type` of a reservation never
  change after creation.
- **C-IMM-2**: `|passengers(r)|` never changes after creation.
- **C-IMM-3**: `baggage_count(r)` is non-decreasing.
- **C-IMM-4**: `has_travel_insurance(r)` is non-increasing after creation
  (and §3.6 forbids increasing it). i.e., constant after creation in practice.
- **C-IMM-5**: If `cabin_class(r) = basic_economy` initially, then segments of
  `r` cannot be replaced (only cabin / baggage / passenger-info may change).
- **C-IMM-6**: If any segment of `r` has status `flying` or `landed`, cabin
  cannot change.

### 4.6 Cancellation
- **C-CANCEL-1**: A reservation with a `flying` or `landed` segment cannot
  enter the cancelled state via the agent (only via human transfer).
- **C-CANCEL-2**: A cancellation is permitted only if at least one of the four
  R-CANCEL-OK conditions holds.

### 4.7 Compensation
- **C-COMP-1**: Compensation is only offered after an explicit user request.
- **C-COMP-2**: Compensation amount must match R-COMP-AMOUNT-* exactly.
- **C-COMP-3**: Compensation is permitted only when R-COMP-ELIGIBLE holds.
- **C-COMP-4**: No compensation outside the two enumerated complaint types.

### 4.8 Agent behavior
- **C-AGENT-1**: No DB-mutating action without prior explicit "yes" from the
  user in the same conversation, after presenting details.
- **C-AGENT-2**: No turn contains both a tool call and a user-facing message.
- **C-AGENT-3**: Transfer happens only when no rule above permits the request.

---

## 5. Mapping to ASP — sketch

A first pass at the encoding shape (not committed to yet — for discussion):

- **Sorts**: typed predicates `user/1`, `flight_instance/1`, `reservation/1`,
  etc. Plus closed enumerations: `cabin(basic_economy). cabin(economy).
  cabin(business).` and similar for membership, status, etc.
- **Attribute access**: relational style, e.g.
  `membership(u, gold)`, `cabin_of(r, economy)`, `status(fi, available)`.
- **Free baggage table**: 9 ground facts `free_bag(M, C, N).`
- **Defaults with exception** (e.g., default = "don't compensate"): use
  `compensable(U,R) :- eligible_condition(U,R), requested(U,R).` plus an
  integrity constraint `:- compensated(U,R), not compensable(U,R).`
- **Arithmetic / time / money**: pushed to external predicates
  (`&recent_booking[CT, BT]`, `&price[…]`) to avoid grounding blowup. Clingo
  supports this via theory atoms / Python integration.
- **Action choice**: at the top level, the agent's permitted action set at a
  state is computed by `permitted(A, S)` rules; the agent then picks one and
  the integrity constraints reject any plan that violates §4.

---

## 6. Open questions / ambiguities

These are interpretive choices we have to make before encoding. Each is
phrased as a yes/no or pick-one so we can resolve them in batch.

**Q1. Insurance coverage mapping.** The policy lists three cancellation
reasons (`change_of_plan`, `airline_cancelled`, `other`) but says insurance
"enables full refund … given health or weather reasons." These two
vocabularies don't overlap. Options:
  - (a) Add `health` and `weather` as new cancellation reasons, expanding §2.7.
  - (b) Treat `insurance_covers(reason)` as an external classifier that maps
    `other`-with-evidence to covered/not-covered.
  - (c) Require the user to explicitly state "health" or "weather" alongside
    `other`, and capture as a sub-reason.

**Q2. "(basic) economy" parsing.** In §"Refunds and Compensation":
"Do not compensate if the user is regular member and has no travel insurance
and flies (basic) economy." We are reading the parenthesized "(basic)" as
"basic_economy OR economy" — i.e., non-business. Confirm.

**Q3. "Airline cancelled flight" as cancellation eligibility.** Is this
inferred from FlightInstance status (would need a new status `airline_cancelled`),
or is it asserted by the user and trusted? If the former, §2.4 needs an extra
enum value.

**Q4. "It is a business flight" in cancellation rules.** Given C-UNIF-1
(uniform cabin per reservation), we read this as
`cabin_class(r) = business`. If a reservation could ever be mixed-cabin (e.g.,
mid-modification state), this needs sharpening. Confirm reservations are
always uniform-cabin at the point of cancellation check.

**Q5. Compensation rules and the two phrasings.** The policy gives both:
- (negative) "Do not compensate if regular ∧ no insurance ∧ (basic) economy"
- (positive) "Only compensate if silver/gold ∨ has insurance ∨ business"

Under Q2's reading, these are logically equivalent by De Morgan, so we can
encode just one. Confirm.

**Q6. Delayed-flight compensation precondition.** The policy says the agent
can offer the $50/passenger certificate "after confirming the facts **and
changing or cancelling the reservation**." We are reading this as: the
modify/cancel must actually be executed first; the compensation is a
follow-on action. Alternative reading: the user must merely *intend* to
change/cancel. Confirm strict reading.

**Q7. Removing insurance.** R-INS-MOD-1 forbids adding insurance post-booking;
the policy is silent on removing it. We are defaulting to "forbidden"
(symmetrically). Confirm.

**Q8. Travel certificate gap.** If a travel certificate exceeds the
reservation cost, the policy says "the remaining amount of a travel
certificate is not refundable." Two readings:
  - (a) Remaining **balance on the certificate** post-application is lost.
  - (b) The reservation locks the full cert value; cancellation refund of the
    cert portion is $0.
  We read (a). Confirm.

**Q9. "Some flight segments can be kept, but their prices will not be updated
based on the current price."** We are reading this as: kept segments keep
their *original-booking* price; replacement segments use *current* price.
Confirm.

**Q10. Recency window reference time.** "Booking was made within the last 24
hrs" — we read "last 24 hrs" relative to `current_time` (i.e., the moment of
the cancellation request, which equals the policy's stated current time).
Confirm vs e.g. "within 24 hrs of original departure".

**Q11. Membership for compensation.** When a reservation is shared, only the
**booking user**'s membership matters for the compensation rule, not any
passenger's. The policy phrasing "If the booking user is …" supports this.
Confirm this also applies to compensation.

**Q12. Status values not in the policy.** The policy enumerates `available`,
`delayed`, `on_time`, `flying`. It says nothing about a post-`flying` state
("landed" / "completed"), but the cancellation rule requires us to detect
"already flown." We are introducing `landed` as a 5th status. Acceptable?

---

## 7. Out of scope for the LP encoding

For completeness, things in `policy.md` that we will **not** encode as logic
(they live in the dialogue/agent layer, not the rule layer):
- The transfer message string literal.
- "One tool call or one response per turn" — a turn-shape constraint, not a
  rule about the world.
- "Don't provide outside knowledge" — a conditioning rule for the LLM, not a
  property of reservations.

These are still listed in §3.10 / §4.8 for completeness, but won't translate
to Clingo predicates; they belong in the agent's controller logic.
