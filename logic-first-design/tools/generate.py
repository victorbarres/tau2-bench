#!/usr/bin/env python3
"""
Generate operation — synthesize (D₀, task) pairs from scenario templates.

This is the third methodology operation. Verify and Solve assume D₀ is given;
Generate constructs D₀ from a high-level scenario description, producing a
minimal world that supports the intent. The output passes through the
existing Verify pipeline as a uniqueness gate — if Clingo can't confirm
exactly one D*, the generated task is rejected.

Scope: scaffold generation. Six templates, each parameterized by knobs
(member_tier, days_since_fulfillment, return_class, declared_condition,
declared_reason, refund_method, ...) that produce a single-customer /
single-product / single-order D₀ tuned to the scenario.

Usage:
  # Run all 6 scenarios with default knobs, print results.
  uv run python tools/generate.py

  # One scenario, default knobs.
  uv run python tools/generate.py happy_path_self_return

  # Override one knob.
  uv run python tools/generate.py happy_path_self_return member_tier=plus

  # Sweep: comma-separated values produce a cartesian product of variants.
  uv run python tools/generate.py happy_path_self_return \\
      member_tier=regular,plus days_since_fulfillment=5,15,28,35

  # Export each generated variant to its own task.json + db.json.
  uv run python tools/generate.py --export out/ happy_path_self_return \\
      days_since_fulfillment=5,15,28,35,85

  # Show pruning distribution across a sweep (useful for difficulty audit).
  uv run python tools/generate.py --summary happy_path_self_return \\
      days_since_fulfillment=5,15,28,29,30,31,32,85
"""

from __future__ import annotations

import argparse
import itertools
import json
import re
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


def _verdict_consistent_with_class(verdict: str, task_class: str) -> bool:
    """
    Does the verifier's verdict match what task_class asserts about D*?

    - mutating tasks should be uniquely solvable.
    - policy_noop tasks should be refused by policy (verdict 'infeasible' or
      'policy_refused' — these are the same outcome from different families).
    - intent_noop tasks need no LP check at all.
    """
    if task_class == "mutating":
        return verdict == "unique"
    if task_class == "policy_noop":
        return verdict in ("policy_refused", "infeasible")
    if task_class == "intent_noop":
        return verdict == "trivial_noop"
    return False


