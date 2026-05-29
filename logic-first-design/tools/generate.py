#!/usr/bin/env python3
"""
Generate operation — synthesize (D₀, task) pairs from scenario templates.

This is the third methodology operation. Verify and Solve assume D₀ is given;
Generate constructs D₀ from a high-level scenario description, producing a
minimal world that supports the intent. The output passes through the
existing Verify pipeline as a uniqueness gate — if Clingo can't confirm
exactly one D*, the generated task is rejected.

v0 scope: scaffold generation. Six templates, each parameterized by knobs
(member_tier, days_since_fulfillment, return_class, condition/reason,
refund_method, ...) that produce a single-customer / single-product /
single-order D₀ tuned to the scenario. No near-miss noise; no automatic
difficulty tuning. Those are v0.1.

Run:
  uv run python tools/generate.py
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

# Reuse the verify pipeline.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clingo_verify import (  # noqa: E402
    encode_task,
    encode_db,
    extract_asp_from_rules_md,
    solve_task,
    verify,
    RULES_PATH,
)


# ============================================================================
# 1. Defaults for synthesized entities
# ============================================================================


DEFAULT_CURRENT_TIME = "2026-06-15T12:00:00Z"
DEFAULT_CONSTANTS = {
    "current_time": DEFAULT_CURRENT_TIME,
    "standard_return_window_days": 30,
    "plus_member_extension_days": 60,
    "defective_return_window_days": 365,
    "damaged_in_shipping_window_days": 14,
    "perishable_defect_report_hours": 48,
    "restocking_fee_percent": 15,
    "gift_return_to_purchaser_threshold_cents": 5000,
}


def _iso(dt: datetime) -> str:
    """Format a UTC datetime as ISO 8601 with trailing Z (matches db.json convention)."""
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _offset(current_time: str, days: int) -> str:
    """Return ISO datetime `days` before current_time."""
    return _iso(_parse_iso(current_time) - timedelta(days=days))


# ============================================================================
# 2. Entity factory — common building blocks
# ============================================================================


def _customer(cid: str, *, member_tier: str = "regular",
              store_credit_balance_cents: int = 0,
              payment_method_ids: list[str] | None = None,
              order_ids: list[str] | None = None) -> dict:
    return {
        "customer_id": cid,
        "name": f"Generated {cid}",
        "email": f"{cid}@example.com",
        "addresses": [{
            "label": "shipping", "line1": "1 Generated St",
            "city": "Cambridge", "region": "MA", "postal_code": "02139", "country": "US",
        }],
        "member_tier": member_tier,
        "payment_method_ids": payment_method_ids or [],
        "store_credit_balance_cents": store_credit_balance_cents,
        "order_ids": order_ids or [],
    }


def _credit_card(pmid: str, customer_id: str, *, valid: bool = True) -> dict:
    return {
        "payment_method_id": pmid,
        "customer_id": customer_id,
        "type": "credit_card",
        "display_label": f"Visa for {customer_id}",
        "valid": valid,
    }


def _product(pid: str, *, return_class: str = "standard",
             replacement_available: bool = True) -> dict:
    return {
        "product_id": pid,
        "sku": f"GEN-{pid.upper()}",
        "name": f"Generated {pid}",
        "category": "generic",
        "return_class": return_class,
        "manufacturer": "Generated Co",
        "replacement_available": replacement_available,
    }


def _order(oid: str, *, purchaser_id: str, recipient_id: str | None,
           payment_method_id: str | None, fulfillment_date: str | None,
           items: list[dict], status: str = "delivered") -> dict:
    order_date = _offset(fulfillment_date, 4) if fulfillment_date else _offset(DEFAULT_CURRENT_TIME, 7)
    total = sum(it["unit_price_cents"] * it["quantity"] for it in items)
    return {
        "order_id": oid,
        "purchaser_customer_id": purchaser_id,
        "recipient_customer_id": recipient_id,
        "order_date": order_date,
        "fulfillment_date": fulfillment_date,
        "payment_method_id": payment_method_id,
        "status": status,
        "total_amount_cents": total,
        "items": items,
    }


def _order_item(oiid: str, order_id: str, product_id: str,
                unit_price_cents: int, quantity: int = 1) -> dict:
    return {
        "order_item_id": oiid,
        "order_id": order_id,
        "product_id": product_id,
        "quantity": quantity,
        "unit_price_cents": unit_price_cents,
        "fulfilled_quantity": quantity,
        "returned_quantity": 0,
    }


def _empty_db() -> dict:
    """Skeleton DB satisfying the JSON schema with all entity buckets empty."""
    return {
        "constants": dict(DEFAULT_CONSTANTS),
        "customers": {},
        "products": {},
        "payment_methods": {},
        "orders": {},
        "returns": {},
    }


# ============================================================================
# 3. Scenarios
# ============================================================================


@dataclass
class Scenario:
    name: str
    expected_task_class: str           # "mutating" | "policy_noop"
    expected_pruning: tuple[int, int]  # (free, constrained); refuse: (0, 0)
    knobs: dict = field(default_factory=dict)
    description: str = ""


def gen_happy_path_self_return(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Self-purchaser returns a standard item within window. Restocking fee
    applies (opened_unused + standard + customer-choice). Refund method is
    pinned by the knob; if absent, defaults to original_payment.
    """
    k = {
        "member_tier": "regular",
        "days_since_fulfillment": 10,
        "unit_price_cents": 5000,
        "declared_condition": "opened_unused",
        "declared_reason": "change_of_mind",
        "refund_method": "original_payment",
        **knobs,
    }

    db = _empty_db()
    cid, pmid, pid, oid, oiid = "gen_cust", "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][cid] = _customer(cid, member_tier=k["member_tier"],
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, cid)
    db["products"][pid] = _product(pid)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, k["days_since_fulfillment"])
    item = _order_item(oiid, oid, pid, k["unit_price_cents"])
    db["orders"][oid] = _order(oid, purchaser_id=cid, recipient_id=None,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid,
        "customer_id": cid,
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": k["declared_condition"],
            "declared_reason": k["declared_reason"],
        }],
        "refund_method": k["refund_method"],
    }
    return db, _task_envelope(task_id, "mutating", intent)


