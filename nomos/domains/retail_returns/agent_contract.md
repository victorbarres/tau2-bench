# Retail Returns & Refunds — Agent Contract (Layer D)

This is **Layer D** of the logic-first design described in
[`docs/methodology.md`](../../docs/methodology.md). It
declares the **deontic layer**: what the agent must, may, must not, and may
transfer-instead-of-act under various conditions.

Layer D is where the *agent* behavior is constrained. Layer B
([`rules.md`](rules.md)) constrains what the *world* can be; Layer C
([`actions.md`](actions.md)) constrains how the world *transitions*; Layer D
constrains what the *agent* can do when interacting with a customer.

A consequence: rules in this layer are mostly **not** machine-checkable as
state invariants. They are checkable against an *agent trajectory*: a
sequence of (customer turn, agent message, tool call) tuples. Some Layer D
rules compile down to runtime checks (e.g., "must call `get_order_details`
before `initiate_return`"); others are dialogue-shape rules that get
rendered into the agent's system prompt and evaluated by an LLM judge during
benchmark grading.

---

## 0. Resolved Layer C questions

The 6 open questions from [`actions.md`](actions.md) §8 are resolved as
follows:

| Q | Resolution |
|---|---|
| **Q-C-1** Approve confirmation | Always required. Agent must list refund method + total amount and obtain explicit "yes" before invoking `approve_return`. Codified as D-CONF-2. |
| **Q-C-2** Refusal authority | With `reject_return` removed from the action surface ([`actions.md`](actions.md) §0), refusal is a **dialogue act**, not a tool call. Agent may refuse in-band on the three policy-derivable grounds (window, returnability, initiator eligibility) — Layer C precondition for `initiate_return` is left structural-only; the agent must not invoke `initiate_return` on ineligible requests. Codified as D-REF-2 and D-REF-3. |
| **Q-C-3** Required reads | Explicit. `get_order_details` is required before any mutation on that Order (D-CONF-5). `get_customer_details` is required before any mutation involving customer-scoped data (D-CONF-7). |
| **Q-C-4** Refund method when customer silent | Agent must re-ask. May not pick a default. Codified as D-CONF-3. |
| **Q-C-5** Mixed-intent returns | Agent must split into two interactions or transfer if the customer insists on doing it as one. Codified as D-OOS-2. |
| **Q-C-6** Idempotency | If the same mutation is requested again on a terminal-state Return, agent reports the existing state and does not re-invoke. Codified as D-CONF-6. |

---

## 1. Deontic vocabulary

Each rule uses one of four normative force levels:

| Marker | Meaning |
|---|---|
| **MUST** | The agent is required to do this. Violation = test failure. |
| **MAY** | The agent is permitted to do this. Not required. |
| **MUST NOT** | The agent is forbidden from doing this. Doing it = test failure. |
| **MUST TRANSFER** | The agent is forbidden from handling this in-band and must invoke `transfer_to_human_agent` (per actions.md §5.1). |

Encoding column on each rule notes the form: `[runtime]` for rules
mechanically checkable against the agent trajectory, `[prompt]` for rules
that live in the agent's system prompt and are LLM-graded, `[both]` for
rules with both forms.

---

## 2. Authentication

### D-AUTH-1 — Customer identification required before any read of customer-scoped data
The agent MUST obtain the customer's `customer_id` (or a unique identifier
the agent can resolve to a single `customer_id` via lookup — e.g., email)
before calling any of `get_customer_details`, `get_return_details`,
`search_customer_orders`, or any mutating action. `[runtime]`

### D-AUTH-2 — No identity transitivity
The agent MUST NOT accept a customer's claim to be acting on behalf of
another customer. A purchaser cannot return a gift on the recipient's behalf
without the recipient being on the line; a recipient cannot modify the
purchaser's data. `[prompt]`

**Encoding hook**: combined with C-MP-1 (rules.md §2.3), the runtime check
is `return_initiator(R, claimed_customer_id) = effective_returner(order)`.

### D-AUTH-3 — Verify identity before disclosing
The agent MUST verify the claimed customer identity by cross-referencing at
least one piece of independent information (e.g., order id, email, name)
before sharing any customer-specific data. `[prompt]`

