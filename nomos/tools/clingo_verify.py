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

# Reuse the Python action simulator from the pure-Python verifier. Same
# directory; just add it to the path. The two verifiers are deliberately
# coupled here: the Clingo solver picks the refund_method; the Python
# simulator applies the policy-determined side effects (quantity bookkeeping,
# store-credit credit, exchange-order creation). Together they constitute the
# Solve operation.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from verify_retail_returns import (  # noqa: E402
    TaskContext,
    apply_initiate_return,
    apply_approve_return,
    compute_diff,
)


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
        """Parse ISO-8601 (with trailing Z) and truncate to date."""
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

    `--warn=no-atom-undefined` is set because Generate produces minimal D₀s
    that intentionally omit some entity types (e.g., a self-purchase scenario
    has no `order_recipient/2` facts). The closed-world semantics still hold
    — `not P` correctly defaults to true when P never fires — but Clingo's
    static-analysis warnings about "atom never appears in any rule head"
    add noise without surfacing bugs. Real correctness issues show up as
    wrong derivations, not as these warnings.
    """
    ctl = clingo.Control([f"--models={max_models}", "--warn=no-atom-undefined"])
    for i, prog in enumerate(programs):
        ctl.add(f"base_{i}", [], prog)
    ctl.ground([(f"base_{i}", []) for i in range(len(programs))])

    models: list[list[str]] = []

    def on_model(m: clingo.Model) -> bool:
        """Collect this answer set's derived-predicate atoms; continue enumerating."""
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


def task_target_entities(encoding: TaskEncoding, db: dict | None = None) -> set[str]:
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
    # For approve_existing: the target Return is pre-existing in D₀. Look up
    # its items + order from db.
    if encoding.target_return_id and db is not None:
        rid = encoding.target_return_id
        ret = db["returns"].get(rid)
        if ret:
            targets.add(rid)
            targets.add(ret["order_id"])
            for ri in ret["items"]:
                targets.add(ri["return_item_id"])
                targets.add(ri["order_item_id"])
    return targets


# ============================================================================
# 4. Per-task encodings
# ============================================================================


@dataclass
class TaskEncoding:
    """ASP encoding of a single task for uniqueness verification + Solve.

    Constructed by `encode_task()` from a task's `operational_spec.intent`
    field. Per-task hardcoded encoders no longer exist — the verifier
    consumes tasks.json directly.
    """
    task_id: str
    task_class: str             # 'mutating' | 'policy_noop' | 'intent_noop'
    family: str                 # 'approve_existing' | 'initiate_approve' | 'refuse' | 'noop'
    hypothetical_facts: str
    action_rules: str
    c_hard_constraint: str
    notes: str = ""
    # For Solve: which action to fire once Clingo picks the refund_method.
    target_return_id: str | None = None
    initiate_args: dict | None = None


# Common action rules: target_return is policy-eligible, picks exactly one
# refund method from the eligible set. Same shape for every "approve" task.
APPROVE_ACTION_RULES = """
:- target_return(R), not return_eligible(R).
1 { picked_refund_method(R, M) : eligible_refund_methods(R, M) } 1 :- target_return(R).
"""


def _encode_return_item(ri_id: str, ret_id: str, item: dict) -> list[str]:
    """Emit ASP facts for one hypothetical ReturnItem."""
    return [
        f"return_item({ri_id}).",
        f"return_item_of({ri_id}, {ret_id}).",
        f"return_item_references({ri_id}, {item['order_item_id']}).",
        f"return_item_quantity({ri_id}, {item['quantity']}).",
        f"return_item_condition({ri_id}, {item['declared_condition']}).",
        f"return_item_reason({ri_id}, {item['declared_reason']}).",
        f"valid_return_quantity({ri_id}).",
    ]


def _refund_method_constraint(refund_method: str | None) -> str:
    """The C_hard integrity constraint pinning the picked refund_method."""
    if refund_method is None:
        return ""
    return f":- target_return(R), not picked_refund_method(R, {refund_method})."


