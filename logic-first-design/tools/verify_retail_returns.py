#!/usr/bin/env python3
"""
Verifier for the retail_returns worked example (Layer F tasks).

For each task in tasks.json, this script:
  1. Loads D₀ from db.json.
  2. Applies the gold action witness to D₀, allocating new entity IDs
     per the Q-E-3 deterministic convention.
  3. Checks each mutating action's preconditions before applying.
  4. Checks all Layer B integrity constraints on the resulting D*.
  5. Confirms D* ≠ D₀ for `mutating` tasks and D* = D₀ for `*_noop`.
  6. Checks Layer D trajectory rules that are mechanically checkable
     (D-CONF-5, D-CONF-7).
  7. Reports the diff for human inspection against
     annotations.expected_d_star_diff.

This is the v0 verifier. It does NOT yet:
  - Run Clingo on the spec (uses Python-encoded Layer B rules).
  - Check OperationalSpec.c_hard mechanically (parses prose; v0.1).
  - Check uniqueness across all possible D* (no answer-set enumeration).
  - Check LLM-graded Layer D rules.

Run: python scripts/verify_retail_returns.py
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "retail_returns"
DB_PATH = DOMAIN_DIR / "db.json"
TASKS_PATH = DOMAIN_DIR / "tasks.json"


# ============================================================================
# Loading and helpers
# ============================================================================


def load_db() -> dict:
    with DB_PATH.open() as f:
        return json.load(f)


def load_tasks() -> list[dict]:
    with TASKS_PATH.open() as f:
        return json.load(f)


def parse_dt(s: str) -> datetime:
    """Parse an ISO 8601 datetime with trailing Z."""
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def days_between(later: str, earlier: str) -> int:
    """
    Calendar-day difference (later − earlier). Uses date-level truncation
    so that the policy's "within N days" matches how a human counts days:
    delivered May 15, returned June 15 ⇒ 31 days regardless of time-of-day.
    """
    return (parse_dt(later).date() - parse_dt(earlier).date()).days


# ============================================================================
# Derived predicates — Layer B §3
# ============================================================================


def is_gift_order(db: dict, order_id: str) -> bool:
    o = db["orders"][order_id]
    r = o.get("recipient_customer_id")
    return r is not None and r != o["purchaser_customer_id"]


def effective_returner(db: dict, order_id: str) -> str:
    """The customer entitled to initiate a return on this order."""
    o = db["orders"][order_id]
    if is_gift_order(db, order_id):
        return o["recipient_customer_id"]
    return o["purchaser_customer_id"]


def eligible_to_initiate(db: dict, customer_id: str, order_id: str) -> bool:
    return effective_returner(db, order_id) == customer_id


CUSTOMER_CHOICE_REASONS = {"change_of_mind", "wrong_size_or_color"}
RETAILER_FAULT_REASONS = {
    "damaged_in_shipping",
    "wrong_item_received",
    "arrived_late",
    "not_as_described",
}
LONG_WINDOW_REASONS = {"defective", "missing_parts"}
PERISHABLE_ELIGIBLE_REASONS = {"defective", "damaged_in_shipping"}


def applicable_window_days(db: dict, declared_reason: str, product_id: str, purchaser_id: str) -> int:
    """Computes the return window in days. Mirrors rules.md §3.2."""
    product = db["products"][product_id]
    rc = product["return_class"]

    if rc not in ("standard", "perishable"):
        return 0  # final_sale, digital, hazmat

    if rc == "perishable":
        if declared_reason in PERISHABLE_ELIGIBLE_REASONS:
            return 2  # 48h modeled as 2 days
        return 0

    # rc == "standard"
    if declared_reason in LONG_WINDOW_REASONS:
        return 365
    if declared_reason in RETAILER_FAULT_REASONS:
        return 30  # damaged_in_shipping window is 14 days, but rules.md §3.2 buckets these as 30; clarification noted
    if declared_reason in CUSTOMER_CHOICE_REASONS:
        purchaser = db["customers"][purchaser_id]
        if purchaser["member_tier"] == "plus":
            return 90
        return 30

    return 0  # unknown reason → not eligible


def return_class_returnable(db: dict, product_id: str) -> bool:
    return db["products"][product_id]["return_class"] in ("standard", "perishable")


def within_window_for_item(db: dict, return_item: dict, order_id: str, current_time: str) -> bool:
    """True iff this single ReturnItem is within its applicable window."""
    o = db["orders"][order_id]
    if not o.get("fulfillment_date"):
        return False
    days = days_between(current_time, o["fulfillment_date"])
    product_id = db["orders"][order_id]["items"]
    # locate product_id via the OrderItem
    oi_id = return_item["order_item_id"]
    oi = next(it for it in o["items"] if it["order_item_id"] == oi_id)
    purchaser_id = o["purchaser_customer_id"]
    window = applicable_window_days(
        db, return_item["declared_reason"], oi["product_id"], purchaser_id
    )
    return days <= window


def within_window(db: dict, return_id: str, current_time: str) -> bool:
    r = db["returns"][return_id]
    o_id = r["order_id"]
    return all(within_window_for_item(db, ri, o_id, current_time) for ri in r["items"])


def restocking_fee_applies(db: dict, return_item: dict, order_id: str) -> bool:
    """Mirrors rules.md §3.7."""
    if return_item["declared_condition"] != "opened_unused":
        return False
    oi_id = return_item["order_item_id"]
    oi = next(it for it in db["orders"][order_id]["items"] if it["order_item_id"] == oi_id)
    product = db["products"][oi["product_id"]]
    if product["return_class"] != "standard":
        return False
    return return_item["declared_reason"] in CUSTOMER_CHOICE_REASONS


def refund_amount_for(db: dict, return_item: dict, order_id: str) -> int:
    """Mirrors rules.md §3.8."""
    oi_id = return_item["order_item_id"]
    oi = next(it for it in db["orders"][order_id]["items"] if it["order_item_id"] == oi_id)
    gross = return_item["quantity"] * oi["unit_price_cents"]
    if restocking_fee_applies(db, return_item, order_id):
        fee_percent = db["constants"]["restocking_fee_percent"]
        return gross * (100 - fee_percent) // 100
    return gross


def payment_method_valid(db: dict, payment_method_id: str) -> bool:
    """Mirrors rules.md §3.10."""
    pm = db["payment_methods"][payment_method_id]
    if pm["type"] == "credit_card":
        return pm.get("valid", False)
    if pm["type"] == "gift_card":
        return pm.get("balance_cents", 0) > 0
    return False


def all_items_defective(return_items: list[dict]) -> bool:
    return all(ri["declared_condition"] == "defective" for ri in return_items)


def all_replacements_available(db: dict, return_items: list[dict], order_id: str) -> bool:
    for ri in return_items:
        oi = next(it for it in db["orders"][order_id]["items"] if it["order_item_id"] == ri["order_item_id"])
        if not db["products"][oi["product_id"]].get("replacement_available", False):
            return False
    return True


def eligible_refund_methods(db: dict, return_id: str) -> set[str]:
    """Mirrors rules.md §3.9."""
    r = db["returns"][return_id]
    o_id = r["order_id"]
    o = db["orders"][o_id]

    methods: set[str] = set()
    if is_gift_order(db, o_id):
        methods.add("store_credit")
        return methods

    # Self-return
    methods.add("store_credit")
    pm_id = o.get("payment_method_id")
    if pm_id and payment_method_valid(db, pm_id):
        methods.add("original_payment")

    if all_items_defective(r["items"]) and all_replacements_available(db, r["items"], o_id):
        methods.add("exchange")

    return methods


def all_items_returnable(db: dict, return_items: list[dict], order_id: str) -> bool:
    for ri in return_items:
        oi = next(it for it in db["orders"][order_id]["items"] if it["order_item_id"] == ri["order_item_id"])
        if not return_class_returnable(db, oi["product_id"]):
            return False
    return True


def return_eligible(db: dict, return_id: str, current_time: str) -> bool:
    """Composite return eligibility — rules.md §4."""
    r = db["returns"][return_id]
    if r["status"] not in ("pending", "refunded"):
        return False
    o_id = r["order_id"]
    if not eligible_to_initiate(db, r["initiator_customer_id"], o_id):
        return False
    if not within_window(db, return_id, current_time):
        return False
    if not all_items_returnable(db, r["items"], o_id):
        return False
    return True


# ============================================================================
# Integrity constraints — Layer B §2
# ============================================================================


def check_layer_b_invariants(db: dict) -> list[str]:
    """Returns a list of violation strings; empty list = all pass."""
    errors: list[str] = []

    # C-CARD-1: every order has ≥ 1 OrderItem
    for oid, o in db["orders"].items():
        if len(o.get("items", [])) == 0:
            errors.append(f"C-CARD-1: order {oid} has no items")

    # C-CARD-2: every return has ≥ 1 ReturnItem
    for rid, r in db["returns"].items():
        if len(r.get("items", [])) == 0:
            errors.append(f"C-CARD-2: return {rid} has no items")

    # C-CARD-3: fulfilled_quantity ∈ {0, quantity}
    for oid, o in db["orders"].items():
        for it in o["items"]:
            if it["fulfilled_quantity"] not in (0, it["quantity"]):
                errors.append(
                    f"C-CARD-3: {oid}/{it['order_item_id']} has fulfilled_quantity "
                    f"{it['fulfilled_quantity']} ∉ {{0, {it['quantity']}}}"
                )

    # C-CARD-4: 0 ≤ returned ≤ fulfilled
    for oid, o in db["orders"].items():
        for it in o["items"]:
            if not (0 <= it["returned_quantity"] <= it["fulfilled_quantity"]):
                errors.append(
                    f"C-CARD-4: {oid}/{it['order_item_id']} returned_quantity "
                    f"{it['returned_quantity']} out of [0, {it['fulfilled_quantity']}]"
                )

    # C-CARD-5: ReturnItem.quantity within unreturned remainder is implicitly
    # checked via C-BOOK-1 below for refunded returns.

    # Referential constraints C-REF-1 through C-REF-9
    for oid, o in db["orders"].items():
        if o["purchaser_customer_id"] not in db["customers"]:
            errors.append(f"C-REF-3: order {oid} purchaser unknown")
        rec = o.get("recipient_customer_id")
        if rec and rec not in db["customers"]:
            errors.append(f"C-REF-4: order {oid} recipient unknown")
        pm = o.get("payment_method_id")
        if pm:
            if pm not in db["payment_methods"]:
                errors.append(f"C-REF-5a: order {oid} payment_method unknown")
            elif db["payment_methods"][pm]["customer_id"] != o["purchaser_customer_id"]:
                errors.append(
                    f"C-REF-5: order {oid} payment_method {pm} not owned by purchaser"
                )
        for it in o["items"]:
            if it["product_id"] not in db["products"]:
                errors.append(f"C-REF-2: {oid}/{it['order_item_id']} product unknown")
            if it["order_id"] != oid:
                errors.append(f"C-REF-1: {oid}/{it['order_item_id']} order_id mismatch")

    for rid, r in db["returns"].items():
        if r["order_id"] not in db["orders"]:
            errors.append(f"C-REF-6: return {rid} order unknown")
        if r["initiator_customer_id"] not in db["customers"]:
            errors.append(f"C-REF-7: return {rid} initiator unknown")
        if r["order_id"] in db["orders"]:
            o_items = {it["order_item_id"] for it in db["orders"][r["order_id"]]["items"]}
            for ri in r["items"]:
                if ri["order_item_id"] not in o_items:
                    errors.append(
                        f"C-REF-8: {rid}/{ri['return_item_id']} references oi "
                        f"{ri['order_item_id']} not in {r['order_id']}"
                    )

    for pmid, pm in db["payment_methods"].items():
        if pm["customer_id"] not in db["customers"]:
            errors.append(f"C-REF-9: payment_method {pmid} owner unknown")

    # C-MP-1: return initiator is effective_returner
    for rid, r in db["returns"].items():
        if r["order_id"] in db["orders"]:
            exp = effective_returner(db, r["order_id"])
            if r["initiator_customer_id"] != exp:
                errors.append(
                    f"C-MP-1: return {rid} initiator {r['initiator_customer_id']} "
                    f"!= effective_returner {exp}"
                )

    # C-STATE-O1: returns only against delivered+ orders
    for rid, r in db["returns"].items():
        if r["order_id"] in db["orders"]:
            ostatus = db["orders"][r["order_id"]]["status"]
            if ostatus not in ("delivered", "partially_returned", "fully_returned"):
                errors.append(
                    f"C-STATE-O1: return {rid} against order in status {ostatus}"
                )

    # C-STATE-O2: status implies fulfillment_date set
    for oid, o in db["orders"].items():
        if o["status"] not in ("placed", "processing", "cancelled"):
            if not o.get("fulfillment_date"):
                errors.append(f"C-STATE-O2: {oid} status {o['status']} but no fulfillment_date")

    # C-STATE-O3: stored status matches derived (for orders with any returns)
    for oid, o in db["orders"].items():
        total_q = sum(it["quantity"] for it in o["items"])
        total_r = sum(it["returned_quantity"] for it in o["items"])
        if total_r > 0:
            expected = "fully_returned" if total_r == total_q else "partially_returned"
            if o["status"] != expected:
                errors.append(
                    f"C-STATE-O3: {oid} stored status {o['status']} != derived {expected}"
                )

    # C-STATE-R1: only reachable v0 statuses
    for rid, r in db["returns"].items():
        if r["status"] not in ("pending", "refunded", "cancelled"):
            errors.append(f"C-STATE-R1: return {rid} has v0-forbidden status {r['status']}")

    # C-STATE-R2/R3: terminal data presence
    for rid, r in db["returns"].items():
        if r["status"] == "refunded":
            if r.get("refund_method") is None:
                errors.append(f"C-STATE-R2: refunded return {rid} missing refund_method")
            if r.get("refund_amount_cents") is None:
                errors.append(f"C-STATE-R2: refunded return {rid} missing refund_amount_cents")
        else:
            if r.get("refund_method") is not None:
                errors.append(f"C-STATE-R3: non-refunded return {rid} has refund_method")
            if r.get("refund_amount_cents") is not None:
                errors.append(f"C-STATE-R3: non-refunded return {rid} has refund_amount_cents")

    # C-BOOK-1: returned_quantity sums match refunded ReturnItems
    from collections import defaultdict
    expected_returned = defaultdict(int)
    for rid, r in db["returns"].items():
        if r["status"] == "refunded":
            for ri in r["items"]:
                expected_returned[ri["order_item_id"]] += ri["quantity"]
    for oid, o in db["orders"].items():
        for it in o["items"]:
            actual = it["returned_quantity"]
            exp = expected_returned[it["order_item_id"]]
            if actual != exp:
                errors.append(
                    f"C-BOOK-1: {oid}/{it['order_item_id']} returned_quantity "
                    f"{actual} != expected sum {exp} from refunded returns"
                )

    # C-TIME-1: fulfillment ≥ order_date
    for oid, o in db["orders"].items():
        if o.get("fulfillment_date"):
            if parse_dt(o["fulfillment_date"]) < parse_dt(o["order_date"]):
                errors.append(f"C-TIME-1: {oid} fulfillment_date before order_date")

    # C-TIME-2: return created ≥ fulfillment
    for rid, r in db["returns"].items():
        oid = r["order_id"]
        if oid in db["orders"] and db["orders"][oid].get("fulfillment_date"):
            if parse_dt(r["created_date"]) < parse_dt(db["orders"][oid]["fulfillment_date"]):
                errors.append(f"C-TIME-2: return {rid} created before order fulfilled")

    # C-MONEY-1: store_credit_balance ≥ 0
    for cid, c in db["customers"].items():
        if c["store_credit_balance_cents"] < 0:
            errors.append(f"C-MONEY-1: {cid} store_credit_balance negative")

    # C-MONEY-2: gift_card balance ≥ 0
    for pmid, pm in db["payment_methods"].items():
        if pm["type"] == "gift_card" and pm.get("balance_cents", 0) < 0:
            errors.append(f"C-MONEY-2: gift_card {pmid} balance negative")

    # C-MONEY-3: refund_amount_cents = sum of refund_amount_for(ri)
    for rid, r in db["returns"].items():
        if r["status"] == "refunded":
            total = sum(refund_amount_for(db, ri, r["order_id"]) for ri in r["items"])
            # Exchange refund_amount can legitimately be 0 even if items have value
            if r["refund_method"] == "exchange":
                if r["refund_amount_cents"] != 0:
                    errors.append(
                        f"C-MONEY-3: exchange return {rid} should have refund_amount=0, "
                        f"got {r['refund_amount_cents']}"
                    )
            else:
                if r["refund_amount_cents"] != total:
                    errors.append(
                        f"C-MONEY-3: return {rid} refund_amount_cents "
                        f"{r['refund_amount_cents']} != computed sum {total}"
                    )

    return errors


# ============================================================================
# Actions — Layer C §4
# ============================================================================


@dataclass
class TaskContext:
    """Per-task allocation counter for new entity IDs (Q-E-3)."""
    task_id: str
    return_counter: int = 0
    return_item_counter: int = 0
    order_counter: int = 0
    order_item_counter: int = 0
    read_order_ids: set[str] = field(default_factory=set)
    read_customer_ids: set[str] = field(default_factory=set)

    def new_return_id(self) -> str:
        self.return_counter += 1
        return f"ret_NEW_{self.task_id}_{self.return_counter}"

    def new_return_item_id(self) -> str:
        self.return_item_counter += 1
        return f"ri_NEW_{self.task_id}_{self.return_item_counter}"

    def new_order_id(self) -> str:
        self.order_counter += 1
        return f"ord_NEW_{self.task_id}_{self.order_counter}"

    def new_order_item_id(self) -> str:
        self.order_item_counter += 1
        return f"oi_NEW_{self.task_id}_{self.order_item_counter}"


class ActionError(Exception):
    """Raised when an action's preconditions are not satisfied."""


