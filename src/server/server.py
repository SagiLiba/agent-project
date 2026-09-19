"""
NovaOps MCP server — policies + knowledge base + HR documents + database.

This is Lesson 10's server.py (itself Lesson 9's, itself Lesson 8's), grown by
six tools this project's two required workflows (Maya, Webex) need that no
lesson provides:

  files    list_policies · get_policy                              (unchanged)
  FAISS    search_knowledge_base · search_hr_documents              (widened corpus, Step 3)
  SQLite   get_employee · check_software_subscription
           list_onboarding_tasks · check_asset_inventory
           list_employee_tickets                                    (unchanged)
  SQLite   create_access_request                                    (unchanged — the one L10 WRITE)
  SQLite   create_ticket                                             <- Lesson 8 homework 2's WRITE
  SQLite   list_direct_reports · check_seat_assignment
           list_access_requests · list_approvals                    <- this project's FOUR reads
                                                                         (PROJECT-DESCRIPTION.md 6.3:
                                                                         "at least one capability...
                                                                         has no tool behind it")

Fifteen tools. Same caveat Lesson 10 states about ten: every schema is a
standing input-token cost on every call that has tools bound — Step 5's
per-scope LOADOUTS (Lesson 10's dynamic-tool-loadout pattern) is what keeps a
single turn from paying for all fifteen.

Run:
    python src/server/server.py        # serves at http://127.0.0.1:9878/mcp

CLOSED IN STEP 5 (was a known limitation through Step 4):

search_hr_documents takes `caller_employee_id` as an ordinary tool argument,
so nothing here stops a MODEL from choosing its own value — that alone would
be backwards for a permission check (PROJECT-DESCRIPTION.md section 12: the
audience filter must run "as a retrieval filter, not a refusal after the
fact", and a model-supplied identity is not that). This server, standing
alone, has no session to bind the argument to, so it does NOT enforce this on
its own. `src/agent/graph.py`'s `inject_caller_identity` is what actually
closes it: every tool call the agent's ToolNode executes has this argument
overwritten with the real, application-supplied caller id from graph state
BEFORE it reaches this server — so treat this file as safe only behind that
graph, never as a bare server exposed to an untrusted model directly.

CLOSED IN STEP 6 — the write gate for create_access_request / create_ticket:

Neither write tool checks anything about approval itself; both simply file a
record, same as always. Authorization lives entirely in `src/agent/graph.py`'s
`approval_gate` node, which releases either tool into a turn's loadout only
once `db.approval_is_recorded(thread_id, tool_name)` is True — a fact recorded
by a human's decision on a LangGraph `interrupt()`, never by anything the
model said. See that file's module docstring for the full mechanism.
"""

import sys
from pathlib import Path

from mcp.server.fastmcp import FastMCP

sys.path.insert(0, str(Path(__file__).resolve().parent))
import db
import rag

POLICIES_DIR = Path(__file__).resolve().parent.parent.parent / "novaops-enterprise-agent-dataset" / "documents" / "policies"

# Port 9878 — distinct from Lesson 8's 9876/9877/reference ports, matches
# MCP_SERVER_URL in .env.example, so all of them can run side by side.
mcp = FastMCP("novaops-assistant", host="127.0.0.1", port=9878)


@mcp.tool()
def list_policies() -> list[str]:
    """List the names of all available NovaOps company policies.

    Call this first to discover which policies exist before fetching one.
    """
    return sorted(p.stem for p in POLICIES_DIR.glob("*.md"))


@mcp.tool()
def get_policy(name: str) -> str:
    """Return the full text of one NovaOps policy.

    Args:
        name: A policy name as returned by list_policies, e.g. 'equipment_policy'.
    """
    path = POLICIES_DIR / f"{name}.md"
    if not path.is_file():
        raise ValueError(f"No policy named {name!r}. Call list_policies for valid names.")
    return path.read_text(encoding="utf-8")


@mcp.tool()
def search_knowledge_base(query: str) -> list[dict]:
    """Search the NovaOps IT knowledge base for articles relevant to a question.

    Use this for how-to and troubleshooting questions — password reset, VPN access,
    MFA, laptop provisioning, Webex licensing, and the like. Returns the most
    relevant articles. Unrestricted collection — no audience filtering applies.

    Args:
        query: A natural-language description of the problem or question.
    """
    return rag.search("it_kb", query)


@mcp.tool()
def search_hr_documents(query: str, caller_employee_id: str) -> list[dict]:
    """Search employment docs, memos, the handbook, manager playbook, and contracts.

    Use this for company policy/benefits/career questions, what was agreed for a
    specific person (an offer letter's equipment entitlement, a remote-work
    addendum), or a vendor contract's terms (e.g. a seat-limit clause).

    Manager-only material (the manager playbook) is filtered out unless the
    caller is a manager — resolved from the database (list_direct_reports),
    never from what this argument merely claims. See the module note below on
    why that resolution belongs one layer up from here, and why this WILL
    change shape in Step 5.

    Args:
        query: A natural-language description of what you need to find.
        caller_employee_id: The id of the employee asking, e.g. 'E001'.
    """
    is_manager = bool(db.list_direct_reports(caller_employee_id))
    return rag.search("hr_docs", query, is_manager=is_manager)


@mcp.tool()
def get_employee(query: str) -> list[dict]:
    """Look up NovaOps employees by employee id, email, or (partial) name.

    Args:
        query: An employee id (e.g. 'E001'), an email, or a name to match.
    """
    return db.get_employee(query)


