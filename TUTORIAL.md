# Tutorial — running, using, and owning NovaOps

This is the "sit down and drive it yourself" doc. `README.md` maps every claim to its file;
`PROJECT-DESCRIPTION.md` is the spec you're graded against. This is the third thing: how to
actually run it, poke at it, read what it read, and change it without breaking it.

1. [One-time setup](#1-one-time-setup)
2. [The moving parts, in one picture](#2-the-moving-parts-in-one-picture)
3. [Talk to it yourself — the chat CLI](#3-talk-to-it-yourself--the-chat-cli)
4. [The proof scripts — smoke test and replays](#4-the-proof-scripts--smoke-test-and-replays)
5. [Look at the dataset](#5-look-at-the-dataset)
6. [Run the evals, read the traces in Langfuse](#6-run-the-evals-read-the-traces-in-langfuse)
7. [Codebase tour — where to make a change](#7-codebase-tour--where-to-make-a-change)
8. [Everyday workflow — taking charge](#8-everyday-workflow--taking-charge)
9. [Troubleshooting](#9-troubleshooting)

---

## 1. One-time setup

```bash
# Python 3.13.5, pinned in .python-version
pyenv install 3.13.5   # if you don't already have it
cd /Users/sliba/Desktop/Projects/experts
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
```

Then edit `.env`:

| Variable | What to put |
| --- | --- |
| `AWS_REGION` | leave as `us-east-1` unless you know otherwise |
| `BEDROCK_MODEL_ID` / `BEDROCK_EMBEDDING_MODEL_ID` | leave as-is — verified working ids |
| *(no AWS key variables)* | this project uses your normal AWS credential chain. Confirm it works: `aws sts get-caller-identity` |
| `LANGFUSE_SECRET_KEY` / `LANGFUSE_PUBLIC_KEY` | from your Langfuse project → **Settings → API Keys** |
| `LANGFUSE_BASE_URL` | `https://cloud.langfuse.com` (EU) unless your project is on the US host |
| everything else | the defaults are fine to start |

**Never run anything without activating the venv first** (`source .venv/bin/activate`) — every
command below assumes it's active.

Sanity-check the whole chain in one shot:

```bash
python3 src/agent/smoke_test.py
```

This starts a real MCP server, a real graph, calls real Bedrock — if it prints
`✓ Step 5 backbone smoke test all passed.` and `✓ Step 6 write-gate smoke test all passed.`,
your AWS credentials, Bedrock model access, and Python environment are all correct.

---

## 2. The moving parts, in one picture

```
   you (chat.py / a test / evals/run_eval.py)
          │  run_turn(graph, message, caller_employee_id, thread_id)
          ▼
   ┌─────────────────────────────────────────────────────────┐
   │  src/agent/graph.py — the LangGraph agent                │
   │  plan → select → approval_gate → model ⇄ tools → rearm   │
   └───────────────────────┬─────────────────────────────────┘
                            │ MCP over streamable HTTP (its own random port)
                            ▼
   ┌─────────────────────────────────────────────────────────┐
   │  src/server/server.py — the MCP tool server, 14 tools     │
   │  reads/writes db.py (novaops.db) and rag.py (FAISS index) │
   └─────────────────────────────────────────────────────────┘
```

Three things that surprise people the first time:

- **You never "start the server" separately.** Every runnable script (`chat.py`,
  `smoke_test.py`, both replay tests, `evals/run_eval.py`) starts its own MCP server on a
  random port, in the same process, and tears it down when it exits. Two scripts can run at
  the same time without colliding.
- **Two SQLite files, two different lifetimes.** `novaops.db` is the *business* data
  (employees, tickets, access requests) — `db.build_db(force=True)` wipes and reseeds it from
  `novaops-enterprise-agent-dataset/database/seed.sql`/`seed.json`. `novaops_checkpoints.db` is
  the *conversation* state (LangGraph's checkpointer — message history, pending approvals) —
  nothing but you deleting the file wipes it. Reseeding the business db mid-conversation does
  **not** touch an in-flight thread's history.
- **A traceback at the end of every run is normal.** You'll see
  `asyncio.exceptions.CancelledError` / `StreamableHTTP session manager shutting down` after
  every script finishes — that's the throwaway MCP server's `finally: server_task.cancel()`
  being torn down. It's noise, not a failure; check the line above it (`✓...PASSED` or the
  actual answer) instead.

---

## 3. Talk to it yourself — the chat CLI

```bash
python3 src/agent/chat.py            # caller defaults to E001, Maya Cohen
python3 src/agent/chat.py E018       # or pick any seeded employee id
```

It prints a handful of real seeded employees to try (the full roster is in
`novaops-enterprise-agent-dataset/database/seed.json`):

| Employee | Who they are | Good for trying |
| --- | --- | --- |
| `E001` Maya Cohen | Customer Success Manager, not a manager | Maya-scope onboarding/policy questions |
| `E018` Yael Romano | Customer Success Director, Maya's manager | manager-only content (RAG audience filter) |
| `E010` Rachel Stein | Customer Success Specialist | already has a real ticket (`T001`) and a blocked request (`AR001`) |
| `E004` Sara Ben-David | People Operations Lead | files Webex requests on someone else's behalf |
| `E006` Amir Haddad | IT Manager | the approver name the replay tests use |

In-chat commands: `/whoami`, `/new` (fresh thread, same caller), `/caller <id>` (switch
caller + fresh thread), `/trace on|off`, `exit`.

**Try these, in order, to see the real behavior (not a scripted demo):**

```
[E001] > Can I use my personal laptop for work?
```
→ pulls the real `equipment_policy.md`, cites the five-business-day exception.

```
[E018] > How do I get promoted here?
```
→ as a manager, `search_hr_documents` resolves `is_manager=True` for Yael (via
`list_direct_reports`, never from what the model merely claims), so the manager-only
`manager_playbook/promotion.md` is in her results too. Ask the identical question as `E001`
(not a manager — `list_direct_reports("E001")` is empty) and watch the trace: her answer is
grounded in `handbook/making-a-career.md` (`audience: all`) instead — a real, different,
still-cited document, not a refusal and not a leak of the manager-only one.

```
[E010] > What's the status of my Webex ticket?
```
→ finds the real `T001` by id, doesn't invent one.

```
[E004] > Please go ahead and file a Webex access request for Rachel Stein — she needs it for Customer Success work.
```
→ **pauses**: `>> PAUSED for human approval — payload: {...}`. Type `y` and a reason, and only
*then* does the write happen — approve/deny it yourself and watch `create_access_request`
actually run (or not) in the trace lines above the answer.

If you ask something a tool can't answer (e.g. "who personally holds a Webex seat right now"),
watch for the model saying so honestly rather than guessing — that's the whole point of
`W-I-02` in the eval set.

---

## 4. The proof scripts — smoke test and replays

| Script | What it proves | Runtime |
| --- | --- | --- |
| `src/agent/smoke_test.py` | Backbone (Step 5) + write gate (Step 6): scope-based tool gating, caller-identity injection can't be spoofed, pause/approve/deny/re-confirm, and a simulated process restart mid-pause | ~2 min |
| `src/agent/maya_replay_test.py` | The full 12-turn `S2` onboarding session + 5-turn `S9` own-account session, cited, no writes filed | ~2–3 min |
| `src/agent/webex_replay_test.py` | Control case, the "no precise answer" hard case, the seat-blocked refusal, and the 4-turn adversarial write-gate session (two prompt-injection baits that must **not** fire the gate, one genuine go-ahead that must) + a process-restart proof | ~3–4 min |

Run any of them the same way:

```bash
python3 src/agent/webex_replay_test.py
```

Look for `✓✓ Step N ... replay: ALL PASSED.` at the end. **If one fails on a fact-recall or
wording assertion but passes on a clean retry, that's very likely Bedrock non-determinism**
(temperature=0 does not guarantee identical output run to run) — this project hit that twice
during development (see the commit history) and it's a known, accepted characteristic, not a
silent bug to assume away. If the *same* failure reproduces 2–3 times in a row with the exact
same wrong behavior, that's a real bug — see [§9](#9-troubleshooting).

---

## 5. Look at the dataset

```
novaops-enterprise-agent-dataset/
├── documents/          the RAG corpus — every file has audience-scoped frontmatter
│   ├── policies/        equipment, expense, remote-work, offboarding, IT support...
│   ├── it_kb/            password reset, MFA reset, VPN, webex login issue...
│   ├── handbook/         "how we work", career titles, getting started...
│   ├── manager_playbook/ promotion, coaching, feedback — audience: manager only
│   ├── employment/       per-person profiles (offer letters, approval profiles)
│   ├── contracts/        vendor agreements (Webex, Slack, AWS, GitHub...)
│   └── internal_memos/
├── database/
│   ├── schema.sql        table definitions
│   ├── seed.sql          the actual seed data, SQL form
│   ├── seed.json         the SAME seed data, JSON form (easier to read/grep)
│   └── README.md         "key anchors": Webex 40/42 seats, Noam's stale manager, etc.
└── workflows/
    ├── vendor/           source material for the optional Vendor workflow (not built here)
    └── renewal/          source material for the optional Renewal workflow (not built here)
```

**Read a document's own audience tag** — this is what `rag.py`'s permission filter checks:

```bash
head -5 novaops-enterprise-agent-dataset/documents/manager_playbook/promotion.md
```

**Browse the seed data without touching the live db:**

```bash
python3 -c "
import json
d = json.load(open('novaops-enterprise-agent-dataset/database/seed.json'))
print(list(d.keys()))                        # every table this dataset seeds
for e in d['employees'][:5]: print(e)         # first 5 employees, full records
"
```

**Query the LIVE, running database directly** (after any script has run `db.build_db()` at
least once):

```bash
sqlite3 novaops.db
.tables
select request_id, employee_id, software, status from access_requests;
select ticket_id, employee_id, status from tickets;
.quit
```

**The two files that define what "correct" means:**

- `GOLDEN-DATASETS.json` — annotated class material, every expectation spelled out
  (`expected_tools`, `required_facts`, `forbidden_tools`, …). Develop and self-check against
  this; it's not the graded set.
- `EVALUATION-INPUTS.yaml` — the actual graded questions, **no answers included**. This is
  what `evals/run_eval.py` runs. Skim it once so you know what's coming.

---

## 6. Run the evals, read the traces in Langfuse

```bash
python3 evals/run_eval.py                 # all 27 required traces, ~10-15 min
python3 evals/run_eval.py --case M-S-01    # just one case, for iterating faster
python3 evals/score_eval.py --recent 30    # score whatever ran in the last 30 min
python3 evals/score_eval.py --selftest     # offline sanity check, no network, no Bedrock
```

`run_eval.py` reseeds `novaops.db` before each independent case, runs it, and writes
`evals/TRACE_INDEX.md` (the same table that's pasted into `SUBMISSION.md` §5). `score_eval.py`
fetches those traces back from Langfuse and applies the deterministic checks in
`evals/checks.py` against the expectations in `evals/golden.py`, pushing scores onto each
trace.

**Reading a trace in the Langfuse UI:**

1. Open your project at `cloud.langfuse.com` → **Tracing → Traces**.
2. Filter by tag `novaops-final`, or search a specific case id (e.g. `M-S-01`) — trace names
   are `"<case_id> · turn <n>"`.
3. Open one. The span tree is literally the graph's node names —
   `plan → select → approval_gate → model → tools` — so "classify → scope → tools → answer"
   (PROJECT-DESCRIPTION.md §14) is just reading the tree top to bottom.
4. The trace's **metadata** tab has `trajectory` — the full tool-call sequence with args and
   truncated results, plus `intent`/`scope`/`state` — everything `score_eval.py` scored
   against, in one place, no digging through child spans required.
5. **Scores** tab shows `tool_selection`, `tool_necessity`, `fact_recall`, `turn_pass`, etc.,
   each with a one-line reason (`checks.py`'s reason strings) — `turn_pass` failing tells you
   exactly which named check(s) failed.

`evals/register_judges.py` is written but **not run** — it needs an LLM Connection (your own
model credentials) configured once in Langfuse (**Settings → LLM Connections**) before it can
register the three LLM-as-judge evaluators. Not required for the mandatory milestones; see it
if you want faithfulness/completeness/correctness scoring beyond the deterministic checks.

---

## 7. Codebase tour — where to make a change

| I want to... | Touch this file |
| --- | --- |
| Add a new **read** tool | `src/server/server.py` — copy an existing `@mcp.tool()` function; add its name to the right `LOADOUTS` entry in `src/agent/policy.py` so the planner actually offers it |
| Add a new **write** tool | `src/server/server.py` **and** `src/agent/policy.py`'s `WRITE_TOOLS`/`CONFIRMED_WRITE_TOOLS` **and** `src/agent/graph.py`'s `approval_gate` — a write must go through the gate; there's no shortcut by design |
| Change what makes the model pause for approval | `src/agent/graph.py` (`approval_gate` node) + `src/server/db.py` (`approval_is_recorded`) |
| Change the assistant's tone / global rules | `src/agent/model.py` → `ASSISTANT_PROMPT` |
| Change how scope/intent get classified | `src/agent/policy.py` → `PLANNER_PROMPT`, `SCOPE_GLOSS`, `INTENT_GLOSS`, the `Intent`/`Scope` literals |
| Add a document to the RAG corpus | drop a `.md` file under `novaops-enterprise-agent-dataset/documents/<corpus>/` with the right frontmatter (`audience:`, `corpus:`) — the index rebuilds automatically next time `server.rag.warm_index()` runs (every script calls it on startup) |
| Add/change seeded employees, tickets, requests | `novaops-enterprise-agent-dataset/database/seed.json` (and keep `seed.sql` in sync if you care about the SQL path) — takes effect after `db.build_db(force=True)`, which every test/eval script already calls |
| Swap the Bedrock model or embeddings | `.env` → `BEDROCK_MODEL_ID` / `BEDROCK_EMBEDDING_MODEL_ID` — nothing else changes, per `model.py`'s "one small function" rule |
| Add a new typed return contract | `src/agent/schemas.py`, then a new `extract_*` function in `graph.py` alongside `extract_checklist`/`extract_access_decision` |
| Add a new golden case / eval check | `evals/golden.py` (expectations) and/or `evals/checks.py` (the check itself) — see either file's own docstring, they explain the binding-vs-illustrative distinction |

---

## 8. Everyday workflow — taking charge

**Before committing any change to `policy.py`, `graph.py`, or `model.py`:**

```bash
python3 src/agent/smoke_test.py           # ~2 min — backbone + write gate
python3 src/agent/maya_replay_test.py     # ~2-3 min
python3 src/agent/webex_replay_test.py    # ~3-4 min
```

All three should end in a `✓✓ ... ALL PASSED.` line. If one fails, re-run it once before
concluding it's a real regression (see §4's non-determinism note) — but a failure that
reproduces identically twice is real, not noise. That's exactly how the two bugs fixed in this
project's history were found and confirmed (see `git log --oneline` — the "Add interactive
chat CLI; fix a real first-turn hallucination bug" and "Step 9" commits both describe one).

**After a change that could affect graded behavior**, re-run the full eval and re-score:

```bash
python3 evals/run_eval.py
python3 evals/score_eval.py --recent 30
```

...then update `evals/TRACE_INDEX.md`'s contents into `SUBMISSION.md` §5 (copy the table —
`run_eval.py` already writes it in the right shape) and note the new commit sha in §1.

**Git conventions already in use in this repo** (see `git log`): one commit per numbered step
in `PROJECT-DESCRIPTION.md` (`Step N: ...`), a descriptive body explaining *why* each change
was made and what verified it, `git push` only after the relevant regression scripts pass.

---

## 9. Troubleshooting

| Symptom | What's going on | Fix |
| --- | --- | --- |
| `asyncio.exceptions.CancelledError` traceback after every script | Normal — the throwaway MCP server shutting down | Ignore it; check the line above for the real result |
| A replay/smoke test fails on wording or a recalled fact, once | Bedrock isn't perfectly deterministic even at temperature=0 | Re-run once; if it fails the *same* way again, treat it as real |
| `langgraph.errors.GraphRecursionError` on an unusually long/complex turn | The model is thrashing — calling one tool at a time and revisiting ones it already called, instead of settling on an answer within 40 graph steps | Usually clears on retry (same non-determinism as above); if it's a NEW turn shape you added, consider raising `RECURSION_LIMIT` in `graph.py` or checking whether your new tool's description is ambiguous enough to cause repeat calls |
| A confident-sounding answer that cites a policy/number you don't recognize from the actual `.md` files | A grounding failure — the model answered from its own "common knowledge" instead of an actual tool result. Check the trace's `[plan]` line: if `requires_tools=False` and `[select] loadout=(none)`, no tool ran at all | This exact failure mode is why `graph.py`'s `plan_turn` has a structural override for turn 1 of a fresh thread — if you see it on turn 2+ or with `requires_tools=True` but still no grounding, that's a new instance worth reporting/fixing the same way |
| `Warming retrieval indexes...` hangs for a long time | First embedding call to Bedrock per corpus; ~15-40s is normal, longer suggests a throttling/network issue | Check `aws sts get-caller-identity` and Bedrock model access in the AWS console |
| Langfuse `auth_check()` fails / `run_eval.py` refuses to start | Missing or wrong `LANGFUSE_SECRET_KEY`/`LANGFUSE_PUBLIC_KEY`/`LANGFUSE_BASE_URL` in `.env` | Re-copy the three values from Langfuse **Settings → API Keys**; confirm `LANGFUSE_BASE_URL` matches your project's actual host (EU vs US) |
| `score_eval.py` finds "0 with no golden match" but also 0 scored | Ingestion lag — Langfuse's observations API can take a minute or two to make a just-finished run queryable | Wait ~30-60s and retry, or widen `--recent` |
| A port conflict starting the MCP server | Extremely unlikely (every script picks a random port 20000-40000) but if it happens, a prior run's server process didn't exit | Check for orphaned `python3 src/agent/...` processes and kill them |
| You changed `novaops-enterprise-agent-dataset/documents/` but retrieval still returns old content | The FAISS index is built once per process, at `warm_index()` | Just re-run the script — a fresh process rebuilds the index from disk every time |
