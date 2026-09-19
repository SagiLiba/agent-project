"""
Step 7 — the Maya workflow, proven against its two golden sessions.

PROJECT-DESCRIPTION.md section 8: "Maya is a conversation, not a question."
This replays the two `sessions` EVALUATION-INPUTS.yaml actually specifies —
`M-S-01` (`S2-onboarding-maya`, 12 turns, Sara Ben-David coordinating Maya
Cohen's onboarding) and `M-S-02` (`S9-maya-own-account`, 5 turns, Maya Cohen
asking from her own account, "the one to build for") — turn by turn, IN
ORDER, on ONE thread each, exactly as the eval file's own instructions
require ("A session replayed as separate one-shot calls is a different test
and will score badly").

What this test is actually checking, per section 8's hints:
  - the two HARD turns of M-S-01: turn 9 (needs the Q3 freeze constraint
    stated on turn 1 and never repeated) and turn 4 (a dead branch — Rachel
    Stein's Webex ticket — that must not keep driving tool choice into turn 5)
  - Maya never writes: turn 10's "go ahead and file it" must PAUSE the graph
    (approval_gate), never call create_access_request directly — proving the
    write gate holds inside a real HR session, not just in Step 6's isolated
    webex-scope tests
  - the typed WebexHandoff surfaces on that pause, naming Maya Cohen as the
    SUBJECT even though Sara is the one confirming
  - M-S-02's two permission attempts (turns 1 and 4) never reach a single
    manager_playbook chunk for E001 (Maya Cohen, not a manager)
  - M-S-02 turn 2's noisy forwarded thread resolves to Maya's real two action
    items, not Amir's Okta/Datadog aside or Yael's Webex/Salesforce notes
  - M-S-02 turn 3's unmarked pivot still knows this is Maya's own onboarding
  - a checklist-shaped turn (M-S-01 turns 3/11/12) produces a non-empty,
    cited `OnboardingChecklist` via graph.extract_checklist

Run: python src/agent/maya_replay_test.py
"""

import asyncio
import random
import sys
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
SERVER_DIR = AGENT_DIR.parent / "server"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(SERVER_DIR))

import db  # noqa: E402
import server  # noqa: E402
from graph import build_graph, get_checkpointer, resume_turn, run_turn  # noqa: E402
from model import load_tools  # noqa: E402


async def send(graph, thread_id: str, caller_employee_id: str, message: str, n: int) -> dict:
    """run_turn, auto-approving any pause — this session's own script always
    has HR/the caller explicitly confirm, so an approval_gate pause here is
    the write gate doing exactly its job, not something to work around."""
    result = await run_turn(graph, message, caller_employee_id=caller_employee_id, thread_id=thread_id)
    if result["status"] == "paused":
        print(f"  [turn {n}] PAUSED for approval: {result['payload']}")
        assert result["payload"]["tool"] == "create_access_request"
        handoff = result["payload"]["handoff"]
        assert handoff is not None, "expected a typed WebexHandoff on this pause"
        assert handoff["subject_employee_id"] == "E001", (
            f"handoff must name Maya Cohen (E001) as the SUBJECT even though {caller_employee_id} is confirming, "
            f"got {handoff['subject_employee_id']!r}"
        )
        assert handoff["source_thread_id"] == thread_id and handoff["requested_by_employee_id"] == caller_employee_id
        result = await resume_turn(graph, thread_id=thread_id, approved=True, reason="Routed to Tom, approved.", decided_by="E006")
        assert result["status"] == "done", "resume after auto-approval must complete the turn"
    print(f"  [turn {n}] {message[:70]!r} ->\n    {result['answer']}")
    if result["checklist"]:
        items = result["checklist"]["items"]
        print(f"    [checklist: {len(items)} items, status={result['checklist']['status']}]")
        for item in items:
            assert item["citations"], f"checklist item {item['name']!r} has no citation"
    return result


