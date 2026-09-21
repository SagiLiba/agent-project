"""
NovaOps agent backbone: one graph, one classify step, per-scope tool visibility,
a write gate that only a recorded human approval can open.

Lesson 10's `02-dynamic-tool-loadout/graph.py` mechanics — section 7's build
table names this file explicitly — extended in the four ways Steps 5 and 6 set
out to close:

    START -> plan -> select -> approval_gate -> model[loadout] -> tools --+
                                 | interrupt()            | no tool calls |
                                 | pauses HERE             | under-served  |
                                 | on a write request      v -> rearm -----+
                                                    +---------------------> END

1. CALLER IDENTITY IS AN APPLICATION INPUT, NEVER A MODEL INFERENCE
   (PROJECT-DESCRIPTION.md section 8, verbatim). `CallerContext` enters state
   once, from the entry point that starts a run — never written by any node,
   never inferred by the planner. It closes the exact gap server.py's
   docstring flagged in Step 4: `search_hr_documents`'s `caller_employee_id`
   argument is now OVERWRITTEN with `state["caller"]["employee_id"]` before
   every tool call, in `inject_caller_identity` below — whatever value the
   model proposed for that argument is discarded, unread.

2. DURABLE CHECKPOINTING. Every lesson graph.py in this course compiles with
   `InMemorySaver` (verified: no lesson uses any SQLite checkpointer). This
   project's Webex approval gate must survive the process dying between the
   interrupt and the human's decision (Milestone 4) — InMemorySaver cannot do
   that. `AsyncSqliteSaver` (not the sync `SqliteSaver` — this graph is built
   with `.ainvoke`/async nodes throughout, and the sync saver raises
   `NotImplementedError` on every async checkpoint call) opens the same real
   file every run, the same way `db.py` opens `novaops.db`.

3. SCOPE ENFORCEMENT IS STRUCTURAL, NOT JUST POLICY. `select_tools` (policy.py)
   is the deterministic READ-tool gate; this file trusts its output completely
   for reads, the same way Lesson 10 trusts `select()`'s output. It releases
   NO write tool at all anymore (Step 6 moved that entirely out of policy.py).

4. THE WRITE GATE — Lesson 9's `interrupt()`, made durable (item 2 above), and
   made to gate on a RECORDED DECISION rather than a model-inferred one
   (PROJECT-DESCRIPTION.md section 12's own framing: "action_confirmed gates
   visibility; the approval record gates the write"). `approval_gate` below is
   the new node: when a turn's plan says the user just confirmed a webex-scope
   write (`action_confirmed`), it checks `db.approval_is_recorded(thread_id,
   tool_name)` — a real column in the dataset's OWN `approvals` table
   (schema.sql), reused here as this gate's ledger. Not recorded yet ->
   `interrupt()` pauses the ENTIRE graph (durably — see item 2) and hands the
   pause back to the caller; recorded -> the write tool joins the loadout and
   `model` gets to call it for real. The model is NEVER the thing that decides
   this; `db.py`'s four ledger functions are deliberately not MCP tools, so
   there is no path by which the model could call them on itself.

5. THE TWO TYPED RETURN CONTRACTS (Step 7, section 6.5). Neither is a new
   graph path: `WebexHandoff` is `policy.TurnPlan.webex_handoff`, filled by
   the SAME planner call every turn already makes, then completed with two
   application facts (`source_thread_id`, `requested_by_employee_id`) right
   here in `approval_gate` — the human approver reads it on the interrupt
   payload. `OnboardingChecklist` is `extract_checklist` below: one EXTRA
   structured-output call, made only on a maya-scope checklist/status turn,
   after the graph itself has already finished — never inside the loop.
"""

import os
import sys
from pathlib import Path
from typing import Annotated, TypedDict

AGENT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(AGENT_DIR))
# db.py is a SERVER-side module (src/server/), imported directly here rather
# than via an MCP tool call — deliberate, and narrow: see item 4 above and
# db.py's own module docstring ("Deliberately NOT exposed as MCP tools").
# Every OTHER piece of business data still goes through the MCP tool layer
# (model.load_tools) exactly as Steps 4/5 established; only the write gate's
# own ledger bypasses it, because exposing it as a tool would let the model
# call the function that authorizes the model's own write.
sys.path.insert(0, str(AGENT_DIR.parent / "server"))