def generate_and_verify(scenario_name: str, knobs: dict | None = None,
                        layer_b: str | None = None) -> GenerationResult:
    """
    Run a scenario: build (D₀, task), verify the task, solve to get the diff.

    `matches_expected` is true iff the verifier's verdict is consistent with
    the synthesized task's `task_class` (e.g. mutating → unique;
    policy_noop → policy_refused). When sweeping knobs across a policy
    boundary (in-window → out-of-window), variants that cross the boundary
    will report `matches_expected = False` — which is informative, not an
    error. The synthesis pipeline itself succeeded.
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

    consistent = _verdict_consistent_with_class(
        result.verdict, task["operational_spec"]["task_class"]
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
        matches_expected=consistent,
        error="" if consistent else (
            f"verdict {result.verdict!r} inconsistent with task_class "
            f"{task['operational_spec']['task_class']!r} — likely a regime change "
            f"from sweeping knobs across a policy boundary"
        ),
    )


# ============================================================================
# 5. Knob parsing + sweep
# ============================================================================


def _parse_knob_value(s: str) -> int | str | bool:
    """Coerce a CLI-supplied knob value to int / bool / str (in that order)."""
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    try:
        return int(s)
    except ValueError:
        return s


def parse_knob_args(knob_strs: list[str]) -> dict[str, list]:
    """
    Parse `key=value` or `key=v1,v2,v3` CLI arguments into a dict of lists.
    Each entry's list is the set of values to sweep over for that knob.
    """
    knobs: dict[str, list] = {}
    for s in knob_strs:
        if "=" not in s:
            raise SystemExit(f"bad knob argument {s!r}; expected key=value")
        key, _, raw = s.partition("=")
        values = [_parse_knob_value(v.strip()) for v in raw.split(",")]
        knobs[key.strip()] = values
    return knobs


def sweep(knobs: dict[str, list]) -> list[dict]:
    """Cartesian product over swept knobs. Empty knobs ⇒ a single empty dict."""
    if not knobs:
        return [{}]
    keys = list(knobs.keys())
    value_lists = [knobs[k] for k in keys]
    return [dict(zip(keys, combo)) for combo in itertools.product(*value_lists)]


def variant_suffix(knob_combo: dict) -> str:
    """
    Build a filesystem-safe suffix that uniquely identifies a knob combo.
    Empty combo → empty string. e.g. 'tier-plus_days-15'.
    """
    if not knob_combo:
        return ""
    parts = [f"{k.replace('_', '')}-{v}" for k, v in knob_combo.items()]
    safe = "_".join(parts)
    return "_" + re.sub(r"[^A-Za-z0-9_\-]+", "", safe)


# ============================================================================
# 6. JSON export
# ============================================================================


def export_variant(out_dir: Path, scenario: str, suffix: str,
                   db: dict, task: dict) -> Path:
    """
    Write a generated variant to `out_dir/<scenario><suffix>/{task.json,db.json}`.
    Schema matches the existing domains/retail_returns/tasks.json + db.json so
    these files can be loaded by the same verifier infrastructure.
    """
    variant_dir = out_dir / f"{scenario}{suffix}"
    variant_dir.mkdir(parents=True, exist_ok=True)
    (variant_dir / "task.json").write_text(json.dumps(task, indent=4) + "\n")
    (variant_dir / "db.json").write_text(json.dumps(db, indent=4) + "\n")
    return variant_dir


# ============================================================================
# 7. Main — CLI
# ============================================================================


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="generate.py",
        description="Synthesize (D₀, task) pairs from scenario templates.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Knobs are positional arguments after the scenario name, in\n"
            "`key=value` or `key=v1,v2,v3` form. Multiple values produce a\n"
            "cartesian-product sweep. See the module docstring for examples.\n"
            "\n"
            "Available scenarios:\n"
            + "\n".join(f"  • {name}  ({sc[1].description})"
                       for name, sc in SCENARIOS.items())
        ),
    )
    p.add_argument(
        "scenario",
        nargs="?",
        default="all",
        choices=list(SCENARIOS.keys()) + ["all"],
        help="scenario name, or 'all' to run every scenario with default knobs",
    )
    p.add_argument(
        "knobs",
        nargs="*",
        help="knob overrides as key=value or key=v1,v2,v3 (sweep)",
    )
    p.add_argument(
        "--export",
        type=Path,
        metavar="DIR",
        help="write each generated variant to DIR/<scenario>[<knob-suffix>]/",
    )
    p.add_argument(
        "--summary",
        action="store_true",
        help="condensed table-only output (no D* diff dumps)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    knobs_swept = parse_knob_args(args.knobs)
    combos = sweep(knobs_swept)

    layer_b = extract_asp_from_rules_md(RULES_PATH)

    if args.scenario == "all":
        scenario_names = list(SCENARIOS.keys())
        if combos != [{}]:
            raise SystemExit("knob sweeps require a specific scenario name; not 'all'")
    else:
        scenario_names = [args.scenario]

    print("=" * 78)
    title = (
        f"Generate — scenario={args.scenario!r}, "
        f"{len(combos)} variant(s)"
        + (f", exporting to {args.export}/" if args.export else "")
    )
    print(title)
    print("=" * 78)

    all_results: list[tuple[str, dict, GenerationResult, Path | None]] = []

    for name in scenario_names:
        for combo in combos:
            try:
                r = generate_and_verify(name, combo, layer_b=layer_b)
            except Exception as e:  # pragma: no cover
                print(f"\n  ✗ {name} {combo}: generation failed — {e}")
                return 1

            export_path: Path | None = None
            if args.export:
                suffix = variant_suffix(combo)
                # Rename the in-memory task id to match the export directory.
                r.task["id"] = f"GEN-{name}{suffix}"
                export_path = export_variant(args.export, name, suffix, r.db, r.task)

            all_results.append((name, combo, r, export_path))

    # ---- Table ----
    print(f"\n{'variant':<60} {'pruning':<10} {'verdict':<18} ok")
    print("─" * 100)
    for name, combo, r, export_path in all_results:
        label = name + (f" {combo}" if combo else "")
        if len(label) > 58:
            label = label[:57] + "…"
        pruning = f"{r.free_count}→{r.constrained_count}"
        ok = "✓" if r.matches_expected else "✗"
        line = f"{label:<60} {pruning:<10} {r.verify_verdict:<18} {ok}"
        if export_path:
            # Show relative path if it sits under cwd, else the full path.
            try:
                shown_path = export_path.relative_to(Path.cwd())
            except ValueError:
                shown_path = export_path
            line += f"  → {shown_path}"
        print(line)

    # ---- D* diffs (skipped in summary mode) ----
    if not args.summary:
        print("\nGenerated D* diffs:")
        for name, combo, r, _ in all_results:
            label = name + (f" {combo}" if combo else "")
            print(f"\n  {label}:")
            print(f"    {r.expected.description}")
            if not r.solve_diff:
                print(f"    D* = D₀ (policy correctly handled the request)")
            else:
                for d in r.solve_diff:
                    print(f"    • {d}")

    # ---- Sweep insight ----
    n_combos = len(combos)
    n_consistent = sum(1 for _, _, r, _ in all_results if r.matches_expected)
    if n_combos > 1:
        print("\n" + "─" * 78)
        print(f"Sweep analysis ({n_combos} variants):")
        verdicts = [r.verify_verdict for _, _, r, _ in all_results]
        for v in sorted(set(verdicts)):
            print(f"  {v:<20} {verdicts.count(v)} variant(s)")
        prunings = sorted({(r.free_count, r.constrained_count) for _, _, r, _ in all_results})
        if len(prunings) > 1:
            print(f"  pruning ratios spanned: {prunings}")
        n_regime_changes = n_combos - n_consistent
        if n_regime_changes:
            print(f"  {n_regime_changes} variant(s) crossed a policy regime boundary "
                  f"(verdict ≠ task_class default)")

    # ---- Summary ----
    print("\n" + "=" * 78)
    print(f"SUMMARY: {n_consistent}/{len(all_results)} variants match their declared task_class.")
    inconsistent = [(name, combo, r) for name, combo, r, _ in all_results if not r.matches_expected]
    if inconsistent:
        print("\n  Regime crossings (not necessarily errors when sweeping):")
        for name, combo, r in inconsistent:
            print(f"    {name} {combo}: verdict={r.verify_verdict}, "
                  f"task_class={r.task['operational_spec']['task_class']}")

    if args.export:
        print(f"\n  Wrote {len(all_results)} variant(s) to {args.export}/")
        print(f"  Each directory contains task.json + db.json matching the")
        print(f"  schema of domains/retail_returns/{{tasks,db}}.json.")

    # Exit code: 0 if all variants synthesized cleanly. Regime crossings are
    # informative (especially during knob sweeps) and don't count as failures.
    # Strict consistency is checked only when running a single scenario with
    # no knob overrides (i.e., the user expects the default to hold).
    is_strict = len(scenario_names) == 1 and not knobs_swept
    if is_strict and inconsistent:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
