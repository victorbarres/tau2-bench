#!/usr/bin/env python3
"""
Clingo verifier for the airline retrofit (cancellation slice).

Parallels tools/clingo_verify.py — same pipeline shape, different domain:
  - Reads domains/airline/{db,tasks}.json.
  - Extracts Layer B ASP from domains/airline/rules.md.
  - Encodes the airline DB as ASP ground facts.
  - For each task, encodes the cancel-reservation intent as a feasibility
    check (no choice surface — Verify reports unique/infeasible).
  - Cross-validates against the task's task_class.

The airline cancellation slice has no "free variable" comparable to
retail_returns' refund_method. The cancellation reason is supplied by
the user (pinned in intent); eligibility either holds or it doesn't.
So Verify here is binary: 1 model (cancel succeeds) or 0 (refused).

This is a parallel implementation rather than an extension of
clingo_verify.py because the encoding has airline-specific quirks
(composite ids, positional passengers, external insurance_covers,
hours_since_creation computed in Python). The two verifiers will be
unified in a v1 once the spec stack stabilizes.

Run:
  uv run python tools/clingo_verify_airline.py
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import clingo

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "airline"
DB_PATH = DOMAIN_DIR / "db.json"
RULES_PATH = DOMAIN_DIR / "rules.md"
TASKS_PATH = DOMAIN_DIR / "tasks.json"

# Reuse retail_returns verifier's rule extractor — it's domain-agnostic.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clingo_verify import extract_asp_from_rules_md, asp_atom  # noqa: E402


# ============================================================================
# 1. Closed enumerations (asserted as ground facts so rules.md grounds cleanly)
# ============================================================================


CLOSED_ENUM_FACTS = """
cancellation_reason_value(change_of_plan).
cancellation_reason_value(airline_cancelled).
cancellation_reason_value(other).

complaint_type_value(cancelled_flight_complaint).
complaint_type_value(delayed_flight_complaint_with_change_or_cancel).

membership_tier_value(regular).
membership_tier_value(silver).
membership_tier_value(gold).