def encode_task(task: dict) -> TaskEncoding:
    """
    Build a TaskEncoding from a task's `operational_spec.intent` field.

    Supported actions:
      - "none"                 — intent_noop tasks; no LP check.
      - "approve_existing"     — target a pre-existing pending Return.
      - "initiate_and_approve" — create a hypothetical Return from items,
                                  then approve it with refund_method.

    The `family` field is derived from (action, task_class):
      - action=none → noop
      - mutating intent → approve_existing | initiate_approve
      - policy_noop intent → refuse (regardless of action shape)
    """
    tid = task["id"]
    spec = task["operational_spec"]
    klass = spec["task_class"]
    intent = spec.get("intent") or {}
    action = intent.get("action", "none")

    if action == "none":
        return TaskEncoding(
            task_id=tid, task_class=klass, family="noop",
            hypothetical_facts="", action_rules="", c_hard_constraint="",
        )

    if action == "approve_existing":
        return_id = intent["return_id"]
        family = "approve_existing" if klass == "mutating" else "refuse"
        return TaskEncoding(
            task_id=tid, task_class=klass, family=family,
            hypothetical_facts="",
            action_rules=f"target_return({return_id}).\n" + APPROVE_ACTION_RULES,
            c_hard_constraint=_refund_method_constraint(intent.get("refund_method")),
            target_return_id=return_id,
        )

    if action == "initiate_and_approve":
        order_id = intent["order_id"]
        customer_id = intent["customer_id"]
        items = intent["items"]

        # Build hypothetical Return + ReturnItem facts. The new Return is
        # called `rnew` and ReturnItems `rinew1`, `rinew2`, ... by convention.
        hypo_lines = [
            "return(rnew).",
            f"return_of_order(rnew, {order_id}).",
            f"return_initiator(rnew, {customer_id}).",
            "return_status(rnew, pending).",
        ]
        for i, item in enumerate(items, start=1):
            hypo_lines.extend(_encode_return_item(f"rinew{i}", "rnew", item))

        family = "initiate_approve" if klass == "mutating" else "refuse"
        return TaskEncoding(
            task_id=tid, task_class=klass, family=family,
            hypothetical_facts="\n".join(hypo_lines),
            action_rules="target_return(rnew).\n" + APPROVE_ACTION_RULES,
            c_hard_constraint=_refund_method_constraint(intent.get("refund_method")),
            initiate_args={
                "order_id": order_id,
                "customer_id": customer_id,
                "items": items,
            },
        )

    raise ValueError(f"unknown intent action: {action!r} (task {tid})")


# ============================================================================
# 5. Verification & complexity metrics
# ============================================================================


@dataclass
class TaskResult:
    """
    Verify result for a single retail_returns task (Phase 1 + 3 metrics).

    Fields:
      verdict          : 'unique' | 'policy_refused' | 'trivial_noop' |
                         'ambiguous_<N>plus' | 'infeasible'
      free_count       : answer-set count without C_hard (the "free policy")
      constrained_count: answer-set count with C_hard (the actual eval)
      coverage         : Counter of derived-predicate name → ground atom count,
                         filtered to atoms touching the task's target entities
      coverage_distinct: len(coverage) — number of distinct predicates that fired
      matches_expected : derived from family alone (mutating→1, refuse→0, noop→OK)
      sample_model     : one of the constrained models, for derivation tracing
    """
    task_id: str
    task_class: str
    family: str
    verdict: str
    free_count: int
    constrained_count: int
    coverage: Counter
    coverage_distinct: int
    matches_expected: bool
    notes: str = ""
    sample_model: list[str] = field(default_factory=list)


def _expected_for(family: str, constrained_count: int) -> bool:
    """The task_class-derived success criterion."""
    if family == "noop":
        return True
    if family == "refuse":
        return constrained_count == 0  # policy correctly refuses
    # approve_existing or initiate_approve — mutating tasks
    return constrained_count == 1


def verify(encoding: TaskEncoding, d0_facts: str, layer_b: str, db: dict | None = None) -> TaskResult:
    """Run free + constrained Clingo passes for a task, then build the result."""

    if encoding.family == "noop":
        return TaskResult(
            task_id=encoding.task_id, task_class=encoding.task_class, family=encoding.family,
            verdict="trivial_noop", free_count=0, constrained_count=0,
            coverage=Counter(), coverage_distinct=0,
            matches_expected=True, notes=encoding.notes,
        )

    base_programs = [d0_facts, layer_b, encoding.hypothetical_facts, encoding.action_rules]

    free_models = solve(base_programs, max_models=10)
    constrained_programs = (
        base_programs + [encoding.c_hard_constraint]
        if encoding.c_hard_constraint else base_programs
    )
    constrained_models = solve(constrained_programs, max_models=2)

    free_count = len(free_models)
    constrained_count = len(constrained_models)

    if encoding.family == "refuse":
        verdict = "policy_refused" if constrained_count == 0 else "unexpected"
    else:
        if constrained_count == 0:
            verdict = "infeasible"
        elif constrained_count == 1:
            verdict = "unique"
        else:
            verdict = f"ambiguous_{constrained_count}plus"

    matches_expected = _expected_for(encoding.family, constrained_count)

    # Coverage from the constrained model (or the free model if no C_hard).
    sample = (
        constrained_models[0] if constrained_models
        else free_models[0] if free_models
        else []
    )
    targets = task_target_entities(encoding, db=db)
    coverage = constraint_coverage(sample, target_entities=targets)

    return TaskResult(
        task_id=encoding.task_id, task_class=encoding.task_class, family=encoding.family,
        verdict=verdict, free_count=free_count, constrained_count=constrained_count,
        coverage=coverage, coverage_distinct=len(coverage),
        matches_expected=matches_expected, notes=encoding.notes, sample_model=sample,
    )


