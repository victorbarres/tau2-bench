#!/usr/bin/env python3
"""
Tutorial verifier for the library micro-world.

Demonstrates the same Verify / Solve pattern as the retail_returns and
airline verifiers, but on a domain small enough to read in 5 minutes.
Three tasks: one happy-path borrow + two refusals (loan cap, no copies).

Run:
  uv run python tools/library_verify.py
"""

from __future__ import annotations

import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import clingo

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "library"
DB_PATH = DOMAIN_DIR / "db.json"
RULES_PATH = DOMAIN_DIR / "rules.md"
TASKS_PATH = DOMAIN_DIR / "tasks.json"

# Reuse the rule extractor — it's domain-agnostic.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clingo_verify import extract_asp_from_rules_md, asp_atom  # noqa: E402


# ============================================================================
# 1. Encode the DB as ASP facts
# ============================================================================


def encode_db(db: dict) -> str:
    """JSON DB → ASP ground facts matching the predicate names in rules.md."""
    lines: list[str] = []
    for cid in db["borrowers"]:
        lines.append(asp_atom("borrower", cid))
    for kid, k in db["books"].items():
        lines.append(asp_atom("book", kid))
        lines.append(asp_atom("total_copies", kid, k["total_copies"]))
    for lid, l in db["loans"].items():
        lines.append(asp_atom("loan", lid))
        lines.append(asp_atom("loan_borrower", lid, l["borrower_id"]))
        lines.append(asp_atom("loan_book", lid, l["book_id"]))
        lines.append(asp_atom("loan_status", lid, l["status"]))
    return "\n".join(lines)


# ============================================================================
# 2. Encode a task as an ASP fragment
# ============================================================================


@dataclass
class TaskEncoding:
    """Per-task encoding: action rules + identifiers needed by Solve."""
    task_id: str
    task_class: str
    family: str  # 'borrow' | 'noop'
    action_rules: str
    target_borrower: str | None = None
    target_book: str | None = None


def encode_task(task: dict) -> TaskEncoding:
    """Read operational_spec.intent and produce a TaskEncoding."""
    tid = task["id"]
    spec = task["operational_spec"]
    klass = spec["task_class"]
    intent = spec.get("intent", {})
    action = intent.get("action", "none")

    if action == "none":
        return TaskEncoding(
            task_id=tid, task_class=klass, family="noop",
            action_rules="",
        )

    if action == "borrow_book":
        b = intent["borrower_id"]
        k = intent["book_id"]
        action_rules = f"""
target_borrow({b}, {k}).

% Action precondition: must be permitted by Layer B's can_borrow/2.
:- target_borrow(B, K), not can_borrow(B, K).

% Expose for inspection.
#show target_borrow/2.
#show can_borrow/2.
#show active_loan_count/2.
#show available_copies/2.
"""
        return TaskEncoding(
            task_id=tid, task_class=klass, family="borrow",
            action_rules=action_rules,
            target_borrower=b, target_book=k,
        )

    raise ValueError(f"unknown intent action: {action!r}")


# ============================================================================
# 3. Solve via Clingo
# ============================================================================


def solve_clingo(programs: list[str], max_models: int = 2) -> list[list[str]]:
    """Run Clingo on the listed programs; return shown atoms per model."""
    ctl = clingo.Control([f"--models={max_models}", "--warn=no-atom-undefined"])
    for i, prog in enumerate(programs):
        ctl.add(f"base_{i}", [], prog)
    ctl.ground([(f"base_{i}", []) for i in range(len(programs))])

    models: list[list[str]] = []

    def on_model(m: clingo.Model) -> bool:
        """Collect this answer set's shown atoms; continue enumerating."""
        atoms = [str(s) for s in m.symbols(shown=True)]
        models.append(sorted(atoms))
        return True

    ctl.solve(on_model=on_model)
    return models


# ============================================================================
# 4. Verify
# ============================================================================


@dataclass
class TaskResult:
    """Outcome of running Verify on one task."""
    task_id: str
    task_class: str
    verdict: str          # 'unique' | 'policy_refused' | 'trivial_noop' | 'unexpected'
    model_count: int
    matches: bool
    sample_atoms: list[str] = field(default_factory=list)


def verify(encoding: TaskEncoding, d0_facts: str, layer_b: str) -> TaskResult:
    """
    Run free + constrained Clingo passes for a task.

    For mutating tasks we expect 1 model (action is fully determined once
    intent pins borrower + book). For policy_noop we expect 0 models.
    """
    if encoding.family == "noop":
        return TaskResult(
            task_id=encoding.task_id, task_class=encoding.task_class,
            verdict="trivial_noop", model_count=0, matches=True,
        )

    programs = [d0_facts, layer_b, encoding.action_rules]
    models = solve_clingo(programs, max_models=2)

    if encoding.task_class == "policy_noop":
        verdict = "policy_refused" if len(models) == 0 else "unexpected"
        matches = len(models) == 0
    else:
        if len(models) == 0:
            verdict, matches = "infeasible", False
        elif len(models) == 1:
            verdict, matches = "unique", True
        else:
            verdict, matches = f"ambiguous_{len(models)}", False

    sample = models[0] if models else []
    return TaskResult(
        task_id=encoding.task_id, task_class=encoding.task_class,
        verdict=verdict, model_count=len(models), matches=matches,
        sample_atoms=sample,
    )