@mcp.tool()
def check_software_subscription(software: str) -> list[dict]:
    """Check a SaaS subscription's seat usage — is it at or over its seat limit?

    Use this when someone can't get access to a tool (e.g. 'Webex says I'm not
    licensed') to see whether seats are available or the subscription is full.
    Also returns the annual cost and renewal date. This is an AGGREGATE count
    across all employees — it does not say which individual holds a seat; for
    that, use check_seat_assignment.

    Args:
        software: The software or vendor name, e.g. 'Webex' or 'Salesforce'.
    """
    return db.check_software_subscription(software)


@mcp.tool()
def list_onboarding_tasks(employee_id: str) -> list[dict]:
    """List an employee's onboarding checklist tasks and their statuses.

    The checklist is the system of record for onboarding — use it to answer
    "what's left?" and to see which tasks are blocked.

    Args:
        employee_id: The employee id, e.g. 'E001'.
    """
    return db.list_onboarding_tasks(employee_id)


@mcp.tool()
def check_asset_inventory(asset_type: str = "", location: str = "") -> list[dict]:
    """Check hardware inventory — what equipment is on hand and where.

    Use this for equipment questions (laptops, monitors, docks). Both arguments are
    optional filters; omit them to list everything.

    Args:
        asset_type: e.g. 'Laptop' or 'Monitor'. Omit for all types.
        location: e.g. 'Israel'. Omit for all locations.
    """
    return db.check_asset_inventory(asset_type, location)


@mcp.tool()
def list_employee_tickets(employee_id: str, status: str = "") -> list[dict]:
    """List the IT tickets raised by or for one employee.

    Use this to see what has already been reported before opening anything new.

    Args:
        employee_id: The employee id, e.g. 'E010'.
        status: Optional status filter, e.g. 'open'. Omit for all statuses.
    """
    return db.list_employee_tickets(employee_id, status)


@mcp.tool()
def create_access_request(
    employee_id: str, software: str, business_justification: str
) -> dict:
    """File an access request for an employee to a system (status: pending_approval).

    This WRITES to the database. Use it only after confirming who the employee is,
    that access is warranted, and — via list_access_requests — that no equivalent
    request already exists for this employee and system (reuse it instead of
    filing a duplicate). The request is created pending a human approval
    decision — it does not grant access on its own.

    Args:
        employee_id: The employee id the access is for, e.g. 'E001'.
        software: The software or system to request, e.g. 'Webex'.
        business_justification: A short reason for the request.
    """
    return db.create_access_request(employee_id, software, business_justification)


@mcp.tool()
def create_ticket(
    employee_id: str, subject: str, description: str, category: str
) -> dict:
    """File a new IT support ticket for an employee (status: open).

    This WRITES to the database. Lesson 8 homework 2's second write tool — files
    the ticket only; it does not diagnose, approve, or resolve anything.

    Args:
        employee_id: The employee id the ticket is for, e.g. 'E010'.
        subject: A short one-line summary.
        description: The full description of the issue.
        category: e.g. 'Access', 'Hardware', 'Security'.
    """
    return db.create_ticket(employee_id, subject, description, category)


@mcp.tool()
def list_direct_reports(manager_id: str) -> list[dict]:
    """List every employee whose manager is this employee id — i.e. "their team".

    Also NovaOps's definition of "is a manager": an id with at least one direct
    report is a manager (PROJECT-DESCRIPTION.md section 12 — this cannot be
    read off user_group; it must be derived from manager_id).

    Args:
        manager_id: The employee id to look up direct reports for, e.g. 'E018'.
    """
    return db.list_direct_reports(manager_id)


@mcp.tool()
def check_seat_assignment(employee_id: str, software: str) -> dict:
    """Check whether ONE employee personally holds an assigned seat for a system.

    Read this tool's result carefully: NovaOps does not track individual seat
    assignment anywhere, so this ALWAYS reports seat_assignment_tracked=False.
    It still returns real, useful evidence — the employee's role-based
    entitlement and the subscription's aggregate seat counts — so an honest
    "I can't answer that at the individual level" is grounded in this tool's
    result, not a refusal made up on the spot.

    Args:
        employee_id: The employee id to check, e.g. 'E010'.
        software: The software or system, e.g. 'Webex'.
    """
    return db.check_seat_assignment(employee_id, software)


@mcp.tool()
def list_access_requests(employee_id: str = "", software: str = "") -> list[dict]:
    """List access requests, optionally filtered by employee and/or system.

    Call this BEFORE create_access_request to check whether an equivalent
    request already exists — reuse it (e.g. AR001) rather than filing a
    duplicate for the same employee and system.

    Args:
        employee_id: Optional employee id filter, e.g. 'E010'. Omit for all.
        software: Optional software/system name filter, e.g. 'Webex'. Omit for all.
    """
    return db.list_access_requests(employee_id, software)


@mcp.tool()
def list_approvals(request_id: str = "") -> list[dict]:
    """List the named-approver chain for an access request.

    AR001's chain shows exactly WHY it is blocked, not just that it is: an IT
    Manager approval AND a Finance subscription-expansion approval are both
    still 'needed' (neither has even been requested from the approver yet).
    AR002's chain shows two 'pending' approvals (a manager and IT). Use this
    to report a real blocker with its actual cause, never a bare status word.

    Args:
        request_id: Optional access-request id filter, e.g. 'AR001'. Omit for all.
    """
    return db.list_approvals(request_id)


if __name__ == "__main__":
    # Build both retrieval indexes up front so the first question isn't slow.
    # The server calls Bedrock (Titan) here — capability, including model
    # calls, lives on the server side, not in the agent.
    print("Building retrieval indexes...")
    for corpus, count in rag.warm_index().items():
        print(f"  {corpus}: {count} documents")
    db.build_db(force=False)
    print(f"Database ready: {db.DB_PATH}")
    print("NovaOps MCP server → http://127.0.0.1:9878/mcp  (Ctrl-C to stop)")
    mcp.run(transport="streamable-http")
