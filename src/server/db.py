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
lifecycle changed. `list_access_requests` and `list_direct_reports` are this
project's two additions (Step 4 of the build plan) and are documented in
server.py where they are exposed as tools.
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
    """File a new access request for an employee to a system; status pending_approval.

    The one WRITE among these six. It resolves the software name to a system id,
    inserts a row into access_requests, and returns the created record. It does
    NOT decide the request — approval is a separate, human step gated well above
    this function (Step 6's write gate); this function only runs once that gate
    has already opened.
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
    }


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
