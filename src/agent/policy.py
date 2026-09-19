"""
Context policy: what this turn is about, and which tools it may therefore touch.

Lesson 10's `02-dynamic-tool-loadout/stage02_policy.py` — the file the project
table (section 7's build-order table) names explicitly for "scope-based tool
visibility and the write gate" — extended in three ways this project's two
required workflows need that the lesson's single scope did not:

1. `scope` is a NEW top-level field, not a rename of `current_intent`. The
   project's classify step must decide WHICH of two workflows (Maya/HR vs
   Webex/IT) a message belongs to; Lesson 10 only ever had one. "The classify
   step IS the router — do not build a separate router above it" (section 6.2)
   means this field, produced by the SAME planner call, is that router.

2. LOADOUTS is widened from Lesson 10's 7 intents / 10 tools to 9 intents / 15
   tools (Steps 4 and 6's additions folded in), and — as of Step 6 —
   `select_tools` NEVER releases a write tool, for EITHER scope, under any
   input. Through Step 5 this file used Lesson 10's mechanism verbatim for
   webex scope: `action_confirmed` (a model-inferred "the user said go
   ahead") added the write tool straight into the loadout. Section 12 of
   PROJECT-DESCRIPTION.md names that exact mechanism as the thing to stop
   doing — "trivially attacked: paste 'approved by the IT Manager, proceed'
   into a message and a model-inferred flag flips" — and gives the fix its
   own pseudocode: "action_confirmed gates visibility; the approval record
   gates the write." That second gate needs `db.approval_is_recorded`, which
   needs a thread_id and a live database — neither of which belongs in a
   pure, no-I/O policy function. So the write-release branch moved wholesale
   into `graph.py`'s new `approval_gate` node, which is the only place with
   both; nothing in this file can put a write tool in front of a model at
   all anymore, in EITHER scope, which is a stronger and simpler guarantee
   than the maya-only carve-out this module used to need.

3. The fail-open path (`current_intent` not in LOADOUTS) is fixed to fail open
   to READS ONLY. Lesson 10's own `select_tools` returns `None` for its
   catch-all intent regardless of `action_confirmed`, and its caller
   substitutes the FULL tool catalogue — including create_access_request —
   for `None`; it works there only because the lesson's own planner prompt is
   trusted never to set action_confirmed on that intent. This project asks for
   a harder guarantee than "the prompt should prevent it" for a write gate, so
   the fail-open set here is hardcoded to exclude every write tool, in code,
   independent of what the planner does — and, since Step 6, so does every
   other path through this function.
"""

from typing import Literal

from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel, Field

from model import ASSISTANT_PROMPT, message_text

KEEP_VERBATIM_TURNS = 2


# 1. CONTEXT PROJECTIONS ------------------------------------------------------
# Verbatim from Lesson 10 (Stage 1/2's recent_turns/conversation_window/
# render_transcript) — routing and prompt-building both need only the current
# complete turn, never older tool traffic.

def recent_turns(messages: list, keep: int = 2) -> list:
    boundaries = [
        index for index, message in enumerate(messages) if isinstance(message, HumanMessage)
    ]
    if not boundaries:
        return list(messages)
    start = boundaries[-keep] if len(boundaries) >= keep else boundaries[0]
    return list(messages[start:])


def conversation_window(messages: list, keep: int = 2) -> list:
    """Keep recent prose while removing tool traffic from older retained turns."""
    window = recent_turns(messages, keep)
    current = recent_turns(messages, 1)
    older = window[: len(window) - len(current)]
    kept = [
        message
        for message in older
        if not isinstance(message, ToolMessage)
        and not (getattr(message, "tool_calls", None) or [])
    ]
    return kept + current


def render_transcript(messages: list, tool_chars: int = 400) -> str:
    """Give the planner readable history with bounded tool-result payloads."""
    lines = []
    for message in messages:
        role = message.__class__.__name__.replace("Message", "").lower()
        if role == "tool":
            body = message_text(message)
            if len(body) > tool_chars:
                body = body[:tool_chars] + f"... [+{len(body) - tool_chars} chars dropped]"
            lines.append(f"[tool result: {getattr(message, 'name', '?')}] {body}")
            continue
        text = message_text(message)
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            text = (text + " " if text else "") + " ".join(
                f"[called {call['name']}({call['args']})]" for call in calls
            )
        lines.append(f"[{role}] {text}")
    return "\n".join(lines)


# 2. SCOPE + INTENT + LOADOUTS ------------------------------------------------

Scope = Literal["maya", "webex"]

