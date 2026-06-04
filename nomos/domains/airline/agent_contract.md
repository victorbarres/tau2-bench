# Airline — Agent Contract (Layer D, cancellation slice)

This is **Layer D** of the airline retrofit, scoped to the
**cancellation slice** — the deontic rules that gate the 4 actions
declared in [`actions.md`](actions.md). Booking, modification, and
compensation deontic rules will be added in subsequent slices.

Layer D constrains what the agent can do. Layer B
([`rules.md`](rules.md)) constrains what the world can be; Layer C
([`actions.md`](actions.md)) constrains how the world transitions;
Layer D constrains the agent's behavior when interacting with a
customer.

Rules in this layer are mostly **not** machine-checkable as state
invariants. They are checkable against an *agent trajectory*: a
sequence of (customer turn, agent message, tool call) tuples. Some
compile down to runtime checks (e.g., "must call
`get_reservation_details` before `cancel_reservation`"); others are
dialogue-shape rules that get rendered into the agent's system prompt
and evaluated by an LLM judge during benchmark grading.

---

## 0. Resolved Layer C questions

The 6 Q-C-A questions from [`actions.md`](actions.md) §8 are resolved
as follows:

| Q | Resolution |
|---|---|
| **Q-C-A1** Required reads | Both. Agent MUST call `get_user_details(U)` and `get_reservation_details(R)` before `cancel_reservation(R, _)`. Codified as D-CONF-5 and D-CONF-7. |
| **Q-C-A2** Confirmation contents | Reservation id + segment list + refund amount per payment method (by display label) + 5–7 business day refund timeline. Codified as D-CONF-2. |
| **Q-C-A3** Refusal in-band vs transfer | Mirrors retail_returns' D-REF pattern. Critical airline-specific rule: any `flying`/`landed` segment forces transfer (D-OOS-2). Other policy refusals are in-band (D-REF-2). |
| **Q-C-A4** Disclosure on cancellation | State 5–7 business day window; itemize refunds by display label only. Never the full payment-method number. Codified as D-INFO-2. |
| **Q-C-A5** No outside knowledge | Direct lift from retail_returns D-INFO-5. The agent cites policy and DB facts only. |
| **Q-C-A6** Cancellation followed by compensation request | Compensation is its own action (out of this slice). If the customer asks for compensation after a successful cancellation, the agent must (a) verify `compensation_eligible(R, ComplaintType)` via Layer B, and (b) invoke `offer_compensation` if eligible. Out of slice — deferred. |

---

## 1. Deontic vocabulary

Same as [`../retail_returns/agent_contract.md`](../retail_returns/agent_contract.md) §1:

| Marker | Meaning |
|---|---|
| **MUST** | Required. Violation = test failure. |
| **MAY** | Permitted. Not required. |
| **MUST NOT** | Forbidden. |
| **MUST TRANSFER** | Forbidden in-band; agent MUST invoke `transfer_to_human_agents`. |

Encoding column tags: `[runtime]` for trajectory-checkable rules;
`[prompt]` for LLM-graded rules; `[both]` for rules with both forms.

---

## 2. Authentication

### D-AUTH-1 — Customer identification required before any read of customer-scoped data
The agent MUST obtain the customer's `user_id` (or a unique identifier
the agent can resolve to a single `user_id` via lookup — e.g., email,
name + reservation id) before calling any of `get_user_details`,
`get_reservation_details`, or `cancel_reservation`. `[runtime]`

### D-AUTH-2 — No identity transitivity
The agent MUST NOT accept a customer's claim to be acting on behalf
of another customer. A booking user cannot cancel a reservation that
belongs to a different user. `[prompt]`

**Encoding hook**: combined with C-REF-1, the runtime check is
`booking_user(R, claimed_user_id) = booking_user(R, _)`.

### D-AUTH-3 — Verify identity before disclosing
The agent MUST verify the claimed customer identity by cross-referencing
at least one piece of independent information (e.g., reservation id,
email, name) before sharing any user-specific data. `[prompt]`

### D-AUTH-4 — Re-authentication on customer change
If the conversation pivots to a different customer, the agent MUST
re-authenticate under D-AUTH-1 for the new customer. `[prompt]`

---

## 3. Information disclosure

### D-INFO-1 — Scope of disclosure
The agent MAY share any information about the **authenticated user's
own** reservations, payment methods (label only, not full numbers),
and membership tier. `[prompt]`

### D-INFO-2 — Refund disclosure
On cancellation confirmation and after execution, the agent MAY (and
SHOULD per D-CONF-2):
- State the refund amount per payment method, labeled by
  `display_label` (e.g., "$1,200 to Visa ending in 4242").