# ============================================================================
# 5. Solve (action simulator)
# ============================================================================


@dataclass
class SolveResult:
    """Outcome of applying the action and computing the structured diff."""
    task_id: str
    success: bool
    d_star: dict | None = None
    diff: list[str] = field(default_factory=list)
    error: str = ""


def apply_borrow_book(db: dict, borrower_id: str, book_id: str, new_loan_id: str) -> tuple[dict, list[str]]:
    """Apply borrow_book to db (deep copy), return (new_db, structured diff)."""
    new_db = copy.deepcopy(db)
    new_db["loans"][new_loan_id] = {
        "loan_id": new_loan_id,
        "borrower_id": borrower_id,
        "book_id": book_id,
        "status": "active",
    }
    # Count before / after for the diff.
    n_before = sum(
        1 for l in db["loans"].values()
        if l["borrower_id"] == borrower_id and l["status"] == "active"
    )
    book_avail_before = (
        db["books"][book_id]["total_copies"]
        - sum(1 for l in db["loans"].values()
              if l["book_id"] == book_id and l["status"] == "active")
    )
    diff = [
        f"loan/{new_loan_id}: NEW (borrower={borrower_id}, book={book_id}, status=active)",
        f"borrower/{borrower_id}.active_loan_count: {n_before} → {n_before + 1}",
        f"book/{book_id}.available_copies: {book_avail_before} → {book_avail_before - 1}",
    ]
    return new_db, diff


def solve_task(encoding: TaskEncoding, db: dict) -> SolveResult:
    """For borrow tasks: apply the action. For noop/refuse: D* = D₀."""
    if encoding.family in ("noop",):
        return SolveResult(task_id=encoding.task_id, success=True, d_star=db, diff=[])

    if encoding.task_class == "policy_noop":
        # Refusal: D* = D₀ by definition.
        return SolveResult(task_id=encoding.task_id, success=True, d_star=db, diff=[])

    if encoding.family != "borrow":
        return SolveResult(task_id=encoding.task_id, success=False,
                           error=f"unsupported family: {encoding.family}")

    new_loan_id = f"loan_NEW_{encoding.task_id}"
    try:
        new_db, diff = apply_borrow_book(
            db, encoding.target_borrower, encoding.target_book, new_loan_id,
        )
        return SolveResult(task_id=encoding.task_id, success=True,
                           d_star=new_db, diff=diff)
    except Exception as e:
        return SolveResult(task_id=encoding.task_id, success=False,
                           error=f"action simulator failed: {e}")


# ============================================================================
# 6. Main
# ============================================================================


def main() -> int:
    """CLI entry: verify each task, then solve, then print table + traces."""
    print("=" * 78)
    print("Library tutorial verifier")
    print("=" * 78)

    db = json.loads(DB_PATH.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)
    d0_facts = encode_db(db)
    tasks = json.loads(TASKS_PATH.read_text())

    print(f"\n[setup] Layer B ASP from rules.md: {len(layer_b)} chars.")
    print(f"[setup] D₀: {len(db['borrowers'])} borrowers, "
          f"{len(db['books'])} books, {len(db['loans'])} active loans.")
    print(f"[setup] {len(tasks)} tasks loaded.")

    print(f"\n{'ID':<12} {'task_class':<14} {'verdict':<18} {'models':<8} ok")
    print("─" * 78)
    results = []
    for t in tasks:
        encoding = encode_task(t)
        r = verify(encoding, d0_facts, layer_b)
        sr = solve_task(encoding, db) if r.matches else None
        results.append((t, encoding, r, sr))
        ok = "✓" if r.matches else "✗"
        print(f"{r.task_id:<12} {r.task_class:<14} {r.verdict:<18} {r.model_count:<8} {ok}")

    print("\nPer-task detail:")
    for t, encoding, r, sr in results:
        print(f"\n  {r.task_id}: {t['description']['purpose']}")
        intent = t['operational_spec']['intent']
        print(f"    intent: {intent}")
        print(f"    verdict: {r.verdict} ({r.model_count} model(s))")
        if r.sample_atoms:
            print(f"    derivation:")
            for atom in r.sample_atoms:
                print(f"      • {atom}")
        if sr and sr.diff:
            print(f"    Solve-derived D* diff:")
            for d in sr.diff:
                print(f"      → {d}")
        elif sr and not sr.diff and r.task_class == "policy_noop":
            print(f"    D* = D₀ (no mutation; policy correctly refused)")

    print("\n" + "=" * 78)
    n_ok = sum(1 for _, _, r, _ in results if r.matches)
    print(f"SUMMARY: {n_ok}/{len(results)} library tasks verified.")
    return 0 if n_ok == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