import aiosqlite
import db  # noqa: E402 — the write gate's ledger; see comment above
from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage, ToolMessage
from langfuse.langchain import CallbackHandler
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import Command, interrupt

from model import get_model, message_text, trace
from policy import (
    CONFIRMED_WRITE_TOOLS,
    TurnPlan,
    WRITE_TOOLS,
    answer_messages,
    planner_messages,
    render_transcript,
    select_tools,
)
from schemas import AccessDecision, OnboardingChecklist, WebexHandoff

CHECKPOINT_PATH = os.environ.get("NOVAOPS_CHECKPOINT_PATH", "./novaops_checkpoints.db")

# Safety net, not a normal path: model -> tools has no other cap on how many
# rounds it can bounce before answering. Discovered the hard way (Step 6):
# a denial the model was never told about made it fish for evidence forever.
# The real fix is telling it (approval_gate's relevant_constraints note,
# above); this just turns "hangs indefinitely, burning real API calls" into a
# clear GraphRecursionError if some future prompt/tool combination does it again.
RECURSION_LIMIT = 40

# Tool name -> the argument that must always carry the REAL caller id, never
# whatever the model proposed. One entry today (search_hr_documents's audience
# gate, Step 4); any future tool needing caller identity is added here, not by
# trusting a model-supplied argument on the tool's own schema.
CALLER_INJECTED_ARGS: dict[str, str] = {"search_hr_documents": "caller_employee_id"}


# 1. GRAPH STATE ---------------------------------------------------------------

class CallerContext(TypedDict):
    """Who is asking. Set once by the entry point; no node ever writes this."""

    employee_id: str


class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    caller: CallerContext
    plan: dict
    loadout: list[str]
    rearmed: bool


def recent_turns(messages: list, keep: int = 2) -> list:
    boundaries = [
        index for index, message in enumerate(messages) if isinstance(message, HumanMessage)
    ]
    if not boundaries:
        return list(messages)
    start = boundaries[-keep] if len(boundaries) >= keep else boundaries[0]
    return list(messages[start:])


def used_tool_this_turn(messages: list) -> bool:
    return any(isinstance(message, ToolMessage) for message in recent_turns(messages, keep=1))


