#!/usr/bin/env python3
"""
Clingo-based uniqueness verifier for retail_returns tasks.

Phase 1 — covers F-001 through F-006. For each task, this script proves (or
refutes) two properties that hand-design cannot guarantee:

  1. Soundness  — at least one D* satisfying (D₀, Policy, C_hard) exists.
  2. Uniqueness — exactly one such D* exists.

Plus two complexity metrics:

  • Pruning ratio   — |valid D* without C_hard| ÷ |valid D* with C_hard|.
                      Measures how much work the user's constraints did.
  • Constraint cov  — number of distinct Layer B derived predicates that
                      fired in deriving the answer set. Measures how
                      much policy machinery the task exercises.

The ASP for Layer B is extracted from rules.md so the markdown stays the
single source of truth. Per-task encodings are hardcoded in §4 because
c_hard in tasks.json is currently prose; a future v0.1 step would parse it.

Run:
  uv run python tools/clingo_verify.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import clingo

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "retail_returns"
DB_PATH = DOMAIN_DIR / "db.json"
RULES_PATH = DOMAIN_DIR / "rules.md"
TASKS_PATH = DOMAIN_DIR / "tasks.json"


# ============================================================================
# 1. Rule extraction — keep rules.md as the single source of truth
# ============================================================================


# Sections of rules.md whose code blocks we want to load for uniqueness
# checking. §2 (integrity constraints) is omitted because we already validate
# D₀ separately and our encodings don't compute a post-state that could
# violate them. §2.3 is included specifically for effective_returner/2 which
# rules.md §3.5 depends on. §5 (worked micro-example) contains facts that
# would conflict with the actual D₀ facts we assert.
RELEVANT_SECTIONS = {"2.3", "3", "4"}


def extract_asp_from_rules_md(path: Path) -> str:
    """
    Pull fenced code blocks from the relevant sections of rules.md.

    Section detection works on '## N. ...' and '### N.M ...' headers.
    A code block is anything between ``` fences while inside a relevant
    section.
    """
    text = path.read_text()
    blocks: list[str] = []
    in_fence = False
    fence_buffer: list[str] = []
    current_section = ""

    # Matches '## N. Title' and '### N.M Title' headers. The trailing period
    # after the number is optional — rules.md uses '### 2.3 Multi-party' (no
    # period) at subsection level but '## 2. Integrity constraints' (period)
    # at section level.
    header_re = re.compile(r"^(#{2,3})\s+(\d+(?:\.\d+)?)\b")

    for line in text.splitlines():
        m = header_re.match(line)
        if m and not in_fence:
            current_section = m.group(2)
            continue

        stripped = line.strip()
        if stripped.startswith("```"):
            if in_fence:
                if _section_is_relevant(current_section):
                    blocks.append("\n".join(fence_buffer))
                fence_buffer = []
                in_fence = False
            else:
                in_fence = True
            continue

        if in_fence:
            fence_buffer.append(line)

    return "\n\n".join(blocks)


def _section_is_relevant(section: str) -> bool:
    """A section identifier like '3.2' is relevant if its prefix matches."""
    parts = section.split(".")
    for n in range(1, len(parts) + 1):
        prefix = ".".join(parts[:n])
        if prefix in RELEVANT_SECTIONS:
            return True
    return False


# ============================================================================
# 2. Encoder — JSON DB → ASP ground facts
# ============================================================================


def asp_atom(name: str, *args: Any) -> str:
    """Format an ASP atom. Strings become bare identifiers; ints stay numeric."""
    formatted = ", ".join(_asp_term(a) for a in args)
    return f"{name}({formatted})."


def _asp_term(v: Any) -> str:
    if isinstance(v, bool):
        raise ValueError("ASP has no booleans — encode as a present/absent fact")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v
    raise TypeError(f"cannot encode {type(v).__name__} as ASP term")


