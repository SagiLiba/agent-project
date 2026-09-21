"""
Interactive CLI — talk to the real NovaOps agent live, as any seeded employee.

PROJECT-DESCRIPTION.md section 6: "A CLI or web chat over Maya and Webex is
optional and ungraded. If you build one, it passes caller context and a
thread id into the SAME core functions the tests call — never a second path
into the workflow." This is exactly that, nothing more: a thin input loop
around `graph.run_turn` / `graph.resume_turn` — the identical two functions
every replay test and `evals/run_eval.py` call. No new agent logic lives here.

Run:
    python src/agent/chat.py            # caller defaults to E001 (Maya Cohen)
    python src/agent/chat.py E018       # or pick any seeded employee id

In-chat commands:
    /whoami          show the current caller and thread id
    /new             start a fresh conversation (new thread), same caller
    /caller <id>     switch caller AND start a fresh conversation
    /trace on|off    toggle the "[plan]/[select]/[model]" node trace lines
    exit / quit      leave (Ctrl-D / Ctrl-C also work)

A write (create_access_request / create_ticket) always PAUSES here for you
to approve or deny by hand — the write gate is not bypassed just because
this is an interactive session.
"""

import asyncio
import random
import sys
import uuid
from pathlib import Path

AGENT_DIR = Path(__file__).resolve().parent
SERVER_DIR = AGENT_DIR.parent / "server"
sys.path.insert(0, str(AGENT_DIR))
sys.path.insert(0, str(SERVER_DIR))

import server  # noqa: E402
from graph import build_graph, get_checkpointer, resume_turn, run_turn  # noqa: E402
from model import load_tools  # noqa: E402

# A few real, seeded employees worth trying — see
# novaops-enterprise-agent-dataset/database/seed.json for the full roster.
EXAMPLE_CALLERS = {
    "E001": "Maya Cohen — Customer Success Manager (a joiner, not a manager)",
    "E018": "Yael Romano — Customer Success Director (Maya's + Rachel's manager)",
    "E010": "Rachel Stein — Customer Success Specialist (Webex seat-blocked, AR001)",
    "E004": "Sara Ben-David — People Operations Lead (files Webex requests on others' behalf)",
    "E006": "Amir Haddad — IT Manager (the approver name used in the replay tests)",
}


def new_thread() -> str:
    return f"chat-{uuid.uuid4().hex[:8]}"


async def main() -> None:
    caller = sys.argv[1] if len(sys.argv) > 1 else "E001"

    print("NovaOps — interactive chat")
    print("=" * 66)
    print("Example callers (novaops-enterprise-agent-dataset/database/seed.json"
          " has the rest):")
    for emp_id, note in EXAMPLE_CALLERS.items():
        marker = "*" if emp_id == caller else " "
        print(f"  {marker} {emp_id}  {note}")
    print("=" * 66)

    port = random.randint(20000, 40000)
    server.mcp.settings.port = port
    import model as model_module
    model_module.MCP_SERVER_URL = f"http://127.0.0.1:{port}/mcp"
    print("Starting MCP server + warming the retrieval index (~15-40s, one-off "
          "Bedrock embedding calls)...")
    server_task = asyncio.create_task(server.mcp.run_streamable_http_async())
    for corpus, count in server.rag.warm_index().items():
        print(f"  {corpus}: {count} documents indexed")
    await asyncio.sleep(2)

    try:
        tools = await load_tools()
        checkpointer = await get_checkpointer()
        graph = build_graph(tools, checkpointer)
        thread_id = new_thread()

        print(f"\nReady. Caller={caller} ({EXAMPLE_CALLERS.get(caller, 'not a listed example')})")
        print(f"Thread={thread_id}")
        print("Type a message, or 'exit' to quit.\n")

        while True:
            try:
                message = input(f"[{caller}] > ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break

            if not message:
                continue
            if message.lower() in ("exit", "quit"):
                break
            if message == "/whoami":
                print(f"  caller={caller}  thread={thread_id}")
                continue
            if message == "/new":
                thread_id = new_thread()
                print(f"  new thread: {thread_id}")
                continue
            if message.startswith("/caller"):
                parts = message.split(maxsplit=1)
                if len(parts) == 2:
                    caller = parts[1].strip()
                    thread_id = new_thread()
                    print(f"  caller switched to {caller}, new thread {thread_id}")
                else:
                    print("  usage: /caller <employee_id>")
                continue
            if message.startswith("/trace"):
                parts = message.split(maxsplit=1)
                off = len(parts) == 2 and parts[1].strip().lower() == "off"
                model_module.TRACE_ENABLED = not off
                print(f"  trace {'off' if off else 'on'}")
                continue

            result = await run_turn(graph, message, caller_employee_id=caller, thread_id=thread_id)

            if result["status"] == "paused":
                print(f"\n  >> PAUSED for human approval — payload: {result['payload']}")
                decision = input("  approve this write? [y/N] ").strip().lower()
                approved = decision == "y"
                reason = input("  reason (optional): ").strip()
                result = await resume_turn(
                    graph, thread_id=thread_id, approved=approved,
                    reason=reason or ("approved via chat CLI" if approved else "denied via chat CLI"),
                    decided_by="cli-user",
                )

            print(f"\n{result['answer']}\n")
            if result.get("checklist"):
                c = result["checklist"]
                print(f"  [checklist: {len(c['items'])} items, status={c['status']}]")
            if result.get("access_decision"):
                d = result["access_decision"]
                print(f"  [AccessDecision: status={d['status']} actions_taken={d['actions_taken']}]")
    finally:
        server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main())