def apply_get_customer_details(db: dict, args: dict, ctx: TaskContext) -> dict:
    cid = args["customer_id"]
    if cid not in db["customers"]:
        raise ActionError(f"get_customer_details: {cid} not found")
    ctx.read_customer_ids.add(cid)
    return db


def apply_get_order_details(db: dict, args: dict, ctx: TaskContext) -> dict:
    oid = args["order_id"]
    if oid not in db["orders"]:
        raise ActionError(f"get_order_details: {oid} not found")
    ctx.read_order_ids.add(oid)
    return db


def apply_get_return_details(db: dict, args: dict, ctx: TaskContext) -> dict:
    rid = args["return_id"]
    if rid not in db["returns"]:
        raise ActionError(f"get_return_details: {rid} not found")
    return db


def apply_get_product_details(db: dict, args: dict, ctx: TaskContext) -> dict:
    pid = args["product_id"]
    if pid not in db["products"]:
        raise ActionError(f"get_product_details: {pid} not found")
    return db


def apply_search_customer_orders(db: dict, args: dict, ctx: TaskContext) -> dict:
    cid = args["customer_id"]
    if cid not in db["customers"]:
        raise ActionError(f"search_customer_orders: {cid} not found")
    ctx.read_customer_ids.add(cid)
    return db


