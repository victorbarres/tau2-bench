# Library — Actions (Layer C)

## 1. Action surface

| Action | Read or mutate | Used to |
|---|---|---|
| `get_borrower_details(B)` | read | Look up a borrower and their active-loan count. |
| `get_book_details(K)` | read | Look up a book's title and copy availability. |
| `borrow_book(B, K)` | mutate | Create a new active Loan; refused if `can_borrow(B, K)` is false. |

Three actions. That's the entire agent-facing tool surface.

## 2. `borrow_book(borrower_id, book_id)`

**Signature**:
- `borrower_id` — existing borrower.
- `book_id` — existing book.

**Preconditions**:
- `borrower(borrower_id)` exists.
- `book(book_id)` exists.
- `can_borrow(borrower_id, book_id)` (rules.md §3.4).

**Effects**:
- Allocate a fresh `loan_id`.
- Insert a new Loan with that id, the two ids, and `status = active`.

**Failure mode**: if `can_borrow/2` fails, the action returns an error
with one of two reasons:
- `borrower_at_loan_cap` — the borrower already has 3 active loans.
- `no_available_copies` — the book has 0 copies free.

## 3. ASP encoding pattern (for Verify)

The same two-snapshot pattern as the other domains. For the
`borrow_book(B, K)` task encoding:

```asp
% Pin the target borrower/book from intent.
target_borrow(B, K).

% Precondition: must be permitted by Layer B.
:- target_borrow(B, K), not can_borrow(B, K).
```

If the precondition fails: 0 models = task should be refused. If it
succeeds: exactly 1 model = `borrow_book` may fire.

There's no choice surface here — once the borrower and book are
pinned by `intent`, the action is fully determined.