def encode_db(db: dict, current_time: str) -> str:
    """
    Encode the subset of D₀ that Layer B rules consult, plus the externals
    Layer B treats as inputs (days_since_fulfillment, payment_method_valid
    attribute facts).
    """
    lines: list[str] = []

    for k, v in db["constants"].items():
        if isinstance(v, int):
            lines.append(asp_atom("const", k, v))

    for cid, c in db["customers"].items():
        lines.append(asp_atom("customer", cid))
        lines.append(asp_atom("member_tier", cid, c["member_tier"]))

    for pid, p in db["products"].items():
        lines.append(asp_atom("product", pid))
        lines.append(asp_atom("return_class", pid, p["return_class"]))
        if p.get("replacement_available"):
            lines.append(asp_atom("replacement_available", pid))

    for pmid, pm in db["payment_methods"].items():
        lines.append(asp_atom("payment_method", pmid))
        lines.append(asp_atom("payment_method_owner", pmid, pm["customer_id"]))
        lines.append(asp_atom("payment_method_type", pmid, pm["type"]))
        if pm["type"] == "credit_card" and pm.get("valid"):
            lines.append(asp_atom("payment_method_credit_card_valid", pmid))
        if pm["type"] == "gift_card":
            lines.append(asp_atom("payment_method_balance_cents", pmid, pm["balance_cents"]))

    for oid, o in db["orders"].items():
        lines.append(asp_atom("order", oid))
        lines.append(asp_atom("order_purchaser", oid, o["purchaser_customer_id"]))
        if o.get("recipient_customer_id"):
            lines.append(asp_atom("order_recipient", oid, o["recipient_customer_id"]))
        if o.get("payment_method_id"):
            lines.append(asp_atom("order_payment_method", oid, o["payment_method_id"]))
        lines.append(asp_atom("order_status", oid, o["status"]))
        if o.get("fulfillment_date"):
            lines.append(asp_atom("fulfillment_date_set", oid))
            days = _days_between(current_time, o["fulfillment_date"])
            lines.append(asp_atom("days_since_fulfillment", oid, days))
        for it in o["items"]:
            lines.append(asp_atom("order_item", it["order_item_id"]))
            lines.append(asp_atom("order_item_of", it["order_item_id"], oid))
            lines.append(asp_atom("product_of", it["order_item_id"], it["product_id"]))
            lines.append(asp_atom("quantity", it["order_item_id"], it["quantity"]))
            lines.append(asp_atom("unit_price_cents", it["order_item_id"], it["unit_price_cents"]))
            lines.append(asp_atom("fulfilled_quantity", it["order_item_id"], it["fulfilled_quantity"]))
            lines.append(asp_atom("returned_quantity", it["order_item_id"], it["returned_quantity"]))

    for rid, r in db["returns"].items():
        lines.append(asp_atom("return", rid))
        lines.append(asp_atom("return_of_order", rid, r["order_id"]))
        lines.append(asp_atom("return_initiator", rid, r["initiator_customer_id"]))
        lines.append(asp_atom("return_status", rid, r["status"]))
        for ri in r["items"]:
            lines.append(asp_atom("return_item", ri["return_item_id"]))
            lines.append(asp_atom("return_item_of", ri["return_item_id"], rid))
            lines.append(asp_atom("return_item_references", ri["return_item_id"], ri["order_item_id"]))
            lines.append(asp_atom("return_item_quantity", ri["return_item_id"], ri["quantity"]))
            lines.append(asp_atom("return_item_condition", ri["return_item_id"], ri["declared_condition"]))
            lines.append(asp_atom("return_item_reason", ri["return_item_id"], ri["declared_reason"]))
            lines.append(asp_atom("valid_return_quantity", ri["return_item_id"]))

    return "\n".join(lines)


def _days_between(later_iso: str, earlier_iso: str) -> int:
    """
    Calendar-day difference between two ISO datetimes. Uses date-level
    truncation rather than timestamp arithmetic so that the policy semantics
    ("within N days of delivery") match how a human would count days — an
    order delivered on day D and returned on day D+31 is 31 days later
    regardless of whether the time-of-day comparison is 30d 8h or 31d 8h.
    """
    from datetime import datetime

    def parse(s: str):
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()

    return (parse(later_iso) - parse(earlier_iso)).days


# ============================================================================
# 3. Solver wrapper
# ============================================================================


