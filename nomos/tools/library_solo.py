#!/usr/bin/env python3
"""
Solo-mode runner for the library micro-world.

Drops the user simulator entirely: each task's structured `intent` is
rendered into a "ticket" and handed to the agent, which solves by tool
calls alone. This isolates *policy-reasoning* difficulty from *dialogue
navigation* difficulty — the latter being where most of tau²-bench's
inter-task variance lives. tau²-bench already ships a solo mode but
only for telecom; this generalizes the pattern to a logic-first domain.

Two modes:

  --oracle              Deterministic perfect agent. Validates the
                        harness end-to-end with no LLM call. Used in
                        CI and as a sanity check.

  --model <name>        Drive a real LLM via litellm (lazy imported).
                        Example: `--model gpt-4o-mini`,
                        `--model anthropic/claude-haiku-4-5-20251001`.

Grading reuses `library_verify.solve_task` to derive D* from
(D₀, intent), then compares the agent's final DB state and refusal
reason against it. Refusals are first-class: a `policy_noop` task that
gets refused with the correct reason is a pass.

Run:
  uv run python tools/library_solo.py --oracle
  uv run python tools/library_solo.py --model gpt-4o-mini
  uv run python tools/library_solo.py --oracle --task LIB-T-002
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = PACKAGE_ROOT / "domains" / "library"
DB_PATH = DOMAIN_DIR / "db.json"
TASKS_PATH = DOMAIN_DIR / "tasks.json"
POLICY_PATH = DOMAIN_DIR / "agent_contract.md"
RULES_PATH = DOMAIN_DIR / "rules.md"

# Reuse Solve from the existing verifier — it returns the ground-truth D*.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from library_verify import encode_task, solve_task  # noqa: E402


# ============================================================================
# 1. Ticket renderer — structured intent → natural-language prompt
# ============================================================================


def render_ticket(task: dict) -> str:
    """
    Render the task's `intent` as a one-paragraph ticket. The ticket
    deliberately *does not* hint at the answer (no "this is allowed" or
    "this should be refused"); the agent must derive that from policy.
    """
    intent = task["operational_spec"]["intent"]
    action = intent.get("action")
    if action == "borrow_book":
        return (
            f"TICKET {task['id']}\n"
            f"Requester (borrower_id): {intent['borrower_id']}\n"
            f"Request: borrow the book with book_id '{intent['book_id']}'.\n"
            f"\n"
            f"Process this borrow request. If the policy permits it, complete\n"
            f"the borrow and stop. If the policy refuses it, do not perform\n"
            f"the borrow — instead, stop with the specific refusal reason."
        )
    return f"TICKET {task['id']}\n(intent action: {action})"


# ============================================================================
# 2. World — DB + tool implementations + transcript
# ============================================================================


# Stable error strings — these are the exact failure modes from Layer C
# `actions.md` §2 and are what the grader matches against on refusal.
ERR_LOAN_CAP = "borrower_at_loan_cap"
ERR_NO_COPIES = "no_available_copies"
ERR_UNKNOWN_BORROWER = "unknown_borrower"
ERR_UNKNOWN_BOOK = "unknown_book"


@dataclass
class TranscriptEntry:
    """One tool call + result. Surfaced in the grader's failure report."""
    tool: str
    args: dict
    result: dict