# ============================================================================
# 6. Solve — derive the unique D* via Clingo + action simulator
# ============================================================================


@dataclass
class SolveResult:
    """
    Solve result for a single retail_returns task.

    Fields:
      success       : did Clingo+simulator produce a clean D*?
      d_star        : the derived final DB (None if !success or family is noop/refuse)
      diff          : structured list of changes from D₀ to D*
      refund_method : the choice Clingo picked (filled in for mutating only)
      error         : non-empty if success is False
    """
    task_id: str
    family: str
    success: bool
    d_star: dict | None
    diff: list[str] = field(default_factory=list)
    refund_method: str | None = None
    error: str = ""


def extract_refund_method(model: list[str]) -> str | None:
    """Pull the chosen refund method out of a `picked_refund_method/2` atom."""
    for atom in model:
        m = re.match(r"picked_refund_method\(\w+,\s*(\w+)\)$", atom)
        if m:
            return m.group(1)
    return None


def solve_task(encoding: TaskEncoding, db: dict, layer_b: str) -> SolveResult:
    """
    Solve operation: derive D* from (D₀, OperationalSpec) via Clingo + action sim.

    For 'refuse' and 'noop' families: D* = D₀ by definition (no mutation).
    For 'approve_existing' and 'initiate_approve': run Clingo to pick the
    refund_method, then apply the corresponding actions to D₀.
    """
    if encoding.family in ("refuse", "noop"):
        return SolveResult(
            task_id=encoding.task_id,
            family=encoding.family,
            success=True,
            d_star=db,  # D* = D₀
            diff=[],
        )

    # Run Clingo with C_hard to get the unique answer set.
    programs = [
        encode_db(db, db["constants"]["current_time"]),
        layer_b,
        encoding.hypothetical_facts,
        encoding.action_rules,
        encoding.c_hard_constraint,
    ]
    models = solve(programs, max_models=2)

    if len(models) != 1:
        return SolveResult(
            task_id=encoding.task_id,
            family=encoding.family,
            success=False,
            d_star=None,
            error=f"expected exactly 1 model after C_hard; got {len(models)}",
        )

    refund_method = extract_refund_method(models[0])
    if refund_method is None:
        return SolveResult(
            task_id=encoding.task_id,
            family=encoding.family,
            success=False,
            d_star=None,
            error="no picked_refund_method atom in the answer set",
        )

    # Apply the actions via the Python simulator.
    ctx = TaskContext(task_id=encoding.task_id)
    try:
        if encoding.family == "initiate_approve":
            db_after_initiate = apply_initiate_return(db, encoding.initiate_args, ctx)
            # New Return id follows the Q-E-3 convention: ret_NEW_<task_id>_1.
            new_return_id = f"ret_NEW_{encoding.task_id}_1"
            d_star = apply_approve_return(
                db_after_initiate,
                {"return_id": new_return_id, "refund_method": refund_method},
                ctx,
            )
        else:  # approve_existing
            d_star = apply_approve_return(
                db,
                {"return_id": encoding.target_return_id, "refund_method": refund_method},
                ctx,
            )
    except Exception as e:
        return SolveResult(
            task_id=encoding.task_id,
            family=encoding.family,
            success=False,
            d_star=None,
            refund_method=refund_method,
            error=f"action simulator failed: {e}",
        )

    diff = compute_diff(db, d_star)
    return SolveResult(
        task_id=encoding.task_id,
        family=encoding.family,
        success=True,
        d_star=d_star,
        diff=diff,
        refund_method=refund_method,
    )


def derive_gold_d_star(task: dict, db: dict) -> dict | None:
    """
    Apply the gold action witness from tasks.json to D₀ to get a reference
    D*. Used to cross-validate the Solve-derived D*.
    """
    from verify_retail_returns import ACTION_DISPATCH

    actions = task["evaluation_criteria"]["actions"]
    ctx = TaskContext(task_id=task["id"])
    current = db
    for a in actions:
        if a["name"] not in ACTION_DISPATCH:
            return None
        try:
            current = ACTION_DISPATCH[a["name"]](current, a["arguments"], ctx)
        except Exception:
            return None
    return current


# ============================================================================
# 7. Main
# ============================================================================


