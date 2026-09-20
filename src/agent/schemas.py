"""
Typed return contracts — section 6.5's minimum, for the Maya workflow.

PROJECT-DESCRIPTION.md section 6.5: "Each workflow returns a typed object... The
fields below are the minimum the assessment reads; everything else about the
shape is yours." Two objects for Maya:

  - `OnboardingChecklist` — items, each with a status and AT LEAST ONE
    citation; anything blocked carries the reason; an overall status.
  - The Maya -> Webex handoff (`WebexHandoff` here) — the subject employee,
    the system requested, a justification, and the id of the conversation it
    came from, "so the write can be traced back and replayed without
    duplicating."

Neither is produced by rebuilding the graph's conversational loop into a
structured-output-only flow (section 8's hint: "your project delta is the
wider corpus and the twelve-turn replay, not new orchestration"). Instead:

  - `WebexHandoff` is filled in by the SAME planner call that already runs
    every turn (`policy.TurnPlan.webex_handoff`) — no extra model call. Only
    `subject_employee_id` / `subject_name` / `system` / `justification` are
    model-inferred; `source_thread_id` and `requested_by_employee_id` are
    added by `graph.py` from application state afterwards, never inferred
    (section 6.6: "caller identity... [is an] application input, never a
    model inference" — the same rule extended to who is asking for a
    handoff, not just who a tool call claims to be).
  - `OnboardingChecklist` is produced by ONE extra structured-output call,
    made only on a turn whose plan says it is a checklist/status question
    (`current_intent` in {onboarding_status, equipment_request} and
    scope=="maya") — see `graph.extract_checklist`. Every other turn (a
    lookup, a tangent, a recap) pays nothing for this.
"""

from typing import Literal

from pydantic import BaseModel, Field

ChecklistStatus = Literal["complete", "in_progress", "blocked", "not_started"]
ChecklistCategory = Literal["system_access", "equipment", "policy_acknowledgement"]


class ChecklistItem(BaseModel):
    """One line of an onboarding checklist. Never invented — every item traces
    to a real read (an onboarding task, an asset, a subscription, a policy)."""

    name: str = Field(description="What this item is, e.g. 'Webex access' or 'Laptop'.")
    category: ChecklistCategory
    status: ChecklistStatus
    citations: list[str] = Field(
        min_length=1,
        description=(
            "At least one source for this line: a source_path from a retrieval "
            "result, a tool name + record id (e.g. 'onboarding_tasks: OT002'), "
            "or a policy name. Never empty — an uncited item is not on this list."
        ),
    )
    blocked_reason: str | None = Field(
        default=None,
        description="Required when status=='blocked'; the REAL cause (e.g. a seat "
        "limit, a missing approval) — never a placeholder like 'pending review'.",
    )


class OnboardingChecklist(BaseModel):
    """Maya's typed return contract (section 6.5). Assembled from onboarding
    tasks, asset inventory, and subscription seat checks already read this
    session — never from items the model hasn't actually seen evidence for."""

    employee_id: str
    employee_name: str
    items: list[ChecklistItem]
    status: Literal["on_track", "blocked", "incomplete"] = Field(
        description="'blocked' if ANY item is blocked; 'incomplete' if items are "
        "still not_started/in_progress with no blocker; 'on_track' otherwise."
    )


class WebexHandoffIntent(BaseModel):
    """The MODEL-INFERRED half of the Maya -> Webex handoff — what the planner
    fills into `TurnPlan.webex_handoff` this turn, and nothing more. Deliberately
    excludes `source_thread_id`/`requested_by_employee_id`: those are application
    facts (the conversation this came from, who is actually asking), and
    section 6.6 draws the same line for those as it does for a tool's caller
    argument — never let the model assert them."""

    subject_employee_id: str = Field(
        description="Employee id ACCESS IS FOR — the subject of the request, "
        "not necessarily whoever is speaking (Sara asks on Maya's behalf)."
    )
    subject_name: str
    system: str = Field(description="The system/software being requested, e.g. 'Webex'.")
    justification: str = Field(description="Why this access is needed, grounded in the conversation.")


AccessStatus = Literal["blocked", "pending_approval", "no_action_needed", "information_only"]


class AccessDecision(BaseModel):
    """Webex's typed return contract (section 6.5): "separated observed facts,
    actions actually taken, and recommended next steps; the blocking reason
    when there is one; the status. It must never state that access was
    granted." That last rule is why `status` has no 'approved'/'granted'
    value at all — filing or reusing a request only ever reaches
    'pending_approval' or 'blocked' here; an actual grant is a human's
    decision this agent never makes and this schema cannot express.

    Produced the same way `OnboardingChecklist` is (graph.extract_access_decision):
    one extra structured-output call after the graph itself has finished,
    reading the transcript's real tool results — never invented past what
    was actually read or written this turn.
    """

    employee_id: str
    employee_name: str
    system: str
    observed_facts: list[str] = Field(
        min_length=1,
        description="Cited facts this turn actually read: seat counts, an "
        "existing ticket/request id, role entitlement, a policy clause.",
    )
    actions_taken: list[str] = Field(
        default_factory=list,
        description="What a WRITE TOOL actually did this turn, e.g. 'Reused "
        "existing AR001 (blocked) — no new request filed' or 'Filed AR006, "
        "pending_approval'. Empty list if no write tool ran. Never phrased as "
        "'access granted' or 'access enabled' — filing/reusing a request is "
        "not granting it.",
    )
    recommended_next_steps: list[str] = Field(default_factory=list)
    blocked_reason: str | None = Field(
        default=None, description="The REAL cause when status=='blocked' (a seat "
        "limit, a missing named approval) — never a placeholder."
    )
    status: AccessStatus


class WebexHandoff(WebexHandoffIntent):
    """The complete typed handoff (section 6.5's minimum, all four fields):
    subject, system, justification (above, model-inferred) plus the two
    application-supplied facts that make a write traceable and idempotent.
    This is what graph.py's approval_gate surfaces to a human approver —
    never a claim that Maya filed anything; Maya cannot reach this file's
    other object, WRITE_TOOLS, at all."""

    source_thread_id: str = Field(description="This conversation's thread id.")
    requested_by_employee_id: str = Field(description="The CALLER's real employee id (from state, not the model).")
