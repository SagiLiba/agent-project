"""
Step 5 smoke test — the agent backbone, end to end, in one process.

Starts the real MCP server (server.py) as a background asyncio task in THIS
event loop (no OS-level backgrounding, no separate port-binding process — just
one script), connects the real MultiServerMCPClient to it, builds the real
graph, and drives it through langgraph_ainvoke exactly as run_turn does.

Run: python src/agent/smoke_test.py
"""

import asyncio
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
SERVER_DIR = AGENT_DIR.parent / "server"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(SERVER_DIR))

from langchain_core.messages import AIMessage  # noqa: E402

import db  # noqa: E402
import server  # noqa: E402
from graph import build_graph, get_checkpointer, inject_caller_identity, run_turn  # noqa: E402
from model import load_tools  # noqa: E402
from policy import select_tools, TurnPlan  # noqa: E402


async def main():
    # --- 0. deterministic policy unit checks (no model, no network) ---------
    maya_confirmed = TurnPlan(
        scope="maya", current_intent="access_request", requires_tools=True, action_confirmed=True,
    )
    webex_confirmed = TurnPlan(
        scope="webex", current_intent="access_request", requires_tools=True, action_confirmed=True,
    )
    webex_other_confirmed = TurnPlan(
        scope="webex", current_intent="other", requires_tools=True, action_confirmed=True,
    )
    assert "create_access_request" not in select_tools(maya_confirmed), (
        "LEAK: maya scope released a write tool"
    )
    assert "create_access_request" in select_tools(webex_confirmed), (
        "webex scope + confirmed access_request should release create_access_request"
    )
    assert not (set(select_tools(webex_other_confirmed)) & {"create_access_request", "create_ticket"}), (
        "LEAK: fail-open 'other' intent released a write tool"
    )
    print("0. policy.select_tools gates: PASS (maya never writes; webex only on confirmed+matching intent)")

    # --- 0b. caller-injection unit check: prove the OVERRIDE, not just that a
    #         real question happens to trigger the tool (it may not, per the
    #         planner's own judgment — that is not this test's concern).
    spoofed = AIMessage(
        content="",
        tool_calls=[{
            "name": "search_hr_documents",
            "args": {"query": "promotion", "caller_employee_id": "E018"},  # model claims manager
            "id": "call_1",
        }],
    )
    fake_state = {"messages": [spoofed], "caller": {"employee_id": "E001"}}  # REAL caller: non-manager
    inject_caller_identity(fake_state, tools=[])
    injected = fake_state["messages"][0].tool_calls[0]["args"]["caller_employee_id"]
    assert injected == "E001", f"caller injection failed: model's E018 was not overridden, got {injected!r}"
    print("0b. inject_caller_identity: PASS (model proposed E018, state's real caller E001 won)")

    # --- 1. start the real MCP server in this event loop ---------------------
    db.build_db(force=True)  # fresh db, this run's E010/E018/AR001 rows are known
    # A throwaway port for this smoke test run only — avoids clashing with any
    # other server.py instance already bound to 9878 on this machine.
    import model as model_module
    import random
    port = random.randint(20000, 40000)
    server.mcp.settings.port = port
    model_module.MCP_SERVER_URL = f"http://127.0.0.1:{port}/mcp"
    print("Warming retrieval indexes + starting MCP server (this calls Bedrock; ~40s)...")
    server_task = asyncio.create_task(server.mcp.run_streamable_http_async())
    for corpus, count in server.rag.warm_index().items():
        print(f"  {corpus}: {count} documents")
    await asyncio.sleep(2)  # let the HTTP transport finish binding

    try:
        tools = await load_tools()
        print(f"1. Connected — discovered {len(tools)} tools: {sorted(t.name for t in tools)}")
        assert len(tools) == 14

        checkpointer = await get_checkpointer()
        graph = build_graph(tools, checkpointer)

        # --- 2. Maya scope: a policy question, no write ever possible --------
        answer = await run_turn(
            graph,
            "How do I get promoted here? What does the path look like for a CSM?",
            caller_employee_id="E001",  # Maya Cohen — not a manager
            thread_id="smoke-maya-1",
        )
        print(f"\n2. Maya scope answer (E001, non-manager):\n   {answer}")

        # --- 3. Caller-injection proof: model cannot spoof manager identity --
        # Ask the SAME graph, SAME question, but as E018 (a real manager) on a
        # fresh thread. If caller injection works, this run can surface
        # manager_playbook content; run 2 above never could, no matter what
        # the model tried to pass as caller_employee_id.
        answer_mgr = await run_turn(
            graph,
            "How do I get promoted here? What does the path look like for a CSM?",
            caller_employee_id="E018",  # Yael Romano — a real manager (has direct reports)
            thread_id="smoke-maya-2",
        )
        print(f"\n3. Same question as E018 (real manager):\n   {answer_mgr}")

        # --- 4. Webex scope: the seat-assignment gap tool (W-I-02 shape) -----
        answer_webex = await run_turn(
            graph,
            "I'm Yael Romano's team lead question: does Rachel Stein (E010) personally hold a Webex seat?",
            caller_employee_id="E018",
            thread_id="smoke-webex-1",
        )
        print(f"\n4. Webex scope, seat-assignment question:\n   {answer_webex}")

        # --- 5. Checkpointer durability: a SECOND, independent connection to
        #        the same file (simulates a process restart) still sees the thread.
        checkpointer2 = await get_checkpointer()
        graph2 = build_graph(tools, checkpointer2)
        state = await graph2.aget_state({"configurable": {"thread_id": "smoke-maya-1"}})
        print(f"\n5. Rebuilt graph, same thread_id 'smoke-maya-1' -> "
              f"{len(state.values.get('messages', []))} messages recovered from SQLite "
              f"(novaops_checkpoints.db) after a fresh build_graph() call.")
        assert state.values.get("messages"), "checkpoint did not survive a fresh build_graph()"

        print("\n✓ Step 5 backbone smoke test all passed.")
    finally:
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
