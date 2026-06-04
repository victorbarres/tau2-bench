# Airline — Actions (Layer C, cancellation slice)

This is **Layer C** of the airline retrofit, scoped to the
**cancellation slice** so we can drive one end-to-end task verification.
Booking, modification (flights / cabin / baggage / passengers), and
compensation as a standalone action are deferred to later slices.

Layer C describes **how the world transitions** when an action fires.
Layer B ([`rules.md`](rules.md)) describes what is true in any single
state. Layer D (`agent_contract.md`, TODO) describes when and how the
agent may invoke an action.

Where an action's effect and a Layer B integrity constraint overlap,
the integrity constraint is authoritative. Actions are responsible for
preserving invariants; they are not allowed to define them.

---

## 0. Resolved Layer B questions

The 6 Q-B-A questions from [`rules.md`](rules.md) §6 are resolved as
follows for the cancellation slice:

| Q | Resolution | Mechanism |
|---|---|---|
| **Q-B-A1** Travel certificate refund | **Applied amount is lost.** No refund event is emitted for the cert portion of a cancelled reservation. The cert was consumed at booking time; cancellation does not restore it. | Effect of `cancel_reservation`. |
| **Q-B-A2** Credit card refund | `cancel_reservation` emits a `refund_to_card(PM, A)` event fact per credit card used. No in-DB balance mutation (credit cards don't carry a DB balance). | Effect of `cancel_reservation`. |
| **Q-B-A3** Compensation as separate action | **Separate action.** `offer_compensation` is its own deferred action (not in this slice). `cancel_reservation` does not auto-emit compensation. The agent must explicitly invoke `offer_compensation` if the customer asks and is eligible. | Layer C surface decision. |
| **Q-B-A4** Multi-reservation cancellation per task | **Forbidden** by the one-logical-transition convention (§6). A task that cancels two reservations splits into two tasks. | Layer F authoring convention. |
| **Q-B-A5** Partial cancellation | **Not supported.** `cancel_reservation` applies to the whole reservation. Multi-segment partial drop is a `modify_reservation_flights` operation (deferred). | Action surface decision. |
| **Q-B-A6** Insurance evidence threshold | **None.** `insurance_covers/1` is asserted directly from `intent.insurance_covers: bool` (Layer F) or scenario template (Generate). No medical documentation or external verification is modeled in v0. | External predicate, encoder-supplied. |

Refund mechanics summary by payment type:

| Type | DB-side effect on cancel | Event emitted |
|---|---|---|
| `credit_card` | None | `refund_to_card(PM, A)` |
| `gift_card` | `payment_method_balance_cents(PM, _)` increased by `A` | `refund_to_gift_card(PM, A)` |
| `travel_certificate` | None | None (Q-B-A1: applied amount is lost) |

Where `A` is the portion of the reservation total paid via that
specific payment method (Layer E will carry per-payment allocation;
v0 generated tasks assume single-payment reservations to sidestep
allocation).

---

## 1. Action surface (cancellation slice)

Four actions in this slice. The full v1 retrofit will add ~8 more
(book / search / modify_* / offer_compensation / send_certificate / etc.).

| Action | Read or mutate | Used to |
|---|---|---|
| `get_user_details(U)` | read | Look up a user and their payment methods + reservation list. |
| `get_reservation_details(R)` | read | Look up a reservation and its segments + passengers + payments. |
| `cancel_reservation(R, Reason)` | mutate | Move `reservation_status(R, active)` → `cancelled` with the stated `Reason`. |
| `transfer_to_human_agents(reason_label)` | escalate | End the agent's session and hand off. No DB effect. |

The remaining ~8 upstream airline actions (book_reservation,
search_direct_flight, search_onestop_flight,
update_reservation_flights, update_reservation_cabin,
update_reservation_baggages, update_reservation_passengers,
offer_compensation, send_certificate, list_all_airports, calculate,
think) are **not in this slice**. They will be added in subsequent
Layer C sessions per scope.

---

## 2. ASP encoding conventions for actions

Same two-snapshot encoding as retail_returns' Layer C:

- **Pre-state predicates** carry no prefix and refer to `D₀`.
- **Post-state predicates** carry a `post_` prefix and refer to `D₁`.
- **Frame axioms** are implicit in the encoder; not written out.
- For each action, the body of the rule is the precondition; the head
  encodes the effect by asserting `post_*` facts.

For **cancel_reservation** specifically, the verifier's choice surface
is degenerate — there is no "free variable" the agent selects (the
reason is supplied by the user). The ASP encoding becomes a feasibility
check: does at least one model exist, given C_hard pinning
`(target_reservation, target_reason)`?

```asp
% --- Cancel-action encoding template ---
target_reservation(R).
cancellation_reason_supplied(R, Reason).

% Hard preconditions from Layer B:
:- target_reservation(R), not reservation_status(R, active).
:- target_reservation(R), requires_transfer_for_cancellation(R).
:- target_reservation(R), cancellation_reason_supplied(R, Reason),
   not cancellable(R, Reason).
```

If all three constraints are satisfied, exactly one trivial model
exists (the "cancel succeeds" outcome). If any fail, 0 models — the
cancel is infeasible, and a `policy_noop` task should be the
classification.

For Verify, the verdict pattern is:
- `unique` (1 model, free count 1) — cancel succeeds.
- `infeasible` (0 models) — cancel refused by policy.

Pruning ratio for cancellation tasks is always `1→1` or `0→0` because
there's no free choice to prune.

---

## 3. Read actions

Read actions do not mutate `D₀`. They return data that the agent can
use in subsequent reasoning. For the verifier they're invisible (no
state change); for the discoverability check they're load-bearing —
they define what the agent *can know*.