async def get_checkpointer() -> AsyncSqliteSaver:
    """Open (or create) the durable checkpoint db — same file-per-path lifecycle
    as db.py's _conn(), but a fresh connection per call: the caller decides
    whether that means "this process's one connection" or, for a restart test,
    deliberately a second, independent connection to the same file.

    Skips AsyncSqliteSaver's own setup(), which unconditionally issues `PRAGMA
    journal_mode=WAL` — WAL's -wal/-shm shared-memory files raise a raw
    "disk I/O error" in some sandboxed environments. Not a langgraph bug and
    not this project's actual deployment target; it is a local dev-sandbox
    limitation, worked around here by creating the identical two tables on
    the default journal mode ourselves and marking `is_setup` so setup()'s own
    PRAGMA never runs. Durability (survives a restart) is unaffected — WAL
    only changes concurrent-writer performance, not whether commits persist.
    """
    conn = await aiosqlite.connect(CHECKPOINT_PATH)
    checkpointer = AsyncSqliteSaver(conn)
    await conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS checkpoints (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            parent_checkpoint_id TEXT,
            type TEXT,
            checkpoint BLOB,
            metadata BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
        );
        CREATE TABLE IF NOT EXISTS writes (
            thread_id TEXT NOT NULL,
            checkpoint_ns TEXT NOT NULL DEFAULT '',
            checkpoint_id TEXT NOT NULL,
            task_id TEXT NOT NULL,
            idx INTEGER NOT NULL,
            channel TEXT NOT NULL,
            type TEXT,
            value BLOB,
            PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
        );
        """
    )
    await conn.commit()
    checkpointer.is_setup = True
    return checkpointer


def inject_caller_identity(state: AgentState, tools: list) -> None:
    """Overwrite caller-identity tool arguments with the REAL caller, in place.

    Runs on the model's just-produced tool_calls, before ToolNode executes
    them. This is the enforcement point for PROJECT-DESCRIPTION.md section 8's
    "caller identity... [is] an application input, never a model inference" —
    the model may emit any value it wants for `caller_employee_id`; only
    `state["caller"]["employee_id"]` is ever actually used.
    """
    last = state["messages"][-1]
    for call in getattr(last, "tool_calls", None) or []:
        arg_name = CALLER_INJECTED_ARGS.get(call["name"])
        if arg_name:
            proposed = call["args"].get(arg_name)
            call["args"][arg_name] = state["caller"]["employee_id"]
            if proposed != state["caller"]["employee_id"]:
                trace(
                    "tools",
                    f"overrode {call['name']}.{arg_name}={proposed!r} "
                    f"-> {state['caller']['employee_id']!r} (real caller)",
                )


def build_graph(tools: list, checkpointer):
    base_model = get_model()
    by_name = {tool.name: tool for tool in tools}
    planner = get_model().with_structured_output(TurnPlan, include_raw=True)
    bound_cache: dict[tuple, object] = {}

    def model_for(names: list[str]):
        key = tuple(sorted(names))
        if key not in bound_cache:
            bound_cache[key] = (
                base_model.bind_tools([by_name[name] for name in key if name in by_name])
                if key
                else base_model
            )
        return bound_cache[key]

    # 2. PLAN AND SELECT --------------------------------------------------------
    async def plan_turn(state: AgentState) -> dict:
        result = await planner.ainvoke(planner_messages(state))
        plan = result["parsed"] or TurnPlan(
            scope="maya", current_intent="other", requires_tools=True,
        )
        # STRUCTURAL BACKSTOP for a real, reproducible planner failure (found
        # via chat.py dogfooding, not a golden-set turn): on turn 1 of a
        # brand-new thread there is, by definition, no earlier fact in this
        # conversation to recall — the planner's own prompt already says so
        # ("a first turn is almost always True", policy.PLANNER_PROMPT) — yet
        # the model reliably (3/3 in isolated testing, with or without extra
        # prompt wording aimed straight at this) still marks a real,
        # never-before-asked policy/lookup question as requires_tools=False
        # and then answers from a fluent but entirely invented "policy" (a
        # fake "HR Policy 4.2" with fabricated numbers) instead of the real,
        # audience-filtered document. Prompt wording alone did not close
        # this; enforce the rule the prompt already states, in code, the
        # same way section 6.6 draws a hard line for caller identity rather
        # than trusting the model to self-police every time.
        if len(state["messages"]) <= 1 and plan.current_intent != "other" and not plan.requires_tools:
            trace("plan", f"OVERRIDE requires_tools False->True (first turn of thread, "
                          f"intent={plan.current_intent} — nothing could have been recalled yet)")
            plan.requires_tools = True
        trace("plan", f"scope={plan.scope} intent={plan.current_intent} "
                       f"requires_tools={plan.requires_tools} action_confirmed={plan.action_confirmed}")
        return {"plan": plan.model_dump()}

    def select(state: AgentState) -> dict:
        """Deterministic code, not a model call — see policy.select_tools's docstring."""
        loadout = select_tools(TurnPlan(**state["plan"]))
        trace("select", f"loadout={loadout or '(none)'}")
        return {"loadout": loadout, "rearmed": False}

    # 2b. THE WRITE GATE ---------------------------------------------------------
    def approval_gate(state: AgentState, config: RunnableConfig) -> dict:
        """The only node that can add a write tool to a turn's loadout.

        Triggers only on `scope=="webex" and action_confirmed` — the model's
        "go ahead" is what puts a request IN FRONT OF a human; it is not what
        authorizes anything. For each write tool this intent could release
        (policy.CONFIRMED_WRITE_TOOLS): if `db.approval_is_recorded` is already
        True, add it and move on — no second interrupt for an already-decided
        case. Otherwise open (or reopen) a pending ledger row and call
        `interrupt()`, which suspends the WHOLE graph right here and hands its
        payload back to whoever called `.ainvoke` — durably, because the
        checkpointer already persisted everything up to this point (item 2 in
        the module docstring). Resuming with `Command(resume=decision)` picks
        up on this exact line; `db.record_write_decision` runs, and only a
        `{"approved": True}` decision adds the tool to the loadout.

        A decision made just now (either way) is also written into
        `plan.relevant_constraints` before `model` ever runs. Without this,
        a DENIAL is invisible to the model: it still sees a webex-scope,
        `action_confirmed=True` access_request with no write tool in its
        loadout, and — nothing in its prompt says a human already ruled on
        this — the model just keeps calling read tools looking for a way to
        justify one, and the graph's rearm fallback keeps giving it more,
        forever. An APPROVAL doesn't strictly need this (the tool is just
        THERE for the model to call), but the note is added for both
        outcomes anyway, so the model never has to guess what happened.
        """
        plan = TurnPlan(**state["plan"])
        loadout = list(state["loadout"])
        if plan.scope == "webex" and plan.action_confirmed:
            thread_id = config["configurable"]["thread_id"]
            for tool_name in sorted(CONFIRMED_WRITE_TOOLS.get(plan.current_intent, set())):
                if tool_name not in by_name:
                    continue  # this run's MCP server doesn't expose it — nothing to gate
                if db.approval_is_recorded(thread_id, tool_name):
                    trace("approval_gate", f"{tool_name} already approved for {thread_id} — releasing")
                    loadout.append(tool_name)
                    continue

                db.request_write_approval(thread_id, tool_name)  # idempotent
                trace("approval_gate", f"pausing for human approval of {tool_name} (thread={thread_id})")
                # The typed Maya -> Webex handoff (section 6.5), completed with the
                # two application-supplied facts the model is never trusted with:
                # which conversation this is, and who is really asking. This is what
                # a human approver actually reads — never a claim that a write
                # already happened.
                handoff = None
                if plan.webex_handoff is not None:
                    handoff = WebexHandoff(
                        **plan.webex_handoff.model_dump(),
                        source_thread_id=thread_id,
                        requested_by_employee_id=state["caller"]["employee_id"],
                    ).model_dump()
                decision = interrupt({
                    "kind": "write_approval",
                    "tool": tool_name,
                    "thread_id": thread_id,
                    "intent": plan.current_intent,
                    "relevant_facts": plan.relevant_facts,
                    "handoff": handoff,
                    "question": f"Approve releasing {tool_name} for this case?",
                })
                approved = bool(decision.get("approved"))
                db.record_write_decision(
                    thread_id, tool_name,
                    approved=approved,
                    reason=decision.get("reason", ""),
                    decided_by=decision.get("decided_by", "human"),
                )
                trace("approval_gate", f"{tool_name} decision recorded: approved={approved}")
                if approved:
                    loadout.append(tool_name)
                    plan.relevant_constraints.append(
                        f"A human just APPROVED releasing {tool_name} for this request "
                        f"(by {decision.get('decided_by', 'human')}). Call it now; do not ask again."
                    )
                else:
                    reason = decision.get("reason") or "no reason given"
                    plan.relevant_constraints.append(
                        f"A human just DENIED releasing {tool_name} for this request: {reason}. "
                        "Do not call any more tools trying to work around this — tell the user "
                        "plainly that it was declined and why, citing that reason."
                    )
        return {"loadout": sorted(set(loadout)), "plan": plan.model_dump()}

    # 3. MODEL, CALLER INJECTION, FALLBACK --------------------------------------
    def call_model(state: AgentState) -> dict:
        loadout = state["loadout"]
        plan = TurnPlan(**state["plan"])
        response = model_for(loadout).invoke(answer_messages(state, plan))
        if getattr(response, "tool_calls", None):
            trace("model", f"-> {[c['name'] for c in response.tool_calls]}")
        return {"messages": [response]}

    async def tools_node(state: AgentState) -> dict:
        # MCP-loaded tools (langchain_mcp_adapters) are async-only — StructuredTool
        # raises NotImplementedError on sync .invoke(). ToolNode itself supports
        # both; only the call style needs to match the tools it's holding.
        inject_caller_identity(state, tools)
        return await ToolNode(tools).ainvoke(state)

    def rearm(state: AgentState) -> dict:
        """Widen to every READ tool; a write comes back only if already in this
        turn's loadout — a retry must never be what opens a write tool."""
        allowed = [
            name for name in by_name if name not in WRITE_TOOLS or name in state["loadout"]
        ]
        trace("rearm", f"widened loadout -> {allowed}")
        return {
            "loadout": allowed,
            "rearmed": True,
            "messages": [RemoveMessage(id=state["messages"][-1].id)],
        }

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if last.tool_calls:
            return "tools"
        plan = TurnPlan(**state["plan"])
        lookup_was_missed = (
            plan.requires_tools
            and not state["rearmed"]
            and not used_tool_this_turn(state["messages"])
        )
        destination = "rearm" if lookup_was_missed else END
        trace("router", f"no tool calls -> {destination}")
        return destination

    # 4. GRAPH WIRING ------------------------------------------------------------
    graph = StateGraph(AgentState)
    graph.add_node("plan", plan_turn)
    graph.add_node("select", select)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("model", call_model)
    graph.add_node("rearm", rearm)
    graph.add_node("tools", tools_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "select")
    graph.add_edge("select", "approval_gate")
    graph.add_edge("approval_gate", "model")
    graph.add_conditional_edges("model", route, {"tools": "tools", "rearm": "rearm", END: END})
    graph.add_edge("rearm", "model")
    graph.add_edge("tools", "model")

    # THE INSTRUMENTATION, IN FULL (Step 9 / Lesson 11 exercise 2): binding the
    # callback here, on the COMPILED graph, means every caller — run_turn,
    # resume_turn, both replay tests, the eval harness — exports without
    # passing anything; nobody downstream can forget to instrument. The six
    # add_node names just above (plan, select, approval_gate, model, rearm,
    # tools) are exactly the span names a trace shows, so section 14's
    # "classify -> scope -> tools -> answer" is the trace tree, unlabelled by
    # anything written here — plan classifies, select picks scope-visible
    # tools, tools runs them, model answers. Request identity (session id,
    # user id, the per-turn root span, trajectory metadata) is NOT this file's
    # job — same line Lesson 11 draws: tracing belongs to the agent, knowing
    # WHICH conversation is being traced belongs to whoever started it
    # (evals/run_eval.py).
    return graph.compile(checkpointer=checkpointer).with_config(
        {"callbacks": [CallbackHandler()]}
    )


