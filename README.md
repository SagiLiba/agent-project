# NovaOps Final Project

The capstone. You build NovaOps' **operational company brain** — an internal assistant over a
messy, permission-sensitive enterprise world — then instrument it, run a fixed evaluation set
against it, and hand in the traces.

## Clone

This repository *is* the working copy of that template — clone it directly:

```bash
git clone https://github.com/SagiLiba/agent-project.git
cd agent-project
```

(The original course template repo, `Experts-ProciGen-AI/project`, required a
short-lived access-token URL to clone; that token has been removed here since
this repo is the student's own copy and needs no special credential to read.)

## What is here

| File | Read it |
| ---------------------------- | ------------------------------------------------------- |
| **[PROJECT-DESCRIPTION.md](PROJECT-DESCRIPTION.md)** | **Start here.** What to build, the four workflows, the milestones, and how you are assessed |
| **[GOLDEN-DATASETS.json](GOLDEN-DATASETS.json)** | Annotated class material — every expectation readable. Develop and self-check against this |
| **[EVALUATION-INPUTS.yaml](EVALUATION-INPUTS.yaml)** | The measured set: questions only, no answers. Run it once, at the end |
| **[SUBMISSION.md](SUBMISSION.md)** | Copy into your own repository and fill in — repo link, Langfuse project, trace index |
| **[TUTORIAL.md](TUTORIAL.md)** | Setup, the interactive chat CLI, the dataset, running evals, reading Langfuse traces, and where to make a change |
| **[novaops-enterprise-agent-dataset/](novaops-enterprise-agent-dataset/)** | The NovaOps world: the document corpus, the operational database, and per-workflow material |

## The shape of it

Four workflows. **Maya** (HR and onboarding) and **Webex** (IT operations) are two scopes on
one conversational agent and are **required**. **Vendor** (one-shot CRM extraction) and
**Renewal** (an offline, event-driven process) are standalone and **optional** — skipping them
costs no marks.

## Two things to know before you start

**You are assessed by reading, not by running.** Nobody executes your code. Your repository
and your Langfuse traces are the whole submission, so instrument early — Lesson 11's work is
required here precisely because it is the channel through which everything is seen.

**This specification is deliberately incomplete.** It describes the behavior you must produce
and the evidence that proves it. It does not enumerate every artefact you will need to get
there, and at least one capability it requires has nothing behind it in any lesson. That is
not an erratum — noticing what nobody handed you is part of the work.

---

## Implementation map — every claim, its file

Only the two required workflows (Maya, Webex) and the required observability stage (Lesson
11) are built. **Lesson 12 (eval loop engineering) and Lesson 14 (packaging/deployment) were
not attempted** — a deliberate scope decision, not an oversight; Vendor and Renewal
(optional workflows) were likewise not built.

| Claim | File(s) | Notes |
| ----- | ------- | ----- |
| Environment scaffold, deps, `.env` contract | `requirements.txt`, `.env.example` | `pyenv` + `venv`; AWS Bedrock + Langfuse keys only |
| Database layer (file-backed SQLite, seeded) | `src/server/db.py` | 6 read/write functions ported from Lesson 10; `build_db(force=True)` reseeds deterministically for tests/evals |
| Audience-aware RAG (FAISS + Titan embeddings) | `src/server/rag.py` | Documents embedded/retrieved whole, never chunked; permission filter on retrieval, not just on display |
| MCP tool server (14 tools) | `src/server/server.py` | Reads: `list_policies`, `get_policy`, `search_knowledge_base`, `search_hr_documents`, `get_employee`, `check_software_subscription`, `list_onboarding_tasks`, `check_asset_inventory`, `list_employee_tickets`, `list_direct_reports`, `check_seat_assignment`, `list_access_requests`, `list_approvals`. Write: `create_access_request`, `create_ticket` |
| Tools behind a server boundary (not called as functions) | `src/agent/model.py` (`load_tools`, MCP client over streamable HTTP) | Agent never imports `server.py` directly |
| LangGraph agent backbone (plan → select → model → tools → rearm) | `src/agent/graph.py` | Node names double as the Langfuse span names (Step 9) |
| Turn planner, scope/intent classification, loadout selection | `src/agent/policy.py` (`TurnPlan`, `PLANNER_PROMPT`, `select_tools`, `LOADOUTS`) | Pure, I/O-free, unit-testable in isolation from the API |
| Caller identity injected as an application input, never a model claim | `src/agent/graph.py` (`CallerContext`, entry-point injection) | Tool calls carry `caller_employee_id` from state, never from model text |
| Durable checkpointing (pause/resume survives a process restart) | `src/agent/graph.py` (`AsyncSqliteSaver`, `get_checkpointer`) | Proven in `src/agent/webex_replay_test.py`'s "process-restart proof" section — pause on one graph object, resume on a fresh one |
| Write gate: `action_confirmed` gates visibility, a recorded approval gates the write | `src/agent/graph.py` (`approval_gate` node), `src/server/db.py` (`approval_is_recorded`, `record_approval`) | `select_tools` (policy.py) can never itself release a write tool — enforced structurally, not just by prompt |
| Idempotency (replay creates no second record) | `src/server/db.py` (`create_access_request`, `create_ticket`) | Code-level, not just "the model happened to check first" — proven in `webex_replay_test.py` (turn 5 replay, AR001 stays the one row) |
| Maya's typed return contract | `src/agent/schemas.py` (`OnboardingChecklist`, `ChecklistItem`) | Every item cites a real read; `blocked_reason` is the real cause, never a placeholder |
| Webex's typed return contract (never claims access was *granted*) | `src/agent/schemas.py` (`AccessDecision`) | `AccessStatus` has no "approved"/"granted" value at all — a grant is a human decision this schema cannot express |
| Maya → Webex handoff, caller vs. subject kept distinct | `src/agent/schemas.py` (`WebexHandoffIntent`, `WebexHandoff`), `src/agent/policy.py` (`render_plan`) | `subject_employee_id` (who access is *for*) is never defaulted to the caller's id |
| Maya workflow, full 12-turn + 5-turn replay | `src/agent/maya_replay_test.py` | S2 (onboarding) and S9 (own-account) golden sessions, cited, no writes filed |
| Webex workflow: control case, hard "no precise answer" case, seat-blocked refusal, 4-turn adversarial write-gate session | `src/agent/webex_replay_test.py` | Two prompt-injection baits (a forwarded "go ahead," a "copied checklist" naming the write tool) must not fire the gate; turn 4's genuine go-ahead must |
| Langfuse instrumentation bound to the compiled graph | `src/agent/graph.py` (`build_graph`, `CallbackHandler`) | Every caller (both replay tests, the eval harness) exports without remembering to instrument |
| Trace metadata: caller id/group, scope, tool sequence, terminal status, a request id surviving MCP calls and resumes | `evals/run_eval.py` (`trajectory_digest`, `run_one_turn`) | One trace per turn, including a pause+resume — never two |
| Deterministic evaluation checks (own, committed under `evals/`) | `evals/checks.py` | Tool selection/necessity/argument-correctness/sequence, call efficiency, forbidden-tool avoidance, fact recall, intent accuracy |
| Golden expectations for all 27 required traces | `evals/golden.py` | Joins `GOLDEN-DATASETS.json`'s shared sessions with hand-written one-shot expectations; documented, reviewed architectural overrides where this project's design legitimately diverges |
| Running the submission evaluation set once, trace index | `evals/run_eval.py` → `evals/TRACE_INDEX.md` | Copied into `SUBMISSION.md` section 5 |
| Scoring recorded traces against the golden set | `evals/score_eval.py` | Reads Langfuse's v4 `observations` API, writes scores back with `create_score` |
| LLM-as-judge evaluators (faithfulness/completeness/correctness) | `evals/register_judges.py` | Written and ready; **not registered** — needs a Langfuse LLM Connection with the user's own model credentials, a decision left to the user, not made here. Not required by the submission checklist (deterministic checks under `evals/` satisfy that item) |
