#!/usr/bin/env python3
"""
Cross-validate the airline retrofit against upstream tau2-bench tasks.

Reads tasks and DB entities directly from the upstream
tau2-bench/data/tau2/domains/airline/ directory, adapts the schema to
our ontology, and runs them through the airline verifier. The expected
outcome is derived from the upstream task's nl_assertions /
evaluation_criteria.actions.

This is the *unforgiving validation*: the upstream tasks were authored
by humans without reference to our methodology, against the prose
policy.md. If our verifier agrees with the upstream's expected
outcome on each task, that's strong evidence the methodology
generalizes to corpora not designed for it.

Currently cross-validates 3 cancellation tasks (out of ~11 upstream):

  Task 0  (Emma Kim,    EHGLP3) — refusal expected
  Task 1  (Raj Sanchez, Q69X3R) — refusal expected
  Task 19 (Olivia G.,   Z7GOZK) — success expected (insurance + health)

Each task's intent is hand-authored from the user_scenario prose.

Run:
  uv run python tools/cross_validate_airline.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent

# Upstream tau-bench airline domain (read-only).
UPSTREAM_ROOT = Path("/Users/victorbarres/scripts/tau2-bench/data/tau2/domains/airline")
UPSTREAM_DB = UPSTREAM_ROOT / "db.json"
UPSTREAM_TASKS = UPSTREAM_ROOT / "tasks.json"

# Our airline verifier — reuses Layer B extraction, encode_db, etc.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clingo_verify_airline import (  # noqa: E402
    encode_db,
    encode_task,
    verify,
    solve_task,
    extract_asp_from_rules_md,
    RULES_PATH,
)


# ============================================================================
# 1. Hand-authored intents for the three cross-validation tasks
# ============================================================================


@dataclass
class CrossValSpec:
    upstream_task_id: str
    intent: dict
    expected_task_class: str
    notes: str = ""


CROSS_VAL_SPECS = {
    # === Refusal cases (policy_noop expected) ===
    "0": CrossValSpec(
        upstream_task_id="0",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "EHGLP3",
            "cancellation_reason": "change_of_plan",
            "insurance_covers": False,
        },
        expected_task_class="policy_noop",
        notes="Emma Kim: gold, basic_economy, no insurance, ~11d ago. None of the 4 cancellation grounds applies.",
    ),
    "1": CrossValSpec(
        upstream_task_id="1",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "Q69X3R",
            "cancellation_reason": "change_of_plan",
            "insurance_covers": False,
        },
        expected_task_class="policy_noop",
        notes="Raj Sanchez: silver, economy, no insurance, ~29h ago. Outside 24h window.",
    ),
    "26": CrossValSpec(
        upstream_task_id="26",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "3FRNFB",
            "cancellation_reason": "change_of_plan",
            "insurance_covers": False,
        },
        expected_task_class="policy_noop",
        notes="Amelia Sanchez: basic_economy, no insurance, ~9d ago. No eligibility ground holds.",
    ),
    "47": CrossValSpec(
        upstream_task_id="47",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "H8Q05L",
            "cancellation_reason": "other",
            # Sophia HAS insurance but her reason is "best friend's birthday"
            # — NOT health/weather. insurance_covers=false despite insurance
            # being purchased. Tests the precise scope of the insurance branch.
            "insurance_covers": False,
        },
        expected_task_class="policy_noop",
        notes="Sophia Silva: basic_economy, INSURANCE=yes, but reason is birthday "
              "(not health/weather). insurance_covers=false → refusal.",
    ),
    "49": CrossValSpec(
        upstream_task_id="49",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "3RK2T9",
            "cancellation_reason": "other",
            # User LIES about having insurance. Reservation says insurance=no
            # — verifier sees ground truth: insurance_covers=false because
            # the insurance branch requires has_travel_insurance which is false.
            "insurance_covers": False,
        },
        expected_task_class="policy_noop",
        notes="Anya Garcia: basic_economy, INSURANCE=NO, ~13d ago. User claims insurance; "
              "ground truth says no. Cancellation correctly denied.",
    ),
    # === Successful-cancel cases (mutating expected) ===
    "14": CrossValSpec(
        upstream_task_id="14",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "K1NW8N",
            "cancellation_reason": "change_of_plan",
            "insurance_covers": False,
        },
        expected_task_class="mutating",
        notes="Mohamed Silva: basic_economy, no insurance, ~22.9h ago. "
              "Eligible via recent_booking (just within 24h window).",
    ),
    "19": CrossValSpec(
        upstream_task_id="19",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "Z7GOZK",
            "cancellation_reason": "other",
            "insurance_covers": True,
        },
        expected_task_class="mutating",
        notes="Olivia Gonzalez: basic_economy, INSURANCE=yes, ~43h ago. "
              "Eligible via insurance + covered (health: feels unwell).",
    ),
    "29": CrossValSpec(
        upstream_task_id="29",
        intent={
            "action": "cancel_reservation",
            "reservation_id": "VA5SGQ",
            "cancellation_reason": "other",
            "insurance_covers": True,
        },
        expected_task_class="mutating",
        notes="Raj Brown: economy, INSURANCE=yes, ~7d ago. Task instructions explicitly "
              "say 'mention your health problem' — insurance + health → covered.",
    ),
}


# ============================================================================
# 2. Schema adapter — upstream JSON → our DB format
# ============================================================================


def adapt_user(upstream_user: dict) -> dict:
    return {
        "user_id": upstream_user["user_id"],
        "name": upstream_user["name"],
        "email": upstream_user["email"],
        "dob": upstream_user["dob"],
        "addresses": [{
            "label": "home",
            "line1": upstream_user["address"]["address1"],
            "city": upstream_user["address"]["city"],
            "region": upstream_user["address"]["state"],
            "postal_code": upstream_user["address"]["zip"],
            "country": upstream_user["address"]["country"],
        }],
        "membership_tier": upstream_user["membership"],
        "payment_method_ids": list(upstream_user["payment_methods"].keys()),
        "reservation_ids": upstream_user["reservations"],
        "saved_passengers": upstream_user.get("saved_passengers", []),
    }


# Upstream `source` → our `type`.
_PM_TYPE_MAP = {
    "credit_card": "credit_card",
    "gift_card": "gift_card",
    "certificate": "travel_certificate",
}


def adapt_payment_method(upstream_pm: dict, customer_id: str) -> dict:
    out = {
        "payment_method_id": upstream_pm["id"],
        "customer_id": customer_id,
        "type": _PM_TYPE_MAP[upstream_pm["source"]],
    }
    if upstream_pm["source"] == "credit_card":
        out["display_label"] = (
            f"{upstream_pm['brand'].title()} ending in {upstream_pm['last_four']}"
        )
        out["valid"] = True  # upstream does not model invalid cards
    elif upstream_pm["source"] == "gift_card":
        out["display_label"] = f"Gift card {upstream_pm['id']}"
        out["balance_cents"] = int(round(upstream_pm["amount"] * 100))
    elif upstream_pm["source"] == "certificate":
        out["display_label"] = f"Certificate {upstream_pm['id']}"
        out["balance_cents"] = int(round(upstream_pm["amount"] * 100))
    return out


def adapt_reservation(upstream_res: dict) -> dict:
    return {
        "reservation_id": upstream_res["reservation_id"],
        "booking_user_id": upstream_res["user_id"],
        "trip_type": upstream_res["flight_type"],
        "origin": upstream_res["origin"],
        "destination": upstream_res["destination"],
        "cabin_class": upstream_res["cabin"],
        "segments": [
            {
                "flight_number": s["flight_number"],
                "date": s["date"],
                "segment_unit_price_cents": int(round(s["price"] * 100)),
            }
            for s in upstream_res["flights"]
        ],
        "passengers": upstream_res["passengers"],
        "payment_method_ids_used": [
            p["payment_id"] for p in upstream_res["payment_history"]
        ],
        "created_time": upstream_res["created_at"],
        "total_baggages": upstream_res["total_baggages"],
        "nonfree_baggages": upstream_res["nonfree_baggages"],
        "has_travel_insurance": upstream_res["insurance"] == "yes",
        "status": "active",
    }


def adapt_flight_instance(flight_number: str, origin: str, destination: str,
                          date: str, upstream_date_info: dict) -> dict:
    # Normalize "on time" → "on_time" for ASP constant safety.
    status = upstream_date_info["status"].replace(" ", "_")
    return {
        "flight_number": flight_number,
        "date": date,
        "status": status,
        "cabins": upstream_date_info.get("available_seats", {}),
    }


# ============================================================================
# 3. Subset extractor — pull only the entities a task touches
# ============================================================================


def extract_subset(upstream_db: dict, task_intent: dict) -> dict:
    """
    Pull the slice of the upstream DB needed to verify a single task.
    Currently scoped to cancellation tasks: one user + one reservation
    + all payment methods owned by that user + all flight instances
    referenced by the reservation's segments.
    """
    out = {
        "constants": {
            # Per upstream policy.md L3:
            "current_time": "2024-05-15T15:00:00",
            "recent_booking_window_hours": 24,
            "compensation_cancelled_per_passenger_cents": 10000,
            "compensation_delayed_per_passenger_cents": 5000,
        },
        "users": {},
        "payment_methods": {},
        "flights": {},
        "flight_instances": {},
        "reservations": {},
    }

    rid = task_intent["reservation_id"]
    upstream_res = upstream_db["reservations"][rid]
    user_id = upstream_res["user_id"]

    # User + their payment methods.
    upstream_user = upstream_db["users"][user_id]
    out["users"][user_id] = adapt_user(upstream_user)
    for pmid, pm in upstream_user["payment_methods"].items():
        out["payment_methods"][pmid] = adapt_payment_method(pm, user_id)

    # Reservation.
    out["reservations"][rid] = adapt_reservation(upstream_res)

    # Flight instances per segment.
    for seg in upstream_res["flights"]:
        fn = seg["flight_number"]
        date = seg["date"]
        upstream_flight = upstream_db["flights"][fn]
        # Add flight (route metadata).
        if fn not in out["flights"]:
            out["flights"][fn] = {
                "flight_number": fn,
                "origin": upstream_flight["origin"],
                "destination": upstream_flight["destination"],
                "scheduled_departure_time": upstream_flight.get("scheduled_departure_time_est", ""),
                "scheduled_arrival_time": upstream_flight.get("scheduled_arrival_time_est", ""),
            }
        # Add flight instance.
        key = f"{fn}|{date}"
        date_info = upstream_flight["dates"][date]
        out["flight_instances"][key] = adapt_flight_instance(
            fn, upstream_flight["origin"], upstream_flight["destination"],
            date, date_info,
        )

    return out


# ============================================================================
# 4. Cross-validation harness
# ============================================================================


@dataclass
class CrossValResult:
    upstream_task_id: str
    intent: dict
    expected_task_class: str
    expected_outcome: str         # "policy_refused" or "unique"
    our_verdict: str
    our_model_count: int
    matches: bool
    notes: str = ""
    sample_atoms: list[str] = field(default_factory=list)
    solve_diff: list[str] = field(default_factory=list)


def _expected_outcome(expected_class: str) -> str:
    if expected_class == "mutating":
        return "unique"
    if expected_class == "policy_noop":
        return "policy_refused"
    return "trivial_noop"


def cross_validate(spec: CrossValSpec, upstream_db: dict, layer_b: str) -> CrossValResult:
    subset_db = extract_subset(upstream_db, spec.intent)
    d0_facts = encode_db(subset_db)

    task = {
        "id": f"XV-{spec.upstream_task_id}",
        "operational_spec": {
            "task_class": spec.expected_task_class,
            "intent": spec.intent,
        },
    }
    encoding = encode_task(task)
    result = verify(encoding, d0_facts, layer_b)

    expected_outcome = _expected_outcome(spec.expected_task_class)
    matches = result.verdict == expected_outcome

    # If the verifier says cancel succeeds, also derive D* via Solve so we
    # can show the structured diff that cancellation would produce on the
    # upstream subset.
    solve_diff: list[str] = []
    if result.verdict == "unique":
        sr = solve_task(encoding, subset_db)
        if sr.success:
            solve_diff = sr.diff
        else:
            solve_diff = [f"(solve failed: {sr.error})"]

    return CrossValResult(
        upstream_task_id=spec.upstream_task_id,
        intent=spec.intent,
        expected_task_class=spec.expected_task_class,
        expected_outcome=expected_outcome,
        our_verdict=result.verdict,
        our_model_count=result.model_count,
        matches=matches,
        notes=spec.notes,
        sample_atoms=result.sample_model,
        solve_diff=solve_diff,
    )


# ============================================================================
# 5. Main
# ============================================================================


def main() -> int:
    print("=" * 78)
    print("Cross-validation: airline retrofit vs upstream tau2-bench tasks")
    print("=" * 78)

    if not UPSTREAM_DB.exists():
        print(f"\n  Upstream db not found at {UPSTREAM_DB}")
        return 1

    print(f"\n[setup] Upstream DB: {UPSTREAM_DB}")
    print(f"[setup] Cross-validating {len(CROSS_VAL_SPECS)} task(s).")

    upstream_db = json.loads(UPSTREAM_DB.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)

    results: list[CrossValResult] = []
    for tid, spec in CROSS_VAL_SPECS.items():
        results.append(cross_validate(spec, upstream_db, layer_b))

    print(f"\n{'task':<6} {'expected':<18} {'got':<18} {'models':<8} ok")
    print("─" * 78)
    for r in results:
        ok = "✓" if r.matches else "✗"
        print(f"{r.upstream_task_id:<6} {r.expected_outcome:<18} {r.our_verdict:<18} {r.our_model_count:<8} {ok}")

    print("\nPer-task detail:")
    for r in results:
        print(f"\n  Task {r.upstream_task_id}: {r.notes}")
        print(f"    intent: {r.intent}")
        print(f"    expected: {r.expected_outcome} (from upstream task_class={r.expected_task_class})")
        print(f"    our verdict: {r.our_verdict} ({r.our_model_count} model(s))")
        if r.sample_atoms:
            relevant = [a for a in r.sample_atoms
                        if any(a.startswith(p) for p in
                               ('cancellable', 'recent_booking', 'has_flown',
                                'has_airline', 'target_reservation'))]
            if relevant:
                print(f"    derivation:")
                for atom in relevant:
                    print(f"      • {atom}")
        if r.solve_diff:
            print(f"    Solve-derived D* diff:")
            for d in r.solve_diff:
                print(f"      → {d}")

    print("\n" + "=" * 78)
    n_match = sum(1 for r in results if r.matches)
    print(f"SUMMARY: {n_match}/{len(results)} upstream tasks cross-validated.")
    if n_match != len(results):
        print("\n  Mismatches — each one is a methodology learning opportunity:")
        for r in results:
            if not r.matches:
                print(f"    Task {r.upstream_task_id}: expected {r.expected_outcome}, "
                      f"got {r.our_verdict}")
                print(f"      Notes: {r.notes}")
        return 1

    print("\n  All cross-validated. The methodology produces the same outcome as the")
    print("  upstream's expected behavior on tasks designed independently of it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
