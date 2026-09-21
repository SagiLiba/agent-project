"""Run the required EVALUATION-INPUTS.yaml traces against the real NovaOps
agent, once, and leave them in Langfuse (PROJECT-DESCRIPTION.md section 14 /
Milestone 5).

    main() -> for each input/session -> reseed db -> run turn(s) -> record trace id

`graph.py`'s `CallbackHandler` (bound to the compiled graph, Step 9) already
exports every node, model call and tool call — nothing here duplicates that.
THIS file supplies the other half section 14 asks for: request identity, the
thing only the caller (never the agent) knows.

    caller id and group    -> langfuse user_id + trajectory.state metadata
    chosen scope            -> trajectory.plan metadata (this turn's TurnPlan)
    the tool sequence       -> trajectory.calls metadata
    the terminal state      -> trajectory.status ("done" / "paused-then-resumed")
    a request id that survives across MCP calls and workflow resumes
                            -> thread_id, identical before and after a pause,
                               carried in both langfuse session_id and metadata

ONE TRACE PER TURN, INCLUDING A PAUSE+RESUME. EVALUATION-INPUTS.yaml's own run
instructions: "A workflow that pauses and resumes stays one trace — the
resume is not a new run." Achieved the same way Lesson 11's `run.py` opens a
per-turn root span and keeps it open for the whole turn — extended here across
an `interrupt()`: the auto-approval and `resume_turn` call both happen INSIDE
the same `with langfuse.start_as_current_observation(...)` block that
`run_turn` opened, so both `graph.ainvoke` calls land under the one root span
the CallbackHandler is currently attached to.

Reseeds `novaops.db` before each INDEPENDENT case or session, never mid-session
— EVALUATION-INPUTS.yaml's own instruction: "Get this wrong and your traces
will show failures that are your harness's, not your system's." Every session
runs on ONE thread so history carries; every one-shot input gets its own fresh
thread with no prior state.

W-S-01 turn 4 is the one turn that pauses. This script auto-approves it
(decided_by="E006", the IT Manager AR001's own AP001 approval names) so a
single run produces the complete, resumed trace section 14 asks for — the
decision a human would make here is not in question; PROJECT-DESCRIPTION.md's
own scenario says this request is "eligible."

    python evals/run_eval.py                    # all 27 required traces
    python evals/run_eval.py --case M-S-01       # one case only, for iterating
"""

import argparse
import asyncio
import json
import sys
import uuid
from contextlib import ExitStack
from pathlib import Path

import yaml
from dotenv import find_dotenv, load_dotenv
from langfuse import get_client, propagate_attributes

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_DIR = REPO_ROOT / "src" / "agent"
SERVER_DIR = REPO_ROOT / "src" / "server"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(SERVER_DIR))
sys.path.insert(0, str(Path(__file__).resolve().parent))

load_dotenv(find_dotenv())

import db  # noqa: E402
import server  # noqa: E402
from graph import build_graph, get_checkpointer, resume_turn, run_turn  # noqa: E402
from model import load_tools  # noqa: E402

langfuse = get_client()

EVAL_PATH = REPO_ROOT / "EVALUATION-INPUTS.yaml"
TOOL_RESULT_CHARS = 1500  # same bound Lesson 10/11 use — a policy excerpt, not a fragment

# The one write-gate pause in the required set (W-S-01 turn 4). Auto-approved
# so the run produces a complete, resumed trace unattended; see module docstring.
AUTO_APPROVE = {"decided_by": "E006", "reason": "IT Manager approved — reused AR001."}


def load_eval_inputs() -> dict:
    data = yaml.safe_load(EVAL_PATH.read_text(encoding="utf-8"))
    return {w["id"]: w for w in data["workflows"]}


def trajectory_digest(before: int, after_messages: list, final_state: dict) -> dict:
    """What the agent DID this turn: calls, results, and the plan behind them —
    exactly `trajectory_digest` in Lesson 11's `run.py`, since a server-side
    reader (a Langfuse evaluation rule, `score_eval.py`) can only see fields
    ON the object it is handed, not sibling observations in the same trace.
    """
    from langchain_core.messages import AIMessage, ToolMessage

    calls: dict[str, dict] = {}
    order: list[str] = []
    for message in after_messages[before:]:
        if isinstance(message, AIMessage):
            for call in (message.tool_calls or []):
                calls[call["id"]] = {"name": call["name"], "args": call["args"], "result": None}
                order.append(call["id"])
        elif isinstance(message, ToolMessage):
            entry = calls.get(message.tool_call_id)
            if entry is not None:
                text = message.content if isinstance(message.content, str) else str(message.content)
                entry["result"] = (
                    text[:TOOL_RESULT_CHARS] + " …[truncated]"
                    if len(text) > TOOL_RESULT_CHARS else text
                )

    plan = final_state.get("plan") or {}
    return {
        "intent": plan.get("current_intent"),
        "scope": plan.get("scope"),
        "requires_tools": plan.get("requires_tools"),
        "tools_available": final_state.get("loadout") or [],
        "state": {
            "facts": plan.get("relevant_facts") or [],
            "constraints": plan.get("relevant_constraints") or [],
        },
        "calls": [calls[key] for key in order],
    }