# Layer B derived predicates we want to see in the model (drives both the
# pruning-ratio check and the constraint-coverage metric).
DERIVED_PREDICATES = {
    "is_gift_order",
    "effective_returner",
    "eligible_to_initiate",
    "applicable_window_days",
    "within_window",
    "out_of_window",
    "exists_out_of_window_item",
    "return_class_returnable",
    "all_items_returnable",
    "all_items_defective",
    "all_replacements_available",
    "exists_non_returnable_item",
    "exists_non_defective_item",
    "exists_unavailable_replacement",
    "return_eligible",
    "eligible_refund_methods",
    "eligible_refund_to_original_payment",
    "eligible_status",
    "restocking_fee_applies",
    "gross_amount",
    "refund_amount_for",
    "payment_method_valid",
    "requires_inspection",
    # task-side
    "picked_refund_method",
    "target_return",
}


def solve(programs: list[str], max_models: int = 2) -> list[list[str]]:
    """
    Run Clingo on a list of program fragments; return each model as a sorted
    list of atom strings (filtered to derived predicates of interest).
    """
    ctl = clingo.Control([f"--models={max_models}"])
    for i, prog in enumerate(programs):
        ctl.add(f"base_{i}", [], prog)
    ctl.ground([(f"base_{i}", []) for i in range(len(programs))])

    models: list[list[str]] = []

    def on_model(m: clingo.Model) -> bool:
        atoms = [
            str(s) for s in m.symbols(atoms=True)
            if s.name in DERIVED_PREDICATES
        ]
        models.append(sorted(atoms))
        return True

    ctl.solve(on_model=on_model)
    return models


def constraint_coverage(model: list[str], target_entities: set[str] | None = None) -> Counter:
    """
    Count occurrences of each Layer B derived predicate in a model.

    If `target_entities` is supplied, only count atoms whose argument list
    references at least one of those entities. This produces a *task-scoped*
    coverage that measures policy machinery specific to the target return,
    rather than counting everything Layer B derives across all of D₀.
    """
    counts: Counter = Counter()
    for atom in model:
        m = re.match(r"^([a-z_][a-z_0-9]*)\((.*)\)$", atom)
        if not m:
            continue
        pred, args = m.group(1), m.group(2)
        if target_entities is not None:
            arg_terms = {t.strip() for t in args.split(",")}
            if not (arg_terms & target_entities):
                continue
        counts[pred] += 1
    return counts


def task_target_entities(encoding: TaskEncoding) -> set[str]:
    """
    Identify the ASP entities specific to this task — the target Return, its
    items, and the Order it acts on. Used to filter coverage to task-relevant
    facts only.
    """
    targets: set[str] = set()
    # Pull all `xxx(yyy).` style atoms from the hypothetical facts.
    for m in re.finditer(r"\b(return|return_item|target_return)\((\w+)", encoding.action_rules + encoding.hypothetical_facts):
        targets.add(m.group(2))
    # Pull the Order id from return_of_order(...) atoms.
    for m in re.finditer(r"return_of_order\(\w+,\s*(\w+)\)", encoding.hypothetical_facts):
        targets.add(m.group(1))
    # F-001 case: ret_004 is in D₀ not the encoding. Add it manually if present.
    if "target_return(ret_004)" in encoding.action_rules:
        targets.update({"ret_004", "ri_004_01", "ord_001", "oi_001_01"})
    return targets


# ============================================================================
# 4. Per-task encodings
# ============================================================================


@dataclass
class TaskEncoding:
    """ASP encoding of a single task for uniqueness verification."""
    task_id: str
    task_class: str             # 'mutating' | 'policy_noop' | 'intent_noop'
    family: str                 # 'approve_existing' | 'initiate_approve' | 'refuse' | 'noop'
    hypothetical_facts: str
    action_rules: str
    c_hard_constraint: str
    expected_free_count: int    # without C_hard
    expected_constrained_count: int  # with C_hard
    notes: str = ""


# Common action rules: target_return is policy-eligible, picks exactly one
# refund method from the eligible set. Same shape for every "approve" task.
APPROVE_ACTION_RULES = """
:- target_return(R), not return_eligible(R).
1 { picked_refund_method(R, M) : eligible_refund_methods(R, M) } 1 :- target_return(R).
"""