async def extract_checklist(state: dict) -> OnboardingChecklist | None:
    """The OTHER typed return contract (section 6.5): one EXTRA structured-
    output call, made only when this turn's plan says it is checklist/status
    shaped (`scope=='maya'` and `current_intent` in {onboarding_status,
    equipment_request}) — every lookup, tangent, and recap turn in a 12-turn
    session pays nothing for this, per section 8's own hint to bound cost.

    Reads the SAME rendered transcript the planner reads (this turn's tool
    results included), so an item can only appear with real evidence behind
    it — never invented past what was actually read this session.
    """
    plan = TurnPlan(**state["plan"])
    if plan.scope != "maya" or plan.current_intent not in {"onboarding_status", "equipment_request"}:
        return None
    extractor = get_model().with_structured_output(OnboardingChecklist, include_raw=True)
    prompt = (
        "Extract the onboarding checklist from this NovaOps conversation's "
        "evidence — the tool results and the answer already given below. "
        "Every item needs at least one citation (a source_path from a "
        "retrieval result, a 'tool_name: record_id' pair, or a policy name) "
        "drawn from what was ACTUALLY read in this transcript. Do not invent "
        "an item with no evidence behind it; if nothing checklist-shaped was "
        "established, return an empty items list.\n\n" + render_transcript(state["messages"])
    )
    result = await extractor.ainvoke([SystemMessage(prompt)])
    return result["parsed"]