async def run_one_turn(graph, *, case_id: str, turn_n: int, message: str,
                        caller_employee_id: str, thread_id: str) -> dict:
    """Run exactly one turn, as exactly one trace — auto-approving a pause
    INSIDE the same root span so a pause+resume never becomes two traces.
    """
    before_state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    before = len(before_state.values.get("messages", []))

    with langfuse.start_as_current_observation(
        as_type="agent",
        name=f"{case_id} · turn {turn_n}",
        input=message,
        metadata={"case_id": case_id, "turn": str(turn_n), "request_id": thread_id,
                  "caller_employee_id": caller_employee_id},
    ) as span:
        result = await run_turn(graph, message, caller_employee_id=caller_employee_id, thread_id=thread_id)
        terminal_status = result["status"]
        if result["status"] == "paused":
            # ONE TRACE PER TURN even across interrupt() — see module docstring.
            # This is also the write gate doing exactly its job: the model's
            # "go ahead" opened the door, a recorded decision is what walks
            # through it, never the model itself.
            result = await resume_turn(graph, thread_id=thread_id, approved=True, **AUTO_APPROVE)
            terminal_status = f"paused->resumed(approved=True)"

        after_state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
        state = after_state.values
        digest = trajectory_digest(before, state["messages"], state)
        digest["status"] = terminal_status
        digest["checklist_produced"] = bool(result.get("checklist"))
        digest["access_decision_produced"] = bool(result.get("access_decision"))

        # Repeats case_id/turn/request_id alongside trajectory rather than
        # trusting `.update()`'s metadata-merge semantics — score_eval.py's
        # join key has to survive on THIS call, not an earlier one.
        span.update(output=result["answer"], metadata={
            "case_id": case_id, "turn": str(turn_n), "request_id": thread_id,
            "caller_employee_id": caller_employee_id, "trajectory": digest,
        })
        trace_id = langfuse.get_current_trace_id()

    return {"trace_id": trace_id, "status": terminal_status, "answer": result["answer"],
            "tools_called": [c["name"] for c in digest["calls"]]}


async def run_case(app, case_id: str, caller: dict, turns: list[dict],
                    trace_index: list[dict]) -> None:
    """One input (len(turns)==1) or one session (len(turns)>1), on one fresh
    thread, one fresh langfuse session_id. Reseeding happens in `main()`,
    once per case, per EVALUATION-INPUTS.yaml's own run instructions.
    """
    run_id = f"{case_id}-{uuid.uuid4().hex[:8]}"
    print(f"\n── {case_id} ── {caller['name']} ({caller['employee_id']}, {caller.get('group', '?')})")
    print(f"── langfuse session: {run_id}")

    with propagate_attributes(
        session_id=run_id,
        user_id=caller["employee_id"],
        tags=["novaops-final", case_id.split("-")[0].lower()],
    ):
        for turn in turns:
            n = turn["n"]
            result = await run_one_turn(
                app, case_id=case_id, turn_n=n, message=turn["message"],
                caller_employee_id=caller["employee_id"], thread_id=run_id,
            )
            called = ", ".join(result["tools_called"]) or "—"
            print(f"  [turn {n:>2}] status={result['status']:<24} tools: {called}")
            print(f"            trace_id: {result['trace_id']}")
            trace_index.append({
                "case_id": case_id, "turn": n, "trace_id": result["trace_id"],
                "status": result["status"],
            })

    langfuse.flush()


def write_trace_index(trace_index: list[dict]) -> None:
    out_path = Path(__file__).resolve().parent / "TRACE_INDEX.md"
    lines = ["# Trace index — generated by `evals/run_eval.py`", "",
             "| case_id | turn | trace_id | terminal status |",
             "| ------- | ---: | -------- | ---------------- |"]
    for row in trace_index:
        lines.append(f"| `{row['case_id']}` | {row['turn']} | `{row['trace_id']}` | {row['status']} |")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n[written] {out_path} ({len(trace_index)} rows) — paste into SUBMISSION.md")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Run the required EVALUATION-INPUTS.yaml traces.")
    parser.add_argument("--case", help="run one case id only (e.g. M-S-01), for iterating")
    args = parser.parse_args()

    try:
        authenticated = langfuse.auth_check()
    except Exception:
        authenticated = False
    if not authenticated:
        raise SystemExit(
            "Langfuse keys are missing or rejected, so this run would record nothing.\n"
            "Check LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY / LANGFUSE_BASE_URL in .env."
        )

    workflows = load_eval_inputs()
    import random
    port = random.randint(20000, 40000)
    server.mcp.settings.port = port
    import model as model_module
    model_module.MCP_SERVER_URL = f"http://127.0.0.1:{port}/mcp"
    print("Warming retrieval indexes + starting MCP server...")
    server_task = asyncio.create_task(server.mcp.run_streamable_http_async())
    server.rag.warm_index()
    await asyncio.sleep(2)

    trace_index: list[dict] = []
    try:
        tools = await load_tools()
        checkpointer = await get_checkpointer()
        app = build_graph(tools, checkpointer)

        for workflow in workflows.values():
            if not workflow.get("required"):
                continue  # Vendor/Renewal are optional and not implemented here
            for one_shot in workflow.get("inputs", []):
                if args.case and one_shot["id"] != args.case:
                    continue
                db.build_db(force=True)  # reseed — INDEPENDENT case
                await run_case(app, one_shot["id"], one_shot["caller"],
                               [{"n": 1, "message": one_shot["message"]}], trace_index)
            for session in workflow.get("sessions", []):
                if args.case and session["id"] != args.case:
                    continue
                db.build_db(force=True)  # reseed — INDEPENDENT session
                await run_case(app, session["id"], session["caller"], session["turns"], trace_index)

        write_trace_index(trace_index)
        print(f"\n✓ {len(trace_index)} traces recorded.")
    finally:
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