def gen_gift_return(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Gift order: purchaser ≠ recipient. Recipient initiates the return; policy
    forces store_credit. Pruning is 1→1 because the gift case collapses to
    a single eligible refund method before C_hard.
    """
    k = {
        "purchaser_tier": "plus",
        "recipient_tier": "regular",
        "days_since_fulfillment": 10,
        "unit_price_cents": 7000,
        "declared_condition": "new_unopened",
        "declared_reason": "change_of_mind",
        **knobs,
    }

    db = _empty_db()
    pid, rid = "gen_purchaser", "gen_recipient"
    pmid, prod_id, oid, oiid = "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][pid] = _customer(pid, member_tier=k["purchaser_tier"],
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["customers"][rid] = _customer(rid, member_tier=k["recipient_tier"], order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, pid)
    db["products"][prod_id] = _product(prod_id)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, k["days_since_fulfillment"])
    item = _order_item(oiid, oid, prod_id, k["unit_price_cents"])
    db["orders"][oid] = _order(oid, purchaser_id=pid, recipient_id=rid,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid,
        "customer_id": rid,  # the recipient initiates
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": k["declared_condition"],
            "declared_reason": k["declared_reason"],
        }],
        "refund_method": "store_credit",  # forced by policy
    }
    return db, _task_envelope(task_id, "mutating", intent)


def gen_exchange_defective(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Defective item on a self-purchased order with a replacement available.
    Three refund methods eligible; C_hard pins exchange. Pruning 3→1.
    """
    k = {
        "member_tier": "plus",
        "days_since_fulfillment": 3,
        "unit_price_cents": 40000,
        **knobs,
    }
    db = _empty_db()
    cid, pmid, pid, oid, oiid = "gen_cust", "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][cid] = _customer(cid, member_tier=k["member_tier"],
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, cid)
    db["products"][pid] = _product(pid, replacement_available=True)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, k["days_since_fulfillment"])
    item = _order_item(oiid, oid, pid, k["unit_price_cents"])
    db["orders"][oid] = _order(oid, purchaser_id=cid, recipient_id=None,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid, "customer_id": cid,
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": "defective", "declared_reason": "defective",
        }],
        "refund_method": "exchange",
    }
    return db, _task_envelope(task_id, "mutating", intent)


