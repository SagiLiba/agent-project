"""
NovaOps database layer — file-backed SQLite (deliberately NOT in-memory).

This deviates from the Lesson 10 reference (`server/db.py`) in exactly one way,
and it matters: Lesson 10 builds an in-memory SQLite database that silently
resets on every process restart, which is fine for a single-session classroom
demo. This project needs the opposite in two places:

  - Milestone 4 (Webex): a pending approval must survive the process dying
    between the interrupt and the human's decision. An in-memory db can't do
    that — there is nothing left to resume into after a restart.
  - Milestone 5 (evaluation harness): independent cases must be reseeded so one
    case's writes cannot leak into the next, while turns WITHIN one session must
    see each other's writes. A real file we can explicitly rebuild gives us both;
    an in-memory db resets whether we want it to or not.

Six read/write functions below are carried over from Lesson 10's db.py verbatim
in logic (same queries, same seed data, same column set) — only the connection
lifecycle changed.

Four functions below are this project's additions (Step 4). None of the ten
Lesson 10 tools, nor Lesson 8 homework 2's `create_ticket`, cover them — see
PROJECT-DESCRIPTION.md section 6.3 ("at least one capability... has no tool
behind it in any lesson"):

  - `list_direct_reports(manager_id)` — resolves "my team" (section 12: a
    caller is a manager when some employee's manager_id is their id — this
    function is that rule, and doubles as the is_manager check for the
    audience-restricted RAG filter).
  - `check_seat_assignment(employee_id, software)` — THE missing-capability
    tool `W-I-02` is built around. There is no employee-to-seat table;
    `employees.systems_allowed_by_role` records role ENTITLEMENT, not an
    assigned seat, and `software_subscriptions` only has aggregate counts.
    This function says so explicitly, so the honest "can't tell you at the
    individual level" answer is grounded in a tool result, not model
    restraint (section 12's own framing of the requirement).
  - `list_access_requests(employee_id, software)` — the read half of
    `create_access_request`; nothing else can see the access_requests table,
    and Step 6/8's write gate needs it for idempotency (`W-I-03`/`S8`: reuse
    `AR001`, never file a duplicate).
  - `create_ticket(employee_id, subject, description, category)` — Lesson 8
    homework 2's second write tool, ported to this dataset's real id
    convention (`T001`, `T002`... matching seed.sql) instead of the
    homework's illustrative `TCK-0001`.

Step 6 adds a fifth read (`list_approvals`) and four functions that are NOT MCP
tools at all — they back the write gate itself:

  - `list_approvals(request_id)` — exposes the `approvals` table schema.sql
    already defines. seed.sql seeds it with REAL named-approver chains for
    AR001 (blocked: IT + Finance approval both still `needed` — the actual
    reason W-I-03 is blocked) and AR002 (`pending` on a manager and IT sign-
    off). Without this, nothing can report those chains; get_employee/
    list_access_requests only show that AR001 is 'blocked', never why.

  - `request_write_approval` / `record_write_decision` / `approval_is_recorded`
    / `get_pending_write_approval` — the write gate's OWN ledger, reusing this
    same `approvals` table for a DIFFERENT purpose than the four rows above:
    seed.sql's rows chain a real approver to a real `access_requests.request_id`
    that already exists; these four functions instead gate the AGENT's own
    decision to call `create_access_request` in the first place, before any
    such row exists yet. request_type is a TOOL NAME here (e.g.
    'create_access_request'), not a business concept, and request_id is the
    conversation's thread_id, not an AR id — a deliberate, documented reuse of
    one generic table for two related but distinct kinds of approval, not a
    schema collision (nothing here reads or writes AR001-AR004's own rows).
    Deliberately NOT exposed as MCP tools — see graph.py's approval_gate:
    "never against the model's reading of go-ahead" (PROJECT-DESCRIPTION.md
    section 12) means the model must never be able to call the function that
    records its own approval. The agent layer imports this module directly.
"""

import functools
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

DB_PATH = Path(os.getenv("NOVAOPS_DB_PATH", "./novaops.db")).resolve()
DATASET_ROOT = Path(
    os.getenv("NOVAOPS_DATASET_ROOT", "./novaops-enterprise-agent-dataset")
).resolve()
SCHEMA_SQL = DATASET_ROOT / "database" / "schema.sql"
SEED_SQL = DATASET_ROOT / "database" / "seed.sql"