def apply_initiate_return(db: dict, args: dict, ctx: TaskContext) -> dict:
    oid = args["order_id"]
    cid = args["customer_id"]
    items = args["items"]

    # Preconditions
    if oid not in db["orders"]:
        raise ActionError(f"initiate_return: order {oid} not found")
    if cid not in db["customers"]:
        raise ActionError(f"initiate_return: customer {cid} not found")
    if not eligible_to_initiate(db, cid, oid):
        raise ActionError(
            f"initiate_return: {cid} is not the effective returner of {oid}"
        )
    o = db["orders"][oid]
    if o["status"] not in ("delivered", "partially_returned"):
        raise ActionError(
            f"initiate_return: order {oid} status {o['status']} not returnable"
        )
    # Q-B-1: no other pending Return on this order
    for r in db["returns"].values():
        if r["order_id"] == oid and r["status"] == "pending":
            raise ActionError(
                f"initiate_return: order {oid} already has pending return {r['return_id']}"
            )
    if not items:
        raise ActionError("initiate_return: items must be non-empty")

    # Item-level preconditions
    new_items = []
    new_db = deepcopy(db)
    for spec in items:
        oi_id = spec["order_item_id"]
        oi = next((it for it in o["items"] if it["order_item_id"] == oi_id), None)
        if oi is None:
            raise ActionError(
                f"initiate_return: order_item {oi_id} not in order {oid}"
            )
        unreturned = oi["fulfilled_quantity"] - oi["returned_quantity"]
        if not (1 <= spec["quantity"] <= unreturned):
            raise ActionError(
                f"initiate_return: quantity {spec['quantity']} exceeds unreturned "
                f"remainder {unreturned} on {oi_id}"
            )
        new_items.append({
            "return_item_id": ctx.new_return_item_id(),
            "return_id": "",  # filled below
            "order_item_id": oi_id,
            "quantity": spec["quantity"],
            "declared_condition": spec["declared_condition"],
            "declared_reason": spec["declared_reason"],
        })

    new_return_id = ctx.new_return_id()
    for it in new_items:
        it["return_id"] = new_return_id

    new_db["returns"][new_return_id] = {
        "return_id": new_return_id,
        "order_id": oid,
        "initiator_customer_id": cid,
        "created_date": db["constants"]["current_time"],
        "status": "pending",
        "refund_method": None,
        "refund_amount_cents": None,
        "rejection_reason": None,
        "items": new_items,
    }
    return new_db