def gen_window_refusal(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Self-return one day outside the applicable window. Policy refuses;
    Generate produces a policy_noop task that Verify reports as 0→0.
    """
    k = {
        "member_tier": "regular",       # 30-day window
        "days_since_fulfillment": 31,   # 1 day outside
        "unit_price_cents": 4000,
        **knobs,
    }
    db = _empty_db()
    cid, pmid, pid, oid, oiid = "gen_cust", "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][cid] = _customer(cid, member_tier=k["member_tier"],
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, cid)
    db["products"][pid] = _product(pid)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, k["days_since_fulfillment"])
    item = _order_item(oiid, oid, pid, k["unit_price_cents"])
    db["orders"][oid] = _order(oid, purchaser_id=cid, recipient_id=None,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid, "customer_id": cid,
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": "opened_unused", "declared_reason": "change_of_mind",
        }],
        # No refund_method — refusal task.
    }
    return db, _task_envelope(task_id, "policy_noop", intent)


def gen_non_returnable_refusal(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Self-return on a product whose return_class is non-returnable
    (final_sale / digital / hazmat). Policy refuses regardless of timing.
    """
    k = {
        "return_class": "final_sale",
        "days_since_fulfillment": 5,
        **knobs,
    }
    db = _empty_db()
    cid, pmid, pid, oid, oiid = "gen_cust", "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][cid] = _customer(cid, member_tier="regular",
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, cid)
    db["products"][pid] = _product(pid, return_class=k["return_class"],
                                    replacement_available=False)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, k["days_since_fulfillment"])
    item = _order_item(oiid, oid, pid, 5000)
    db["orders"][oid] = _order(oid, purchaser_id=cid, recipient_id=None,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid, "customer_id": cid,
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": "new_unopened", "declared_reason": "change_of_mind",
        }],
    }
    return db, _task_envelope(task_id, "policy_noop", intent)


def gen_wrong_initiator_refusal(task_id: str, knobs: dict) -> tuple[dict, dict]:
    """
    Gift order, but the purchaser tries to return it (instead of the
    recipient). eligible_to_initiate fails; policy refuses.
    """
    db = _empty_db()
    pid, rid = "gen_purchaser", "gen_recipient"
    pmid, prod_id, oid, oiid = "gen_pm", "gen_prod", "gen_ord", "gen_oi"

    db["customers"][pid] = _customer(pid, member_tier="regular",
                                     payment_method_ids=[pmid], order_ids=[oid])
    db["customers"][rid] = _customer(rid, member_tier="regular", order_ids=[oid])
    db["payment_methods"][pmid] = _credit_card(pmid, pid)
    db["products"][prod_id] = _product(prod_id)
    fulfillment = _offset(DEFAULT_CURRENT_TIME, 10)
    item = _order_item(oiid, oid, prod_id, 5000)
    db["orders"][oid] = _order(oid, purchaser_id=pid, recipient_id=rid,
                                payment_method_id=pmid, fulfillment_date=fulfillment,
                                items=[item])

    intent = {
        "action": "initiate_and_approve",
        "order_id": oid,
        "customer_id": pid,   # WRONG — purchaser, not recipient
        "items": [{
            "order_item_id": oiid, "quantity": 1,
            "declared_condition": "new_unopened", "declared_reason": "change_of_mind",
        }],
    }
    return db, _task_envelope(task_id, "policy_noop", intent)


SCENARIOS: dict[str, tuple[Callable, Scenario]] = {
    "happy_path_self_return": (
        gen_happy_path_self_return,
        Scenario("happy_path_self_return", "mutating", (2, 1),
                 description="regular member, recent self-purchase, restocking fee path"),
    ),
    "gift_return_forced_store_credit": (
        gen_gift_return,
        Scenario("gift_return_forced_store_credit", "mutating", (1, 1),
                 description="recipient initiates; policy forces store_credit"),
    ),
    "exchange_defective": (
        gen_exchange_defective,
        Scenario("exchange_defective", "mutating", (3, 1),
                 description="defective + replacement available → 3 eligible methods"),
    ),
    "window_refusal": (
        gen_window_refusal,
        Scenario("window_refusal", "policy_noop", (0, 0),
                 description="self-purchase, 1 day outside 30-day window"),
    ),
    "non_returnable_refusal": (
        gen_non_returnable_refusal,
        Scenario("non_returnable_refusal", "policy_noop", (0, 0),
                 description="final_sale product; no return possible"),
    ),
    "wrong_initiator_refusal": (
        gen_wrong_initiator_refusal,
        Scenario("wrong_initiator_refusal", "policy_noop", (0, 0),
                 description="purchaser tries to return their own gift"),
    ),
}


