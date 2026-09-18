"""
NovaOps agent backbone: one graph, one classify step, per-scope tool visibility.

Lesson 10's `02-dynamic-tool-loadout/graph.py` mechanics — section 7's build
table names this file explicitly — extended in the three ways Step 5 set out
to close:

    START -> plan -> select -> model[loadout] -> tools --+
                               | no tool calls            |
                               | under-served -> rearm ---+
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

3. SCOPE ENFORCEMENT IS STRUCTURAL, NOT JUST POLICY. `select_tools` (Step 5's
   policy.py) is the deterministic gate; this file adds nothing on top of it
   for scope — it trusts that gate completely, the same way Lesson 10 trusts
   `select()`'s output. What it does NOT yet trust as complete: releasing a
   write tool into the loadout is not the same as executing it against a
   RECORDED approval. That second gate is Step 6.
"""

import os
import sys
from pathlib import Path
from typing import Annotated, TypedDict

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aiosqlite
from langchain_core.messages import HumanMessage, RemoveMessage, ToolMessage
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode

from model import get_model, message_text, trace
from policy import TurnPlan, WRITE_TOOLS, answer_messages, planner_messages, select_tools

CHECKPOINT_PATH = os.environ.get("NOVAOPS_CHECKPOINT_PATH", "./novaops_checkpoints.db")

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
        trace("plan", f"scope={plan.scope} intent={plan.current_intent} "
                       f"requires_tools={plan.requires_tools} action_confirmed={plan.action_confirmed}")
        return {"plan": plan.model_dump()}

    def select(state: AgentState) -> dict:
        """Deterministic code, not a model call — see policy.select_tools's docstring."""
        loadout = select_tools(TurnPlan(**state["plan"]))
        trace("select", f"loadout={loadout or '(none)'}")
        return {"loadout": loadout, "rearmed": False}

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
    graph.add_node("model", call_model)
    graph.add_node("rearm", rearm)
    graph.add_node("tools", tools_node)

    graph.add_edge(START, "plan")
    graph.add_edge("plan", "select")
    graph.add_edge("select", "model")
    graph.add_conditional_edges("model", route, {"tools": "tools", "rearm": "rearm", END: END})
    graph.add_edge("rearm", "model")
    graph.add_edge("tools", "model")

    return graph.compile(checkpointer=checkpointer)


async def run_turn(graph, message: str, *, caller_employee_id: str, thread_id: str):
    """The one entry point every caller uses: tests, an eval harness, an
    optional CLI (PROJECT-DESCRIPTION.md section 8: "passes caller context and
    a thread id into the SAME core functions the tests call — never a second
    path into the workflow"). `caller_employee_id` and `thread_id` are the two
    application inputs section 8 requires; nothing else establishes identity.
    """
    result = await graph.ainvoke(
        {"messages": [HumanMessage(message)], "caller": {"employee_id": caller_employee_id}},
        config={"configurable": {"thread_id": thread_id}},
    )
    return message_text(result["messages"][-1])
