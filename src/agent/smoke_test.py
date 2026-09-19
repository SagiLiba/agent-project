"""
Step 5/6 smoke test — the agent backbone AND the write gate, end to end, in
one process.

Starts the real MCP server (server.py) as a background asyncio task in THIS
event loop (no OS-level backgrounding, no separate port-binding process — just
one script), connects the real MultiServerMCPClient to it, builds the real
graph, and drives it through langgraph_ainvoke exactly as run_turn/resume_turn
do. Sections 0-5 are Step 5 (unchanged in substance); sections 6-8 are Step 6's
write gate: pause-on-interrupt, resume-approved, resume-denied, the
already-approved short-circuit, and a simulated process restart mid-pause.

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
from graph import build_graph, get_checkpointer, inject_caller_identity, resume_turn, run_turn  # noqa: E402
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
    # Step 6: select_tools no longer releases ANY write tool, in EITHER scope —
    # not even webex + confirmed. That release now happens only in graph.py's
    # approval_gate, gated on db.approval_is_recorded, never on this plan alone.
    assert "create_access_request" not in select_tools(webex_confirmed), (
        "select_tools must never release a write tool itself post-Step 6 — that is approval_gate's job"
    )
    assert not (set(select_tools(webex_other_confirmed)) & {"create_access_request", "create_ticket"}), (
        "LEAK: fail-open 'other' intent released a write tool"
    )
    print("0. policy.select_tools gates: PASS (no scope, no intent, ever releases a write tool anymore)")

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
        assert len(tools) == 15

        checkpointer = await get_checkpointer()
        graph = build_graph(tools, checkpointer)

        # --- 2. Maya scope: a policy question, no write ever possible --------
        result = await run_turn(
            graph,
            "How do I get promoted here? What does the path look like for a CSM?",
            caller_employee_id="E001",  # Maya Cohen — not a manager
            thread_id="smoke-maya-1",
        )
        assert result["status"] == "done"
        print(f"\n2. Maya scope answer (E001, non-manager):\n   {result['answer']}")

        # --- 3. Caller-injection proof: model cannot spoof manager identity --
        # Ask the SAME graph, SAME question, but as E018 (a real manager) on a
        # fresh thread. If caller injection works, this run can surface
        # manager_playbook content; run 2 above never could, no matter what
        # the model tried to pass as caller_employee_id.
        result_mgr = await run_turn(
            graph,
            "How do I get promoted here? What does the path look like for a CSM?",
            caller_employee_id="E018",  # Yael Romano — a real manager (has direct reports)
            thread_id="smoke-maya-2",
        )
        assert result_mgr["status"] == "done"
        print(f"\n3. Same question as E018 (real manager):\n   {result_mgr['answer']}")

        # --- 4. Webex scope: the seat-assignment gap tool (W-I-02 shape) -----
        result_webex = await run_turn(
            graph,
            "I'm Yael Romano's team lead question: does Rachel Stein (E010) personally hold a Webex seat?",
            caller_employee_id="E018",
            thread_id="smoke-webex-1",
        )
        assert result_webex["status"] == "done"
        print(f"\n4. Webex scope, seat-assignment question:\n   {result_webex['answer']}")

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

        # --- 6. Write gate: a confirmed webex access request PAUSES, not writes
        thread_a = "smoke-webex-2"
        assert db.list_access_requests("E003", "Slack") == [], "test assumes E003 has no prior Slack request"
        paused = await run_turn(
            graph,
            "Please go ahead and file an access request for E003 for Slack, "
            "business justification: general team collaboration.",
            caller_employee_id="E003",
            thread_id=thread_a,
        )
        assert paused["status"] == "paused", f"expected a pause for human approval, got {paused}"
        assert paused["payload"]["tool"] == "create_access_request"
        assert db.get_pending_write_approval(thread_a, "create_access_request") is not None
        assert db.list_access_requests("E003", "Slack") == [], "must NOT write before approval is recorded"
        print(f"\n6. Confirmed webex write PAUSED for human approval: {paused['payload']}")

        # --- 7. Resume approved: NOW the write actually happens -------------
        resumed = await resume_turn(graph, thread_id=thread_a, approved=True, reason="IT approved.", decided_by="E006")
        assert resumed["status"] == "done", f"expected completion after approval, got {resumed}"
        assert db.approval_is_recorded(thread_a, "create_access_request") is True
        created = db.list_access_requests("E003", "Slack")
        assert len(created) == 1, f"expected exactly one new AR for E003/Slack, got {created}"
        print(f"\n7. Resumed approved -> wrote {created[0]['request_id']}:\n   {resumed['answer']}")

        # --- 7b. Re-confirming on the SAME already-approved thread must NOT
        #         pause again — the short-circuit in approval_gate, proven live.
        reconfirmed = await run_turn(
            graph, "Yes, please go ahead and file that Slack access request.",
            caller_employee_id="E003", thread_id=thread_a,
        )
        assert reconfirmed["status"] == "done", "an already-approved (thread, tool) must never re-interrupt"
        print(f"\n7b. Re-confirming an already-approved case did NOT re-pause: PASS")

        # --- 8. Resume denied: the write NEVER happens, and it is not recorded
        #        as an approval — only as a denial a human could reconsider.
        thread_b = "smoke-webex-3"
        assert db.list_access_requests("E009", "GitHub") == [], "test assumes E009 has no prior GitHub request"
        paused_b = await run_turn(
            graph,
            "Please go ahead and file an access request for E009 for GitHub, "
            "business justification: reviewing a vendor integration.",
            caller_employee_id="E009",
            thread_id=thread_b,
        )
        assert paused_b["status"] == "paused"
        denied = await resume_turn(graph, thread_id=thread_b, approved=False, reason="Not justified.", decided_by="E006")
        assert denied["status"] == "done"
        assert db.approval_is_recorded(thread_b, "create_access_request") is False
        assert db.list_access_requests("E009", "GitHub") == [], "a denied write must never have executed"
        print(f"\n8. Resumed DENIED -> no write, model told the user:\n   {denied['answer']}")

        # --- 9. Process-restart proof: pause on a NEW thread, then resume from
        #        a FRESH checkpointer + FRESH graph (simulates killing the
        #        process between the interrupt and the human's decision).
        thread_c = "smoke-webex-4"
        assert db.list_access_requests("E017", "Jira") == [], "test assumes E017 has no prior Jira request"
        paused_c = await run_turn(
            graph,
            "Please go ahead and file an access request for E017 for Jira, "
            "business justification: tracking security review tickets.",
            caller_employee_id="E017",
            thread_id=thread_c,
        )
        assert paused_c["status"] == "paused"
        checkpointer3 = await get_checkpointer()      # a fresh connection, as after a restart
        graph3 = build_graph(tools, checkpointer3)     # a fresh graph object — no shared Python state with `graph`
        resumed_c = await resume_turn(graph3, thread_id=thread_c, approved=True, reason="IT approved.", decided_by="E006")
        assert resumed_c["status"] == "done", "a fresh graph+checkpointer must resume the SAME paused case"
        assert len(db.list_access_requests("E017", "Jira")) == 1
        print(f"\n9. Paused on `graph`, resumed on a FRESH graph+checkpointer (simulated restart): PASS")

        print("\n✓ Step 6 write-gate smoke test all passed.")
    finally:
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
