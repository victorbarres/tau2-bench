#!/usr/bin/env python3
"""
Clingo-based uniqueness verifier for retail_returns tasks.

This is the first piece of LP machinery in the project. It demonstrates that
the ASP code in rules.md can actually execute, and uses it to give a
*provable* uniqueness guarantee on F-001 (the simplest task: approve a
pre-existing pending Return).

The pure-Python verifier in verify_retail_returns.py checks that *a* gold
trajectory produces a sound D*. This Clingo verifier checks that *exactly
one* policy-valid D* exists given (D₀, OperationalSpec). That's the property
the methodology calls "uniqueness" — the property hand-design cannot
guarantee.

v0 scope:
  - Handles F-001 only (approve_return on an existing pending Return, where
    the only "free variable" is refund_method).
  - Extracts Layer B rules from rules.md so the markdown stays the single
    source of truth (no parallel ASP copy in Python).
  - Encodes the relevant subset of D₀ as ASP facts.
  - Encodes C_hard.refund_method as an integrity constraint.
  - Reports: unique / ambiguous(N) / infeasible.
  - Also reports the pruning ratio (count without C_hard ÷ count with C_hard)
    as a first-cut difficulty metric.

Run:
  uv run python tools/clingo_verify.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import clingo

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "retail_returns"
DB_PATH = DOMAIN_DIR / "db.json"
RULES_PATH = DOMAIN_DIR / "rules.md"


# ============================================================================
# 1. Rule extraction — keep rules.md as the single source of truth
# ============================================================================


# Sections of rules.md whose code blocks we want to load for uniqueness
# checking. §2 (integrity constraints) is omitted because we already validate
# D₀ separately and our F-001 encoding doesn't compute a post-state that could
# violate them. §5 (worked micro-example) contains facts that would conflict
# with the actual D₀ facts we assert.
RELEVANT_SECTIONS = {"2.3", "3", "4"}


def extract_asp_from_rules_md(path: Path) -> str:
    """
    Pull fenced code blocks from the relevant sections of rules.md.

    Section detection works on '## N. ...' and '### N.M ...' headers.
    A code block is anything between ``` fences while inside a relevant
    section. We strip leading `%` comments to keep the embedded program
    smaller, but preserve everything else verbatim.

    This is deliberately a small, opinionated extractor — it relies on
    rules.md's existing structure rather than parsing markdown
    comprehensively.
    """
    text = path.read_text()
    blocks: list[str] = []
    in_fence = False
    fence_buffer: list[str] = []
    current_section = ""  # e.g. "3", "3.2", "2.3"

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
                # Closing fence
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
        # Avoid Python's bool-is-an-int trap.
        raise ValueError("ASP has no booleans — encode as a present/absent fact")
    if isinstance(v, int):
        return str(v)
    if isinstance(v, str):
        return v  # identifiers — must already be ASP-safe (lowercase, no quotes)
    raise TypeError(f"cannot encode {type(v).__name__} as ASP term")


def encode_db(db: dict, current_time: str) -> str:
    """
    Encode the subset of D₀ that Layer B rules consult, plus the externals
    Layer B treats as inputs (days_since_fulfillment, payment_method_valid
    attribute facts).

    Only emits facts using predicate names that rules.md actually references.
    """
    lines: list[str] = []

    # Numeric constants used by Layer B
    for k, v in db["constants"].items():
        if isinstance(v, int):
            lines.append(asp_atom("const", k, v))

    # Customers
    for cid, c in db["customers"].items():
        lines.append(asp_atom("customer", cid))
        lines.append(asp_atom("member_tier", cid, c["member_tier"]))

    # Products
    for pid, p in db["products"].items():
        lines.append(asp_atom("product", pid))
        lines.append(asp_atom("return_class", pid, p["return_class"]))
        if p.get("replacement_available"):
            lines.append(asp_atom("replacement_available", pid))

    # Payment methods (drives payment_method_valid in rules.md §3.10)
    for pmid, pm in db["payment_methods"].items():
        lines.append(asp_atom("payment_method", pmid))
        lines.append(asp_atom("payment_method_owner", pmid, pm["customer_id"]))
        lines.append(asp_atom("payment_method_type", pmid, pm["type"]))
        if pm["type"] == "credit_card" and pm.get("valid"):
            lines.append(asp_atom("payment_method_credit_card_valid", pmid))
        if pm["type"] == "gift_card":
            lines.append(asp_atom("payment_method_balance_cents", pmid, pm["balance_cents"]))

    # Orders + OrderItems
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

    # Returns + ReturnItems
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
    """Whole calendar days between two ISO datetimes (later − earlier)."""
    from datetime import datetime

    def parse(s: str):
        return datetime.fromisoformat(s.replace("Z", "+00:00"))

    return (parse(later_iso) - parse(earlier_iso)).days


# ============================================================================
# 3. Task-specific encoding for F-001
# ============================================================================


F001_TARGET_RETURN = "ret_004"
F001_C_HARD_REFUND_METHOD = "original_payment"
F001_EXPECTED_REFUND_AMOUNT = 4250


F001_CHOICE_RULE = """
% --- F-001 task encoding ---
% The only free variable in F-001 is which refund method to pick.
% C_hard pins it to original_payment.

target_return(ret_004).

% Precondition of approve_return: target must be policy-eligible.
% If return_eligible fails, no model exists — that's the soundness check.
:- target_return(R), not return_eligible(R).

% Choice: pick exactly one refund method from the eligible set.
1 { picked_refund_method(R, M) : eligible_refund_methods(R, M) } 1 :- target_return(R).

% Expose for inspection.
#show picked_refund_method/2.
#show refund_amount_for/2.
"""


F001_C_HARD_CONSTRAINT = """
% --- C_hard ---
:- target_return(R), not picked_refund_method(R, original_payment).
"""


# ============================================================================
# 4. Solving
# ============================================================================


def solve(programs: list[str], max_models: int = 2) -> list[list[str]]:
    """
    Run Clingo on the given concatenation of programs; return the atoms in
    each model as a list of strings.
    """
    ctl = clingo.Control([f"--models={max_models}"])
    for i, prog in enumerate(programs):
        ctl.add(f"base_{i}", [], prog)
    ctl.ground([(f"base_{i}", []) for i in range(len(programs))])

    models: list[list[str]] = []

    def on_model(m: clingo.Model) -> bool:
        atoms = [str(s) for s in m.symbols(shown=True)]
        models.append(sorted(atoms))
        return True

    ctl.solve(on_model=on_model)
    return models


# ============================================================================
# 5. F-001 uniqueness check
# ============================================================================


def verify_f001(db: dict, layer_b: str) -> dict:
    """
    Run the F-001 uniqueness check and return a structured result.
    """
    current_time = db["constants"]["current_time"]
    d0_facts = encode_db(db, current_time)

    # Run 1: WITHOUT C_hard — counts "policy-valid" choices.
    free_models = solve(
        [d0_facts, layer_b, F001_CHOICE_RULE],
        max_models=10,  # higher cap to see all alternatives
    )

    # Run 2: WITH C_hard — counts choices that also satisfy the spec.
    constrained_models = solve(
        [d0_facts, layer_b, F001_CHOICE_RULE, F001_C_HARD_CONSTRAINT],
        max_models=2,  # we only need to know if it's >=2
    )

    free_count = len(free_models)
    constrained_count = len(constrained_models)

    if constrained_count == 0:
        verdict = "infeasible"
    elif constrained_count == 1:
        verdict = "unique"
    else:
        verdict = f"ambiguous({constrained_count}+)"

    pruning_ratio = (
        f"{free_count} → 1" if constrained_count == 1
        else f"{free_count} → {constrained_count}"
    )

    return {
        "verdict": verdict,
        "free_count": free_count,
        "constrained_count": constrained_count,
        "pruning_ratio": pruning_ratio,
        "free_models": free_models,
        "constrained_models": constrained_models,
    }


# ============================================================================
# 6. Main
# ============================================================================


def main() -> int:
    print("=" * 78)
    print("Clingo uniqueness verifier — F-001 prototype")
    print("=" * 78)

    db = json.loads(DB_PATH.read_text())
    layer_b = extract_asp_from_rules_md(RULES_PATH)
    print(f"\n[setup] Extracted Layer B ASP from rules.md ({len(layer_b)} chars).")
    print(f"[setup] Loaded D₀ with {len(db['customers'])} customers, "
          f"{len(db['orders'])} orders, {len(db['returns'])} returns.")

    print(f"\n[F-001] Target: approve_return({F001_TARGET_RETURN}, {F001_C_HARD_REFUND_METHOD!r})")
    result = verify_f001(db, layer_b)

    print(f"\n[F-001] Verdict: {result['verdict']}")
    print(f"[F-001] Pruning ratio: {result['pruning_ratio']} models")
    print(f"        (policy alone allowed {result['free_count']} refund_method choices; "
          f"C_hard reduced to {result['constrained_count']})")

    print("\n[F-001] Free-policy models (without C_hard):")
    for m in result["free_models"]:
        print(f"        - {m}")
    print("[F-001] Constrained models (with C_hard):")
    for m in result["constrained_models"]:
        print(f"        - {m}")

    # Validate against the expected result for F-001
    expected_free = 2   # original_payment, store_credit
    expected_constrained = 1
    success = (
        result["free_count"] == expected_free
        and result["constrained_count"] == expected_constrained
    )

    if success:
        print("\n✓ F-001 uniqueness mechanically proven.")
        print(f"  policy permits {expected_free} refund methods; C_hard pins to original_payment;")
        print(f"  exactly one D* satisfies (D₀, Policy, C_hard).")
    else:
        print(f"\n✗ Unexpected result. Expected free={expected_free}, "
              f"constrained={expected_constrained}.")

    # Diagnostic check: confirm the verifier catches an infeasible C_hard.
    # If someone wrote `refund_method = exchange` for F-001, that's not in
    # the eligible set (ret_004's condition is opened_unused, not defective).
    # The verifier should report "infeasible".
    print("\n[diagnostic] Repeating verification with a deliberately-bad C_hard:")
    print("             c_hard.refund_method = exchange (not eligible for ret_004)")
    bad_c_hard = """
:- target_return(R), not picked_refund_method(R, exchange).
"""
    bad_models = solve(
        [encode_db(db, db["constants"]["current_time"]), layer_b,
         F001_CHOICE_RULE, bad_c_hard],
        max_models=2,
    )
    if len(bad_models) == 0:
        print("             ✓ Reported infeasible (0 models). Verifier diagnoses bad spec.")
    else:
        print(f"             ✗ Expected 0 models, got {len(bad_models)}.")
        success = False

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
