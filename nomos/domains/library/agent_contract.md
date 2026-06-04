# Library — Agent Contract (Layer D)

For the tutorial domain we keep Layer D minimal — just enough to
illustrate the deontic-vs-state separation.

## D-AUTH-1 — Borrower identification required

The agent MUST obtain the `borrower_id` before invoking any
borrower-scoped action. `[runtime]`

## D-CONF-1 — Confirmation before borrow

The agent MUST list the borrow request (borrower + book title) and
obtain "yes" before invoking `borrow_book`. `[runtime + prompt]`

## D-REF-1 — In-band refusal grounds

The agent MUST refuse in-band (no transfer needed) when `can_borrow/2`
fails. The refusal message MUST cite the specific reason:
- `borrower_at_loan_cap` — "You've reached the 3-book limit. Please
  return a book before borrowing another."
- `no_available_copies` — "All copies of this title are checked out."
`[prompt]`

That's it. Three deontic rules. The other 35+ rules from the
retail/airline contracts (identity verification, disclosure scope,
challenge requirements, transfer logic, etc.) don't apply to a
library micro-world without sensitive customer data, payment methods,
or escalation paths.

## What this micro-world deliberately doesn't model

- Privacy / identity verification — borrower IDs are public-equivalent.
- Information disclosure rules — library catalogs are public.
- Challenge requirements — no adversarial customer narrative to push
  back on.
- Transfer to human — there's nothing the agent can't handle.

These are real concerns in retail/airline; they're absent here because
the methodology is general enough to scale up to them but doesn't
require them in every domain.