@dataclass
class World:
    """Working DB the agent mutates via tool calls."""
    db: dict
    transcript: list[TranscriptEntry] = field(default_factory=list)
    next_loan_seq: int = 1

    @classmethod
    def from_baseline(cls) -> "World":
        """Snapshot D₀ from disk; the agent mutates this copy."""
        baseline = json.loads(DB_PATH.read_text())
        return cls(db=copy.deepcopy(baseline))

    # --- read tools -------------------------------------------------------

    def get_borrower_details(self, borrower_id: str) -> dict:
        """Return borrower record + active-loan count. Errors if unknown."""
        if borrower_id not in self.db["borrowers"]:
            return {"error": ERR_UNKNOWN_BORROWER, "borrower_id": borrower_id}
        active = [
            lid for lid, l in self.db["loans"].items()
            if l["borrower_id"] == borrower_id and l["status"] == "active"
        ]
        return {
            "borrower_id": borrower_id,
            "name": self.db["borrowers"][borrower_id]["name"],
            "active_loans": active,
            "active_loan_count": len(active),
            "loan_cap": self.db["constants"]["max_active_loans_per_borrower"],
        }

    def get_book_details(self, book_id: str) -> dict:
        """Return book record + available copies. Errors if unknown."""
        if book_id not in self.db["books"]:
            return {"error": ERR_UNKNOWN_BOOK, "book_id": book_id}
        book = self.db["books"][book_id]
        active_on_book = sum(
            1 for l in self.db["loans"].values()
            if l["book_id"] == book_id and l["status"] == "active"
        )
        return {
            "book_id": book_id,
            "title": book["title"],
            "total_copies": book["total_copies"],
            "active_loans_on_book": active_on_book,
            "available_copies": book["total_copies"] - active_on_book,
        }

    # --- mutate tool ------------------------------------------------------

    def borrow_book(self, borrower_id: str, book_id: str) -> dict:
        """
        Layer C `borrow_book` with Layer B preconditions enforced inline.
        Returns the new loan record on success, or an `error` field with
        one of the two refusal reasons on failure.
        """
        if borrower_id not in self.db["borrowers"]:
            return {"error": ERR_UNKNOWN_BORROWER, "borrower_id": borrower_id}
        if book_id not in self.db["books"]:
            return {"error": ERR_UNKNOWN_BOOK, "book_id": book_id}

        b_info = self.get_borrower_details(borrower_id)
        if b_info["active_loan_count"] >= b_info["loan_cap"]:
            return {"error": ERR_LOAN_CAP, "borrower_id": borrower_id,
                    "active_loan_count": b_info["active_loan_count"]}

        k_info = self.get_book_details(book_id)
        if k_info["available_copies"] < 1:
            return {"error": ERR_NO_COPIES, "book_id": book_id}

        loan_id = f"loan_NEW_{self.next_loan_seq:03d}"
        self.next_loan_seq += 1
        self.db["loans"][loan_id] = {
            "loan_id": loan_id, "borrower_id": borrower_id,
            "book_id": book_id, "status": "active",
        }
        return {"success": True, "loan_id": loan_id,
                "borrower_id": borrower_id, "book_id": book_id}

    # --- dispatch ---------------------------------------------------------

    TOOLS = ("get_borrower_details", "get_book_details", "borrow_book")

    def call(self, tool: str, args: dict) -> dict:
        """Dispatch a tool call by name, recording it in the transcript."""
        if tool not in self.TOOLS:
            result = {"error": f"unknown tool: {tool}"}
        else:
            result = getattr(self, tool)(**args)
        self.transcript.append(TranscriptEntry(tool=tool, args=args, result=result))
        return result


# ============================================================================
# 3. Oracle driver — deterministic "perfect agent" for harness testing
# ============================================================================


@dataclass
class FinalAction:
    """What the agent declares at end of turn: completion or refusal."""
    refused: bool
    refusal_reason: str | None = None  # one of the ERR_* strings, when refused


def oracle_drive(world: World, task: dict) -> FinalAction:
    """
    Solve the task with full knowledge of policy. Useful for harness
    testing (does the grader catch the right answer?) and for measuring
    LLM degradation against a known-correct ceiling.
    """
    intent = task["operational_spec"]["intent"]
    b, k = intent["borrower_id"], intent["book_id"]
    # Always look up state first — exercises both read tools.
    binfo = world.call("get_borrower_details", {"borrower_id": b})
    kinfo = world.call("get_book_details", {"book_id": k})
    if binfo.get("active_loan_count", 0) >= binfo.get("loan_cap", 0):
        return FinalAction(refused=True, refusal_reason=ERR_LOAN_CAP)
    if kinfo.get("available_copies", 0) < 1:
        return FinalAction(refused=True, refusal_reason=ERR_NO_COPIES)
    result = world.call("borrow_book", {"borrower_id": b, "book_id": k})
    if "error" in result:
        return FinalAction(refused=True, refusal_reason=result["error"])
    return FinalAction(refused=False)


# ============================================================================
# 4. LLM driver — litellm tool-calling loop
# ============================================================================


SOLO_SYSTEM_PROMPT = """\
You are a library policy agent operating in solo mode. There is no user to
talk to — only tool calls. You will receive a ticket describing a borrow
request and must decide whether the policy permits it.

<policy>
{policy}
</policy>

Tools:
  - get_borrower_details(borrower_id): look up a borrower's record and
    active-loan count.
  - get_book_details(book_id): look up a book's title and how many copies
    are currently available.
  - borrow_book(borrower_id, book_id): create a new active loan. Will
    return an error with one of {{ "borrower_at_loan_cap", "no_available_copies" }}
    if the policy refuses.
  - done(refusal_reason?): call this exactly once at the end. If the
    request was completed successfully, pass no refusal_reason. If you
    refused, pass the refusal reason string — must be one of the two
    error strings above (or "unknown_borrower" / "unknown_book" if the
    ids didn't resolve).

Make tool calls. Do not write prose responses.
"""


TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "get_borrower_details",
            "description": "Look up a borrower's record and active-loan count.",
            "parameters": {
                "type": "object",
                "properties": {"borrower_id": {"type": "string"}},
                "required": ["borrower_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_book_details",
            "description": "Look up a book's title and available copies.",
            "parameters": {
                "type": "object",
                "properties": {"book_id": {"type": "string"}},
                "required": ["book_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "borrow_book",
            "description": "Create a new active loan. May fail with a policy refusal.",
            "parameters": {
                "type": "object",
                "properties": {
                    "borrower_id": {"type": "string"},
                    "book_id": {"type": "string"},
                },
                "required": ["borrower_id", "book_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "Call once at the end of the task.",
            "parameters": {
                "type": "object",
                "properties": {
                    "refusal_reason": {
                        "type": "string",
                        "description": "If the request was refused, the specific reason.",
                    }
                },
                "required": [],
            },
        },
    },
]


MAX_TURNS = 8  # 1–2 reads + 1 borrow + done is enough for the library.


def llm_drive(world: World, task: dict, model: str) -> FinalAction:
    """
    Drive the agent with a real LLM via litellm. Lazy import so the
    oracle mode doesn't pay the dependency cost.
    """
    try:
        from litellm import completion  # type: ignore
    except ImportError as e:
        raise SystemExit(
            f"litellm not installed ({e}). Run: uv add --optional solo litellm\n"
            f"Or use --oracle for the dependency-free harness test."
        )

    policy = POLICY_PATH.read_text()
    system = SOLO_SYSTEM_PROMPT.format(policy=policy)
    messages: list[dict] = [
        {"role": "system", "content": system},
        {"role": "user", "content": render_ticket(task)},
    ]

    for turn in range(MAX_TURNS):
        response = completion(
            model=model, messages=messages, tools=TOOL_SCHEMAS,
            tool_choice="auto", temperature=0.0,
        )
        msg = response.choices[0].message
        # Mirror the assistant message back into history before processing
        # tool calls — litellm requires this for the next turn.
        messages.append({
            "role": "assistant",
            "content": msg.content or "",
            "tool_calls": [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in (msg.tool_calls or [])
            ],
        })
        if not msg.tool_calls:
            # Model gave up without calling done — treat as silent refusal.
            return FinalAction(refused=True, refusal_reason="agent_no_tool_call")

        final: FinalAction | None = None
        for tc in msg.tool_calls:
            name = tc.function.name
            try:
                args = json.loads(tc.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}

            if name == "done":
                reason = args.get("refusal_reason")
                final = FinalAction(refused=bool(reason), refusal_reason=reason)
                tool_result = {"acknowledged": True}
            else:
                tool_result = world.call(name, args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": name,
                "content": json.dumps(tool_result),
            })

        if final is not None:
            return final

    # Out of turns — agent didn't terminate. Treat as no-decision.
    return FinalAction(refused=True, refusal_reason="agent_exhausted_turns")


# ============================================================================
# 5. Grader — compare working DB and refusal reason to Solve-derived D*
# ============================================================================


@dataclass
class Grade:
    """Per-task pass/fail with the specific reason if failed."""
    task_id: str
    passed: bool
    reason: str = ""
    n_tool_calls: int = 0


def _strip_loan_ids(db: dict) -> dict:
    """
    Normalize: loan IDs are arbitrary handles. Two equivalent D*s with
    different new-loan ids must compare equal. Sort by (borrower, book,
    status) tuples.
    """
    normalized = copy.deepcopy(db)
    loans = list(normalized["loans"].values())
    for l in loans:
        l.pop("loan_id", None)
    loans.sort(key=lambda l: (l["borrower_id"], l["book_id"], l["status"]))
    normalized["loans"] = loans
    return normalized


def grade(task: dict, world: World, final: FinalAction) -> Grade:
    """
    Compare the agent's final DB to the Solve-derived D*. For
    `policy_noop` tasks, also require the agent to have issued a
    refusal with the correct reason.
    """
    tid = task["id"]
    task_class = task["operational_spec"]["task_class"]
    intent = task["operational_spec"]["intent"]
    n = len(world.transcript)

    # Ground truth from the verifier.
    enc = encode_task(task)
    baseline = json.loads(DB_PATH.read_text())
    gold = solve_task(enc, baseline)
    if not gold.success:
        return Grade(task_id=tid, passed=False,
                     reason=f"verifier failed to produce D*: {gold.error}",
                     n_tool_calls=n)

    got = _strip_loan_ids(world.db)
    want = _strip_loan_ids(gold.d_star)

    if task_class == "policy_noop":
        if not final.refused:
            return Grade(task_id=tid, passed=False,
                         reason="task is policy_noop but agent did not refuse",
                         n_tool_calls=n)
        if got != want:
            return Grade(task_id=tid, passed=False,
                         reason="agent mutated DB despite refusal",
                         n_tool_calls=n)
        # Layer D D-REF-1: refusal reason must be specific.
        expected = _expected_refusal_reason(intent, baseline)
        if final.refusal_reason != expected:
            return Grade(task_id=tid, passed=False,
                         reason=f"wrong refusal reason: got {final.refusal_reason!r}, "
                                f"want {expected!r}",
                         n_tool_calls=n)
        return Grade(task_id=tid, passed=True,
                     reason=f"correctly refused: {final.refusal_reason}",
                     n_tool_calls=n)

    # Mutating task.
    if final.refused:
        return Grade(task_id=tid, passed=False,
                     reason=f"task is mutating but agent refused with "
                            f"{final.refusal_reason!r}",
                     n_tool_calls=n)
    if got != want:
        return Grade(task_id=tid, passed=False,
                     reason="final DB differs from Solve-derived D*",
                     n_tool_calls=n)
    return Grade(task_id=tid, passed=True,
                 reason="DB matches Solve-derived D*",
                 n_tool_calls=n)


def _expected_refusal_reason(intent: dict, baseline: dict) -> str:
    """
    For a policy_noop borrow_book task, derive which branch of
    can_borrow/2 fails — that's the reason the agent should cite.
    """
    b, k = intent["borrower_id"], intent["book_id"]
    active_count = sum(
        1 for l in baseline["loans"].values()
        if l["borrower_id"] == b and l["status"] == "active"
    )
    cap = baseline["constants"]["max_active_loans_per_borrower"]
    if active_count >= cap:
        return ERR_LOAN_CAP
    total = baseline["books"][k]["total_copies"]
    out = sum(
        1 for l in baseline["loans"].values()
        if l["book_id"] == k and l["status"] == "active"
    )
    if total - out < 1:
        return ERR_NO_COPIES
    return "<unknown — task may be misclassified>"


# ============================================================================
# 6. CLI
# ============================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--oracle", action="store_true",
                   help="run the deterministic perfect-agent harness")
    g.add_argument("--model", type=str,
                   help="litellm model id, e.g. gpt-4o-mini")
    p.add_argument("--task", type=str, default=None,
                   help="run only one task by id (default: all)")
    return p.parse_args()


def main() -> int:
    args = parse_args()
    tasks = json.loads(TASKS_PATH.read_text())
    if args.task:
        tasks = [t for t in tasks if t["id"] == args.task]
        if not tasks:
            print(f"no task with id {args.task!r}")
            return 1

    mode = "oracle" if args.oracle else f"model={args.model}"
    print("=" * 78)
    print(f"Library solo-mode runner ({mode})")
    print("=" * 78)

    grades: list[Grade] = []
    for task in tasks:
        world = World.from_baseline()
        ticket = render_ticket(task)
        print(f"\n── {task['id']} ──")
        print(ticket)
        try:
            if args.oracle:
                final = oracle_drive(world, task)
            else:
                final = llm_drive(world, task, args.model)
        except Exception as e:
            grades.append(Grade(task_id=task["id"], passed=False,
                                reason=f"driver crashed: {e}",
                                n_tool_calls=len(world.transcript)))
            continue

        g = grade(task, world, final)
        grades.append(g)
        print(f"\n   transcript ({g.n_tool_calls} tool call{'s' if g.n_tool_calls != 1 else ''}):")
        for entry in world.transcript:
            args_str = ", ".join(f"{k}={v!r}" for k, v in entry.args.items())
            result_summary = (
                "✓ success" if entry.result.get("success")
                else f"✗ {entry.result['error']}" if "error" in entry.result
                else f"→ {entry.result}"
            )
            print(f"     • {entry.tool}({args_str}) → {result_summary}")
        print(f"   final: refused={final.refused} reason={final.refusal_reason}")
        verdict = "✓ PASS" if g.passed else "✗ FAIL"
        print(f"   grade: {verdict} — {g.reason}")

    print("\n" + "=" * 78)
    n_ok = sum(1 for g in grades if g.passed)
    print(f"SUMMARY ({mode}): {n_ok}/{len(grades)} tasks passed.")
    return 0 if n_ok == len(grades) else 1


if __name__ == "__main__":
    sys.exit(main())