- State the expected refund timeline of 5–7 business days.
The agent MUST NOT disclose the full payment method number or any
data beyond the display label. `[prompt]`

### D-INFO-3 — Policy transparency
The agent MAY explain policy rules to the customer when relevant to a
request (e.g., "I can only cancel reservations booked within 24
hours, or with covered insurance, or in business class…") but MUST
NOT cite specific numeric thresholds beyond what's in the
customer-facing policy. `[prompt]`

### D-INFO-4 — No subjective recommendation
The agent MUST NOT recommend a course of action beyond what the
policy and available tools enable. The agent may state options; it
may not opine on which is better. `[prompt]`

### D-INFO-5 — No invented facts
The agent MUST NOT provide information not present in the policy or
returnable by an action. If the customer asks something out-of-scope
(e.g., "what's the weather at JFK?"), the agent must say it does not
have that information. `[prompt]`

---

## 4. Confirmation

### D-CONF-1 — Confirmation required before mutation
The agent MUST list the proposed action's details and obtain explicit
affirmative confirmation ("yes" or unambiguous equivalent) from the
customer before invoking `cancel_reservation`. `[runtime + prompt]`

### D-CONF-2 — Cancel-specific confirmation contents and ordering
For `cancel_reservation`, the agent MUST follow this ordering:
1. Obtain the cancellation reason from the customer
   (`change_of_plan` / `airline_cancelled` / `other` — D-CONF-3).
2. Verify eligibility via `cancellable(R, Reason)` (computed from the
   data returned by `get_reservation_details` + `get_user_details`).
3. Compute per-payment refund amounts.
4. Present the confirmation message containing:
   - Reservation id + flight segments being cancelled.
   - Per-payment refund amounts (by `display_label`).
   - Expected refund timeline (5–7 business days).
   - The cancellation reason being recorded.
5. Obtain explicit "yes" (D-CONF-1) before invoking the tool.

`[prompt]`

### D-CONF-3 — Cancellation reason elicitation
The agent MUST obtain the cancellation reason from the customer before
proceeding to D-CONF-2. The reason MUST be one of
`{change_of_plan, airline_cancelled, other}` (closed enum).

If the customer states a reason outside this enum (e.g., "the weather
was bad"), the agent MAY ask whether `other` applies and whether the
customer has travel insurance covering this case. `[prompt]`

### D-CONF-4 — In-band refusal flow
When the agent determines (via reads against D₀ + Layer B's
`cancellable/2`) that a cancellation request is ineligible **and**
no flown segment is involved, the agent MUST:
1. State the specific policy reason in customer-facing terms (D-TURN-5).
2. NOT invoke `cancel_reservation` (a policy_noop task requires
   D* = D₀).
3. Offer the customer the choice to (a) acknowledge and close, or
   (b) request transfer to a human.

If the cancellation involves a flown segment, the path is **transfer
only** (D-OOS-2) — there is no in-band refusal; the agent transfers
directly per the upstream policy. `[prompt]`

### D-CONF-5 — Pre-mutation reservation lookup
Before invoking `cancel_reservation(R, _)`, the agent MUST have
called `get_reservation_details(R)` in the same conversation. The
cancellation eligibility (window, business cabin, insurance, flown
segments) cannot be computed without it. `[runtime]`

### D-CONF-6 — Idempotency in dialogue
If the customer requests cancellation on a reservation already in
`status = cancelled`, the agent MUST NOT invoke `cancel_reservation`
again. The agent MUST report the existing cancellation state to the
customer. `[runtime]`

### D-CONF-7 — Pre-mutation user lookup
Before invoking `cancel_reservation(R, _)` where the cancellation's
eligibility depends on user-scoped attributes (membership tier,
insurance status — both apply to most cancellations), the agent MUST
have called `get_user_details(U)` in the same conversation where U is
the reservation's booking user. `[runtime]`

---

## 5. Challenge requirements

### D-CHAL-1 — Insurance coverage challenge
If the customer claims their cancellation is covered by insurance
(`has_travel_insurance = true` AND policy permits `insurance_covers`
for the stated reason), but the reservation's
`has_travel_insurance` field in D₀ is false, the agent MUST surface
the inconsistency and ask the customer to clarify. The agent MUST
NOT take the customer's word over D₀. `[prompt]`

### D-CHAL-2 — Recent booking claim
If the customer claims the booking was made recently (within 24
hours) but `hours_since_creation > 24` per D₀, the agent MUST cite
the actual creation time and reject the recent-booking eligibility
argument. `[prompt]`

### D-CHAL-3 — Stated reason vs. reservation
If the customer asserts a cancellation reason that is unsupported by
the reservation's data (e.g., claims `airline_cancelled` but no
segment has `flight_status = cancelled`), the agent MUST surface the
mismatch and ask the customer to choose a reason that aligns with
the data. `[prompt]`

### D-CHAL-4 — Membership claim
If the customer asserts a membership tier that contradicts
`membership_tier(U, _)` in D₀, the agent MUST defer to D₀ and gently
correct the customer. `[prompt]`

---

## 6. Refusal vs transfer

The agent has three terminal responses to a cancellation request:
**execute** (with confirmation), **refuse** (deny in-band), or
**transfer** (hand off to human).

### D-REF-1 — Decision order
On every cancellation request, the agent MUST evaluate in order:
1. Is the request within the action surface (actions.md §1)? If no →
   D-OOS-1.
2. Is the request a flown-segment cancellation
   (`requires_transfer_for_cancellation(R)`)? If yes →
   `MUST TRANSFER` per D-OOS-2.
3. Is the agent authorized to handle it (this section + §2)? If no →
   `MUST TRANSFER`.
4. Does the policy permit the cancellation
   (`cancellable(R, Reason)`)? If no → `MUST` refuse with policy
   citation (D-REF-2).
5. Otherwise → execute with confirmation.

### D-REF-2 — In-band refusal grounds
The agent MUST refuse in-band (and not transfer, and not invoke
`cancel_reservation`) when the request fails `cancellable(R, Reason)`
AND `not requires_transfer_for_cancellation(R)`. In each refusal the
agent MUST cite the specific policy clause in customer-facing terms
(D-TURN-5) and follow the refusal flow in D-CONF-4. `[prompt]`

### D-REF-3 — Refusal authority limit
The agent MUST NOT refuse in-band on grounds outside the
`cancellable/2` predicate. If the agent suspects fraud, manipulation,
or has any other reservation not derivable from Layer B, the agent
`MUST TRANSFER`. `[prompt]`

### D-REF-4 — Customer escalation request
If the customer asks for a supervisor, a manager, or a human, the
agent `MUST TRANSFER` after one polite confirmation of the request.
`[prompt]`

### D-REF-5 — Persistence threshold
If the agent has refused a cancellation request twice (with policy
citation) and the customer continues to insist, the agent
`MUST TRANSFER` on the third request. `[prompt]`

### D-REF-6 — Transfer message
On transfer, the agent MUST invoke `transfer_to_human_agents(reason_label)`
and then send the customer-facing message:
```
"I'm transferring you to a human agent. Please hold on."
```
No additional content after that message. `[runtime + prompt]`

---

## 7. Out-of-scope handling

### D-OOS-1 — Outside the action surface
Requests not expressible via any action in
[`actions.md`](actions.md) §1 `MUST TRANSFER` after acknowledgement.
For the cancellation slice, common out-of-scope cases include:
- Booking a new flight.
- Searching flights.
- Modifying an existing reservation (flights / cabin / baggage /
  passengers).
- Offering compensation (deferred to a separate slice).
- Tracking baggage / flight status changes beyond what
  `get_reservation_details` returns.

`[prompt]`

### D-OOS-2 — Flown-segment cancellation
**The most consequential airline-specific rule.** If
`requires_transfer_for_cancellation(R) = true` (any segment of `R`
has `flight_status ∈ {flying, landed}`), the agent
`MUST TRANSFER` with `reason_label = "flown_segment_cannot_cancel"`.
The agent MUST NOT attempt in-band refusal in this case — the upstream
policy explicitly requires transfer.

```
:- target_reservation(R), requires_transfer_for_cancellation(R),
   action_invoked(cancel_reservation).
```

`[runtime + prompt]`

---

## 8. Conversation conduct

### D-TURN-1 — One tool call OR one customer message per turn
Each agent turn MUST be either (a) a single tool call with no
customer-facing text, or (b) a single customer-facing message with
no tool call. Never both. `[runtime]`

### D-TURN-2 — No volunteering
The agent MUST NOT volunteer information the customer did not ask
for and the policy does not require disclosing. Specifically, the
agent MUST NOT proactively offer compensation. (Compensation is
its own action; the customer must ask for it.) `[prompt]`

### D-TURN-3 — Clarification before action
If the customer's request is ambiguous (e.g., they mention "my
reservation" but have multiple active reservations), the agent MUST
ask a clarifying question before invoking any tool. `[prompt]`

### D-TURN-5 — Stating policy in customer terms
When citing policy, the agent MUST use plain language, not internal
rule IDs or predicate names. ("I can only cancel a reservation
that's within 24 hours of booking, or where the airline cancelled
the flight, or for a business-class fare, or with insurance" — not
"`cancellable/2` fails: not `recent_booking`, not
`has_airline_cancelled_segment`, etc.") `[prompt]`

---

## 9. The agent state machine (informal)

```
                ┌─────────────────────┐
                │   1. UNAUTH         │
                │   awaiting customer │
                │   identification    │
                └──────────┬──────────┘
                           │ user_id obtained / resolvable
                           ▼
                ┌─────────────────────┐
                │   2. AUTH'D         │
                │   awaiting intent   │
                └──────────┬──────────┘
                           │ "I want to cancel reservation R"
                           ▼
              ┌──────────────────────────┐
              │  3. INFO GATHERING        │
              │  read user + reservation, │
              │  obtain cancellation_reason,│
              │  compute eligibility       │
              └──────────┬───────────────┘
                         │
              ┌──────────┴──────────┐──────────┐
              ▼                     ▼          ▼
  ┌────────────────────┐   ┌──────────────┐ ┌──────────────────┐
  │ 4a. PROPOSING      │   │ 4b. REFUSAL  │ │ 4c. TRANSFER     │
  │ cancel + refund    │   │ in-band      │ │ flown segment    │
  │ details, awaiting  │   │ (cancellable │ │ (or escalation)  │
  │ confirmation       │   │ = false)     │ │                  │
  └─────────┬──────────┘   └────────┬─────┘ └────────┬─────────┘
            │ "yes"           ┌─────┴─────┐          │
            ▼                 │ "ok"      │ insist x3│
  ┌────────────────────┐      ▼           ▼          ▼
  │ 5a. EXECUTED       │  ┌────────┐  ┌──────────┐  (terminal)
  │ cancel_reservation │  │ 5c.    │  │ 5b.      │
  │ fired              │  │ CLOSED │  │ TRANSFER │
  └────────────────────┘  │ (no    │  │          │
                          │ tool)  │  └──────────┘
                          └────────┘
```

Aid only; the normative content is the rule set in §2–§8.

---

## 10. Mapping rules to test trajectories

Each runtime-checkable rule has a corresponding failure pattern:

| Rule | Failure pattern |
|---|---|
| D-AUTH-1 | Tool call to customer-scoped action before user_id obtained. |
| D-CONF-1 | `cancel_reservation` invocation with no immediately-prior "yes". |
| D-CONF-5 | `cancel_reservation(R, _)` without prior `get_reservation_details(R)` in the same conversation. |
| D-CONF-7 | `cancel_reservation(R, _)` without prior `get_user_details(U)` where U = booking_user(R). |
| D-OOS-2 | `cancel_reservation(R, _)` invocation when `requires_transfer_for_cancellation(R) = true`. |
| D-REF-6 | Transfer message text differs from the mandated string. |
| D-TURN-1 | Agent turn contains both tool call and customer-facing text. |

LLM-graded rules supply the trajectory to a judge model along with
the rule body and an instruction to flag violations.

---

## 11. Open questions for E/F

**Q-D-A1. The single-payment v0 simplification (from
[`actions.md`](actions.md) §4.2).** Layer F's first retrofitted task
will use a single-payment reservation. Multi-payment refund
allocation is deferred — the encoder will refuse to encode
multi-payment reservations until v1.

**Q-D-A2. Strictness of D-CONF-1 "explicit yes".** Same question as
retail_returns Q-D-1. v0 default: small accepted vocabulary
{yes, yeah, yep, confirm, please go ahead, do it}; strict otherwise.

**Q-D-A3. Persistence threshold calibration (D-REF-5).** Same as
retail_returns Q-D-2. v0: 3.

**Q-D-A4. Transfer reason vocabulary.** The `reason_label` parameter
on `transfer_to_human_agents` is a closed enumeration for cancellation:
{`flown_segment_cannot_cancel`, `customer_escalation_request`,
`out_of_action_surface`}. Other slices will add labels.

---

## 12. Status

- **2026-05-29** — initial Layer D draft, cancellation slice only.
  6 Q-C-A questions resolved (§0). 27 deontic rules across §2–§8.
  Agent state machine sketch (§9). Trajectory-failure mapping (§10).
  4 questions surfaced for Layer E/F (§11).

The most consequential airline-specific rule is **D-OOS-2** — flown
segments force transfer, not in-band refusal. This is a real
deviation from retail_returns' uniform refusal pattern and reflects
the upstream policy text directly.

Booking, search, modification (flights / cabin / baggage / passengers),
and compensation deontic rules remain TODO. They will be added in
subsequent Layer D sessions as their corresponding Layer C actions
come online.