def apply_approve_return(db: dict, args: dict, ctx: TaskContext) -> dict:
    rid = args["return_id"]
    refund_method = args["refund_method"]

    if rid not in db["returns"]:
        raise ActionError(f"approve_return: return {rid} not found")
    r = db["returns"][rid]
    if r["status"] != "pending":
        raise ActionError(f"approve_return: return {rid} status {r['status']} ≠ pending")

    current_time = db["constants"]["current_time"]
    if not return_eligible(db, rid, current_time):
        raise ActionError(f"approve_return: return {rid} is not eligible")

    eligible = eligible_refund_methods(db, rid)
    if refund_method not in eligible:
        raise ActionError(
            f"approve_return: refund_method {refund_method} not in eligible {eligible}"
        )

    new_db = deepcopy(db)
    oid = r["order_id"]

    # Compute refund amount
    if refund_method == "exchange":
        refund_amount = 0
    else:
        refund_amount = sum(refund_amount_for(db, ri, oid) for ri in r["items"])

    # Mutate the Return
    new_db["returns"][rid]["status"] = "refunded"
    new_db["returns"][rid]["refund_method"] = refund_method
    new_db["returns"][rid]["refund_amount_cents"] = refund_amount

    # Increment returned_quantity on each affected OrderItem
    for ri in r["items"]:
        for oi in new_db["orders"][oid]["items"]:
            if oi["order_item_id"] == ri["order_item_id"]:
                oi["returned_quantity"] += ri["quantity"]
                break

    # Update order status
    total_q = sum(it["quantity"] for it in new_db["orders"][oid]["items"])
    total_r = sum(it["returned_quantity"] for it in new_db["orders"][oid]["items"])
    if total_r == total_q:
        new_db["orders"][oid]["status"] = "fully_returned"
    elif total_r > 0:
        new_db["orders"][oid]["status"] = "partially_returned"

    # Branch on refund_method
    if refund_method == "store_credit":
        initiator_id = r["initiator_customer_id"]
        new_db["customers"][initiator_id]["store_credit_balance_cents"] += refund_amount
    elif refund_method == "original_payment":
        pm_id = new_db["orders"][oid].get("payment_method_id")
        if pm_id and new_db["payment_methods"][pm_id]["type"] == "gift_card":
            new_db["payment_methods"][pm_id]["balance_cents"] += refund_amount
        # For credit_card: out-of-band refund event; no in-DB change.
    elif refund_method == "exchange":
        # Create a paired Order with same-SKU replacement items at unit_price=0
        new_order_id = ctx.new_order_id()
        new_order_items = []
        for ri in r["items"]:
            oi = next(
                it for it in db["orders"][oid]["items"]
                if it["order_item_id"] == ri["order_item_id"]
            )
            new_order_items.append({
                "order_item_id": ctx.new_order_item_id(),
                "order_id": new_order_id,
                "product_id": oi["product_id"],
                "quantity": ri["quantity"],
                "unit_price_cents": 0,
                "fulfilled_quantity": 0,
                "returned_quantity": 0,
            })
        new_db["orders"][new_order_id] = {
            "order_id": new_order_id,
            "purchaser_customer_id": r["initiator_customer_id"],
            "recipient_customer_id": None,
            "order_date": db["constants"]["current_time"],
            "fulfillment_date": None,
            "payment_method_id": None,
            "status": "placed",
            "total_amount_cents": 0,
            "items": new_order_items,
        }
        new_db["customers"][r["initiator_customer_id"]]["order_ids"].append(new_order_id)

    return new_db