async def extract_access_decision(state: dict) -> AccessDecision | None:
    """Webex's counterpart to `extract_checklist` — one EXTRA structured-output
    call, made on every webex-scope turn (unlike the checklist's narrower
    intent gate: section 9 treats `AccessDecision` as THIS workflow's return
    contract full stop, and Webex's required traces are few enough that the
    cost is trivial). Reads the same rendered transcript, so `actions_taken`
    can only name a write that actually ran this turn — including a REUSE
    (`create_access_request`'s `reused: True`), which the prompt below calls
    out by name so 'reused AR001' is never misreported as 'filed a new one'.
    """
    plan = TurnPlan(**state["plan"])
    if plan.scope != "webex":
        return None
    extractor = get_model().with_structured_output(AccessDecision, include_raw=True)
    prompt = (
        "Extract the access decision from this NovaOps conversation's evidence "
        "— the tool results and the answer already given below. observed_facts "
        "must be things actually read (seat counts, ticket/request ids, "
        "entitlement, a policy clause). actions_taken must name only a write "
        "tool call that ACTUALLY ran this turn — if a tool result says "
        "'reused': true, say it reused an existing request, never that a new "
        "one was filed; if no write tool ran, actions_taken is an empty list. "
        "NEVER state or imply that access was granted or enabled — filing or "
        "reusing a request is not the same as access being granted, and status "
        "has no such value.\n\n" + render_transcript(state["messages"])
    )
    result = await extractor.ainvoke([SystemMessage(prompt)])
    return result["parsed"]