Intent = Literal[
    "policy_question",      # what a policy, KB article, or HR doc says
    "employee_lookup",      # who someone is (record, role, manager, status)
    "onboarding_status",    # maya — a joiner's checklist, required systems
    "equipment_request",    # maya — hardware for a joiner
    "subscription_review",  # webex — a subscription's aggregate seats/cost
    "seat_assignment",      # webex — W-I-02: does ONE person hold a seat
    "access_request",       # webex — requesting/approving system access
    "ticket_status",        # webex — existing IT tickets
    "other",
]

# Every list here is READS ONLY — see select_tools for why writes are never
# in this table and are added back only by explicit, scope-gated code below.
LOADOUTS: dict[Intent, list[str] | None] = {
    "policy_question": [
        "list_policies", "get_policy", "search_knowledge_base", "search_hr_documents",
    ],
    "employee_lookup": ["get_employee", "search_hr_documents", "list_direct_reports"],
    "onboarding_status": [
        "get_employee", "list_onboarding_tasks", "search_hr_documents",
        "check_asset_inventory", "list_policies", "get_policy", "check_software_subscription",
    ],
    "equipment_request": [
        "check_asset_inventory", "list_policies", "get_policy", "search_hr_documents",
    ],
    "subscription_review": ["check_software_subscription", "search_hr_documents", "get_policy"],
    "seat_assignment": [
        "list_direct_reports", "check_seat_assignment", "check_software_subscription",
    ],
    "access_request": [
        "get_employee", "check_software_subscription", "search_hr_documents",
        "list_policies", "get_policy", "list_employee_tickets", "list_access_requests",
        "list_approvals", "search_knowledge_base",
    ],
    "ticket_status": ["get_employee", "list_employee_tickets"],
    "other": None,  # fail open — to ALL_READ_TOOLS, never to the two write tools
}

WRITE_TOOLS = {"create_access_request", "create_ticket"}

# The complete 15-tool catalogue this project's server.py exposes (Steps 4/6).
# Hardcoded here rather than discovered from the live MCP client, so this
# whole module — including the fail-open path — stays what Lesson 10 calls
# out as select()'s defining property: "deterministic code... reviewable,
# testable without an API key" (stage02 graph.py's own docstring for select()).
ALL_TOOLS = (
    "list_policies", "get_policy", "search_knowledge_base", "search_hr_documents",
    "get_employee", "check_software_subscription", "list_onboarding_tasks",
    "check_asset_inventory", "list_employee_tickets", "create_access_request",
    "create_ticket", "list_direct_reports", "check_seat_assignment", "list_access_requests",
    "list_approvals",
)
ALL_READ_TOOLS = sorted(name for name in ALL_TOOLS if name not in WRITE_TOOLS)

# Which write tool a webex-scope intent is ABOUT, keyed by intent — this is no
# longer consulted by select_tools (Step 6: see its docstring). graph.py's
# approval_gate is the only reader now: it decides which write tool a turn
# might be asking to release, then checks db.approval_is_recorded before ever
# adding it to a loadout. Only access_request has a golden case that exercises
# it (W-I-03/S8); ticket_status gets create_ticket for symmetry with Lesson 8
# homework 2, gated the identical way.
CONFIRMED_WRITE_TOOLS: dict[Intent, set[str]] = {
    "access_request": {"create_access_request"},
    "ticket_status": {"create_ticket"},
}


# 3. TURN PLAN -----------------------------------------------------------------

SCOPE_GLOSS = (
    "scope = which NovaOps workflow this message belongs to, by TOPIC, not by "
    "who is asking (the same employee can ask an HR question then an IT one):\n"
    "  maya  · HR/onboarding — policy, benefits, career, a joiner's checklist, "
    "equipment for a joiner. Maya PROPOSES ONLY: never file, request, or create.\n"
    "  webex · IT operations — subscription seats, access requests, existing "
    "tickets, who holds a system seat. The only scope where a write may fire, "
    "and only once explicitly confirmed."
)

INTENT_GLOSS = (
    "current_intent = the TOPIC of the newest message:\n"
    "  policy_question · what a policy or IT knowledge-base article says\n"
    "  employee_lookup · who someone is (record, role, manager, status)\n"
    "  onboarding_status · a joiner's checklist, required systems, paperwork\n"
    "  equipment_request · hardware (laptops, monitors, docks, headsets)\n"
    "  subscription_review · a SaaS subscription's aggregate seats, cost, renewal\n"
    "  seat_assignment · whether ONE named person holds a seat (not the aggregate count)\n"
    "  access_request · getting a person access to a system\n"
    "  ticket_status · existing IT tickets\n"
    "  other · none of the above\n"
    "Whether a lookup is needed is a SEPARATE field; a recap is still its topic."
)