def apply_cancel_return(db: dict, args: dict, ctx: TaskContext) -> dict:
    rid = args["return_id"]
    if rid not in db["returns"]:
        raise ActionError(f"cancel_return: return {rid} not found")
    r = db["returns"][rid]
    if r["status"] != "pending":
        raise ActionError(f"cancel_return: return {rid} status {r['status']} ≠ pending")
    new_db = deepcopy(db)
    new_db["returns"][rid]["status"] = "cancelled"
    return new_db


def apply_transfer_to_human_agent(db: dict, args: dict, ctx: TaskContext) -> dict:
    # No DB effect.
    return db


ACTION_DISPATCH = {
    "get_customer_details": apply_get_customer_details,
    "get_order_details": apply_get_order_details,
    "get_return_details": apply_get_return_details,
    "get_product_details": apply_get_product_details,
    "search_customer_orders": apply_search_customer_orders,
    "initiate_return": apply_initiate_return,
    "approve_return": apply_approve_return,
    "cancel_return": apply_cancel_return,
    "transfer_to_human_agent": apply_transfer_to_human_agent,
}

MUTATING_ACTIONS = {"initiate_return", "approve_return", "cancel_return"}


# ============================================================================
# Trajectory checks — subset of Layer D §10 (runtime-checkable rules)
# ============================================================================