### 3.1 `get_user_details(user_id)`

**Returns**: `User` record (name, email, dob, member_tier,
addresses, saved_passengers) + the list of `PaymentMethod` records
owned by that user + the list of reservation_ids.

**Preconditions**: `user(user_id)` exists.

**Error**: user not found → returns null; agent must handle.

**Discoverability note**: required before any reservation action that
references a user-owned payment method, and before invoking
`cancel_reservation` (the agent contract layer will codify a D-CONF
rule for this).

### 3.2 `get_reservation_details(reservation_id)`

**Returns**: `Reservation` record (including `booking_user_id`,
`trip_type`, `origin`, `destination`, `cabin_class`,
`payment_method_ids_used`, `total_baggages`, `nonfree_baggages`,
`has_travel_insurance`, `created_time`, `status`) + the ordered list
of segments (each `{flight_number, date, segment_unit_price_cents}`)
+ the list of Passenger records.

**Preconditions**: `reservation(reservation_id)` exists.

**Discoverability note**: this is the canonical lookup for a
cancellation flow. The agent computes `cancellable` eligibility from
the returned record. The Layer D contract requires this read before
invoking `cancel_reservation`.

---

## 4. Mutating action — cancel_reservation

The single mutating action in this slice.

### 4.1 `cancel_reservation(reservation_id, cancellation_reason)`

Moves a reservation from `active` to `cancelled`, sets the
cancellation reason, and emits refund events per the payment-type
table in §0.

**Signature**:
- `reservation_id` — the Reservation to cancel.
- `cancellation_reason ∈ cancellation_reason_value` (i.e.,
  `change_of_plan | airline_cancelled | other`).

**Preconditions** (in this exact order):
- `reservation(reservation_id)` exists.
- `reservation_status(reservation_id, active)`.
- `not requires_transfer_for_cancellation(reservation_id)` —
  equivalently, no segment is `flying` or `landed`. If this fails,
  the cancel CANNOT be invoked; the agent must transfer instead
  (Layer D).
