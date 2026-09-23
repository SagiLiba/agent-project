# Agent Low-Level Design — Template

*A starting point for designing an LLM agent, distilled from the AI Engineer course
(14 lessons — prompting through cloud serving) and from actually building NovaOps
(this repo) against it. Copy this file, fill in every section, delete the guidance
blocks (or leave them — see note below), and you have an LLD you can review.*

**How to use this:**
1. Copy this file to `<your-project>/LLD.md`.
2. Each section has a guidance block between `--- SECTION EXPLAINED START/END ---`
   markers, explaining what the section is for and which lesson/decision it maps
   to. Read it, then fill in the **Fill in:** block below it. You can delete the
   guidance blocks once filled in, or leave them — the `parse-design-document`
   skill already knows to strip anything between those exact markers, so a
   design-review pipeline can read this template the same way it reads any other
   LLD.
3. Not every section applies to every agent (a pure-tool agent may have no RAG
   section; a single-user CLI tool may have no serving/scaling section). Write
   `N/A — <why>` rather than deleting the section — an explicit "not needed and
   here's why" is a design decision; a missing section is just a gap.
4. Sections are ordered so that reading top to bottom tells the story: what it's
   for → what it can do → how it's wired → how it's kept honest → how it's proven
   → how it's run. That's also roughly the order the course teaches it in.

---

## 0. Document Control

--- SECTION EXPLAINED START ---
Standard front matter — who owns this, what it's called, what it links to. Cheap
to fill in, easy to skip, and the first thing a reviewer or a future you needs.
Two agent-specific additions vs. a normal service LLD: a link to the **golden
dataset / eval set** (§12) and to the **observability project** (§11, e.g. a
Langfuse project URL) — for an agent, "does it work" is answered by those two
artifacts, not by reading the code.
--- SECTION EXPLAINED END ---

**Fill in:**

| Field | Value |
| --- | --- |
| Agent name | |
| Owner(s) | |
| Status | draft / in review / approved / shipped |
| One-line summary | *what does it do, for whom* |
| Related docs | HLD, product spec, Jira epic |
| Golden dataset / eval set | *link or path* |
| Observability project | *e.g. Langfuse project URL* |
| Security review | *link, date, reviewer — or "not yet scheduled"* |

