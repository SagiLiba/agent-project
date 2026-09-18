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

2. LOADOUTS is widened from Lesson 10's 7 intents / 10 tools to 9 intents / 14
   tools (Step 4's four additions folded in), and `select_tools` enforces an
   ABSOLUTE rule Lesson 10 never needed: in `maya` scope, no write tool is
   EVER releasable, regardless of `action_confirmed` — "Maya proposes, she
   does not file" (section 8) is stronger than Lesson 10's write gate, which
   only required confirmation, not a whole scope barred from writing at all.

3. The fail-open path (`current_intent` not in LOADOUTS) is fixed to fail open
   to READS ONLY. Lesson 10's own `select_tools` returns `None` for its
   catch-all intent regardless of `action_confirmed`, and its caller
   substitutes the FULL tool catalogue — including create_access_request —
   for `None`; it works there only because the lesson's own planner prompt is
   trusted never to set action_confirmed on that intent. This project asks for
   a harder guarantee than "the prompt should prevent it" for a write gate, so
   the fail-open set here is hardcoded to exclude every write tool, in code,
   independent of what the planner does.
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
        "search_knowledge_base",
    ],
    "ticket_status": ["get_employee", "list_employee_tickets"],
    "other": None,  # fail open — to ALL_READ_TOOLS, never to the two write tools
}

WRITE_TOOLS = {"create_access_request", "create_ticket"}

# The complete 14-tool catalogue this project's server.py exposes (Step 4).
# Hardcoded here rather than discovered from the live MCP client, so this
# whole module — including the fail-open path — stays what Lesson 10 calls
# out as select()'s defining property: "deterministic code... reviewable,
# testable without an API key" (stage02 graph.py's own docstring for select()).
ALL_TOOLS = (
    "list_policies", "get_policy", "search_knowledge_base", "search_hr_documents",
    "get_employee", "check_software_subscription", "list_onboarding_tasks",
    "check_asset_inventory", "list_employee_tickets", "create_access_request",
    "create_ticket", "list_direct_reports", "check_seat_assignment", "list_access_requests",
)
ALL_READ_TOOLS = sorted(name for name in ALL_TOOLS if name not in WRITE_TOOLS)

# Which write tool a CONFIRMED action in webex scope releases, keyed by intent.
# Only access_request has a golden case that exercises it (W-I-03/S8); ticket_status
# gets create_ticket for symmetry with Lesson 8 homework 2, on the same confirmed-only gate.
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
            "True only if THIS message authorises filing/creating a record "
            "('go ahead', 'file it'). Writing, drafting, or summarising is "
            "composing text, NOT authorisation. In maya scope this field is "
            "advisory only — select_tools ignores it; a write never fires there."
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


# This is the only function that can release a write tool into a loadout.
def select_tools(plan: TurnPlan) -> list[str]:
    """Map the plan to this turn's allowed tools. Always concrete — never None.

    Three gates, in order:
      1. Nothing needed this turn -> [].
      2. maya scope -> whatever the intent's loadout allows, MINUS every write
         tool, unconditionally. `action_confirmed` is not consulted here at
         all — there is no code path in this branch that can add a write tool
         back in, by construction, not by prompt discipline.
      3. webex scope -> the intent's loadout, plus this intent's own write
         tool(s) if and only if action_confirmed is True THIS turn.
    """
    if not plan.requires_tools and not plan.action_confirmed:
        return []

    base = LOADOUTS.get(plan.current_intent)
    selected = list(ALL_READ_TOOLS) if base is None else list(base)

    if plan.scope == "maya":
        return sorted(name for name in selected if name not in WRITE_TOOLS)

    if plan.action_confirmed:
        releasable = CONFIRMED_WRITE_TOOLS.get(plan.current_intent, set())
        selected = list(selected) + sorted(releasable - set(selected))
    return sorted(set(selected))


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