def encode_f001() -> TaskEncoding:
    """F-001: approve the pre-existing pending return ret_004."""
    return TaskEncoding(
        task_id="F-001",
        task_class="mutating",
        family="approve_existing",
        hypothetical_facts="",  # ret_004 already in D₀
        action_rules="target_return(ret_004).\n" + APPROVE_ACTION_RULES,
        c_hard_constraint=":- target_return(R), not picked_refund_method(R, original_payment).",
        expected_free_count=2,       # original_payment + store_credit
        expected_constrained_count=1,
        notes="opened_unused + standard + customer-choice → restocking fee → $42.50",
    )


def encode_f002() -> TaskEncoding:
    """F-002: initiate + approve a gift return on ord_005 (Eva returning Bob's cookbook)."""
    hypothetical = """
return(rnew).
return_of_order(rnew, ord_005).
return_initiator(rnew, cust_005).
return_status(rnew, pending).
return_item(rinew1).
return_item_of(rinew1, rnew).
return_item_references(rinew1, oi_005_01).
return_item_quantity(rinew1, 1).
return_item_condition(rinew1, new_unopened).
return_item_reason(rinew1, change_of_mind).
valid_return_quantity(rinew1).
"""
    return TaskEncoding(
        task_id="F-002",
        task_class="mutating",
        family="initiate_approve",
        hypothetical_facts=hypothetical,
        action_rules="target_return(rnew).\n" + APPROVE_ACTION_RULES,
        c_hard_constraint=":- target_return(R), not picked_refund_method(R, store_credit).",
        expected_free_count=1,       # gift forces store_credit; only 1 option
        expected_constrained_count=1,
        notes="gift order → store_credit-only; new_unopened → no restocking fee → $70.00",
    )


def encode_f003() -> TaskEncoding:
    """F-003: refuse return on ord_007 (one day outside the 30-day window)."""
    hypothetical = """
return(rnew).
return_of_order(rnew, ord_007).
return_initiator(rnew, cust_003).
return_status(rnew, pending).
return_item(rinew1).
return_item_of(rinew1, rnew).
return_item_references(rinew1, oi_007_01).
return_item_quantity(rinew1, 1).
return_item_condition(rinew1, opened_unused).
return_item_reason(rinew1, change_of_mind).
valid_return_quantity(rinew1).
"""
    return TaskEncoding(
        task_id="F-003",
        task_class="policy_noop",
        family="refuse",
        hypothetical_facts=hypothetical,
        action_rules="target_return(rnew).\n" + APPROVE_ACTION_RULES,
        c_hard_constraint="",  # we want to confirm 0 models even without C_hard
        expected_free_count=0,      # within_window false → return_eligible false
        expected_constrained_count=0,
        notes="days_since_fulfillment(ord_007)=31; window=30; should be refused",
    )


def encode_f004() -> TaskEncoding:
    """F-004: Bob (cust_002) attempts to return Eva's gift (ord_005)."""
    hypothetical = """
return(rnew).
return_of_order(rnew, ord_005).
return_initiator(rnew, cust_002).
return_status(rnew, pending).
return_item(rinew1).
return_item_of(rinew1, rnew).
return_item_references(rinew1, oi_005_01).
return_item_quantity(rinew1, 1).
return_item_condition(rinew1, new_unopened).
return_item_reason(rinew1, change_of_mind).
valid_return_quantity(rinew1).
"""
    return TaskEncoding(
        task_id="F-004",
        task_class="policy_noop",
        family="refuse",
        hypothetical_facts=hypothetical,
        action_rules="target_return(rnew).\n" + APPROVE_ACTION_RULES,
        c_hard_constraint="",
        expected_free_count=0,      # eligible_to_initiate false (Bob is purchaser, Eva is recipient)
        expected_constrained_count=0,
        notes="Bob is purchaser of gift ord_005; effective_returner is Eva (cust_005)",
    )


