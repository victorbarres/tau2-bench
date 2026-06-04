# Library — World Rules (Layer B)

The integrity constraints and derivations that give the library
ontology its semantics. Cancellation-slice of the methodology applied
to the smallest non-trivial domain.

## 1. ASP encoding conventions

Same as the other domains. Predicates are lowercase snake_case;
attributes are 2-ary predicates (`borrower_name(B, "Alice")`,
`total_copies(K, 2)`).

## 2. Integrity constraints

- **C-CARD-1.** No borrower has more than `max_active_loans_per_borrower`
  active loans:
  ```
  :- borrower(B),
     #count{ L : loan_borrower(L, B), loan_status(L, active) } > 3.
  ```

- **C-CARD-2.** No book has more active loans than copies:
  ```
  :- book(K), total_copies(K, T),
     #count{ L : loan_book(L, K), loan_status(L, active) } > T.
  ```

- **C-REF-1.** Every loan references an existing borrower and book:
  ```
  :- loan_borrower(L, B), not borrower(B).
  :- loan_book(L, K), not book(K).
  ```

That's it. Three integrity constraints carry the policy at the world
level.

## 3. Derivation rules

### 3.1 `active_loan_count(B, N)`

```
active_loan_count(B, N) :-
  borrower(B),
  N = #count{ L : loan_borrower(L, B), loan_status(L, active) }.
```

### 3.2 `available_copies(K, N)`

```
active_against(K, M) :-
  book(K),
  M = #count{ L : loan_book(L, K), loan_status(L, active) }.

available_copies(K, N) :-
  book(K),
  total_copies(K, T),
  active_against(K, M),
  N = T - M.
```

### 3.3 `has_available_copy(K)`

```
has_available_copy(K) :- available_copies(K, N), N >= 1.
```

### 3.4 `can_borrow(B, K)`

The composite predicate. Both conditions must hold:

```
can_borrow(B, K) :-
  borrower(B),
  book(K),
  active_loan_count(B, N),
  N < 3,
  has_available_copy(K).
```

## 4. Worked micro-example

Suppose D₀ contains:
- One borrower `alice` with 0 active loans.
- One book `hamlet` with `total_copies = 2`, 0 active loans against it.

Derived predicates:

| Predicate | Value |
|---|---|
| `active_loan_count(alice, _)` | 0 |
| `active_against(hamlet, _)` | 0 |
| `available_copies(hamlet, _)` | 2 |
| `has_available_copy(hamlet)` | true |
| `can_borrow(alice, hamlet)` | **true** |

Suppose instead `bob` has 3 active loans (he's at the cap).
`active_loan_count(bob, 3)`. `can_borrow(bob, _)` requires `N < 3`;
this fails. **Refused** for any book, regardless of availability.

That's the entire library policy.

## 5. Open questions for Layer C

None for this micro-world. The action surface is so small there are no
ambiguities to resolve.