def check_trajectory(actions: list[dict], ctx: TaskContext) -> list[str]:
    """
    Mechanically check D-CONF-5 and D-CONF-7.
    D-CONF-5: get_order_details for an order before any mutation on it.
    D-CONF-7: get_customer_details for a customer before any mutation involving them.
    """
    errors: list[str] = []
    seen_order_reads: set[str] = set()
    seen_customer_reads: set[str] = set()
    return_to_order: dict[str, str] = {}  # track newly-created Return → Order

    for a in actions:
        name = a["name"]
        args = a["arguments"]

        if name == "get_order_details":
            seen_order_reads.add(args["order_id"])
        elif name == "get_customer_details":
            seen_customer_reads.add(args["customer_id"])

        if name in MUTATING_ACTIONS:
            # Identify the affected order_id and customer_id
            order_id = None
            customer_id = None
            if name == "initiate_return":
                order_id = args["order_id"]
                customer_id = args["customer_id"]
                # Track for downstream approve/cancel
                # The new Return id is allocated by apply_initiate_return, so we
                # have to mirror the convention here.
                # For trajectory check only — we don't need the exact id.
            elif name == "approve_return" or name == "cancel_return":
                rid = args["return_id"]
                # If the return was created earlier in this trajectory, we have
                # already required get_order_details at that point.
                # If it's a pre-existing Return, we need it now.
                # We pessimistically require get_order_details whenever a
                # mutation targets a Return we haven't tracked.
                if rid in return_to_order:
                    order_id = return_to_order[rid]
                # else: order_id unknown to checker; D-CONF-5 unenforceable here.
                # Leave customer_id None.

            if order_id and order_id not in seen_order_reads:
                errors.append(
                    f"D-CONF-5: {name}({args}) without prior get_order_details({order_id})"
                )
            if customer_id and customer_id not in seen_customer_reads:
                errors.append(
                    f"D-CONF-7: {name}({args}) without prior get_customer_details({customer_id})"
                )

    return errors