def encode_f005() -> TaskEncoding:
    """F-005: initiate + approve exchange on defective Smartwatch (ord_008)."""
    hypothetical = """
return(rnew).
return_of_order(rnew, ord_008).
return_initiator(rnew, cust_004).
return_status(rnew, pending).
return_item(rinew1).
return_item_of(rinew1, rnew).
return_item_references(rinew1, oi_008_02).
return_item_quantity(rinew1, 1).
return_item_condition(rinew1, defective).
return_item_reason(rinew1, defective).
valid_return_quantity(rinew1).
"""
    return TaskEncoding(
        task_id="F-005",
        task_class="mutating",
        family="initiate_approve",
        hypothetical_facts=hypothetical,
        action_rules="target_return(rnew).\n" + APPROVE_ACTION_RULES,
        c_hard_constraint=":- target_return(R), not picked_refund_method(R, exchange).",
        expected_free_count=3,       # original_payment + store_credit + exchange
        expected_constrained_count=1,
        notes="defective + replacement_available + valid card → 3 options; C_hard pins exchange",
    )


def encode_f006() -> TaskEncoding:
    """F-006: intent_noop — Bob asks about ret_003's status (no mutation requested)."""
    return TaskEncoding(
        task_id="F-006",
        task_class="intent_noop",
        family="noop",
        hypothetical_facts="",
        action_rules="",
        c_hard_constraint="",
        expected_free_count=0,
        expected_constrained_count=0,
        notes="no mutation requested → no LP check applicable; trivial",
    )


ENCODERS = [encode_f001, encode_f002, encode_f003, encode_f004, encode_f005, encode_f006]


# ============================================================================
# 5. Verification & complexity metrics
# ============================================================================


@dataclass
class TaskResult:
    task_id: str
    task_class: str
    family: str
    verdict: str                  # 'unique' | 'policy_refused' | 'trivial_noop' | 'ambiguous' | 'unexpected'
    free_count: int
    constrained_count: int
    coverage: Counter             # predicate-name → count
    coverage_distinct: int        # number of distinct derived predicates
    expected_free: int
    expected_constrained: int
    matches_expected: bool
    notes: str = ""
    sample_model: list[str] = field(default_factory=list)


def verify(encoding: TaskEncoding, d0_facts: str, layer_b: str) -> TaskResult:
    """Run free + constrained Clingo passes for a task, then build the result."""

    # Family-specific handling
    if encoding.family == "noop":
        return TaskResult(
            task_id=encoding.task_id,
            task_class=encoding.task_class,
            family=encoding.family,
            verdict="trivial_noop",
            free_count=0,
            constrained_count=0,
            coverage=Counter(),
            coverage_distinct=0,
            expected_free=0,
            expected_constrained=0,
            matches_expected=True,
            notes=encoding.notes,
        )

    base_programs = [d0_facts, layer_b, encoding.hypothetical_facts, encoding.action_rules]

    # Free pass — no C_hard. Cap at a high count so we see all alternatives.
    free_models = solve(base_programs, max_models=10)

    # Constrained pass — with C_hard. We only need to know if it's 0 / 1 / ≥2.
    constrained_programs = base_programs + [encoding.c_hard_constraint] if encoding.c_hard_constraint else base_programs
    constrained_models = solve(constrained_programs, max_models=2)

    free_count = len(free_models)
    constrained_count = len(constrained_models)

    # Verdict
    if encoding.family == "refuse":
        # Expect 0 models — that's the policy correctly refusing.
        verdict = "policy_refused" if (free_count == 0 and constrained_count == 0) else "unexpected"
    else:
        if constrained_count == 0:
            verdict = "infeasible"
        elif constrained_count == 1:
            verdict = "unique"
        else:
            verdict = f"ambiguous_{constrained_count}plus"

    matches_expected = (
        free_count == encoding.expected_free_count
        and constrained_count == encoding.expected_constrained_count
    )

    # Coverage from the constrained model (or the free model if no C_hard).
    # Filter to atoms touching the task's target entities so the number
    # actually reflects task-specific complexity, not D₀ size.
    sample = (
        constrained_models[0] if constrained_models
        else free_models[0] if free_models
        else []
    )
    targets = task_target_entities(encoding)
    coverage = constraint_coverage(sample, target_entities=targets)

    return TaskResult(
        task_id=encoding.task_id,
        task_class=encoding.task_class,
        family=encoding.family,
        verdict=verdict,
        free_count=free_count,
        constrained_count=constrained_count,
        coverage=coverage,
        coverage_distinct=len(coverage),
        expected_free=encoding.expected_free_count,
        expected_constrained=encoding.expected_constrained_count,
        matches_expected=matches_expected,
        notes=encoding.notes,
        sample_model=sample,
    )