# Only non-sensitive profile columns — same restriction as the Lesson 10
# reference. A production version would also filter by the caller's user group
# (HR-only fields exist); that guardrail lives in the retrieval/tool-scope
# layer (Step 3/5), not here.
EMPLOYEE_FIELDS = (
    "employee_id, full_name, email, role, department_id, "
    "manager_id, location, employment_type, status"
)


def build_db(force: bool = False) -> None:
    """Create novaops.db from schema.sql + seed.sql if it doesn't exist yet.

    `force=True` deletes and rebuilds unconditionally — this is the eval
    harness's reseed hook (Milestone 5 requires reseeding between independent
    cases; see EVALUATION-INPUTS.yaml's run instructions). Call it with
    force=False (the default) everywhere else so a session's writes persist
    across turns and across a restart.
    """
    if force:
        _conn.cache_clear()
        if DB_PATH.exists():
            DB_PATH.unlink()
    elif DB_PATH.exists():
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA_SQL.read_text(encoding="utf-8"))
    conn.executescript(SEED_SQL.read_text(encoding="utf-8"))
    conn.commit()
    conn.close()


@functools.lru_cache(maxsize=1)
def _conn() -> sqlite3.Connection:
    """One shared connection to the on-disk db for this process's lifetime.

    check_same_thread=False for the same reason as the Lesson 10 reference:
    FastMCP runs sync tools in a worker thread that may not be the thread that
    first opened this connection.
    """
    build_db(force=False)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def get_employee(query: str) -> list[dict]:
    """Look up NovaOps employees by id, email, or (partial) name.

    Returns EVERY match — the seed data intentionally has duplicate first names
    (two Daniels, two Mayas, two Saras), so a name search can return more than
    one person, which the caller then has to disambiguate by id.
    """
    like = f"%{query}%"
    rows = _conn().execute(
        f"SELECT {EMPLOYEE_FIELDS} FROM employees "
        "WHERE employee_id = ? OR lower(email) = lower(?) OR lower(full_name) LIKE lower(?) "
        "ORDER BY full_name",
        (query, query, like),
    ).fetchall()
    return [dict(row) for row in rows]


def check_software_subscription(software: str) -> list[dict]:
    """Look up a SaaS subscription's seat usage by software or vendor name.

    Returns seat_limit against active_seats, plus a computed `over_limit` flag —
    the signal the Webex workflow reads to decide whether a request needs
    approval before it can proceed.
    """
    like = f"%{software}%"
    rows = _conn().execute(
        "SELECT sys.system_name, v.vendor_name, sub.seat_limit, sub.active_seats, "
        "       sub.status, sub.renewal_date, sub.annual_cost "
        "FROM software_subscriptions sub "
        "JOIN systems sys ON sub.system_id = sys.system_id "
        "JOIN vendors  v  ON sub.vendor_id = v.vendor_id "
        "WHERE lower(sys.system_name) LIKE lower(?) OR lower(v.vendor_name) LIKE lower(?) "
        "ORDER BY sys.system_name",
        (like, like),
    ).fetchall()
    results = []
    for row in rows:
        sub = dict(row)
        sub["seats_available"] = sub["seat_limit"] - sub["active_seats"]
        sub["over_limit"] = sub["active_seats"] >= sub["seat_limit"]
        results.append(sub)
    return results


