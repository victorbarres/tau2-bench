# Library — Ontology (Layer A)

The tutorial micro-world. Minimal enough to be held in one head; rich
enough to demonstrate Verify, Solve, and Generate end-to-end.

A library lends physical Books to Borrowers. Loans track who has what.
The agent's job is to process borrow requests.

## 1. Sorts

| Sort | Description | Identifier |
|---|---|---|
| **Borrower** | A library member. | `borrower_id` |
| **Book** | A title with a stock of physical copies. | `book_id` |
| **Loan** | One Borrower currently holding one copy of one Book. | `loan_id` |

## 2. Closed enumerations

### 2.1 `loan_status` (on Loan)
- `active` — book is currently checked out.
- `returned` — book has been returned.

(That's it. No `overdue` in this micro-world — we don't model time.)

## 3. Attributes

### 3.1 Borrower
- `borrower_id` (id)
- `name` (string)

### 3.2 Book
- `book_id` (id)
- `title` (string)
- `total_copies` (int, ≥ 1)

### 3.3 Loan
- `loan_id` (id)
- `borrower_id` (Borrower id)
- `book_id` (Book id)
- `status` (enum, §2.1)

## 4. Numeric constants

| Symbol | Value |
|---|---|
| `max_active_loans_per_borrower` | 3 |

## 5. Derived predicates (defined in Layer B)

| Predicate | Arity | Intuition |
|---|---|---|
| `active_loan_count(B, N)` | 2 | Number of active loans the borrower currently holds. |
| `available_copies(K, N)` | 2 | Total copies of book K minus active loans against it. |
| `has_available_copy(K)` | 1 | True iff at least one copy of K is available. |
| `can_borrow(B, K)` | 2 | True iff borrower B may currently borrow book K. |

## 6. Out of scope

- Time / due dates / overdue logic.
- Holds, reservations, transfers between branches.
- Lost-or-damaged books.
- Multiple Borrower tiers (everyone is a regular member).

Six sorts/concepts in total. The whole domain fits on one page; that's
the point.