# ============================================================================
# 6. Main
# ============================================================================


def main() -> int:
    print("=" * 78)
    print("Clingo uniqueness verifier — Phase 1 (F-001 through F-006)")
    print("=" * 78)

    db = json.loads(DB_PATH.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)
    d0_facts = encode_db(db, db["constants"]["current_time"])
    print(f"\n[setup] Layer B ASP from rules.md: {len(layer_b)} chars.")
    print(f"[setup] D₀: {len(db['customers'])} customers, "
          f"{len(db['orders'])} orders, {len(db['returns'])} returns "
          f"({len(d0_facts.splitlines())} ASP facts).")

    results: list[TaskResult] = []
    for encoder in ENCODERS:
        encoding = encoder()
        result = verify(encoding, d0_facts, layer_b)
        results.append(result)

    # --- Per-task results table ---
    print("\n" + "─" * 78)
    print("Per-task verification")
    print("─" * 78)
    print(f"{'ID':<7} {'family':<18} {'verdict':<18} {'pruning':<10} {'cov':<5} ok")
    for r in results:
        if r.family == "noop":
            pruning = "—"
            cov = "—"
        else:
            pruning = f"{r.free_count}→{r.constrained_count}"
            cov = str(r.coverage_distinct)
        ok = "✓" if r.matches_expected else "✗"
        print(f"{r.task_id:<7} {r.family:<18} {r.verdict:<18} {pruning:<10} {cov:<5} {ok}")

    # --- Complexity ranking ---
    mutating = [r for r in results if r.task_class == "mutating"]
    if mutating:
        print("\n" + "─" * 78)
        print("Complexity ranking (mutating tasks)")
        print("─" * 78)
        print("\nBy pruning ratio (most-constrained first):")
        for r in sorted(mutating, key=lambda x: -x.free_count + x.constrained_count):
            note = f"  ({r.notes})" if r.notes else ""
            print(f"  {r.task_id}  {r.free_count} → {r.constrained_count}{note}")

        print("\nBy constraint coverage (most-policy-machinery first):")
        for r in sorted(mutating, key=lambda x: -x.coverage_distinct):
            print(f"  {r.task_id}  {r.coverage_distinct} distinct predicates fired")

    # --- Per-task constraint coverage detail ---
    print("\n" + "─" * 78)
    print("Constraint coverage detail")
    print("─" * 78)
    for r in results:
        if r.family == "noop":
            print(f"\n{r.task_id}: no LP check applicable")
            continue
        print(f"\n{r.task_id}: {r.coverage_distinct} predicates × {sum(r.coverage.values())} ground atoms")
        for pred, count in sorted(r.coverage.items(), key=lambda kv: -kv[1]):
            print(f"    {pred:<35} {count}")

    # --- Summary ---
    print("\n" + "=" * 78)
    n = len(results)
    n_ok = sum(1 for r in results if r.matches_expected)
    n_mutating = sum(1 for r in results if r.task_class == "mutating")
    n_policy_noop = sum(1 for r in results if r.task_class == "policy_noop")
    n_intent_noop = sum(1 for r in results if r.task_class == "intent_noop")

    print(f"SUMMARY: {n_ok}/{n} tasks correctly verified.")
    print(f"  {n_mutating} mutating tasks — uniquely solvable.")
    print(f"  {n_policy_noop} policy_noop tasks — policy correctly refuses.")
    print(f"  {n_intent_noop} intent_noop task — no LP check applicable.")

    failures = [r.task_id for r in results if not r.matches_expected]
    if failures:
        print(f"\n  Unexpected results: {', '.join(failures)}")
        return 1

    print("\n  Phase 1 generalization complete. Both methodology goals delivered:")
    print("    Goal 1 (correctness):  soundness + uniqueness mechanically proven.")
    print("    Goal 2 (complexity):   pruning ratio + coverage available per task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