def list_onboarding_tasks(employee_id: str) -> list[dict]:
    """Return one employee's onboarding checklist, earliest due date first."""
    rows = _conn().execute(
        "SELECT task_id, task_type, description, owner_group, status, due_date "
        "FROM onboarding_tasks WHERE employee_id = ? ORDER BY due_date, task_id",
        (employee_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def check_asset_inventory(asset_type: str = "", location: str = "") -> list[dict]:
    """Return hardware assets, optionally narrowed to a type and/or a location."""
    rows = _conn().execute(
        "SELECT asset_id, asset_type, model, status, location, employee_id, notes "
        "FROM assets "
        "WHERE lower(asset_type) LIKE lower(?) AND lower(location) LIKE lower(?) "
        "ORDER BY asset_type, asset_id",
        (f"%{asset_type}%", f"%{location}%"),
    ).fetchall()
    return [dict(row) for row in rows]


def list_employee_tickets(employee_id: str, status: str = "") -> list[dict]:
    """Return an employee's IT tickets, newest first; optionally filter by status."""
    rows = _conn().execute(
        "SELECT ticket_id, category, subcategory, priority, status, subject, "
        "       created_at, assigned_team "
        "FROM tickets WHERE employee_id = ? AND lower(status) LIKE lower(?) "
        "ORDER BY created_at DESC",
        (employee_id, f"%{status}%"),
    ).fetchall()
    return [dict(row) for row in rows]


def create_access_request(
    employee_id: str,
    software: str,
    business_justification: str,
    access_level: str = "standard_user",
) -> dict:
    """File an access request for an employee to a system — or REUSE the one
    that already exists (status pending_approval either way it's fresh).

    Section 9's hint is explicit that this cannot be left to good prompting:
    "Idempotency is not decoration. Run the case twice and assert the row
    counts are unchanged." AR001 already exists for Rachel Stein/Webex
    (seed.sql) precisely so this path gets exercised — W-S-01/W-I-03 are
    graded on NOT creating an AR002 next to it. So the check lives HERE, one
    level below the model's own judgment, not only in list_access_requests'
    docstring telling the model to check first: whatever the model did or
    didn't check, calling this twice for the same (employee, system) can
    never produce a second row. Returns `reused: True/False` so a caller
    (graph.py's extract_access_decision) can report accurately which
    happened — "actions actually taken" must never claim a fresh filing that
    didn't happen.

    Approval is a separate, human step gated well above this function
    (Step 6's write gate); this function only runs once that gate has
    already opened, and it does not decide the request either way.
    """
    conn = _conn()

    if conn.execute(
        "SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone() is None:
        raise ValueError(f"No employee {employee_id!r}. Look them up with get_employee first.")

    system = conn.execute(
        "SELECT system_id, system_name FROM systems "
        "WHERE lower(system_name) LIKE lower(?) ORDER BY system_name LIMIT 1",
        (f"%{software}%",),
    ).fetchone()
    if system is None:
        raise ValueError(f"No system matching {software!r}.")

    existing = conn.execute(
        "SELECT request_id, employee_id, system_id, access_level, status, created_at "
        "FROM access_requests WHERE employee_id = ? AND system_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (employee_id, system["system_id"]),
    ).fetchone()
    if existing is not None:
        return {
            "request_id": existing["request_id"],
            "employee_id": existing["employee_id"],
            "system_id": existing["system_id"],
            "system_name": system["system_name"],
            "access_level": existing["access_level"],
            "status": existing["status"],
            "created_at": existing["created_at"],
            "reused": True,
        }

    last = conn.execute(
        "SELECT request_id FROM access_requests ORDER BY request_id DESC LIMIT 1"
    ).fetchone()
    next_num = int(last["request_id"][2:]) + 1 if last else 1
    request_id = f"AR{next_num:03d}"

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO access_requests "
        "(request_id, employee_id, system_id, access_level, business_justification, "
        " status, approver_id, created_at, decision_reason) "
        "VALUES (?, ?, ?, ?, ?, 'pending_approval', NULL, ?, NULL)",
        (request_id, employee_id, system["system_id"], access_level,
         business_justification, created_at),
    )
    conn.commit()
    return {
        "request_id": request_id,
        "employee_id": employee_id,
        "system_id": system["system_id"],
        "system_name": system["system_name"],
        "access_level": access_level,
        "status": "pending_approval",
        "created_at": created_at,
        "reused": False,
    }


def list_direct_reports(manager_id: str) -> list[dict]:
    """Return every employee whose manager_id is this id.

    This IS the "is a manager" check (PROJECT-DESCRIPTION.md section 12):
    `audience: manager` cannot be resolved from `user_group` (two of five
    people who manage someone are on the same UG_REGULAR group as everyone
    else), so it is derived from the data instead — a caller is a manager
    exactly when this returns a non-empty list for their own id. Called from
    two places: server.py's tool (answering "who's on my team"), and rag.py's
    is_manager gate (server.py resolves it before calling search_hr_documents).
    """
    rows = _conn().execute(
        f"SELECT {EMPLOYEE_FIELDS} FROM employees WHERE manager_id = ? ORDER BY full_name",
        (manager_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def check_seat_assignment(employee_id: str, software: str) -> dict:
    """Report whether this employee currently holds an assigned seat for a system.

    The answer is always "not tracked at the individual level" — deliberately.
    `employees.systems_allowed_by_role` records role-based ENTITLEMENT (who is
    ALLOWED to use a system); `software_subscriptions` records only aggregate
    `seat_limit`/`active_seats` COUNTS. Neither, nor anything else in this
    schema, maps a specific employee to a specific seat. `W-I-02` ("which of
    my team holds a Webex seat") has no precise answer for exactly this
    reason — reading `systems_allowed_by_role` instead produces a fluent,
    wrong answer, because entitlement is not assignment.

    This function's whole job is to make that gap explicit and citable: it
    returns the employee's entitlement and the subscription's aggregate
    counts as evidence, and states plainly that individual assignment is not
    tracked — so the honest answer is grounded in a tool result, not restraint.
    """
    employee = _conn().execute(
        "SELECT employee_id, full_name, systems_allowed_by_role FROM employees WHERE employee_id = ?",
        (employee_id,),
    ).fetchone()
    if employee is None:
        raise ValueError(f"No employee {employee_id!r}. Look them up with get_employee first.")

    entitled_by_role = software.lower() in (employee["systems_allowed_by_role"] or "").lower()
    subscriptions = check_software_subscription(software)

    return {
        "employee_id": employee_id,
        "full_name": employee["full_name"],
        "software": software,
        "entitled_by_role": entitled_by_role,
        "seat_assignment_tracked": False,
        "reason": (
            "NovaOps does not record which individual employee holds an assigned "
            "seat for a system. 'entitled_by_role' reflects role-based eligibility "
            "(employees.systems_allowed_by_role), not an actual seat; "
            "'subscription' below is an aggregate seat_limit/active_seats count "
            "across ALL employees, not this one. Whether this specific employee "
            "personally occupies one of the active seats cannot be answered from "
            "this database."
        ),
        "subscription": subscriptions[0] if subscriptions else None,
    }


def list_access_requests(employee_id: str = "", software: str = "") -> list[dict]:
    """Return access requests, optionally filtered by employee and/or system.

    The read half of create_access_request — nothing exposes the
    access_requests table otherwise. Needed for idempotency: check for an
    existing request before filing a new one, so a replayed turn reuses
    AR001 rather than creating a duplicate (W-I-03 / S8).
    """
    rows = _conn().execute(
        "SELECT ar.request_id, ar.employee_id, sys.system_name, ar.access_level, "
        "       ar.business_justification, ar.status, ar.approver_id, ar.created_at, "
        "       ar.decision_reason "
        "FROM access_requests ar "
        "JOIN systems sys ON ar.system_id = sys.system_id "
        "WHERE ar.employee_id LIKE ? AND lower(sys.system_name) LIKE lower(?) "
        "ORDER BY ar.created_at DESC",
        (f"%{employee_id}%", f"%{software}%"),
    ).fetchall()
    return [dict(row) for row in rows]


def create_ticket(
    employee_id: str,
    subject: str,
    description: str,
    category: str,
) -> dict:
    """File a new IT support ticket for an employee; status 'open'.

    Lesson 8 homework 2's second write tool: validate the employee exists,
    insert into `tickets` with a generated id, and return the created record.
    No approval logic here, by design — same boundary as create_access_request:
    this function only files the ticket, it never decides anything.

    Ported to this dataset's real id convention (T001, T002... — see
    seed.sql) rather than the homework's illustrative TCK-0001, and every
    ticket in the seed data routes to 'IT' regardless of category, so that is
    the one static assigned_team here — there's no data yet to justify a
    real category->team table.
    """
    conn = _conn()
    if conn.execute(
        "SELECT 1 FROM employees WHERE employee_id = ?", (employee_id,)
    ).fetchone() is None:
        raise ValueError(f"No employee {employee_id!r}. Look them up with get_employee first.")

    last = conn.execute(
        "SELECT ticket_id FROM tickets ORDER BY ticket_id DESC LIMIT 1"
    ).fetchone()
    next_num = int(last["ticket_id"][1:]) + 1 if last else 1
    ticket_id = f"T{next_num:03d}"
    assigned_team = "IT"

    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO tickets "
        "(ticket_id, employee_id, category, subcategory, priority, status, subject, "
        " description, created_at, assigned_team, related_system_id) "
        "VALUES (?, ?, ?, '', 'medium', 'open', ?, ?, ?, ?, NULL)",
        (ticket_id, employee_id, category, subject, description, created_at, assigned_team),
    )
    conn.commit()
    return {
        "ticket_id": ticket_id,
        "employee_id": employee_id,
        "category": category,
        "status": "open",
        "subject": subject,
        "assigned_team": assigned_team,
        "created_at": created_at,
    }


def list_approvals(request_id: str = "") -> list[dict]:
    """Return approval-chain rows, optionally filtered to one request_id.

    Read tool. Exposes named-approver chains such as AR001's (IT Manager E006
    AND Finance E011, both still 'needed' — the actual reason it is blocked,
    not just that it is) and AR002's (manager E013 and IT E006, both
    'pending'). This is how the Webex workflow reports a real blocker instead
    of a bare status string (Milestone 4: "find the real blocker and report
    it truthfully").
    """
    rows = _conn().execute(
        "SELECT approval_id, request_type, request_id, approver_id, status, "
        "       decision_reason, created_at "
        "FROM approvals WHERE request_id LIKE ? ORDER BY created_at",
        (f"%{request_id}%",),
    ).fetchall()
    return [dict(row) for row in rows]


# --- Write-gate ledger (Step 6) — NOT MCP tools; see module docstring. ------

def _next_approval_id(conn: sqlite3.Connection) -> str:
    last = conn.execute(
        "SELECT approval_id FROM approvals ORDER BY approval_id DESC LIMIT 1"
    ).fetchone()
    next_num = int(last["approval_id"][2:]) + 1 if last else 1
    return f"AP{next_num:03d}"


def request_write_approval(thread_id: str, tool_name: str) -> dict:
    """Open (or return the existing) pending gate for one (thread, tool) pair.

    Idempotent by design — this is what lets the graph call it again on every
    resume without filing a duplicate row: an existing 'approved' or 'pending'
    row is returned as-is; only a missing or previously-'denied' row gets a
    fresh 'pending' one (a denial is not permanent — a human can reconsider).
    """
    conn = _conn()
    existing = conn.execute(
        "SELECT approval_id, request_type, request_id, approver_id, status, "
        "       decision_reason, created_at "
        "FROM approvals WHERE request_type = ? AND request_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (tool_name, thread_id),
    ).fetchone()
    if existing is not None and existing["status"] in ("pending", "approved"):
        return dict(existing)

    approval_id = _next_approval_id(conn)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    conn.execute(
        "INSERT INTO approvals "
        "(approval_id, request_type, request_id, approver_id, status, decision_reason, created_at) "
        "VALUES (?, ?, ?, '', 'pending', NULL, ?)",
        (approval_id, tool_name, thread_id, created_at),
    )
    conn.commit()
    return {
        "approval_id": approval_id, "request_type": tool_name, "request_id": thread_id,
        "approver_id": "", "status": "pending", "decision_reason": None, "created_at": created_at,
    }


def record_write_decision(
    thread_id: str, tool_name: str, *, approved: bool, reason: str = "", decided_by: str = "human",
) -> dict:
    """Record a human's decision against the pending gate for (thread, tool).

    Raises if no pending row exists — a decision must always be ABOUT a gate
    that request_write_approval already opened; there is no path that lets a
    decision get recorded without one.
    """
    conn = _conn()
    pending = conn.execute(
        "SELECT approval_id FROM approvals "
        "WHERE request_type = ? AND request_id = ? AND status = 'pending' "
        "ORDER BY created_at DESC LIMIT 1",
        (tool_name, thread_id),
    ).fetchone()
    if pending is None:
        raise ValueError(
            f"No pending approval for tool={tool_name!r} thread={thread_id!r}. "
            "Call request_write_approval first."
        )
    status = "approved" if approved else "denied"
    conn.execute(
        "UPDATE approvals SET status = ?, decision_reason = ?, approver_id = ? "
        "WHERE approval_id = ?",
        (status, reason or None, decided_by, pending["approval_id"]),
    )
    conn.commit()
    row = conn.execute(
        "SELECT approval_id, request_type, request_id, approver_id, status, "
        "       decision_reason, created_at FROM approvals WHERE approval_id = ?",
        (pending["approval_id"],),
    ).fetchone()
    return dict(row)


def approval_is_recorded(thread_id: str, tool_name: str) -> bool:
    """True only if a human has already APPROVED this exact (thread, tool) gate.

    The one function graph.py's approval_gate trusts to release a write tool
    into a turn's loadout — never `action_confirmed`, never anything the model
    said. A 'pending' or 'denied' row is not an approval; only 'approved' is.
    """
    row = _conn().execute(
        "SELECT 1 FROM approvals WHERE request_type = ? AND request_id = ? AND status = 'approved'",
        (tool_name, thread_id),
    ).fetchone()
    return row is not None


def get_pending_write_approval(thread_id: str, tool_name: str) -> dict | None:
    """Return the open pending gate for (thread, tool), or None.

    Lets the graph (or a resumed process after a restart) check whether a case
    is already mid-pause without triggering a second interrupt.
    """
    row = _conn().execute(
        "SELECT approval_id, request_type, request_id, approver_id, status, "
        "       decision_reason, created_at FROM approvals "
        "WHERE request_type = ? AND request_id = ? AND status = 'pending' "
        "ORDER BY created_at DESC LIMIT 1",
        (tool_name, thread_id),
    ).fetchone()
    return dict(row) if row else None


if __name__ == "__main__":
    # Step 2 smoke test — run directly: python src/server/db.py
    build_db(force=False)
    print(f"DB at: {DB_PATH}")

    webex = check_software_subscription("Webex")
    print("Webex subscription:", webex)
    assert webex and webex[0]["seat_limit"] == 40 and webex[0]["active_seats"] == 42
    assert webex[0]["over_limit"] is True

    rachel = get_employee("E010")
    print("E010:", rachel)
    assert rachel and rachel[0]["full_name"] == "Rachel Stein"

    tickets = list_employee_tickets("E010")
    print("E010 tickets:", tickets)
    assert any(t["ticket_id"] == "T001" for t in tickets)

    ar001 = _conn().execute(
        "SELECT request_id, employee_id, status, decision_reason FROM access_requests WHERE request_id = 'AR001'"
    ).fetchone()
    print("AR001:", dict(ar001) if ar001 else None)
    assert ar001 and ar001["employee_id"] == "E010" and ar001["status"] == "blocked"

    print("\n✓ Step 2 done-when criteria all pass.")

    # Step 4 smoke test — the four capabilities no lesson tool covers.
    reports = list_direct_reports("E018")
    print("\nE018 (Yael Romano) direct reports:", [r["full_name"] for r in reports])
    assert {r["employee_id"] for r in reports} >= {"E001", "E003", "E010"}
    assert list_direct_reports("E010") == [], "Rachel Stein manages no one — must be []"

    gap = check_seat_assignment("E010", "Webex")
    print("\ncheck_seat_assignment(E010, Webex):", gap)
    assert gap["seat_assignment_tracked"] is False
    assert gap["entitled_by_role"] is True  # Webex IS in E010's systems_allowed_by_role
    assert gap["subscription"]["active_seats"] == 42  # same over-limit fact as Step 2

    existing = list_access_requests("E010", "Webex")
    print("\nlist_access_requests(E010, Webex):", existing)
    assert any(r["request_id"] == "AR001" for r in existing)

    ticket = create_ticket("E010", "Test ticket", "Smoke test only.", "Access")
    print("\ncreate_ticket result:", ticket)
    assert ticket["ticket_id"] not in {"T001", "T002", "T003", "T004", "T005", "T006"}
    assert ticket["status"] == "open" and ticket["assigned_team"] == "IT"

    print("\n✓ Step 4 db.py additions all pass.")

    # Step 6 smoke test — the write gate's own ledger, reusing `approvals`.
    ar001_chain = list_approvals("AR001")
    print("\nAR001 approval chain:", ar001_chain)
    assert {a["approver_id"] for a in ar001_chain} == {"E006", "E011"}
    assert all(a["status"] == "needed" for a in ar001_chain), "AR001's chain is seeded as 'needed', not yet requested"

    thread, tool = "smoke-thread-1", "create_access_request"
    assert approval_is_recorded(thread, tool) is False, "nothing requested yet — must not be recorded"

    opened = request_write_approval(thread, tool)
    print("\nrequest_write_approval:", opened)
    assert opened["status"] == "pending"
    reopened = request_write_approval(thread, tool)
    assert reopened["approval_id"] == opened["approval_id"], "idempotent — must not open a second pending row"

    pending = get_pending_write_approval(thread, tool)
    assert pending and pending["approval_id"] == opened["approval_id"]

    decided = record_write_decision(thread, tool, approved=True, reason="IT signed off.", decided_by="E006")
    print("\nrecord_write_decision (approved):", decided)
    assert decided["status"] == "approved"
    assert approval_is_recorded(thread, tool) is True
    assert get_pending_write_approval(thread, tool) is None, "no longer pending once decided"

    denied_thread = "smoke-thread-2"
    request_write_approval(denied_thread, tool)
    record_write_decision(denied_thread, tool, approved=False, reason="Not justified.", decided_by="E006")
    assert approval_is_recorded(denied_thread, tool) is False, "a denial is not a recorded approval"
    reopened_after_denial = request_write_approval(denied_thread, tool)
    assert reopened_after_denial["status"] == "pending", "a denial can be reconsidered — a fresh gate opens"

    print("\n✓ Step 6 db.py additions all pass.")