def main() -> int:
    """
    CLI entry: load D₀ + Layer B + tasks for retail_returns, run Verify
    on each task, then Solve on each task that passes Verify, and
    cross-check Solve-derived D* against the gold trajectory D*. Print
    per-task table + complexity ranking + Solve diffs. Returns non-zero
    on any failure.
    """
    print("=" * 78)
    print("Clingo uniqueness verifier — Phase 1 (F-001 through F-006)")
    print("=" * 78)

    db = json.loads(DB_PATH.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)
    d0_facts = encode_db(db, db["constants"]["current_time"])
    tasks = json.loads(TASKS_PATH.read_text())
    tasks_by_id = {t["id"]: t for t in tasks}
    print(f"\n[setup] Layer B ASP from rules.md: {len(layer_b)} chars.")
    print(f"[setup] D₀: {len(db['customers'])} customers, "
          f"{len(db['orders'])} orders, {len(db['returns'])} returns "
          f"({len(d0_facts.splitlines())} ASP facts).")
    print(f"[setup] {len(tasks)} tasks loaded from tasks.json (encoding driven by"
          f" operational_spec.intent — no hardcoded per-task encoders).")

    # Each task is encoded directly from its operational_spec.intent field.
    encodings: list[TaskEncoding] = [encode_task(t) for t in tasks]
    results: list[TaskResult] = [verify(e, d0_facts, layer_b, db=db) for e in encodings]

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

    # --- Solve: derive D* from spec, cross-validate against gold trajectory ---
    print("\n" + "─" * 78)
    print("Solve operation — derive D* from (D₀, OperationalSpec)")
    print("─" * 78)

    solve_results: list[SolveResult] = []
    cross_validations: list[tuple[str, bool, str]] = []
    for encoding in encodings:
        sr = solve_task(encoding, db, layer_b)
        solve_results.append(sr)

        if sr.family in ("refuse", "noop"):
            print(f"\n{sr.task_id} ({sr.family}): D* = D₀ (no mutation)")
            cross_validations.append((sr.task_id, True, "trivially D* = D₀"))
            continue

        if not sr.success:
            print(f"\n{sr.task_id}: SOLVE FAILED — {sr.error}")
            cross_validations.append((sr.task_id, False, sr.error))
            continue

        print(f"\n{sr.task_id} ({sr.family}): D* derived via Clingo + simulator")
        print(f"  picked refund_method = {sr.refund_method}")
        print(f"  diff ({len(sr.diff)} changes):")
        for d in sr.diff:
            print(f"    • {d}")

        # Cross-validate: does the gold trajectory produce the same D*?
        gold_d_star = derive_gold_d_star(tasks_by_id[sr.task_id], db)
        if gold_d_star is None:
            cross_validations.append((sr.task_id, False, "gold trajectory failed to apply"))
            continue
        gold_diff = compute_diff(db, gold_d_star)
        if sorted(sr.diff) == sorted(gold_diff):
            print(f"  ✓ Cross-validates against gold-trajectory D* ({len(gold_diff)} changes match)")
            cross_validations.append((sr.task_id, True, ""))
        else:
            print(f"  ✗ DIFFERS from gold-trajectory D*:")
            print(f"      gold-only:  {set(gold_diff) - set(sr.diff)}")
            print(f"      solve-only: {set(sr.diff) - set(gold_diff)}")
            cross_validations.append((sr.task_id, False, "diff mismatch"))

    # --- Summary ---
    print("\n" + "=" * 78)
    n = len(results)
    n_ok = sum(1 for r in results if r.matches_expected)
    n_mutating = sum(1 for r in results if r.task_class == "mutating")
    n_policy_noop = sum(1 for r in results if r.task_class == "policy_noop")
    n_intent_noop = sum(1 for r in results if r.task_class == "intent_noop")
    n_xv_pass = sum(1 for _, ok, _ in cross_validations if ok)

    print(f"SUMMARY:")
    print(f"  Verify: {n_ok}/{n} tasks correctly verified.")
    print(f"    {n_mutating} mutating — uniquely solvable.")
    print(f"    {n_policy_noop} policy_noop — policy correctly refuses.")
    print(f"    {n_intent_noop} intent_noop — no LP check applicable.")
    print(f"  Solve:  {n_xv_pass}/{len(cross_validations)} Solve-derived D* match gold trajectory.")

    failures = [r.task_id for r in results if not r.matches_expected]
    xv_failures = [tid for tid, ok, _ in cross_validations if not ok]
    if failures or xv_failures:
        if failures:
            print(f"\n  Verify failures: {', '.join(failures)}")
        if xv_failures:
            print(f"  Solve cross-validation failures: {', '.join(xv_failures)}")
        return 1

    print("\n  Three operations now working:")
    print("    Verify  — soundness + uniqueness proven per task.")
    print("    Solve   — D* derived from (D₀, OperationalSpec) alone, no gold trajectory needed.")
    print("    Metrics — pruning ratio + constraint coverage per task.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