# ============================================================================
# 4. Task envelope and verification
# ============================================================================


def _task_envelope(task_id: str, task_class: str, intent: dict) -> dict:
    """Wrap an intent into a minimal tasks.json-compatible task object."""
    return {
        "id": task_id,
        "operational_spec": {"task_class": task_class, "intent": intent},
        "evaluation_criteria": {"actions": []},
    }


@dataclass
class GenerationResult:
    scenario: str
    expected: Scenario
    db: dict
    task: dict
    verify_verdict: str
    free_count: int
    constrained_count: int
    solve_diff: list[str]
    matches_expected: bool
    error: str = ""


def generate_and_verify(scenario_name: str, knobs: dict | None = None,
                        layer_b: str | None = None) -> GenerationResult:
    """
    Run a scenario: build (D₀, task), verify the task, solve to get the diff,
    confirm the pruning ratio matches the scenario's expectation.
    """
    if scenario_name not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario_name!r}")
    gen_fn, expected = SCENARIOS[scenario_name]

    if layer_b is None:
        layer_b = extract_asp_from_rules_md(RULES_PATH)

    task_id = f"GEN-{scenario_name}"
    db, task = gen_fn(task_id, knobs or {})
    encoding = encode_task(task)
    d0_facts = encode_db(db, db["constants"]["current_time"])

    result = verify(encoding, d0_facts, layer_b, db=db)
    sr = solve_task(encoding, db, layer_b)

    matches = (
        (result.free_count, result.constrained_count) == expected.expected_pruning
        and result.matches_expected
    )

    return GenerationResult(
        scenario=scenario_name,
        expected=expected,
        db=db,
        task=task,
        verify_verdict=result.verdict,
        free_count=result.free_count,
        constrained_count=result.constrained_count,
        solve_diff=sr.diff,
        matches_expected=matches,
        error="" if matches else f"expected pruning {expected.expected_pruning}, got ({result.free_count}, {result.constrained_count})",
    )


# ============================================================================
# 5. Main — run all scenarios
# ============================================================================


def main() -> int:
    print("=" * 78)
    print("Generate operation — synthesize (D₀, task) pairs from scenario templates")
    print("=" * 78)

    layer_b = extract_asp_from_rules_md(RULES_PATH)
    results: list[GenerationResult] = []
    for name in SCENARIOS:
        try:
            results.append(generate_and_verify(name, layer_b=layer_b))
        except Exception as e:  # pragma: no cover — surface generation errors
            print(f"\n  ✗ {name}: generation failed — {e}")
            return 1

    print(f"\n{'scenario':<35} {'expected':<12} {'got':<12} {'verdict':<18} ok")
    print("─" * 78)
    for r in results:
        exp = f"({r.expected.expected_pruning[0]}, {r.expected.expected_pruning[1]})"
        got = f"({r.free_count}, {r.constrained_count})"
        ok = "✓" if r.matches_expected else "✗"
        print(f"{r.scenario:<35} {exp:<12} {got:<12} {r.verify_verdict:<18} {ok}")

    print("\nGenerated D* diffs (Solve outputs on the synthesized D₀):")
    for r in results:
        print(f"\n  {r.scenario}:")
        print(f"    {r.expected.description}")
        if not r.solve_diff:
            print(f"    D* = D₀ (no mutation; policy correctly handled the request)")
        else:
            for d in r.solve_diff:
                print(f"    • {d}")

    print("\n" + "=" * 78)
    n_ok = sum(1 for r in results if r.matches_expected)
    print(f"SUMMARY: {n_ok}/{len(results)} scenarios generated and verified.")
    if n_ok != len(results):
        print("\n  Failures:")
        for r in results:
            if not r.matches_expected:
                print(f"    {r.scenario}: {r.error}")
        return 1

    print("\n  Generate operation working. The methodology now has:")
    print("    Verify  — soundness + uniqueness for any (D₀, OperationalSpec).")
    print("    Solve   — derive D* from spec alone, no gold trajectory.")
    print("    Generate — synthesize D₀ from scenario template, end-to-end verified.")
    print("\n  Generated tasks can be exported to tasks.json + db.json for")
    print("  inclusion in a benchmark corpus. Each is provably uniquely solvable.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