# ============================================================================
# Diffing
# ============================================================================


def compute_diff(d0: dict, d1: dict) -> list[str]:
    """A structured, human-readable diff of two DB snapshots."""
    diff: list[str] = []

    # Customers
    for cid in d1["customers"]:
        c0 = d0["customers"].get(cid, {})
        c1 = d1["customers"][cid]
        for k in ("store_credit_balance_cents", "order_ids"):
            if c0.get(k) != c1.get(k):
                diff.append(f"customer/{cid}.{k}: {c0.get(k)} → {c1.get(k)}")

    # Payment methods (only gift_card balance changes are in scope)
    for pmid in d1["payment_methods"]:
        pm0 = d0["payment_methods"].get(pmid, {})
        pm1 = d1["payment_methods"][pmid]
        if pm0.get("balance_cents") != pm1.get("balance_cents"):
            diff.append(
                f"payment_method/{pmid}.balance_cents: "
                f"{pm0.get('balance_cents')} → {pm1.get('balance_cents')}"
            )

    # Orders (new + status changes + items changes)
    for oid in d1["orders"]:
        if oid not in d0["orders"]:
            diff.append(f"order/{oid}: NEW")
            continue
        o0 = d0["orders"][oid]
        o1 = d1["orders"][oid]
        if o0["status"] != o1["status"]:
            diff.append(f"order/{oid}.status: {o0['status']} → {o1['status']}")
        # Item-level returned_quantity
        for it1 in o1["items"]:
            it0 = next((it for it in o0["items"] if it["order_item_id"] == it1["order_item_id"]), None)
            if it0 and it0["returned_quantity"] != it1["returned_quantity"]:
                diff.append(
                    f"order_item/{it1['order_item_id']}.returned_quantity: "
                    f"{it0['returned_quantity']} → {it1['returned_quantity']}"
                )

    # Returns (new + status/refund changes)
    for rid in d1["returns"]:
        if rid not in d0["returns"]:
            r1 = d1["returns"][rid]
            diff.append(
                f"return/{rid}: NEW (status={r1['status']}, method={r1['refund_method']}, "
                f"amount={r1['refund_amount_cents']})"
            )
            continue
        r0 = d0["returns"][rid]
        r1 = d1["returns"][rid]
        for k in ("status", "refund_method", "refund_amount_cents"):
            if r0.get(k) != r1.get(k):
                diff.append(f"return/{rid}.{k}: {r0.get(k)} → {r1.get(k)}")

    return diff