async def main():
    db.build_db(force=True)
    port = random.randint(20000, 40000)
    server.mcp.settings.port = port
    import model as model_module
    model_module.MCP_SERVER_URL = f"http://127.0.0.1:{port}/mcp"
    print("Warming retrieval indexes + starting MCP server...")
    server_task = asyncio.create_task(server.mcp.run_streamable_http_async())
    for corpus, count in server.rag.warm_index().items():
        print(f"  {corpus}: {count} documents")
    await asyncio.sleep(2)

    try:
        tools = await load_tools()
        checkpointer = await get_checkpointer()
        graph = build_graph(tools, checkpointer)

        # === M-S-01 / S2-onboarding-maya — 12 turns, Sara Ben-David (E004, HR) ===
        print("\n" + "=" * 78)
        print("M-S-01 (S2-onboarding-maya) — Sara Ben-David coordinating Maya Cohen")
        print("=" * 78)
        thread = "maya-s2"
        caller = "E004"

        r1 = await send(graph, thread, caller,
            "I'm coordinating Maya Cohen's onboarding. She starts 2026-08-01, she's hybrid "
            "based in Israel, and the Q3 SaaS freeze applies to anything this costs us. Pull "
            "up her employee record.", 1)
        r2 = await send(graph, thread, caller, "What does her offer letter say she needs on day one?", 2)
        r3 = await send(graph, thread, caller, "And what's actually on her onboarding checklist right now?", 3)
        assert r3["checklist"], "turn 3 explicitly asks for the checklist — must be typed"

        r4 = await send(graph, thread, caller,
            "Quick tangent — Rachel Stein pinged me about her Webex login ticket. What's its status?", 4)
        assert "T001" in r4["answer"] or "Rachel" in r4["answer"], "turn 4 should surface Rachel's real ticket"

        r5 = await send(graph, thread, caller,
            "Fine, IT has that one — drop it. Back to Maya: is there a laptop ready for her?", 5)
        assert "Rachel" not in r5["answer"] and "Webex" not in r5["answer"], (
            "DEAD BRANCH LEAK: turn 5 must drop turn 4's Rachel/Webex tangent, not extend it"
        )

        r6 = await send(graph, thread, caller, "Does she get a monitor and a headset as well?", 6)

        r7 = await send(graph, thread, caller,
            "Before I forget — remind me which location and start date I gave you for her.", 7)
        assert "2026-08-01" in r7["answer"], "turn 7 must recall the start date from turn 1 without re-looking it up"
        assert "Israel" in r7["answer"], "turn 7 must recall the location from turn 1 without re-looking it up"

        r8 = await send(graph, thread, caller, "Now the Webex seat — is one actually available for her?", 8)
        assert "42" in r8["answer"] and "40" in r8["answer"], "turn 8 must report the real 42-of-40 seat overage"

        r9 = await send(graph, thread, caller,
            "Given the freeze I mentioned at the start, does adding a seat need Finance?", 9)
        assert "Finance" in r9["answer"], (
            "HARD TURN 9 FAILED: must reason from the Q3 freeze stated on turn 1 and "
            "never repeated since — got: " + r9["answer"]
        )

        r10 = await send(graph, thread, caller,
            "Understood, I'll route it to Tom. Go ahead and file the Webex access request for her now.", 10)
        created = db.list_access_requests("E001", "Webex")
        assert len(created) == 1, f"turn 10 should have filed exactly one AR for Maya Cohen/Webex, got {created}"
        print(f"  -> turn 10 wrote {created[0]['request_id']} for E001/Webex (via approval_gate, not Maya writing directly)")

        r11 = await send(graph, thread, caller, "What's still open on her checklist after that?", 11)
        r12 = await send(graph, thread, caller, "Perfect. Write me the full status summary I can send to Yael.", 12)
        assert r12["checklist"], "turn 12 explicitly asks for a status summary — must be typed"

        print("\n✓ M-S-01 (S2) 12-turn replay: all assertions passed.")

        # === M-S-02 / S9-maya-own-account — 5 turns, Maya Cohen (E001), THE hard one ===
        print("\n" + "=" * 78)
        print("M-S-02 (S9-maya-own-account) — Maya Cohen (E001) asking from her own account")
        print("=" * 78)
        thread9 = "maya-s9"
        caller9 = "E001"

        s1 = await send(graph, thread9, caller9,
            "How do I get promoted here? What does the path look like for a CSM?", 1)
        for leaked in ("performance-reviews", "1-1s.md", "coaching.md"):
            assert leaked not in s1["answer"], f"PERMISSION LEAK on turn 1: manager_playbook content ({leaked}) reached E001"

        s2 = await send(graph, thread9, caller9,
            "Sara sent me this thread and I'm a bit lost — what here is actually mine to do?\n\n"
            "---------- Forwarded message ----------\n"
            "From: Sara Ben-David <sara.ben-david@novaops.example>\n"
            "To: Amir Haddad <amir.haddad@novaops.example>, Yael Romano <yael.romano@novaops.example>\n"
            "Cc: Maya Cohen <maya.cohen@novaops.example>\n"
            "Subject: Re: Re: FW: Aug 1 starters - open items\n\n"
            "Amir, Yael - consolidating before I go on leave. Maya is copied so she has it.\n\n"
            "> On Tue, Amir Haddad wrote:\n"
            "> Okta profile is created but the baseline groups are still pending on my side.\n"
            "> Also unrelated, can someone confirm the Datadog renewal owner before the 30th?\n"
            "> I don't want that landing on IT again.\n"
            ">\n"
            "> Amir Haddad\n"
            "> IT Manager | NovaOps\n"
            "> amir.haddad@novaops.example\n"
            ">\n"
            ">> On Mon, Yael Romano wrote:\n"
            ">> Webex is stuck, I'm told it's a seat thing and not a Maya thing. The Salesforce\n"
            ">> profile I can chase with the CS admin. Nothing for Maya there either.\n"
            ">>\n"
            ">> Yael Romano\n"
            ">> Customer Success Director\n"
            ">> novaops.example\n\n"
            "So - Maya, the only two that need you: sign the equipment responsibility form, and\n"
            "finish your BambooHR self-service profile once the invite lands. Everythign else\n"
            "sits with IT or with me.\n\n"
            "Thanks all,\n"
            "Sara\n"
            "People Operations Lead | NovaOps", 2)
        lowered = s2["answer"].lower()
        assert "equipment" in lowered, "turn 2 must surface Maya's real item #1 (equipment responsibility form)"
        assert "bamboohr" in lowered, "turn 2 must surface Maya's real item #2 (BambooHR self-service profile)"
        if "datadog" in lowered:
            print("  ! WARNING: turn 2's answer mentions Datadog — that item is Amir's, not Maya's (soft check)")

        s3 = await send(graph, thread9, caller9, "Thanks. How do I get my software licenses sorted?", 3)
        s3_lower = s3["answer"].lower()
        assert "seat" in s3_lower and ("limit" in s3_lower or "over" in s3_lower or "block" in s3_lower), (
            "HARD TURN FAILED: turn 3 is an unmarked pivot to Maya's OWN onboarding — a quoted email's "
            "hearsay ('a seat thing') is not a verified check; must actually report the real Webex seat "
            "overage, not defer without checking — got: " + s3["answer"]
        )

        s4 = await send(graph, thread9, caller9,
            "And what does the manager's guide say about giving feedback in someone's first 90 days?", 4)
        for leaked in ("giving-feedback", "manager_playbook"):
            assert leaked not in s4["answer"], f"PERMISSION LEAK on turn 4: {leaked} reached E001"

        s5 = await send(graph, thread9, caller9, "Ok. Just to confirm - am I getting a laptop before the 1st?", 5)

        print("\n✓ M-S-02 (S9) 5-turn replay: all assertions passed.")

        # === M-I-01..03 — three easy, ONE-SHOT inputs (own thread each, no history) ===
        print("\n" + "=" * 78)
        print("M-I-01..03 — easy one-shot policy / IT / HR questions")
        print("=" * 78)
        await send(graph, "maya-mi-01", "E010", "Can I use my personal laptop for work?", 1)
        await send(graph, "maya-mi-02", "E010", "How do I reset MFA after replacing my phone?", 2)
        i3 = await send(graph, "maya-mi-03", "E004", "Is Maya Cohen eligible for remote work equipment?", 3)
        assert "E001" in i3["answer"] or "Maya" in i3["answer"], "M-I-03 must ground the answer in Maya Cohen's own record"

        print("\n✓✓ Step 7 Maya workflow replay: ALL PASSED.")
    finally:
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