### D-AUTH-4 — Re-authentication on customer change
If the conversation pivots to a different customer (e.g., "I'm calling on
behalf of my daughter"), the agent MUST re-authenticate under D-AUTH-1 for
the new customer. `[prompt]`

---

## 3. Information disclosure

### D-INFO-1 — Scope of disclosure
The agent MAY share any information about the **authenticated customer's
own** orders, returns, payment methods (label only, not full numbers), and
store credit balance. `[prompt]`

### D-INFO-2 — Cross-customer privacy
The agent MUST NOT disclose another customer's data. In a gift return
context: the agent MAY confirm to the recipient that a gift was sent (date,
sender first name), but MUST NOT disclose the purchaser's payment method,
address, contact information, or other order history. `[prompt]`

### D-INFO-3 — Policy transparency
The agent MAY explain policy rules to the customer when relevant to a
request, but MUST NOT cite specific numeric thresholds unless they're
already stated in the customer-facing policy document. (Avoid leaking
internal-only constants.) `[prompt]`

### D-INFO-4 — No subjective recommendation
The agent MUST NOT recommend a course of action beyond what the policy and
available tools enable. The agent may state what options are available; it
may not opine on which is better. `[prompt]`

### D-INFO-5 — No invented facts
The agent MUST NOT provide information not present in the policy document or
returnable by an action. If the customer asks something out-of-scope (e.g.,
"when will my replacement arrive?"), the agent must say it does not have
that information. `[prompt]`

---

## 4. Confirmation

### D-CONF-1 — Confirmation required before any mutation
The agent MUST list the proposed action's details and obtain explicit
affirmative confirmation ("yes" or unambiguous equivalent) from the customer
before invoking any mutating action (`initiate_return`, `approve_return`,
`cancel_return`). `[runtime + prompt]`

### D-CONF-2 — Approve-specific confirmation contents and ordering
For `approve_return`, the agent MUST follow this ordering:
1. Determine the refund method (per D-CONF-3 if multiple are eligible).
2. Compute the total refund amount given that method (the amount depends on
   the method via restocking-fee logic — see [`rules.md`](rules.md) §3.7
   and §3.8).
3. Present the confirmation message containing:
   - The list of items being returned (with quantities).
   - The chosen refund method.
   - The total refund amount in dollars and cents.
   - For exchanges: the SKU of the replacement.
4. Obtain explicit "yes" (D-CONF-1) before invoking the tool.

`[prompt]`

### D-CONF-3 — Refund method elicitation
When more than one refund method is in `eligible_refund_methods(R, _)`, the
agent MUST present all options and ask the customer to choose. The agent
MUST NOT pick a default. If the customer is non-committal, the agent MUST
re-ask. `[prompt]`

### D-CONF-4 — In-band refusal flow
When the agent determines (via reads against `D₀` + the eligibility
predicates in [`rules.md`](rules.md) §3 and §4) that a requested return is
ineligible, the agent MUST:
1. State the specific policy reason in customer-facing terms (D-TURN-5).
2. NOT invoke `initiate_return` (since policy_noop tasks require
   `D* = D₀`; creating a pending Return would diverge from this).
3. Offer the customer the choice to (a) acknowledge the refusal and close,
   or (b) request transfer to a human.

If the customer chooses (a): the conversation closes with no tool calls.
If the customer chooses (b): `MUST TRANSFER` per D-REF-6. `[prompt]`

### D-CONF-5 — Pre-mutation lookup
Before invoking any mutating action on an Order, the agent MUST have called
`get_order_details(order_id)` in the same conversation (the agent cannot
mutate state it has not read). `[runtime]`

### D-CONF-6 — Idempotency in dialogue
If the customer requests a mutation that has already been performed on a
Return (Return is in a terminal state), the agent MUST NOT invoke the action
again. The agent MUST report the existing state to the customer. `[runtime]`

### D-CONF-7 — Pre-mutation customer lookup
Before invoking any mutating action that depends on customer-scoped data
(member tier for window selection, store credit balance for refund target,
payment-method ownership), the agent MUST have called
`get_customer_details(customer_id)` in the same conversation. Combined with
D-CONF-5, this guarantees the agent has both the order context and the
customer context before mutating. `[runtime]`

---

## 5. Challenge requirements

Cases where the agent is required to push back on a customer claim before
proceeding.

### D-CHAL-1 — Reason/condition coherence (O6)
When the customer's declared `return_reason` and declared `item_condition`
are mutually incoherent, the agent MUST surface the inconsistency and ask
the customer to clarify before invoking `initiate_return`. Examples of
incoherent pairs:
- `change_of_mind` + `defective`
- `change_of_mind` + `damaged_in_shipping`
- `defective` + `new_unopened` (defective claim without ever opening the
  item is implausible)
- `wrong_item_received` + `used`

`[prompt]`

### D-CHAL-2 — Defective claim challenge
When the customer declares `defective` (which extends the window to 365
days), the agent MUST ask for a brief description of the defect before
proceeding. The agent need not validate the description against any
external source — the challenge is a discoverability check, not a
verification step. `[prompt]`

### D-CHAL-3 — Stated-date vs. order-date mismatch
If the customer asserts a purchase date (or delivery date) that materially
contradicts the Order record (off by more than a day or two), the agent MUST
clarify which is correct before proceeding. `[prompt]`

### D-CHAL-4 — Membership claim
If the customer asserts a membership tier (e.g., "I'm a Plus member") that
contradicts `member_tier(C, _)` in the DB, the agent MUST defer to the DB
and gently correct the customer. `[prompt]`

### D-CHAL-5 — Quantity overrun
If the customer requests a return quantity that exceeds the unreturned
remainder on an OrderItem, the agent MUST surface the discrepancy (citing
the remainder) and ask the customer to amend before proceeding. `[runtime]`

---

## 6. Refusal vs transfer

The agent has three terminal responses to a request: **execute** (with
confirmation), **refuse** (deny in-band, conversation continues or closes),
or **transfer** (hand off to human).

### D-REF-1 — Decision order
On every customer request, the agent MUST evaluate in order:
1. Is the request within the action surface (actions.md §1)? If no →
   D-OOS-1.
2. Is the agent authorized to handle it (this section + §2)? If no →
   `MUST TRANSFER`.
3. Does the policy permit the requested mutation (Layer B + C
   preconditions)? If no → `MUST` refuse with policy citation (D-REF-2).
4. Otherwise → execute with confirmation.

### D-REF-2 — In-band refusal grounds
The agent MUST refuse in-band (and not transfer, and not invoke
`initiate_return`) when the request fails one of the following Layer B
eligibility predicates and the failure is unambiguous:
- `not within_window(R_hypothetical)` — outside the applicable return window.
- `not return_class_returnable(P)` — product class is non-returnable (final
  sale, digital, hazmat).
- `not eligible_to_initiate(C, O)` — customer is not the order's purchaser
  or recipient.

Eligibility is evaluated against the **prospective** return shape (i.e.,
what the Return record *would* contain), computed by the agent from the
customer's request + the data returned by `get_order_details`,
`get_product_details`, and `get_customer_details`. The agent MUST NOT call
`initiate_return` to "test" eligibility — it is a precondition of calling
`initiate_return` that eligibility holds. In each refusal the agent MUST
cite the specific policy clause in customer-facing terms (D-TURN-5) and
follow the refusal flow in D-CONF-4. `[prompt]`

### D-REF-3 — Refusal authority limit (Q-C-2)
The agent MUST NOT refuse a return in-band on grounds outside D-REF-2. If
the agent suspects fraud, manipulation, or has any other reservation not
derivable from the three policy-listed predicates, the agent
`MUST TRANSFER` instead. (Refusal in-band asserts that policy *clearly*
forbids the request; transfer asserts that the case is *too ambiguous* for
the agent to decide.) `[prompt]`

### D-REF-4 — Customer escalation request
If the customer asks for a supervisor, a manager, or a human, the agent
`MUST TRANSFER` after one polite confirmation of the request. `[prompt]`

### D-REF-5 — Persistence threshold
If the agent has refused a request twice (with policy citation) and the
customer continues to insist, the agent `MUST TRANSFER` on the third
request. The customer is not refused a path forward; they're handed to a
human. `[prompt]`

### D-REF-6 — Transfer message
On transfer, the agent MUST invoke `transfer_to_human_agent(reason)` and
then send the customer-facing message:
```
"I'm transferring you to a human agent. Please hold on."
```
No additional content after that message. `[runtime + prompt]`

---

## 7. Out-of-scope handling

### D-OOS-1 — Outside the action surface
Requests that are not expressible via any action in actions.md §1
`MUST TRANSFER` after the agent acknowledges what was asked. Common cases:
- Placing a new (non-exchange) order.
- Browsing the catalog.
- Address changes, shipment tracking, delivery time inquiries.
- Disputing a charge (chargeback) — separate from a return.
- Reporting suspected fraud.

`[prompt]`

### D-OOS-2 — Mixed-intent returns (Q-C-5)
If the customer wants to refund some items and exchange others on the same
Order, the agent MUST explain that these must be handled as two separate
returns (one per `refund_method`), then either:
- Invite the customer to choose one to handle in this interaction and
  proceed, or
- If the customer insists on one combined action, `MUST TRANSFER`.

`[prompt]`

### D-OOS-3 — Refund to closed payment method on a gift order
When a gift return is requested and the original payment method is closed
(or the purchaser's consent would otherwise be needed for an alternative),
the agent `MUST TRANSFER`. The recipient cannot override the purchaser's
payment-method decision. `[prompt]`

### D-OOS-4 — Hazmat products
Products with `return_class = hazmat` are non-returnable in v0 (per
rules.md §3.4 and the ontology), but if a customer specifically requests
hazmat disposal handling, the agent `MUST TRANSFER`. `[prompt]`

---

## 8. Conversation conduct

### D-TURN-1 — One tool call OR one customer message per turn
Each agent turn MUST be either (a) a single tool call with no
customer-facing text, or (b) a single customer-facing message with no tool
call. Never both. `[runtime]`

### D-TURN-2 — No volunteering
The agent MUST NOT volunteer information the customer did not ask for and
the policy does not require disclosing. Specifically, the agent MUST NOT
proactively offer compensation, promotions, or alternative products that
were not requested. (Mirrors airline's compensation rule by spirit.)
`[prompt]`

### D-TURN-3 — Clarification before action
If the customer's request is ambiguous, the agent MUST ask a clarifying
question before invoking any tool. `[prompt]`

### D-TURN-4 — One thing at a time
The agent MUST NOT bundle multiple distinct requests into a single dialogue
move ("I'll cancel return A and initiate return B"). Each mutating action
gets its own confirmation cycle. `[prompt]` (Follows from §6 "one mutating
action per task" in actions.md.)

### D-TURN-5 — Stating policy in customer terms
When citing policy, the agent MUST use plain language, not internal rule
IDs. ("Returns must be initiated within 30 days of delivery" — not "rule
applicable_window_days fired with value 30".) `[prompt]`

---

## 9. The agent state machine (informal)

For readability, the agent's flow through a typical interaction. Each box
is an agent state; transitions are customer messages / tool results.

```
                ┌─────────────────────┐
                │   1. UNAUTH         │
                │   awaiting customer │
                │   identification    │
                └──────────┬──────────┘
                           │ customer_id or resolvable identifier
                           ▼
                ┌─────────────────────┐
                │   2. AUTH'D         │
                │   awaiting intent   │
                └──────────┬──────────┘
                           │ intent stated
                           ▼
              ┌──────────────────────┐
              │  3. INFO GATHERING   │
              │  reading orders,     │
              │  challenging,        │
              │  clarifying          │
              └──────────┬───────────┘
                         │
              ┌──────────┴──────────┐
              ▼                     ▼
  ┌────────────────────┐   ┌──────────────────┐
  │ 4a. PROPOSING      │   │ 4b. REFUSAL      │
  │ mutation, awaiting │   │ citing policy,   │
  │ confirmation       │   │ awaiting close   │
  └─────────┬──────────┘   └────────┬─────────┘
            │ "yes"           ┌─────┴─────┐
            ▼                 │ "ok"      │ insist x3
  ┌────────────────────┐      ▼           ▼
  │ 5a. EXECUTED       │  ┌────────┐  ┌──────────┐
  │ tool fired,        │  │ 5c.    │  │ 5b.      │
  │ confirmed to user  │  │ CLOSED │  │ TRANSFER │
  └────────────────────┘  │ (no    │  │ (term)   │
                          │ tool)  │  └──────────┘
                          └────────┘
```

This diagram is not normative; it's an aid for understanding how the rules
in §2–§8 compose. The normative content is the rule set.

---

## 10. Mapping rules to test trajectories

Each rule has a corresponding *failure pattern* in an agent trajectory:

| Rule | Failure pattern |
|---|---|
| D-AUTH-1 | Tool call to customer-scoped action before identifier obtained. |
| D-CONF-1 | Mutating tool call with no immediately-prior "yes" from customer. |
| D-CONF-2 | Mutating `approve_return` tool call whose preceding agent message lacks refund method + amount. |
| D-CONF-5 | `initiate_return` / `approve_return` / `cancel_return` without prior `get_order_details` for the same order_id. |
| D-CONF-7 | Mutating action without prior `get_customer_details` for the affected customer. |
| D-CHAL-1 | `initiate_return` with incoherent reason/condition pair on any ReturnItem. |
| D-REF-2 | `initiate_return` invocation whose hypothetical Return would fail `return_eligible` (agent should have refused in-band instead). |
| D-REF-3 | Refusal cited with a non-policy reason; agent did not transfer. |
| D-REF-6 | Transfer with text content other than the exact mandated string. |
| D-TURN-1 | Agent turn contains both tool call and customer-facing text. |

For LLM-graded rules (`[prompt]`), the test framework supplies the trajectory
to a judge model along with the rule body and an instruction to flag
violations.

---

## 11. Open questions for Layer E/F

Surfaced while writing Layer D.

**Q-D-1. Strictness of D-CONF-1 "explicit yes".** Does "sure", "ok",
"please go ahead", "do it", etc. all count? Need a published list of
affirmative tokens that the runtime check accepts. v0 default: small list,
strict. Layer F will exercise edge cases.

**Q-D-2. Persistence threshold (D-REF-5) calibration.** "Twice with citation,
transfer on third" — is three the right number? v0 default: yes. Tasks
should test this boundary.

**Q-D-3. Membership of "incoherent" pairs (D-CHAL-1).** The four enumerated
pairs in D-CHAL-1 may not be exhaustive. Should this be a closed list, or a
judge-graded "obviously incoherent" check? v0 default: enumerated. Tasks
may surface missing pairs.

**Q-D-4. Disclosure thresholds for gift orders (D-INFO-2).** "Sender's first
name and date" — is that the right boundary? Need to confirm with the F
tasks that test gift flows.

**Q-D-5. Re-authentication scope (D-AUTH-4).** When does "the conversation
pivots to a different customer" trigger? If a recipient says "my mother
bought this for me", is the agent now talking to a different customer? v0
default: only if the agent is about to access *other-customer-scoped* data,
re-auth is needed. Otherwise the gift-return flow handles it.

**Q-D-6. Transfer reason vocabulary.** The `transfer_to_human_agent` action
takes a `reason: string`. Is this enumerated, or free text? v0 default: a
short controlled vocabulary, e.g., `customer_escalation_request`,
`out_of_action_surface`, `mixed_intent_refused`, `gift_purchaser_consent_needed`,
`hazmat_disposal`. To be finalized when F tasks are written.

---

## 12. Status

- **2026-05-24** — initial Layer D draft. All 6 Q-C questions resolved (§0).
  37 deontic rules across 7 sections (§2–§8). Agent state machine sketch
  (§9). Trajectory-failure mapping (§10). 6 questions surfaced for Layer
  E/F (§11).
- **2026-05-26** — reconciliation pass. `reject_return` cascade (see
  actions.md §0): Q-C-2 / D-REF-2 / D-REF-3 reframed as in-band dialogue
  refusal; D-CONF-1 mutating-action list trimmed; D-CONF-4 rewritten as
  in-band refusal flow; §9 state machine updated to add the "closed without
  tool" terminal. Q-C-3 cleanly resolved: D-CONF-7 added requiring
  `get_customer_details` before customer-scoped mutations. D-CONF-2
  tightened to specify the four-step ordering. Total rules: 37 → 38.

With Layer D drafted, the **policy** part of the domain is complete. Layers
E (instantiation) and F (tasks) are about giving the policy something to
operate on.