- `cancellable(reservation_id, cancellation_reason)` — the composite
  from rules.md §3.7. If this fails, the cancel is refused in-band
  (no Layer C invocation; the failure is a `policy_noop` task per
  Layer D's D-REF pattern).

**Effects**:
- `reservation_status(reservation_id, cancelled)`.
- `reservation_cancellation_reason(reservation_id, cancellation_reason)`.
- For each `payment_used(reservation_id, PM)`:
  - If `payment_method_type(PM, credit_card)`: emit a `refund_to_card(PM, A)`
    event fact where `A` = portion paid via PM. No in-DB balance change.
  - If `payment_method_type(PM, gift_card)`: increment
    `payment_method_balance_cents(PM, _)` by `A`; emit
    `refund_to_gift_card(PM, A)` event.
  - If `payment_method_type(PM, travel_certificate)`: nothing
    (Q-B-A1).

**Post-conditions** (implied by Layer B):
- All integrity constraints continue to hold. In particular:
  - C-STATE-RES-2: `cancellation_reason_set(R)` is now true.
  - C-MONEY-1: gift_card balances ≥ 0 (after increment).

**Failure modes**:
- `reservation` not found, status ≠ active, or cancellable predicate
  fails → action raises a specific error. Layer D's agent contract
  rules specify how the agent communicates each.
- Requires-transfer case is **not** a failure of `cancel_reservation`
  — the agent should never invoke `cancel_reservation` in that case;
  the contract requires `transfer_to_human_agents` instead.

### 4.2 Per-payment allocation (v0 simplification)

For v0 generated tasks and the first retrofitted upstream task, we
assume **single-payment reservations** — exactly one PaymentMethod
in `payment_method_ids_used`. The `A` (refund portion per payment
method) is then simply the reservation's total payment amount. This
avoids the multi-payment cents-level allocation question.

Multi-payment reservations (e.g., 1 credit card + 2 gift cards) are
common in the upstream airline tasks but require an allocation
attribute `payment_amount(R, PM, A)` on the Reservation. v1 will
introduce this; v0 sidesteps it for the first end-to-end retrofit.

---

## 5. Escalation

### 5.1 `transfer_to_human_agents(reason_label)`

Hand off the conversation to a human. No DB effect.

**Signature**:
- `reason_label: string` — short label citing why escalation is
  needed. For the cancellation slice, the canonical labels are:
  - `"flown_segment_cannot_cancel"` — at least one segment has
    `flying` or `landed` status; the upstream policy requires
    transfer.
  - `"customer_escalation_request"` — the customer asked for a
    supervisor.
  - `"out_of_action_surface"` — the customer's request is not
    expressible by an available action.

**Preconditions**: none.

**Effects**: emits a `transfer(reason_label)` event fact. The system
terminates the agent session.

**Layer D will gate** when this is appropriate. Layer C just declares
the operation exists.

---

## 6. The "one logical transition per task" convention

Same convention as retail_returns' Layer C §6: at most one logical
state transition between `D₀` and `D*` per task.

For the cancellation slice, this means:
- One task may invoke `cancel_reservation` at most once.
- A task that wants to cancel two reservations splits into two tasks.
- The cancel may be followed by `offer_compensation` in subsequent
  slices (Q-B-A3), but only as a *follow-on action* in the same task,
  not a separate transition.

Read actions remain unlimited.

---

## 7. Generated artifacts (downstream of Layer C)

For v0 retrofit, we hand-author the airline encoder + actions in the
verifier (`tools/clingo_verify.py` will need an airline-domain
extension). v1 will generate them from the spec, per the methodology.
Specifically:

1. **Pydantic data model** — one class per airline sort, mirroring
   `data_model.py` in the upstream tau2-bench repo. (Already exists
   upstream; we are generating a methodology-compliant version.)
2. **Tool stubs** — one tool per action; descriptions generated
   from the action's prose.
3. **Action validators** — code-level checks mirroring Layer B
   integrity constraints.

For this slice, the verifier extension is the critical missing
piece; it will be authored in a subsequent session.

---

## 8. Open questions for Layer D

Items surfaced while writing this Layer C slice. Listed for resolution
at Layer D, not now.

**Q-C-A1. Required reads before mutation.** Default: agent MUST call
`get_user_details(U)` and `get_reservation_details(R)` before
`cancel_reservation(R, _)`. The user_id read is necessary because
cancellation eligibility depends on the booking user's tier (for the
"business cabin" branch this isn't strictly needed, but for the
"insurance" branch we need to read the reservation to know
`has_travel_insurance`). Codify as D-CONF rules mirroring
retail_returns'.

**Q-C-A2. Confirmation requirements.** Default: agent MUST list the
cancellation details (reservation id, segments being cancelled, refund
amounts per payment method, expected refund timeline 5–7 business
days) and obtain explicit "yes" before invoking `cancel_reservation`.
Codify as D-CONF.

**Q-C-A3. Refusal in-band vs transfer.** Mirrors retail_returns'
D-REF pattern:
- In-band refusal: `not cancellable(R, Reason)` with no flown segment.
  Agent cites policy clause, gets ack, ends conversation.
- Transfer: `requires_transfer_for_cancellation(R)` (any flown
  segment), or persistence-threshold exceeded, or out-of-scope request.

**Q-C-A4. Information disclosure on cancellation.** What can the
agent tell the customer about refund timing and amounts? Default:
state the 5–7 business days window; itemize refund amounts per
payment method by display label only (e.g., "Visa ending in 4242"),
never the full card number. Standard PCI-flavored discretion.

**Q-C-A5. The "you should not provide knowledge" rule.** Upstream
policy says the agent should not provide information not from the
user or available tools. This is a dialogue-shape rule mirroring
retail_returns' D-INFO-5 and lives in Layer D.

**Q-C-A6. Cancellation followed by compensation request.** The
customer may, after a successful cancellation, ask for compensation.
Per Q-B-A3, `offer_compensation` is a separate action. Layer D needs
to specify the dialogue ordering (cancel first → confirm → ask if
they want compensation → if so, compensation_eligible check).

---

## 9. Status

- **2026-05-29** — initial Layer C draft, cancellation slice only.
  6 Q-B-A questions resolved (§0). 4 actions declared (§1: 2 read +
  1 mutate + 1 escalate). Cancel action specified in full (§4).
  Single-payment v0 simplification flagged. One-logical-transition
  convention adopted (§6). 6 questions surfaced for Layer D (§8).

Booking, search, flight modification, cabin change, baggage updates,
compensation, and passenger updates remain TODO. They will be added
in subsequent Layer C sessions before broadening the verifier scope.