async def _outcome(result: dict) -> dict:
    """Every run either finished or paused on an approval — never anything else.

    `result["__interrupt__"]` is how LangGraph reports a live interrupt from
    `.ainvoke` (Lesson 9's `graph.py` reads the identical key). Shaped as a
    dict rather than a bare string so a caller — a test, an eval harness, a
    CLI — can branch on `status` without inspecting graph internals.
    """
    interrupts = result.get("__interrupt__")
    if interrupts:
        return {
            "status": "paused", "payload": interrupts[0].value, "answer": None,
            "checklist": None, "access_decision": None,
        }
    checklist = await extract_checklist(result)
    access_decision = await extract_access_decision(result)
    return {
        "status": "done",
        "answer": message_text(result["messages"][-1]),
        "payload": None,
        "checklist": checklist.model_dump() if checklist else None,
        "access_decision": access_decision.model_dump() if access_decision else None,
    }


async def run_turn(graph, message: str, *, caller_employee_id: str, thread_id: str) -> dict:
    """The one entry point every caller uses to SEND a message: tests, an eval
    harness, an optional CLI (PROJECT-DESCRIPTION.md section 8: "passes caller
    context and a thread id into the SAME core functions the tests call —
    never a second path into the workflow"). `caller_employee_id` and
    `thread_id` are the two application inputs section 8 requires; nothing
    else establishes identity.

    Returns `{"status": "done", "answer": str}` or, if `approval_gate` paused
    this turn, `{"status": "paused", "payload": {...}}` — call `resume_turn`
    with a human's decision to continue.
    """
    result = await graph.ainvoke(
        {"messages": [HumanMessage(message)], "caller": {"employee_id": caller_employee_id}},
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
    )
    return await _outcome(result)


async def resume_turn(graph, *, thread_id: str, approved: bool, reason: str = "", decided_by: str = "human") -> dict:
    """Resume a turn `approval_gate` paused, with a human's decision.

    The counterpart to `run_turn` — together they are the ONLY two ways to
    drive this graph; nothing else (not even a CLI, per section 8) gets a
    third path. `Command(resume=...)` is Lesson 9's mechanism, unchanged: it
    picks the paused run back up on the exact `interrupt()` line that
    suspended it, using the checkpointed state under this `thread_id` —
    which, because that checkpointer is `AsyncSqliteSaver`, works identically
    whether this call happens in the SAME process that paused, or a fresh one
    after a restart (a fresh `build_graph`/`get_checkpointer` pair pointed at
    the same file recovers the same paused run — proven in smoke_test.py).
    """
    result = await graph.ainvoke(
        Command(resume={"approved": approved, "reason": reason, "decided_by": decided_by}),
        config={"configurable": {"thread_id": thread_id}, "recursion_limit": RECURSION_LIMIT},
    )
    return await _outcome(result)