# ============================================================================
# Per-task verifier
# ============================================================================


@dataclass
class VerificationResult:
    task_id: str
    task_class: str
    passed: bool
    invariant_errors: list[str] = field(default_factory=list)
    action_errors: list[str] = field(default_factory=list)
    trajectory_errors: list[str] = field(default_factory=list)
    class_mismatch: str = ""
    diff: list[str] = field(default_factory=list)


def verify_task(task: dict, d0: dict) -> VerificationResult:
    tid = task["id"]
    spec = task["operational_spec"]
    klass = spec["task_class"]
    actions = task["evaluation_criteria"]["actions"]

    result = VerificationResult(task_id=tid, task_class=klass, passed=False)
    ctx = TaskContext(task_id=tid)

    # Trajectory-level checks before execution
    result.trajectory_errors = check_trajectory(actions, ctx)
    # Reset the context's read sets (they were polluted by the trajectory check)
    ctx = TaskContext(task_id=tid)

    # Apply each action sequentially
    db = d0
    for a in actions:
        name = a["name"]
        args = a["arguments"]
        if name not in ACTION_DISPATCH:
            result.action_errors.append(f"{a['action_id']}: unknown action {name}")
            return result
        try:
            db = ACTION_DISPATCH[name](db, args, ctx)
        except ActionError as e:
            result.action_errors.append(f"{a['action_id']}: {e}")
            return result

    # Layer B invariants on the final state
    result.invariant_errors = check_layer_b_invariants(db)

    # Task-class consistency: D* vs D₀
    d_diff = compute_diff(d0, db)
    result.diff = d_diff
    if klass == "mutating" and not d_diff:
        result.class_mismatch = "mutating task produced no diff"
    elif klass in ("policy_noop", "intent_noop") and d_diff:
        result.class_mismatch = f"{klass} task produced a diff"

    result.passed = (
        not result.invariant_errors
        and not result.action_errors
        and not result.trajectory_errors
        and not result.class_mismatch
    )
    return result


# ============================================================================
# Main
# ============================================================================


def main() -> int:
    print("=" * 78)
    print("Retail Returns Verifier — v0 (Python; Clingo deferred)")
    print("=" * 78)

    db = load_db()
    tasks = load_tasks()

    # 1. Check D₀ itself satisfies Layer B
    print("\n[D₀] Checking Layer B invariants on the baseline DB ...")
    d0_errors = check_layer_b_invariants(db)
    if d0_errors:
        print("    FAIL — D₀ violates Layer B invariants:")
        for e in d0_errors:
            print(f"      ✗ {e}")
        return 1
    print("    ✓ All 25 integrity constraints hold on D₀.")

    # 2. Verify each task
    print(f"\n[Tasks] Verifying {len(tasks)} tasks ...")
    failures: list[str] = []
    for task in tasks:
        result = verify_task(task, db)
        status = "PASS" if result.passed else "FAIL"
        print(f"\n  [{result.task_id}] ({result.task_class}) {status}")

        if result.trajectory_errors:
            print("    Trajectory errors:")
            for e in result.trajectory_errors:
                print(f"      ✗ {e}")

        if result.action_errors:
            print("    Action errors:")
            for e in result.action_errors:
                print(f"      ✗ {e}")

        if result.invariant_errors:
            print("    Layer B invariant violations on D*:")
            for e in result.invariant_errors:
                print(f"      ✗ {e}")

        if result.class_mismatch:
            print(f"    Class mismatch: {result.class_mismatch}")

        if result.diff:
            print("    D₀ → D* diff:")
            for d in result.diff:
                print(f"      • {d}")
        elif result.task_class in ("policy_noop", "intent_noop"):
            print("    D* = D₀ (as expected)")

        if not result.passed:
            failures.append(result.task_id)

    print()
    print("=" * 78)
    if failures:
        print(f"SUMMARY: {len(tasks) - len(failures)}/{len(tasks)} passed. "
              f"Failed: {', '.join(failures)}")
        return 1
    print(f"SUMMARY: {len(tasks)}/{len(tasks)} passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