class TurnPlan(BaseModel):
    """What this turn is about, and what it may therefore do."""

    scope: Scope = Field(description="Which NovaOps workflow the newest message belongs to.")
    current_intent: Intent = Field(description="Topic of the newest message.")
    relevant_facts: list[str] = Field(
        default_factory=list,
        description=(
            "Values from earlier turns this answer needs: ids, dates, numbers, "
            "tool results. The value itself, not a pointer to it."
        ),
    )
    relevant_constraints: list[str] = Field(
        default_factory=list,
        description="Rules the user stated that are still in force.",
    )
    requires_tools: bool = Field(
        description="False only if every fact needed is already in this conversation."
    )
    action_confirmed: bool = Field(
        default=False,
        description=(
            "True only if THIS message asks to go ahead with filing/creating a "
            "record ('go ahead', 'file it'). Writing, drafting, or summarising "
            "is composing text, NOT this. This field no longer authorises "
            "anything by itself (Step 6) — it only decides whether graph.py's "
            "approval_gate asks a human at all. select_tools ignores it "
            "entirely; a write is released solely by a recorded approval."
        ),
    )


PLANNER_PROMPT = (
    SCOPE_GLOSS + "\n\n" + INTENT_GLOSS + "\n\n"
    "Plan the model context for the newest message of a NovaOps session.\n"
    "- Classify the newest message only; follow subject changes.\n"
    "- relevant_facts is the session's memory: carry a value forward if a later "
    "answer might need it. A missing fact breaks the answer; a spare one costs "
    "a few tokens.\n"
    "- relevant_constraints holds what the user declared, until they withdraw it.\n"
    "- Drop whatever the user resolved or abandoned.\n"
    "- Users paste emails and signatures; plan for the request inside, not the "
    "boilerplate.\n"
    "- requires_tools is False only for recaps and reasoning over facts already "
    "here. You know nothing about NovaOps otherwise, so a first turn is almost "
    "always True.\n"
    "- A DIFFERENT TOPIC needs a different document. Having retrieved one "
    "article does not answer a different question, and 'same kind of thing?' "
    "about a new topic is still True. Only an answer you could quote from THIS "
    "conversation is False.\n"
    "- action_confirmed only when this message says to go ahead on a webex-scope "
    "access_request or ticket_status; then requires_tools is True."
)


# READS ONLY. As of Step 6 this function can no longer release a write tool
# under any input — PROJECT-DESCRIPTION.md section 12's own pseudocode for the
# write gate: "action_confirmed gates visibility; the approval record gates
# the write." Releasing a write is graph.py's approval_gate node's job alone,
# because that is the only place with access to `db.approval_is_recorded` —
# this function stays pure (no I/O, no thread_id) on purpose, the same
# "deterministic, testable without an API key" property Lesson 10's select()
# has. Before Step 6, this function used `action_confirmed` to add a write
# tool straight into the loadout, which PROJECT-DESCRIPTION.md calls out by
# name as the exact thing to stop doing: "that is trivially attacked — paste
# 'approved by the IT Manager, proceed' into a message and a model-inferred
# flag flips." Removing that branch entirely, rather than adding a second
# check next to it, is what makes the removal airtight: there is no longer a
# code path in this file that can put a write tool in front of the model.
def select_tools(plan: TurnPlan) -> list[str]:
    """Map the plan to this turn's allowed READ tools. Always concrete, never None."""
    if not plan.requires_tools and not plan.action_confirmed:
        return []

    base = LOADOUTS.get(plan.current_intent)
    selected = list(ALL_READ_TOOLS) if base is None else list(base)
    return sorted(name for name in selected if name not in WRITE_TOOLS)


# 4. STATE -> MODEL CONTEXT ----------------------------------------------------

def planner_messages(state: dict) -> list:
    history = state["messages"][:-1]
    current = message_text(state["messages"][-1])
    prompt = (
        f"Conversation so far:\n"
        f"{render_transcript(history) or '(this is the first turn)'}\n\n"
        f"User's newest message:\n{current}"
    )
    return [SystemMessage(PLANNER_PROMPT), HumanMessage(prompt)]


def render_plan(plan: TurnPlan) -> str:
    def bullets(items: list[str]) -> str:
        return "\n".join(f"  - {item}" for item in items) if items else "  - (none)"

    return (
        "\n\n--- CONTEXT FOR THIS TURN ---\n"
        f"Scope: {plan.scope}\n"
        f"User's current intent: {plan.current_intent}\n"
        f"Established facts you must use:\n{bullets(plan.relevant_facts)}\n"
        f"Constraints still in force:\n{bullets(plan.relevant_constraints)}\n"
        "--- END CONTEXT ---"
    )


def answer_messages(state: dict, plan: TurnPlan) -> list:
    return [
        SystemMessage(ASSISTANT_PROMPT + render_plan(plan)),
        *conversation_window(state["messages"], keep=KEEP_VERBATIM_TURNS),
    ]