cabin_class_value(basic_economy).
cabin_class_value(economy).
cabin_class_value(business).
"""


# ============================================================================
# 2. JSON DB → ASP facts
# ============================================================================


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00").rstrip("Z"))


def _hours_between(later_iso: str, earlier_iso: str) -> int:
    """Whole-hour difference between two ISO datetimes (later − earlier)."""
    delta = _parse_iso(later_iso) - _parse_iso(earlier_iso)
    return int(delta.total_seconds() // 3600)


def _asp_safe(s: str) -> str:
    """
    Make a string usable as an ASP constant identifier. ASP requires the
    first character to be a lowercase letter; we prepend 'r' (for
    "reservation") if the lowercased id starts with a digit. This matters
    for real upstream reservation ids like '3FRNFB' and '3RK2T9' that
    would otherwise produce parser errors.
    """
    out = s.lower()
    if not out:
        return out
    if out[0].isalpha() or out[0] == "_":
        return out
    return f"r{out}"


def encode_db(db: dict) -> str:
    """
    Encode the airline DB as ASP facts using the predicate names from
    domains/airline/rules.md §3 + the integrity constraints in §2.
    """
    lines: list[str] = []
    current_time = db["constants"]["current_time"]

    # Numeric constants.
    for k, v in db["constants"].items():
        if isinstance(v, int):
            lines.append(asp_atom("const", k, v))

    # Users.
    for uid, u in db["users"].items():
        lines.append(asp_atom("user", uid))
        lines.append(asp_atom("membership_tier", uid, u["membership_tier"]))

    # Payment methods.
    for pmid, pm in db["payment_methods"].items():
        lines.append(asp_atom("payment_method", pmid))
        lines.append(asp_atom("payment_method_owner", pmid, pm["customer_id"]))
        lines.append(asp_atom("payment_method_type", pmid, pm["type"]))
        if pm["type"] == "credit_card" and pm.get("valid"):
            lines.append(asp_atom("payment_method_credit_card_valid", pmid))
        if pm["type"] in ("gift_card", "travel_certificate"):
            lines.append(asp_atom("payment_method_balance_cents", pmid, pm["balance_cents"]))

    # Flight instances. Identified by the (flight_number, date) pair —
    # quoted strings in ASP need backslash-escaped, but rules.md uses bare
    # identifiers for date strings so we use the YYYY_MM_DD form.
    for key, fi in db["flight_instances"].items():
        fn = fi["flight_number"]
        d = fi["date"].replace("-", "_")  # 2024-05-20 → 2024_05_20
        lines.append(asp_atom("flight_instance", fn.lower(), f"d{d}"))
        lines.append(asp_atom("flight_status", fn.lower(), f"d{d}", fi["status"]))

    # Reservations.
    for rid, r in db["reservations"].items():
        rid_asp = _asp_safe(rid)
        lines.append(asp_atom("reservation", rid_asp))
        lines.append(asp_atom("booking_user", rid_asp, r["booking_user_id"]))
        lines.append(asp_atom("reservation_cabin", rid_asp, r["cabin_class"]))
        lines.append(asp_atom("reservation_status", rid_asp, r["status"]))
        if r.get("has_travel_insurance"):
            lines.append(asp_atom("has_travel_insurance", rid_asp))

        # Segments.
        for seg in r["segments"]:
            d = seg["date"].replace("-", "_")
            lines.append(asp_atom("segment_of", rid_asp, seg["flight_number"].lower(), f"d{d}"))

        # Passengers — positional indices for ASP-grounding purposes.
        for idx in range(len(r["passengers"])):
            lines.append(asp_atom("passenger", rid_asp, idx + 1))

        # Payment usage.
        for pm_id in r["payment_method_ids_used"]:
            lines.append(asp_atom("payment_used", rid_asp, pm_id))

        # External: hours_since_creation.
        hours = _hours_between(current_time, r["created_time"])
        lines.append(asp_atom("hours_since_creation", rid_asp, hours))

    return "\n".join(lines)


# ============================================================================
# 3. Per-task intent → ASP encoding
# ============================================================================


@dataclass
class TaskEncoding:
    """
    ASP encoding of a single airline task for Verify + Solve.

    Fields:
      task_id              : task id from tasks.json (e.g. "AIRLINE-T-001")
      task_class           : "mutating" | "policy_noop" | "intent_noop"
      family               : "cancel" | "noop" — selects encoder/solver path
      hypothetical_facts   : ASP facts the task supplies (e.g. insurance_covers/1)
      action_rules         : per-task ASP fragment (target_reservation/1,
                             cancellation_reason_supplied/2, precondition
                             constraints, #show directives)
      target_reservation_id: upstream-original reservation id (for DB lookup)
      cancellation_reason  : the reason supplied by the intent (for Solve)
    """
    task_id: str
    task_class: str
    family: str
    hypothetical_facts: str
    action_rules: str
    target_reservation_id: str | None = None
    cancellation_reason: str | None = None


def encode_task(task: dict) -> TaskEncoding:
    """
    Build a TaskEncoding from a task's operational_spec.intent.
    Cancellation slice supports two actions: cancel_reservation and none.
    """
    tid = task["id"]
    spec = task["operational_spec"]
    klass = spec["task_class"]
    intent = spec.get("intent") or {}
    action = intent.get("action", "none")

    if action == "none":
        return TaskEncoding(
            task_id=tid, task_class=klass, family="noop",
            hypothetical_facts="", action_rules="",
        )

    if action == "cancel_reservation":
        rid_original = intent["reservation_id"]
        rid_asp = _asp_safe(rid_original)
        reason = intent["cancellation_reason"]
        insurance_covers_flag = intent.get("insurance_covers", False)

        # The external predicate insurance_covers/1: emit a fact iff the
        # task says coverage applies. Otherwise the predicate stays false
        # by negation-as-failure.
        external_facts: list[str] = []
        if insurance_covers_flag:
            external_facts.append(f"insurance_covers({reason}).")

        # The "action rules": pin target_reservation + supplied reason +
        # the three preconditions from actions.md §4.1.
        action_rules = f"""
target_reservation({rid_asp}).
cancellation_reason_supplied({rid_asp}, {reason}).

% Precondition: reservation must be active.
:- target_reservation(R), not reservation_status(R, active).

% Precondition: no flown segment (otherwise the agent must transfer
% — Layer D D-OOS-2; encoded here as Layer C precondition for the
% specific Verify scope where Layer D is not a separate program).
:- target_reservation(R), requires_transfer_for_cancellation(R).

% Precondition: policy permits the cancellation.
:- target_reservation(R), cancellation_reason_supplied(R, Reason),
   not cancellable(R, Reason).

% Expose for inspection.
#show target_reservation/1.
#show cancellable/2.
#show recent_booking/1.
#show has_flown_segment/1.
#show has_airline_cancelled_segment/1.
"""

        return TaskEncoding(
            task_id=tid, task_class=klass,
            family="cancel",
            hypothetical_facts="\n".join(external_facts),
            action_rules=action_rules,
            target_reservation_id=rid_original,  # for db lookup (original case)
            cancellation_reason=reason,
        )

    raise ValueError(f"unknown intent action: {action!r}")


# ============================================================================
# 4. Solving
# ============================================================================


def solve(programs: list[str], max_models: int = 2) -> list[list[str]]:
    """Run Clingo on the listed programs; return each model's atoms."""
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
# 5. Verify
# ============================================================================


@dataclass
class TaskResult:
    """
    Verify result for a single airline task.

    Fields:
      verdict        : 'unique' (1 model — cancel succeeds) /
                       'policy_refused' (0 models — policy correctly denies) /
                       'trivial_noop' (intent_noop, no LP check applicable) /
                       'unexpected' (verdict ≠ task_class)
      model_count    : how many Clingo answer sets satisfy the program
      matches_expected: derived from task_class — mutating wants 1,
                       policy_noop wants 0, intent_noop wants trivial
      sample_model   : first model's shown atoms (for derivation tracing)
    """
    task_id: str
    task_class: str
    family: str
    verdict: str
    model_count: int
    matches_expected: bool
    sample_model: list[str] = field(default_factory=list)
    notes: str = ""


def _expected_for(family: str, task_class: str, model_count: int) -> bool:
    if family == "noop":
        return task_class == "intent_noop"
    if task_class == "mutating":
        return model_count == 1
    if task_class == "policy_noop":
        return model_count == 0
    return False


def reservation_total_cents(reservation: dict) -> int:
    """
    Approximate total payment amount: sum of segment prices × passenger count.
    Real upstream totals include baggage + insurance fees we don't model in
    v0; this is sufficient for Solve diff display + cross-validation that
    "cancel succeeds." Full per-payment allocation is Q-D-A1 v1 work.
    """
    num_pax = len(reservation["passengers"])
    return sum(s["segment_unit_price_cents"] for s in reservation["segments"]) * num_pax


def apply_cancel_reservation(db: dict, reservation_id: str, reason: str) -> tuple[dict, list[str]]:
    """
    Apply cancel_reservation to db (deep copy), return (new_db, structured diff).
    Mirrors the effects spec in actions.md §4.1.
    """
    import copy
    new_db = copy.deepcopy(db)
    r = new_db["reservations"][reservation_id]
    diff: list[str] = []

    # Status + reason.
    diff.append(f"reservation/{reservation_id}.status: active → cancelled")
    diff.append(f"reservation/{reservation_id}.cancellation_reason: null → {reason}")
    r["status"] = "cancelled"
    r["cancellation_reason"] = reason

    # Per-payment refund (v0 single-payment simplification: full amount to
    # the one payment method). Per-payment allocation is Q-D-A1 v1 work.
    total = reservation_total_cents(r)
    for pm_id in r["payment_method_ids_used"]:
        pm = new_db["payment_methods"].get(pm_id)
        if pm is None:
            diff.append(f"(payment_method/{pm_id} not in encoded subset — refund event skipped)")
            continue
        if pm["type"] == "credit_card":
            diff.append(f"event: refund_to_card({pm_id}, {total} cents = ${total/100:.2f})")
        elif pm["type"] == "gift_card":
            old = pm.get("balance_cents", 0)
            pm["balance_cents"] = old + total
            diff.append(f"payment_method/{pm_id}.balance_cents: {old} → {pm['balance_cents']}")
        elif pm["type"] == "travel_certificate":
            diff.append(f"(travel_certificate/{pm_id}: applied amount {total} not refunded — Q8 reading (a))")

    return new_db, diff


@dataclass
class SolveResult:
    """
    Solve result for a single airline task.

    Fields:
      success: did the action simulator run cleanly?
      d_star : the synthesized post-state DB (None if !success)
      diff   : structured list of changes (status flip, reason set,
               per-payment refund events). Empty for refuse/noop families.
      error  : non-empty if success is False (precondition failure,
               unsupported family, action simulator exception)
    """
    task_id: str
    success: bool
    d_star: dict | None = None
    diff: list[str] = field(default_factory=list)
    error: str = ""


def solve_task(encoding: TaskEncoding, db: dict) -> SolveResult:
    """
    Derive D* by applying the cancel action to D₀. Only called when Verify
    has reported `unique` (1 model exists). For refusal tasks, D* = D₀.
    """
    if encoding.family == "noop":
        return SolveResult(task_id=encoding.task_id, success=True, d_star=db, diff=[])

    if encoding.family != "cancel":
        return SolveResult(task_id=encoding.task_id, success=False,
                           error=f"unsupported family for Solve: {encoding.family}")

    # target_reservation_id is the upstream original (e.g., "Q69X3R" or
    # "3FRNFB"); look it up directly.
    rid = encoding.target_reservation_id
    if rid not in db["reservations"]:
        return SolveResult(task_id=encoding.task_id, success=False,
                           error=f"reservation {rid!r} not found in DB")

    try:
        new_db, diff = apply_cancel_reservation(db, rid, encoding.cancellation_reason)
        return SolveResult(task_id=encoding.task_id, success=True,
                           d_star=new_db, diff=diff)
    except Exception as e:
        return SolveResult(task_id=encoding.task_id, success=False,
                           error=f"action simulator failed: {e}")


def verify(encoding: TaskEncoding, d0_facts: str, layer_b: str) -> TaskResult:
    """
    Run Clingo on (closed-enum facts, D₀ facts, Layer B rules,
    hypothetical facts, action rules) and report a TaskResult.

    For policy_noop tasks: success means 0 models exist (policy correctly
    refused). For mutating: success means exactly 1 model exists. For
    intent_noop: returns trivial_noop without running Clingo.
    """
    if encoding.family == "noop":
        return TaskResult(
            task_id=encoding.task_id, task_class=encoding.task_class,
            family=encoding.family, verdict="trivial_noop",
            model_count=0, matches_expected=encoding.task_class == "intent_noop",
        )

    programs = [
        CLOSED_ENUM_FACTS,
        d0_facts,
        layer_b,
        encoding.hypothetical_facts,
        encoding.action_rules,
    ]
    models = solve(programs, max_models=2)

    if encoding.task_class == "policy_noop":
        verdict = "policy_refused" if len(models) == 0 else "unexpected"
    else:
        if len(models) == 0:
            verdict = "infeasible"
        elif len(models) == 1:
            verdict = "unique"
        else:
            verdict = f"ambiguous_{len(models)}plus"

    matches = _expected_for(encoding.family, encoding.task_class, len(models))
    sample = models[0] if models else []

    return TaskResult(
        task_id=encoding.task_id, task_class=encoding.task_class,
        family=encoding.family, verdict=verdict,
        model_count=len(models), matches_expected=matches, sample_model=sample,
    )


# ============================================================================
# 6. Main
# ============================================================================


def main() -> int:
    """
    CLI entry: load D₀ + tasks from domains/airline/, run Verify on each,
    print a results table + per-task derivation traces, return non-zero
    exit code if any task's verdict diverges from its declared task_class.
    """
    print("=" * 78)
    print("Airline retrofit verifier — cancellation slice")
    print("=" * 78)

    db = json.loads(DB_PATH.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)
    d0_facts = encode_db(db)
    tasks = json.loads(TASKS_PATH.read_text())

    print(f"\n[setup] Layer B ASP from rules.md: {len(layer_b)} chars.")
    print(f"[setup] D₀: {len(db['users'])} users, {len(db['reservations'])} reservations, "
          f"{len(db['flight_instances'])} flight instances "
          f"({len(d0_facts.splitlines())} ASP facts).")
    print(f"[setup] {len(tasks)} tasks loaded.")

    results: list[TaskResult] = []
    for t in tasks:
        encoding = encode_task(t)
        result = verify(encoding, d0_facts, layer_b)
        results.append(result)

    print(f"\n{'ID':<18} {'task_class':<14} {'verdict':<18} {'models':<8} ok")
    print("─" * 78)
    for r in results:
        ok = "✓" if r.matches_expected else "✗"
        print(f"{r.task_id:<18} {r.task_class:<14} {r.verdict:<18} {r.model_count:<8} {ok}")

    print("\nPer-task derivation traces:")
    for r in results:
        print(f"\n  {r.task_id}:")
        if r.sample_model:
            for atom in r.sample_model:
                print(f"    • {atom}")
        else:
            print(f"    (no model — policy refused or infeasible)")

    print("\n" + "=" * 78)
    n_ok = sum(1 for r in results if r.matches_expected)
    print(f"SUMMARY: {n_ok}/{len(results)} airline tasks verified.")

    if n_ok != len(results):
        print("\n  Failures:")
        for r in results:
            if not r.matches_expected:
                print(f"    {r.task_id}: verdict={r.verdict}, "
                      f"task_class={r.task_class}")
        return 1

    print("\n  First end-to-end airline retrofit task verifications passing.")
    print("  Layer B's cancellable/2 derivation correctly classifies both branches:")
    print("    • Q69X3R (28h-old, regular, economy, no insurance) → REFUSED")
    print("    • RECENT01 (6h-old, recent_booking branch) → APPROVED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