| Term | Meaning |
| --- | --- |
| *(add any domain-specific or agent-specific terms your reviewers won't already know)* | |

---

## 1. Problem, Scope & Why an Agent

--- SECTION EXPLAINED START ---
Before any architecture: does this need to be an **agent** at all? Lesson 9's test
is the sharpest tool here — *"does this abstraction save keystrokes, or does it
give me a runtime capability I'd otherwise have to build?"* A fixed pipeline
(a chain, a script, a form) is predictable, cheap, and easy to test; reach for a
model-driven loop only when the steps genuinely vary per request in a way you
can't enumerate up front. Write the use cases as scenarios a human would actually
say, not features — that's what keeps the tool list and the eval set honest later.
Non-functional requirements for an agent are different from a normal service's:
latency and cost are **per model call**, not per request, so a bad tool loadout or
an unbounded history multiplies them silently.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Problem statement**: *what breaks or is slow/expensive today without this?*
- **Why an agent, not a script/workflow**: *which steps genuinely vary per
  request? What would a fixed pipeline get wrong?*
- **Primary use cases** (one line each, as a scenario): *"An employee asks X and
  the agent should Y."*
- **Explicit non-goals**: *what this agent will NOT do, even if related — say so
  now, not when someone asks why it can't*
- **Non-functional requirements**:

| Requirement | Target |
| --- | --- |
| Latency per turn | |
| Cost per conversation (token budget) | |
| Groundedness (must cite/never invent) | usually: always |
| Availability of the model/provider | |
| Max conversation length supported | |

---

## 2. Callers, Identity & Scope

--- SECTION EXPLAINED START ---
The single most important security line in the whole design, and the easiest to
get wrong: **the model can claim to be anyone.** If a tool takes "who is this
for," that value must come from the application's own authenticated context
(a session, a token, an API caller id) and be substituted into the tool call in
code — never trusted from what the model wrote, even if the model only ever
proposes the correct value in testing. Lesson 8/9's NovaOps tools accept a
caller-id argument for exactly this reason: it exists so the code has somewhere
to put the *real* value, overwriting whatever the model proposed. If your agent
serves more than one kind of user (roles, tenants, permission tiers), that
becomes a **scope** — a first-class field the rest of the design routes on
(which tools are visible, which documents are retrievable), not something the
prompt "tries to remember."
--- SECTION EXPLAINED END ---

**Fill in:**
- **Who calls this agent** (people, services, both?):
- **How is caller identity established** (session, JWT, header, CLI arg)?
- **Where in the code is the model-proposed identity overridden with the real
  one?** *(name the function/module — this must be a real answer, not "the
  prompt tells it not to lie")*
- **Scopes/roles**, if more than one caller type exists:

| Scope/Role | Who | What's different for them (tools, corpora, tone) |
| --- | --- | --- |
| | | |

---

## 3. Capability Map — Tools & Data Sources

--- SECTION EXPLAINED START ---
Every tool is a contract: a name, a schema (the model's only view of what it
does), a backing system, and a read/write classification. Get the read/write
split explicit early — it drives §8 entirely. Decide **in-process function
tools vs. an MCP server** (Lesson 8) by whether the tools need to be reused by a
*different* client (another agent, Claude Desktop, Cursor) or run on a different
machine from the agent loop; if it's one agent, one process, one deployable,
plain function tools are less machinery for the same result. A tool's docstring
*is* its schema to the model — write it like API documentation, not a code
comment, because a vague one is the #1 cause of the model calling the wrong tool
or not calling one it should have.
--- SECTION EXPLAINED END ---

**Fill in:**
- **In-process tools or MCP server?** *(and why)*

| Tool | Read/Write | Backing system | Args | Visible in which scope/loadout | Notes |
| --- | --- | --- | --- | --- | --- |
| | | | | | |

- **Read/write separation rule**: *state in one sentence how a write tool is
  distinguished from a read tool in this codebase (a naming convention, a set/
  list literal, a decorator) — §8 depends on this being unambiguous in code, not
  just in this table.*

---

## 4. Retrieval / RAG Design

--- SECTION EXPLAINED START ---
Mark this section `N/A` if the agent has no unstructured-document corpus. If it
does, the decisions in order of how much they cost to get wrong:

1. **Pipeline RAG vs. agentic (tool-based) RAG** (Lesson 6): does every turn
   retrieve, or does the model decide *when* to search? Pipeline RAG stuffs
   irrelevant chunks into "hello"; tool-based RAG costs one extra decision but
   only pays for retrieval when it's needed.
2. **Vector store: exact/local (FAISS) vs. managed/approximate (OpenSearch or
   equivalent, HNSW)** (Lesson 7): FAISS-on-disk is free and fine up to a small,
   single-process corpus; a managed store earns its keep at real scale, when
   multiple processes need the same index, or when you need one index across
   multiple audiences instead of one index per audience (see next point).
3. **Access control is a hard filter, never a soft one.** If some documents are
   restricted by role/tenant, that filter is resolved from the caller's real
   permissions (§2) and applied *before* the model ever sees candidate chunks —
   it is a security boundary, not a relevance signal, and it must **fail
   closed** (when in doubt, exclude). Contrast with a *topical* filter (e.g.
   "only chunks about expenses") planned from the question itself — that one
   should **fail open** (when unsure, search wider) because getting it wrong
   only costs relevance, not a leak.
4. **Reranking and query planning** (Lesson 7) are quality levers, not
   correctness requirements — add them once you've measured (§12) that plain
   top-k similarity is missing or misranking the right chunk.
--- SECTION EXPLAINED END ---

**Fill in:** *(or write "N/A — no unstructured corpus")*

| Corpus | Audience(s) | Source of truth | Update frequency |
| --- | --- | --- | --- |
| | | | |

- **Pipeline vs. agentic RAG**: *and why*
- **Vector store**: *FAISS / OpenSearch / other, and why at this scale*
- **Chunking strategy**: *size, overlap, splitting rule*
- **Embedding model**: *and why (must match at index-time and query-time)*
- **Access-control filter** (hard, fails closed): *what field, resolved how*
- **Topical/relevance filter** (soft, fails open), if any: *what field, planned
  by what*
- **Recency filter**, if any:
- **Reranking**: *yes/no, and why*

---

## 5. Orchestration Architecture

--- SECTION EXPLAINED START ---
Lesson 9's capability ladder, cheapest to most powerful — **pick the cheapest
rung that satisfies §1's requirements, not the most impressive one:**

| Rung | Who chooses the steps | Reach for it when |
| --- | --- | --- |
| Fixed chain/pipeline | you, at design time | the steps never vary by request |
| Single agent loop (model + tools) | the model, per request | steps vary, but one focused agent can do it all |
| Graph + human-in-the-loop gate | model, with a pause point | any step can mutate real state and needs approval |
| Multi-agent supervisor | model, dispatching sub-agents | subtasks are genuinely independent AND each needs a different focused prompt/toolset — this is the expensive rung; most tasks that look "multi-agent" are actually one agent with a bigger tool list |

Whatever rung you land on, keep the model call behind **one small function**
(Lesson 9/10's `get_model()` pattern) so a provider or model swap touches one
place, and draw the actual graph — nodes and edges — before writing code; the
diagram *is* the design here, more than any prose.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Rung chosen**: *and why the rung below it wasn't enough / the rung above it
  wasn't worth it*
- **Graph diagram** (nodes and edges — mermaid, ASCII, or an image):

```
(draw it here)
```

- **State schema** (the fields carried between nodes):

| Field | Type | Set by | Read by |
| --- | --- | --- | --- |
| | | | |

- **Model-call seam**: *name the one function every node calls to get a model*

---

## 6. Context Engineering — What Goes Into Each Call

--- SECTION EXPLAINED START ---
The model is stateless; every call rebuilds its whole world, and more context is
not automatically better — irrelevant, stale, or duplicated context measurably
*reduces* answer quality (Lesson 10). Pull apart the seven things that all get
called "context" so each one gets its own decision instead of "send everything":
**graph state** (everything the app knows), **model context** (what's actually
sent this call), **conversation history** (grows without bound by default),
**retrieved context** (§4's chunks — stale the moment the source changes),
**tool results** (load-bearing this turn, noise after), **runtime config** (who's
asking, their scope, the thread id — small, easy to forget), and **persisted
thread state** (the checkpoint — durable, not the same thing as what gets sent).
Two concrete techniques worth defaulting to: (1) a small **structured plan**
per turn (intent, scope, whether a tool is even needed) that routes everything
downstream, cheaper and more reliable than re-deriving intent ad hoc in the
system prompt; (2) a **dynamic tool loadout** — only the tools this turn's plan
says are relevant, because tool schemas are billed context too (ten schemas is a
real per-call cost). For long conversations, decide a **history distillation**
policy up front (summarize/structure old turns past some threshold) — and treat
persisting, sending, and cleaning up old history as three separate decisions,
not one.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Per-turn plan**: *what fields does it have (intent, scope, requires_tools,
  ...), and what model call produces it?*
- **Tool loadout policy**: *fixed for all turns, or dynamic per intent/scope?
  If dynamic, is the mapping deterministic code or another model call?*
- **History policy**: *send everything verbatim / distill after N turns / other
  — state the threshold*
- **System prompt location**: *file/function — keep this to one place per
  "role" the model plays*
- **What's explicitly excluded from model context and why** (e.g. raw tool
  JSON beyond what's needed, other users' data, secrets):

---

## 7. Structured Output Contracts

--- SECTION EXPLAINED START ---
Anywhere the agent's output needs to be *used* by code (not just read by a
human) — a status enum, a list of actions taken, a decision object — force it
through a typed schema (Pydantic/JSON-schema) rather than parsing free text.
Use a **forced** tool/structured-output call when the shape must be produced no
matter what (Lesson 3/4's `toolChoice: tool`); use the model's own judgment
(`auto`) when it's actually optional whether the model calls anything at all.
List every contract here so a reviewer can see, at a glance, everywhere this
agent's output becomes a program's input.
--- SECTION EXPLAINED END ---

**Fill in:**

| Contract (schema name) | Produced when | Forced or auto? | Consumed by |
| --- | --- | --- | --- |
| | | | |

---

## 8. Write Actions, Approval Gates & Idempotency

--- SECTION EXPLAINED START ---
A write tool changes real state, so "the model decided to call it" is never
sufficient authorization on its own for anything consequential. The pattern
(Lesson 9's human-in-the-loop, hardened further in this course's final project):
a write tool **proposes**, a graph node gates it behind human approval via an
`interrupt()`/pause mechanism, and only an explicit approve resumes the graph
into actually calling it. This *requires* a **durable checkpointer** — the pause
must survive a process restart between the interrupt and the human's decision,
or the approval gate is decorative. Two more properties worth designing in
deliberately: **idempotency** (replaying the same request twice — a retried
webhook, a user re-confirming — must not create two records; check-then-reuse in
the write tool itself, not by hoping the model doesn't ask twice) and a
**re-confirmation short-circuit** (once a (thread, tool) pair is already
approved, re-asking the same thing must not re-trigger a second pause).
--- SECTION EXPLAINED END ---

**Fill in:**
- **Write tools and what each one does**:

| Write tool | Approval required? | Idempotency key | Reuse behavior on replay |
| --- | --- | --- | --- |
| | | | |

- **Checkpointer**: *technology, what durability guarantee it gives, tested how
  (does a test actually kill the process mid-pause and resume from a fresh
  connection?)*
- **Re-confirmation short-circuit**: *how is "already approved" detected before
  a second interrupt fires?*

---

## 9. Security & Guardrails

--- SECTION EXPLAINED START ---
There are (at least) four different things people mean by "guardrail," and they
stop different attacks — decide which layer stops which, don't rely on one:

| Layer | Stops | Fails how when wrong |
| --- | --- | --- |
| Planner/prompt hardening | the model narrating a bad decision into existing | still lets a determined attacker through — a classifier can be mistaken |
| A dedicated guardrail node/classifier | inputs classified as malicious before they reach tool selection | same — a classifier judges text and can be wrong |
| Tool-level permission + confirmation checks (§8) | a write actually executing without real authorization | this is the one that must never fail open |
| RAG access filter (§4) | a caller reading documents outside their audience | must fail closed |

Name your specific threat model, don't just say "prompt injection": private
approval claims ("my manager already approved this"), role/identity spoofing
(claiming to be someone else — see §2), instructions pasted inside forwarded
email/ticket content (content the user is *quoting*, not asserting), and — if
you have RAG — a poisoned document reaching an answer. For RAG poisoning
specifically, note that filtering the input and deleting the bad document are
not the same as fixing an *already-poisoned conversation* — a checkpoint made
before the deletion still has the bad content in its history; recovering fully
means checking whether affected threads need to be reset, not just fixing the
corpus.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Threat model** (list the specific attacks this agent is exposed to, not a
  generic list):
- **Control-to-threat mapping**:

| Threat | Which layer stops it | Verified how (a test, a red-team case) |
| --- | --- | --- |
| | | |

- **RAG poisoning recovery plan**, if applicable: *filter → quarantine → delete
  → what happens to conversations that already read the bad chunk?*

---

## 10. Persistence & State

--- SECTION EXPLAINED START ---
Separate **conversation/checkpoint state** (durable, replayable, what makes §8's
pause/resume and a process restart survivable) from **business data** (what the
tools actually read/write) from **ephemeral working state** (this call's tool
results, gone after the turn). They usually live in different stores with
different lifecycles, and conflating them is how "reseed the test database"
accidentally wipes someone's in-progress approval. If you'll ever run more than
one worker process (§14), the checkpointer must be a **shared** store (e.g.
Postgres, not a local SQLite file) — a conversation pinned to one worker's local
disk is a correctness bug the moment a second worker exists, and it fails
silently: nothing errors, the agent just "forgets."
--- SECTION EXPLAINED END ---

**Fill in:**
- **Checkpointer / conversation state**: *store, shared across workers? (yes/no
  — if this agent will ever scale past one process, this must be yes)*
- **Business data store**: *store, schema sketch or link*
- **Ephemeral state**: *what's per-call only, never persisted*

---

## 11. Observability

--- SECTION EXPLAINED START ---
Observability answers "what did it do"; it is not the same question as
evaluation ("was that right" — §12), and conflating them is the single most
common mistake here. Instrument with the framework's tracing integration
(often ~3 lines — e.g. a callback bound to the compiled graph); the free part is
automatic, and what it does *not* give you for free is identity — who is asking,
which conversation this is, a stable request id across resumed/paused
turns — that has to be attached explicitly by whoever starts the run, because
the agent itself often can't know it. Name spans after your graph's own node
names (§5) so the trace tree IS the architecture diagram, not a second thing to
maintain. Decide up front what metadata every trace must carry — at minimum
enough to join a trace back to a specific eval case and a specific caller.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Tracing tool**: *and the one integration point (file/line) where it's bound*
- **Span naming**: *confirm spans are named after graph nodes*
- **Required metadata per trace**:

| Field | Purpose |
| --- | --- |
| session/thread id | |
| caller/user id | |
| case id (for eval joins) | |
| tool-call trajectory | |
| terminal status | |

- **What a trace must show to debug a bad answer** (the checklist you'd actually
  use):

---

## 12. Evaluation Strategy

--- SECTION EXPLAINED START ---
A trace can show a perfect record of the agent confidently doing the wrong
thing — nothing in the tracing tool knows what turn 1 was *supposed* to do; that
standard lives in a golden dataset you write and keep in version control.
Two kinds of evaluation exist because they can see different things — decide
which applies to which check, don't default to one:

| | Deterministic checks | LLM-as-judge |
| --- | --- | --- |
| Runs on | your machine/CI, after the run | the eval platform's servers, continuously |
| Sees | the whole trace | usually one observation/turn |
| Decides with | code (exact match, set membership) | a model's judgment |
| Cost | free, identical every time | a model call, may vary run to run |
| Good for | tool-called, arguments-correct, forbidden-tool-not-called, fact-present | faithfulness, completeness, tone, "was this actually helpful" |

Build the golden set as **expected outcomes per turn** (expected tools, required
facts, forbidden tools/actions), not "the exact expected sentence" — that's
too brittle for anything except unit-test-style cases. Decide a **gate**: what
score/rate has to hold before shipping a change, and who owns lowering it if a
new case is added that legitimately can't pass yet.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Golden dataset**: *location, how many cases/turns, what each case specifies
  (expected tools, required facts, forbidden actions, ...)*
- **Deterministic checks**: *list them*
- **LLM-judge checks**, if any: *list them, and confirm they're only used where
  a compact per-turn view is sufficient evidence*
- **Gate**: *the number that has to hold, and what happens when a run misses it*
- **Coverage**: *does the eval set include multi-turn sessions, adversarial/
  red-team cases, and "should refuse / doesn't know" cases — not just the happy
  path?*

---

## 13. Reliability & Failure Handling

--- SECTION EXPLAINED START ---
The most dangerous failure mode in an agent is the **silent** one: a structured-
output parse failure that quietly falls back to a "valid-looking" default plan,
or a history-distillation step that fails and just stops updating — neither
raises, neither logs, and the trace of that run looks perfectly healthy (this
is a real, documented failure mode from this course's own reference agent).
Grep your own code for `except` and ask, for each one, "if this fires, does
anything downstream notice?" Beyond that: bound every retry (a turn cap, same as
the tool-use loop itself needs one — an agent loop with no cap doesn't fail, it
runs forever), decide what happens on a tool timeout or malformed structured
output (a single repair attempt is usually right; silently guessing is not),
and decide the user-facing behavior when the model provider itself is degraded
or unavailable.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Turn/step caps**: *the agent loop's own recursion or turn limit*
- **Structured-output failure handling**: *repair attempt? fallback? does it
  raise/log, or silently substitute a default?*
- **Tool-call failure handling**: *retry policy, what the model is told*
- **Provider outage/throttling behavior**:
- **Audit**: *list every `except`/silent-fallback in the codebase and confirm
  each one is either loud (logged/raised) or explicitly justified as safe to be
  quiet*

---

## 14. Serving & Deployment

--- SECTION EXPLAINED START ---
Once "somebody else" runs this, several things need an explicit answer that a
terminal session gave you for free. **Interface**: how is it called (HTTP API,
CLI, both) — validate and reject bad requests before they ever reach the agent
(a 422 that never spends a model call is cheap; one that does is not).
**Credentials**: consider putting model access behind a gateway (e.g. LiteLLM)
so the agent process itself never holds real provider keys — only the gateway
does, which makes key rotation and per-caller budgets a gateway concern instead
of an every-service concern. **Concurrency**: an in-process semaphore is an
honest limit for one process and a fiction the moment you run two — real
backpressure needs to live where all instances can see it (a queue, a shared
counter). **Health checks**: a readiness probe that reports healthy once and
never rechecks its dependencies (e.g. the tool server) is worse than no probe —
it tells the platform to keep sending traffic somewhere that can't serve it.
**Scaling**: if a conversation can be served by a different worker turn to turn,
the checkpointer (§10) must already be shared, or scaling silently breaks
conversation continuity.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Interface**: *HTTP / CLI / both — and where request validation happens*
- **Model access path**: *direct to provider, or behind a gateway — and why*
- **Containerization**: *base image, non-root, health/readiness routes*
- **Concurrency limit**: *where it's enforced, and whether it holds across
  multiple instances*
- **Autoscaling / worker model**: *and confirm §10's checkpointer choice
  matches (shared store if >1 worker)*

---

## 15. Cost & Model Choice

--- SECTION EXPLAINED START ---
State the model(s) chosen and why — not just "the best one," but the actual
trade-off against latency, cost, and what this specific task needs (a planner
call that just classifies intent rarely needs the most expensive model
available; a final user-facing answer might). Keep the "one small function"
seam from §5 explicit here too: this section should be answerable by changing
one line, not by grepping the codebase for every place a model name is
hardcoded.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Primary model**: *and why (cost/latency/quality trade-off for this task)*
- **Embedding model**, if applicable:
- **Estimated cost per conversation**:
- **Provider-swap seam**: *confirm changing the model is a config/one-function
  change, not a multi-file change*

---

## 16. Risks, Assumptions & Limitations

--- SECTION EXPLAINED START ---
Say the quiet parts out loud. An assumption nobody wrote down becomes a bug
report; a known limitation written down here becomes an FAQ answer instead of
an escalation. Score risks so "everything is a risk" doesn't collapse into
"nothing gets prioritized."
--- SECTION EXPLAINED END ---

**Fill in:**

| Risk | Probability (1-5) | Impact (1-5) | Mitigation |
| --- | --- | --- | --- |
| | | | |

- **Assumptions**: *what has to be true for this design to work*
- **Known limitations**: *what this agent will confidently NOT handle well*

---

## 17. Test Plan & Rollout

--- SECTION EXPLAINED START ---
Distinguish tests that prove the *machinery* works (a smoke test: can it start,
connect, complete one round trip end to end) from tests that prove *specific
behavior* is correct (replay/regression sessions matching real use cases) from
the eval suite (§12, quality at scale). All three matter and catch different
regressions. Because LLM calls are not perfectly deterministic even at low
temperature, a one-off flaky assertion is not automatically a real bug — but the
same failure reproducing identically is. Say what that means for CI (a retry
policy? a tolerance?) instead of leaving it as an unwritten team norm.
--- SECTION EXPLAINED END ---

**Fill in:**
- **Smoke test**: *what it proves, how long it takes*
- **Regression/replay sessions**: *what real scenarios they cover*
- **Non-determinism policy**: *how a flaky-vs-real failure is distinguished*
- **Rollout plan**: *phased scope, approval gates, what "done" looks like for
  each phase*

---

## 18. Alternatives Considered

--- SECTION EXPLAINED START ---
For every non-obvious decision above (§5's rung, §4's vector store, §9's
guardrail layer), a one-line "we also considered X, here's why not" is often
worth more to a future reader than the decision itself — it prevents someone
from re-litigating a trade-off you already measured.
--- SECTION EXPLAINED END ---

**Fill in:**

| Area | Alternative considered | Why not chosen | Selected |
| --- | --- | --- | --- |
| | | | |

---

## Appendix — Section-to-lesson map

*For anyone extending this template: which course lesson each section leans on
most, if you want to go deeper on the reasoning behind it.*

| Section | Primary lesson(s) |
| --- | --- |
| §1 Problem, Scope & Why an Agent | Lesson 9 (capability ladder) |
| §2 Callers, Identity & Scope | Lesson 8/9, Final Project (caller-identity injection) |
| §3 Capability Map | Lesson 4 (tool loop), Lesson 8 (MCP) |
| §4 Retrieval / RAG | Lesson 6 (naive RAG), Lesson 7 (production RAG) |
| §5 Orchestration Architecture | Lesson 9 (LangChain & LangGraph) |
| §6 Context Engineering | Lesson 10 |
| §7 Structured Output Contracts | Lesson 3/4 (forced tool choice) |
| §8 Write Actions & Approval Gates | Lesson 9 (human-in-the-loop), Final Project |
| §9 Security & Guardrails | Lesson 13 |
| §10 Persistence & State | Lesson 9 (checkpointer), Lesson 14 (queue runtime) |
| §11 Observability | Lesson 11 |
| §12 Evaluation Strategy | Lesson 11, Lesson 12 (eval-loop engineering) |
| §13 Reliability & Failure Handling | Lesson 12 |
| §14 Serving & Deployment | Lesson 14 |
| §15 Cost & Model Choice | Lesson 2/3, Lesson 14 (LiteLLM gateway) |
