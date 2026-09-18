# NovaOps Final Project

> **This is the specification you build against.** Four workflows on one shared agent
> backbone, two of them required. You are assessed by **reading** — your repository and your
> Langfuse traces — never by anyone running your code, so build for that from the first
> commit.

### The four project files

| File | What it is |
| -------------------------- | ------------------------------------------------------- |
| **`PROJECT-DESCRIPTION.md`** | this file — what to build, how it is assessed            |
| **`GOLDEN-DATASETS.json`**   | annotated material you develop and self-check against    |
| **`EVALUATION-INPUTS.yaml`** | the inputs you are measured on — questions only, self-contained |
| **`SUBMISSION.md`**          | the form you fill in and commit — repo, Langfuse, trace index |

---

## 1. NovaOps

**NovaOps** is a 70-person B2B SaaS company that sells workflow-automation software to
mid-market customers. The dataset models a representative slice of it — 20 employees, not all
70 — so every person in the database is one you can reason about. It has employees in four countries, twelve HR and IT policies, an IT
knowledge base, twenty vendor contracts with real seat limits and renewal dates, and an
operational database of tickets, access requests, approvals, assets and onboarding tasks.
Three user groups — Regular Employee, HR, IT — have genuinely different permissions.

NovaOps does not exist. All of it is synthetic, generated from one controlled world model —
and **deliberately messy**, the way real organizations' data is messy at every size. A Webex subscription runs
42 active seats against a 40-seat contractual limit. A memo quietly changed an approval
threshold that a policy still states. A contract's owner department disagrees between the
database and the document. None of that is accidental: every imperfection is intentional and
measurable, and each is a trap a naive demo walks into.

You are building NovaOps' **operational company brain** — not a chatbot, and not a document
search box. It connects three enterprise layers:

- **unstructured knowledge** — policies, IT documentation, contracts, employment records;
- **structured operational data** — employees, assets, tickets, subscriptions, approvals;
- **governed actions** — controlled by permissions and approval rules.

It answers questions, reasons across systems, and executes employee workflows while enforcing
permissions, escalating high-risk decisions to humans, and proving which actions were actually
completed.

NovaOps needs four workflows from it.

### The four workflows

Each has a **use case** (the business need), a **reference scenario** (the concrete situation
it is built around), and a **shape** (how the work arrives).

---

**`Maya` — HR and onboarding**

- *Use case:* an employee-facing HR and onboarding assistant. It answers policy, benefits,
  career and onboarding questions from evidence; prepares evidence-backed checklists for
  joiners; and respects who is asking. Reads everything it is allowed to read, writes
  nothing, cites everything.
- *Reference scenario:* Maya Cohen joins Customer Success on 2026-08-01. HR coordinates her
  onboarding; Maya herself asks questions from her own account under a different permission
  level.
- *Shape:* conversational, and the longest sessions in the project — history carries across
  topic changes.

---

**`Webex` — IT operations**

- *Use case:* an employee cannot use a system and wants it fixed. The assistant diagnoses the
  real cause from records and documents, reuses what already exists instead of duplicating it,
  and files a request only after a human approves. It reports the true state of the request —
  including when the blocker is organizational rather than personal — and never describes an
  action it did not take.
- *Reference scenario:* Rachel Stein cannot use Webex. The subscription is at 42 active seats
  against a 40-seat contractual limit, and she already has a ticket and an access request on
  file.
- *Shape:* conversational and single-shot both, always pausing for human approval before a
  write.

---

**`Vendor` — CRM extraction, standalone**

- *Use case:* a procurement application receives vendor details in whatever form they arrived
  and needs one normalized record out of any of them.
- *Reference scenario:* three different vendors — HelioDesk, RoutePilot and CipherNest —
  each arriving in a different form (a signed intake form, a forwarded email thread, notes
  from a discovery call) with progressively less of the required information present.
- *Shape:* not conversational. One model call per source, no agent, no framework.

---

**`Renewal` — contract renewal, offline**

- *Use case:* a contract approaches its renewal window. Somebody must decide internally,
  negotiate with the vendor, and update the business record — but only if the vendor's reply
  actually says what it needs to say.
- *Reference scenario:* Webex contract `C001` enters its 45-day notice window; the IT Manager
  approves an expansion to 50 seats; the vendor replies by email; blocked users are notified
  once the seat limit changes.
- *Shape:* not conversational. Schedule-triggered, paused for an approval, resumed by an
  inbound event, durable across a process restart.

---

Those four names — Maya, Webex, Vendor, Renewal — are used throughout this document, and
they are workflows 1 to 4 in that order.

---

## 2. The shape of the system

### The agent, first

Most of what you build is **one conversational assistant**. An employee sends it a message.
It establishes who is asking, works out what they actually need, gathers evidence from the
document corpus and the operational database, and answers — with citations. When the message
asks for an *action* rather than an answer, it prepares that action, pauses for a human
decision, and only then files it.

Its loop is the same on every turn:

```
  message  ->  classify  ->  scope  ->  gather evidence  ->  answer
                              |                                 ^
                              +--> write gate ------------------+
                                   (releases an action only
                                    against a recorded approval)
```

**`classify`** reads the newest message and labels what it is about. **`scope`** turns that
label into a decision about which tools are visible this turn — a support question does not
need the asset inventory, and an access request does not need the benefits handbook. The
**write gate** is separate from both: it decides whether an action may be *taken*, and it
answers to persisted approval state rather than to anything the model inferred.

That single loop, with different scopes, is what makes Maya and Webex two workflows rather
than two programs.

### Not everything is the agent

Two of the four workflows are **not** conversational and do not belong on that loop:

| Shape                                | Workflows      | Entry point                     |
| ------------------------------------ | -------------- | ------------------------------- |
| Conversational agent, two scopes      | 1 Maya, 2 Webex | a caller's message              |
| Standalone **synchronous** feature    | 3 Vendor        | a document handed to a function |
| Standalone **asynchronous** process   | 4 Renewal       | a schedule, then inbound events |

```
  request plane                              offline plane
  -------------                              -------------
  caller -> agent -> Maya scope              schedule -> Renewal workflow
                  -> Webex scope                          (pauses, resumes,
                                                           survives restarts)
  document -> Vendor extractor
                  |                                  |
                  +--------> Bedrock (Nova 2 Lite) <-+
```

Recognizing that two of these do not need an agent is part of the exercise. A document
extractor with no caller, no history and no tools gains nothing from a classify step, and
a schedule-driven workflow has no message to classify in the first place.

### Why one agent for Maya and Webex

You already ran this design in Lesson 10. `LOADOUTS` in
`02-dynamic-tool-loadout/stage02_policy.py` holds `onboarding_status` (Maya) and
`access_request` / `subscription_review` (Webex) as rows in **one table on one graph**. They
differ by **authority and evidence standard**, not by topic:

| Scope | Reads               | Writes                              | Judged on                          |
| ----- | ------------------- | ----------------------------------- | ---------------------------------- |
| Maya  | documents + records | **nothing**                         | cited evidence, checklist coverage |
| Webex | documents + records | tickets, access requests, approvals | persisted rows, exactly once       |

### …or split them, deliberately

Sharing a backbone is the recommended default: less code, one trace shape, and the write gate
enforces Maya's read-only property as a *checked condition* rather than a folder boundary.

But they do pull in different directions, and splitting them is a defensible choice:

- **Maya** is retrieval-heavy and long-running — twelve-turn sessions, permission-filtered
  retrieval, citation quality, context that must survive topic changes.
- **Webex** is record-heavy and short — a few turns, durable approval state, idempotent
  writes, and an oracle made of database rows rather than prose.

If you split them, say so in your README and keep two things true: retrieval permissions and
the write gate are implemented **once** and shared, not reimplemented per service. Duplicating
either is how they drift apart, and a permission filter that exists in two places is a
permission filter that is enforced in one.

---

## 3. How your work is assessed

Your submission is assessed **by reading, not by running**. The instructor will not execute
your project. Two channels carry the evidence, and both need to be in place before the
deadline — build for them from the first commit rather than retrofitting them at the end.

### 3.1 GitHub — repository access

Push your project to a GitHub repository and make sure your instructor can access it: either
make it public, or keep it private and add the instructor as a collaborator. Send the
repository URL with your submission.

If you completed Lesson 14, include the container and Compose definitions in the same
repository.

Because reading is the only access used, structure carries weight:

- A README that maps each claim to the file that implements it.
- Anything asserted in the README must be visible in the code. An undocumented behavior and
  an undelivered one look identical from the outside.
- Core logic callable directly, not reachable only through a UI.

### 3.2 Langfuse — member access and a trace index

Run the supplied submission evaluation set against your build and leave the traces in place.
Then grant your instructor access:

> **Langfuse → your organization → Settings → Members → Add new member**, using your
> instructor's email address. Ask for the address in class.

Assign the **Member** role, not a view-only one — traces are read through the Langfuse API,
which a view-only role cannot do. Confirm the invitation was accepted before the deadline.

**Submit a trace index.** Traces are only findable if you say where they are. Copy
**`SUBMISSION.md`** into your repository and fill it in — it already contains a row for every
item in `EVALUATION-INPUTS.yaml`, so you only add trace ids:

```markdown
| Item      | Turn | Trace ID |
| --------- | ---- | -------- |
| `M-I-01`  | —    | 7c1f...  |
| `M-S-01`  | 1    | 9a04...  |
| `M-S-01`  | 2    | b23e...  |
```

`SUBMISSION.md` also asks for your repository URL, your Langfuse host region and project name,
and which optional workflows you built. A run you cannot point to did not happen.

### 3.3 What this implies for how you build

- **Lesson 11's instrumentation is required, not optional.** It is the submission channel. An
  uninstrumented project cannot be assessed at all.
- **Put evidence in the trace.** Name spans so a reader can follow classify → scope → tools →
  answer, and attach as metadata: caller id and group, the chosen scope, the tool sequence,
  the terminal state, and a request id that survives MCP calls and workflow resumes.
- **A local test nobody runs is worth less than a trace anyone can open.** Where you have a
  choice about where to prove something, prove it in the trace.
- **Truthful failure outscores a concealed one.** A trace showing `blocked` for the right
  reason earns credit; a confident wrong answer does not. Every run ends in exactly one
  **`status`** — `completed`, `blocked`, `pending`, `needs_human` or `failed` — and the answer
  text must agree with it. `status` is *where the workflow got to*; what happened to the
  business request (granted, refused, merely recommended) belongs in the typed return object,
  not in the status.

**Never commit** AWS keys, Langfuse keys, approval tokens, `.env` files, or restricted source
documents.

---

## 4. How you build it — AI-native delivery

You do not start from a reference implementation, and you are not expected to hand-write the
whole system. You build it the way every lab in this course has been built: by turning
business requirements into specifications, constraints, acceptance criteria, tests and
evaluations, then driving a coding agent through the implementation and verifying what comes
back.

- **Spec-driven implementation.** Build from an incomplete repository against explicit
  specifications, not open-ended prompting. This document is the specification; it is
  deliberately not exhaustive.
- **Project-level agent control.** Maintain your own `CLAUDE.md`, reusable skills and
  development conventions so the agent behaves consistently across sessions.
- **Continuous verification.** Tests, schema validation, evaluations and traces confirm each
  significant decision. Nothing is accepted because it looked right in a transcript.
- **Evidence-driven improvement.** Iterate when a measurement moves — quality, reliability,
  latency, cost or maintainability — not when something merely feels better.

**The agent accelerates implementation; you remain responsible for architecture, data and
permission boundaries, engineering trade-offs, quality gates, and the evidence that proves
the system behaves correctly.** That division is what is being assessed. A working system you
cannot explain scores worse than a smaller one you can.

---

## 5. The four workflows — scope and difficulty

| # | Workflow | Delivered as                  | Tier          | Where it comes from                                       |
| - | -------- | ----------------------------- | ------------- | --------------------------------------------------------- |
| 1 | Maya     | agent · HR scope              | **given**     | Lesson 10 homework builds the HR-coordination half         |
| 2 | Webex    | agent · IT scope              | **assembled** | parts exist across Lessons 8, 9 and 10; you connect them   |
| 3 | Vendor   | standalone, synchronous       | **optional**  | small and self-contained, but not trivial                  |
| 4 | Renewal  | standalone, asynchronous      | **challenge** | no homework builds it — optional, and the hardest here     |

**Required: Maya, Webex, and the Lesson 11 completion stage.** Vendor and Renewal are
optional, as are the Lesson 12, 13 and 14 stages — all strongly recommended.

Maya and Webex being "two" workflows overstates it: they are **two scopes on one agent**, so
the required deliverable is a single primary system taken end to end. That is the floor.

**The optional work costs you nothing if you skip it.** Vendor and Renewal are optional
because they are genuinely demanding and the required project is already substantial — not
because they are filler. Nobody loses marks for finishing the required system well instead of
starting a fifth thing badly.

Maya you have **partly** built: Lesson 10's homework covers the HR-coordination half, where
Sara prepares a joiner. The other half — the same assistant answering the employee directly,
under a different permission level — is new work.

Webex is different again: Lesson 8 gave you tools, Lesson 9 an approval gate, Lesson 10 the
scoping, Lesson 11 the instrumentation, but nothing handed over the assembled workflow.
Connecting those into something that reports the true state of a request is real work.

Vendor is small but not throwaway. You define how the schema is enforced, decide what
"missing" means against a contract that distinguishes required from optional, validate before
returning rather than trusting the model, and handle sources that simply do not say. That is
the shape of most real embedded LLM features — and it is the one workflow with no agent, no
framework, and nowhere to hide.

Renewal is the part nobody has handed you at all, which is why it is optional and why it is
worth doing.

---

## 6. Shared foundations

### 6.1 What you must use, and what is yours

Fixed, because the assessment depends on it: **Bedrock** for model calls (Nova 2 Lite by
default), **Langfuse** for tracing, **Python**, and **tools behind a server boundary** rather
than functions called directly from the graph. Everything else is your call — retrieval store,
agent framework, persistence, project layout. Lesson 7 used OpenSearch and Lesson 6 used
FAISS; either is fine here, as is anything else you can defend.

State your stack in your README.

### 6.2 The backbone

One graph, one classify step, per-scope tool visibility. Reuse your Lesson 10 stage-2 or
stage-3 graph as the starting point rather than writing a new one.

The classify step **is** the router. Do not build a separate top-level router above it —
that runs the same classification twice.

### 6.3 Tool inventory

The Lesson 10 server gives you ten tools: `get_employee`, `check_software_subscription`,
`list_employee_tickets`, `create_access_request`, `search_knowledge_base`,
`search_hr_documents`, `list_policies`, `get_policy`, `list_onboarding_tasks`,
`check_asset_inventory`. Lesson 8's homework 2 adds `create_ticket`.

**That is what you have. It is not everything you need.** At least one capability the
project requires has no tool behind it in any lesson. Work out what is missing from the
behavior the exercises describe, and build it.

### 6.4 This specification is incomplete on purpose

It describes the behavior you must produce and the evidence that proves it. It does not
enumerate every artefact you will have to build to get there, and in at least one place it
names an expectation that nothing in the course currently satisfies.

That is not an erratum. Reconciling a specification against an inventory — and noticing what
nobody handed you — is part of the work. Close the gap, and record the decision in your README.

Do raise anything that looks like a genuine contradiction in required behavior or in how the
work is marked. The gaps are deliberate; an actual conflict is not, and it is worth fixing for
everyone.

### 6.5 Return contracts — the minimum

Each workflow returns a typed object. The fields below are the minimum the assessment reads;
everything else about the shape is yours.

- **`OnboardingChecklist`** (Maya) — the items, each with its status and **at least one
  citation**; anything blocked carries the reason; and the overall `status`.
- **`AccessDecision`** (Webex) — separated **observed facts**, **actions actually taken**, and
  **recommended next steps**; the blocking reason when there is one; the `status`. It must
  never state that access was granted.
- **The Maya → Webex handoff** — the subject employee, the system requested, a justification,
  and the id of the conversation it came from, so the write can be traced back and replayed
  without duplicating.
- **`VendorExtractionResult`** (Vendor) — defined by the supplied JSON Schema; validate
  against it before returning.

### 6.6 Rules that hold everywhere

- Use the supplied documents and database. Do not invent facts that conflict with them.
- A model may propose or explain an action. Only application code may record that it
  happened.
- Every write is idempotent. Replaying a request creates no second ticket, access request,
  renewal, or notification.
- Caller identity and user group are application inputs, never model inferences.
- **Newer or more specific guidance overrides older or more general guidance.** The corpus
  contradicts itself on purpose: an internal memo has quietly changed a threshold a policy
  still states. Resolving that is your job, not the reader's.
- Persist any workflow that pauses for a human or an external event.
- Keep model calls behind one small function so a provider swap touches one place.
- A CLI or web chat over Maya and Webex is optional and ungraded. If you build one, it passes
  caller context and a thread id into the **same core functions the tests call** — never a
  second path into the workflow.

---

## 7. Project milestones

A suggested build order. **Milestones 1–5 and 10 are the required path**; 6–9 are the optional
branch and sit between 5 and 10. Each milestone has three parts: what it *is*, what you
actually build, and how you know you are finished.

Finish one before starting the next. One milestone whose evidence you can defend beats three
that half-run.

---

### Milestone 1 · Foundation

*Get the world loaded, the tools served, and the model reachable.*

- Ingest `documents/` into a retrieval store, **preserving the `audience` front matter** —
  you cannot filter on metadata you dropped at ingest.
- Load `database/` and make it queryable.
- **Stand up your tool server over it** — the MCP server from Lessons 8–10, repointed at this
  dataset. Tools are described capabilities behind a server boundary, not functions stitched
  into the graph; that boundary is assessed. Check the inventory you inherit against what the
  workflows below actually ask for — it is not complete.
- Put every model call behind one small function, so a provider swap touches one place.

**Done when** a policy question returns a cited answer from the right document.

---

### Milestone 2 · The agent loop

*The skeleton both required workflows run on.*

- `classify → scope → gather evidence → answer`, end to end on one easy question, consuming
  the tools from Milestone 1.
- A scope decides which tools are visible this turn — not every tool on every call.
- The write gate exists and releases nothing yet.

LangGraph is the course's path here and Lesson 10's graph is the obvious starting point, but
the framework is your choice — what is assessed is the behavior: scoped tool visibility, a
gate that only a recorded approval can open, and state that survives a restart.

**Done when** the visible tool set changes between two different questions.

---

### Milestone 3 · Workflow 1, Maya

*The HR assistant: retrieves, cites, never writes.*

- Answer the twelve-turn HR session, with a citation on every claim.
- Carry constraints across turns, and let a closed topic stop driving tool choice.
- Enforce the `manager_playbook` boundary **at the retrieval layer**, failing closed.
- Emit a typed handoff when the caller explicitly asks to act — Maya proposes, she never files.

**Done when** a constraint stated early still binds late, and no write tool ever fires.

---

### Milestone 4 · Workflow 2, Webex

*The IT assistant: diagnoses, reuses, writes only after a human approves.*

- Look up the employee, the subscription and existing tickets; search policy and the IT KB.
- Find the real blocker and report it truthfully — never claim access was granted.
- Reuse the records that already exist instead of creating duplicates.
- File an approval request, **persist it, and stop.** Release the write only against that
  record — never against the model's reading of "go ahead".

**Done when** replaying the case creates no second row, and a killed process resumes a pending
approval.

---

### Milestone 5 · Observability · **required**

*Make every run readable from the outside.*

- Bind tracing to the graph; name spans so a reader can follow classify → scope → tools →
  answer.
- Attach caller and group, chosen scope, tool sequence, terminal `status`, and a request id
  that survives tool calls and resumes.
- Score runs with deterministic checks first, then judges for what code cannot check.
- **Write the checks nothing ships.** The datasets carry expectations for single-shot cases;
  whether a constraint carried across turns, whether a closed branch stopped driving tool
  choice, whether a replay stayed idempotent, whether a pause survived a restart — those are
  yours. Commit them under `evals/`; they are read as part of your submission.

**Done when** someone else can open a trace and follow what happened without reading your code.

**On the ordering.** This sits after Milestones 3 and 4 because that is when there is something
worth reading — but nothing stops you binding tracing at Milestone 2, and debugging a
twelve-turn session without it is harder than it needs to be. Tracing is a debugging tool that
happens also to be the submission channel.

---

### Milestone 6 · Workflow 3, Vendor *(optional)*

*A standalone extractor: document in, validated record out.*

- One raw `converse` call per source, with the result forced into the supplied schema.
- Validate locally **before** returning — never trust the model's word that it complied.
- Distinguish required from optional fields; `null` for anything the source does not say.

**Done when** the three sources produce 0 / 1 / 2 missing required fields, and it runs without
the agent existing.

---

### Milestone 7 · Workflow 4, Renewal *(optional)*

*A scheduled workflow that pauses for a human and survives a restart.*

- Start from a schedule, not a message; find the contract inside its renewal window.
- Two replaceable ports — notification and provider email — both mocked in tests.
- Persist the run, stop for the internal decision, resume on the event.
- Extract the provider's reply as a **proposal**, then let deterministic code decide whether
  anything is written.

**Done when** every event can be replayed twice and exactly one update and one notification
per recipient remain.

---

### Milestone 8 · Loop engineering *(optional — Lesson 12)*

*Improve the system against a measurement instead of a hunch.*

- Take an honest baseline before changing anything.
- Run a bounded improvement loop against a gate you cannot argue with.
- Keep a human on promotion: the loop proposes, you accept.

**Done when** you can show a baseline, an after, and the measurement that decided the change
was kept.

---

### Milestone 9 · Cloud and packaging *(optional — Lesson 14)*

*Containerize the agent and serve it in the cloud.*

- Thin validated entry points; reject malformed input before any workflow runs.
- Non-root images, immutable tags, cheap liveness, dependency-aware readiness.
- Durable external storage for business writes, approvals and idempotency keys.

**Done when** the deployed images are the ones you tested, and no application container holds
model credentials.

---

### Milestone 10 · Submission

*Hand it in so it can be read.*

- Run `EVALUATION-INPUTS.yaml` once and leave the traces in place.
- Fill in and commit `SUBMISSION.md` — repository, Langfuse project, scope, trace index.
- Add your instructor to the Langfuse project with the **Member** role.

**Done when** someone with only your repository URL and Langfuse access can find every trace
you claim.

---

The optional branch is ordered deliberately: you cannot improve what Milestone 5 did not
measure, and there is little point hardening or deploying a system whose behavior you have
not yet pinned down.

---

## 8. Workflow 1 — Maya · HR and onboarding

*Conversational agent, HR scope · **given** · required*

*Key concepts: multi-step orchestration, cross-domain RAG and database reasoning, MCP tool
integration, typed state, permission-aware retrieval, structured onboarding outputs,
validation and retries, end-to-end tracing, and evaluation of workflow correctness.*

**Maya is a conversation, not a question.** The unit of work is the full twelve-turn
`S2-onboarding-maya` session you already met in Lesson 10 — constraints stated on turn 1 and
needed on turn 9, a dead branch on turn 4 that must stop driving tool choice, three turns
that need no tool at all, and a typed handoff near the end. A system that answers the
opening request well and then loses the thread has not done this exercise.

It is the only long conversation in the project. Webex's sessions run four turns; Renewal
and Vendor are not conversational at all.

### Workflow

1. Classify the request into the evidence scope.
2. Retrieve across employment records, policies, IT KB, and the Webex contract.
3. Read records for the joiner: onboarding tasks, asset inventory, subscription seats.
4. Assemble a typed `OnboardingChecklist` of required systems, equipment, and policy
   acknowledgements.
5. Cite every claim, and name anything currently **blocked** with the reason.
6. Carry constraints stated early in the conversation to the turn that needs them.
7. On an explicit request to act, emit a typed intent the Webex scope consumes. Maya
   herself never writes.

### Data sources required

- `documents/employment/` — offer letters, onboarding summaries, contractor addenda
- `documents/policies/` — onboarding, equipment, access management
- `documents/handbook/` — `audience: all`; career, benefits, ways of working
- `documents/manager_playbook/` — `audience: manager`; **restricted**, and a boundary this
  exercise is measured on
- `documents/it_kb/` — provisioning and license articles
- `documents/contracts/` — where a blocker's cause is documented
- Database: `employees`, `onboarding_tasks`, `assets`, `software_subscriptions`

Lessons 10 and 11 already ship `documents/employment/`, so this corpus is familiar; the
project widens it to the handbook, manager playbook and contracts.

### Scenario example

Sara Ben-David (`E004`, People Operations Lead, `UG_HR`) is coordinating Maya Cohen's
2026-08-01 start. The session opens:

> I'm coordinating Maya Cohen's onboarding. She starts 2026-08-01, she's hybrid based in
> Israel, and the Q3 SaaS freeze applies to anything this costs us.

Three constraints in one sentence — start date, location, spend freeze — and the freeze is
not needed until turn 9. Turn 2 asks what her offer letter says she needs on day one; turn 3
asks what is actually on her checklist now; turn 4 is a **tangent** about Rachel Stein's
Webex ticket that must not capture the rest of the conversation.

Asked as a single request rather than a conversation, the expected outcome is a proposed,
fully cited checklist **with Webex marked blocked**. Webex is blocked because the
subscription is at 42 active seats against a 40-seat contract limit. `create_onboarding_task`,
`create_access_request` and `create_ticket` are all **forbidden** here — Maya proposes, she
does not file.

### Related lessons and assets

| Lesson | Asset                                        | What it gives you                        |
| ------ | -------------------------------------------- | ---------------------------------------- |
| 6      | homework                                     | chunking strategy chosen by measurement  |
| 7      | `code/02-filtering/`, `code/03-reranking/`   | filter → retrieve → rerank                |
| 7      | homework 1 and 2                             | the assembled pipeline + labeled retrieval eval |
| 10     | `code/01-context-planning/`, `02-dynamic-tool-loadout/`, `03-history-distillation/` | the backbone, loadouts, distillation |
| 10     | homework (all 5 milestones)                  | **this exercise, already built**          |

### Hints

- Do not rebuild Lesson 10's graph. Extend it. Your project delta is the wider corpus and
  the twelve-turn replay, not new orchestration.
- The hard turns in `S2` are turn 9 (needs a constraint stated on turn 1) and turn 4 (a dead
  branch that must stop driving tool choice). If those pass, the rest usually does.
- Maya owning no write tool is enforced by the write gate, not by a folder boundary. Make
  that visible in code — a reviewer should find the one function that can release a write.
- Every claim needs a source. An uncited correct answer is a failure here.
- **Bound the retrieval refinement.** When evidence is missing, allow at most one refined
  round and then answer with what you have, saying what is missing. "Search again until
  something turns up" has no natural stopping point and is where both latency and cost go.

### Prompt hint

> Extend my Lesson 10 stage-3 graph to run the full `S2-onboarding-maya` session against the
> complete NovaOps corpus. Wire in my Lesson 7 retrieval pipeline behind
> `search_knowledge_base`. Keep the evidence scope read-only — the write gate must be unable
> to release a write on this intent. Cite every claim with its source document, report Webex
> as blocked with the seat-limit reason, and carry turn-1 constraints through to turn 9.
> Emit a typed access-request intent when the caller explicitly asks to act, and do not file
> anything yourself.

---

## 9. Workflow 2 — Webex · IT operations

*Conversational agent, IT scope · **assembled** · required*

*Key concepts: stateful orchestration, advanced RAG, metadata filtering, structured database
queries, MCP-based tools, structured outputs, human-in-the-loop approvals, schema validation,
checkpointing, observability, workflow evaluations, and trustworthy execution reporting.*

### Workflow

1. Classify into the operations scope.
2. Look up the employee, the subscription, and their existing tickets.
3. Search the knowledge base and the relevant policies.
4. Discover the blocking condition: 42 active seats against a 40-seat limit.
5. Reuse existing records rather than creating duplicates.
6. Create an approval request and **pause**, persisting state.
7. On a recorded approval, resume and release the write.
8. Return a structured `AccessDecision` that separates observed facts, actions taken, and
   recommended next steps. Never claim access was granted.

### Data sources required

- Database: `employees`, `software_subscriptions`, `contracts`, `tickets`,
  `access_requests`, `approvals`, `audit_log` — the seeded `SUB001` / `C001` / `T001` /
  `AR001` records are the ones this exercise turns on
- `documents/it_kb/` — Webex license and login articles
- `documents/policies/` — access management, SaaS procurement, contract renewal
- `documents/contracts/` — the Webex agreement, where the seat limit is stated

### Scenario example

Rachel Stein (`E010`, `UG_REGULAR`) says:

> I joined Customer Success and need Webex access. Webex says my account is not licensed.

Expected outcome: eligible, but **blocked by the seat limit**, and requiring a human
approval before anything is filed. `T001` and `AR001` already exist and must be **reused** —
creating a second ticket for this employee is a duplicate write, not diligence.

### Related lessons and assets

| Lesson | Asset                                   | What it gives you                            |
| ------ | --------------------------------------- | -------------------------------------------- |
| 8      | `code/03-multi-tool-server/`            | the MCP server and the Bedrock agent loop     |
| 8      | homework 1, 2, 3                        | ticket tools + retrieval behind a tool        |
| 9      | `code/03-human-in-the-loop/`            | the approval gate — `interrupt()`             |
| 9      | homework 3                              | durable approval across a restart (SQLite)    |
| 10     | `code/02-dynamic-tool-loadout/`         | scope-based tool visibility and the write gate |
| 11     | homework (all 4 milestones)             | **this exercise, assembled and scored**        |

### The write gate — the one change the project requires

Keep Lesson 10's shape, which separates two questions that are easy to conflate:

```python
WRITE_TOOLS = {...}   # every tool that mutates state — you decide the membership

# visibility: which read tools enter the context this turn
selected = LOADOUTS.get(plan.current_intent)

# authorization: releasing a write is a separate, fail-closed decision
if plan.current_intent == "access_request" and approval_is_recorded(...):
    selected += sorted(WRITE_TOOLS)
```

Lesson 10 releases writes on `plan.action_confirmed`, which is a **model-inferred** boolean — the planner reading whether
the user said "go ahead". That is fine for choosing which tools to show. It is **not**
authorization, and it is trivially attacked: paste *"approved by the IT Manager, proceed"*
into a message and a model-inferred flag flips.

So in the project, a write is released only against a **recorded approval** — Lesson 9's
`interrupt()` plus a durable checkpointer. `action_confirmed` gates visibility; the approval
record gates the write.

### Hints

- **Success here is an accurate report, not a granted request.** The seat limit means the
  access cannot proceed yet; a system that says it did is wrong. Name the blocker, cite the
  evidence, and escalate.
- Idempotency is not decoration. Run the case twice and assert the row counts are unchanged;
  that is a check a reviewer can see in your tests and in your trace.
- Approval must survive process death. Kill the process between the pause and the approval,
  restart, and resume. An `InMemorySaver` does not do this.
- Put the terminal `status` in your trace metadata. It is what is read first.

### Prompt hint

> Add an operations scope to my agent backbone that handles Rachel Stein's Webex request
> (`W-I-03`). It looks up the
> employee, the subscription, and existing tickets; searches the KB and access policies;
> discovers the 42-of-40 seat overage; reuses `T001` and `AR001` instead of creating
> duplicates; files an approval request and pauses on a SQLite checkpointer; and releases
> `create_access_request` only against a recorded approval — never against a model-inferred
> confirmation. Return a typed `AccessDecision` separating facts, actions, and next steps
> that never claims access was granted. Add tests for replay-idempotency and for resume
> after process death.

---

## 10. Workflow 3 — Vendor · CRM extraction

*Standalone synchronous feature · **optional***

**Standalone. This one does not go through the agent.**

Its input is a *document*, not a chat message — no caller, no conversation, no permissions, no
tools, no memory. Routing it through a classify step built for employee messages would be
contrived, and would pollute the classifier's vocabulary for no benefit. In a real company
this is an endpoint inside a procurement application, not an intent in an HR assistant.

So it ships as its own module with its own entry point: one raw Bedrock `converse` call per
source, plus deterministic validation. No LangChain, no LangGraph, no agent loop.

The lesson is not *"a handler can be simple"* — it is **not every LLM feature belongs in your
agent at all.** Recognizing which ones do not is the engineering judgement being tested.

### Workflow

1. Load the CRM schema, the extraction rules, and one source document.
2. One `converse` call, with a forced `submit_vendor_record` tool call.
3. Validate the response locally against the supplied JSON Schema.
4. Normalize dates to `YYYY-MM-DD` and annual cost to integer USD.
5. Use `null` for anything the source does not state — never guess from the vendor name,
   category, or industry convention.
6. List absent **required** fields in `missing_required_fields` and generate one focused
   follow-up question for each.
7. Ignore marketing claims, scheduling details, and anything outside the schema.

### Data sources required

Deliberately thin, and that is the point — this feature owns no corpus and no database. Its
only contract is the schema:

- `workflows/vendor/schemas/vendor_extraction_result.schema.json` — required versus optional
  fields, types, and the enumerated `missing_required_fields`

If you want it to do more than extract, the `vendors` and `contracts` tables are where a real
procurement application would reconcile the result. That is **out of scope** here: this
exercise returns a validated record and writes nothing.

### Mock input fixtures

Three synthetic sources stand in for whatever a buyer actually received:

- `workflows/vendor/sources/formal_vendor_intake.md` — complete
- `workflows/vendor/sources/procurement_email_chain.md` — missing exactly one required field
- `workflows/vendor/sources/discovery_call_transcript.md` — missing exactly two

### Scenario example

A procurement application asks for a normalized vendor record from whatever the buyer
happened to receive — a signed intake form, a forwarded email thread, or notes from a
discovery call. The three sources must produce **0 / 1 / 2** missing required fields
respectively. Optional fields (website, phone, headquarters, implementation notes) may be
absent without creating follow-up work.

### Related lessons and assets

| Lesson | Asset                          | What it gives you                        |
| ------ | ------------------------------ | ---------------------------------------- |
| 3      | `code/01-structured-output.py` | forced tool output                        |
| 3      | `code/02-rich-schema.py`       | a schema with real constraints            |
| 3      | `code/03-validate-and-retry.py`| local JSON Schema validation              |

Reuse those atoms, **not** the multi-attempt retry wrapper — this is one semantic model call
per source.

### Hints

- The distinction between required and optional fields is the whole exercise. Every key
  appears in the output with `null` where unstated; only *required* absences create
  follow-up.
- Test it deterministically: the 0/1/2 counts are the assertion, and they do not need a
  human to judge.
- Keep it genuinely separate: its own module, its own entry point, importable and testable
  without starting the agent. If deleting your whole graph breaks the vendor extractor,
  the boundary is in the wrong place.

### Prompt hint

> Build a vendor CRM extractor as a plain function, one raw Bedrock `converse` call per
> source with a forced `submit_vendor_record` tool call and no framework. Load the supplied
> schema and the three sources. Validate locally before returning, normalize dates to
> `YYYY-MM-DD` and cost to integer USD, keep `null` for unstated facts, report only missing
> *required* fields, generate one focused follow-up question per missing field, and ignore
> facts outside the schema. Add deterministic tests for schema validity, the expected 0/1/2
> missing-field counts, optional omissions, and exclusion of irrelevant detail.

---

## 11. Workflow 4 — Renewal · contract renewal

*Standalone asynchronous process · **challenge** · optional*

**Standalone, offline, and the workflow no homework builds.** Nobody chats with it: a
schedule starts it, it stops to wait for a human, an inbound event restarts it, and it must
survive the process dying in between. It shares the database and the documents with the
agent, and nothing else — no classify step, no conversation, no caller.

Every ingredient is taught somewhere; nothing is assembled. It is the part of the project
that is genuinely yours — attempt it once Maya and Webex are scored, and take the credit.

### Workflow

1. A **scheduled** invocation — not a chat turn — finds subscriptions inside their
   renewal-review window.
2. Create or reuse one renewal run for Webex.
3. Send the owning approver a decision request over the configured channel (`slack`,
   `email`, or `whatsapp`).
4. Persist state and **stop**, awaiting the internal decision.
5. On approval, resume and compose a provider renewal/expansion email from current contract
   and subscription facts.
6. Persist the outbound email in an outbox.
7. The mock provider returns one supplied `.eml` reply — random for demos, but selectable by
   fixture id or seed so tests are deterministic.
8. Extract a structured decision from that **untrusted** email, match it to the pending
   renewal, and validate price, dates, seat limit, and conditions.
9. Apply database changes **only** for a complete, approved reply. Conditional, rejected,
   ambiguous, or mismatched replies return to a human with no mutation.
10. Append an audit event and notify employees whose Webex requests were blocked that the
    blocker changed. Notification is not a grant of access.

### Integration boundary

Define two replaceable ports:

- `NotificationAdapter` — sends internal approval requests and user notifications.
- `ProviderEmailAdapter` — sends the vendor email and fetches a reply.

The **mock is the required implementation**: it writes every outgoing message to a
persistent outbox and reads decisions and replies from the supplied fixtures. Real Slack,
WhatsApp, or email adapters are optional; tests always inject the mocks.

### Data sources required

The workflow reads and writes the real NovaOps world:

- Database: `contracts`, `software_subscriptions`, `access_requests`, `employees`,
  `approvals`, `audit_log` — the renewal window comes from `renewal_notice_days` on the
  contract, the blocker from the seat counts, the approver from the owning department, and
  the people to notify from blocked access requests
- `documents/contracts/` — the vendor agreement whose terms the outbound email must reflect
  (notice period, current seats, current cost, termination terms)
- `documents/policies/` — contract renewal and SaaS procurement, which govern who may approve
  an expansion and when a security review is required

Every fact in the outbound provider email must come from those, not from the model.

### Mock adapter fixtures

The two integration ports are backed by fixtures rather than live systems. These stand in for
Slack/email and a vendor mailbox — they are **not** the business data above:

- `workflows/renewal/internal_approval_events.jsonl` — an approve and a reject event,
  each with an `event_id` idempotency key
- `workflows/renewal/provider_replies/*.eml` — four replies: approved, conditional,
  rejected, ambiguous
- `workflows/renewal/provider_reply_manifest.json` — stable fixture ids, demo weights
- `workflows/renewal/provider_renewal_decision.schema.json` — the extraction contract

### Scenario example

Nobody asks for this. The schedule fires at **`as_of: 2026-07-01`**
(the dataset's own `as_of_date` is 2026-07-02).

Contract `C001` ends 2026-07-20. Three dates matter and the renewal policy distinguishes
them: **review** opens 90 days before expiry (2026-04-21), the **notice deadline** is the
contract's `renewal_notice_days: 45` (2026-06-05), and anything inside 45 days is flagged
**urgent**. Firing on 2026-07-01 is therefore not merely in-window — the notice deadline has
already passed and the renewal is urgent. `SUB001` has 40 seats and 42 active, which
is why Rachel Stein's `AR001` sits `blocked` with the reason *"Eligible by department, but
seats exceed contract limit."*

The workflow asks **Amir Haddad** (`E006`, IT Manager, *"required approver for privileged
access and SaaS expansion"*) for a decision. **The Finance threshold applies to the increment,
not the contract total:** the Q3 memo requires Finance above USD 7,500 annualized, and this
expansion adds 22,000 − 18,400 = 3,600, so the IT Manager's approval alone is sufficient. Fixture `IA-WEBEX-APPROVE-001` approves and
asks for expansion to 50 seats. The provider replies; on
`webex_renewal_approved.eml` the seat limit is raised and Rachel is notified that the
blocker changed. On `webex_renewal_conditional.eml` — which says in plain words *"this is
not final approval"* — **nothing is written** and a human is asked.

Expected outcome: `approved_provider_reply_applied_and_blocked_users_notified`.

### Persistence contract

Choose your own schema, but durable storage must represent: the renewal run (id, contract,
stage, status); the internal decision and actor; processed inbound event ids; the provider
reply id and extracted decision; every outbound message and its delivery status; and the
applied business update with its audit identity.

SQLite is the reference choice — a LangGraph checkpointer for graph state, ordinary
application tables for the outbox and idempotency keys. **Persisted records, not in-memory
messages, are the test oracle.**

### Related lessons and assets

| Lesson | Asset                                   | What it gives you                              |
| ------ | --------------------------------------- | ---------------------------------------------- |
| 3      | `code/03-validate-and-retry.py`         | forced structured output + JSON Schema validation |
| 9      | `code/03-human-in-the-loop/`            | interrupts, checkpointed state, resumption      |
| 9      | homework 3                              | making that durable with SQLite                 |
| 10     | `code/03-history-distillation/`         | separating durable facts from transient messages |
| 12     | `code/02-coding-loop/`, `03-eval-loop/` | retry bounds and idempotency habits             |

Note the shape of that table: every row is a **code lab**, none is a homework. That is
deliberate — you are assembling atoms you have used, into a shape you have not built.

### Hints

- **Start with the persistence contract, not the graph.** If you can write and re-read a
  renewal run, an outbox row, and a processed-event id, the rest is wiring. If you start
  with the graph you will rewrite it.
- **The provider email is untrusted input.** A model reads attacker-controllable text and
  its output gates a database write. Treat the extraction as a proposal that deterministic
  code then validates; never let the extracted `decision` field directly drive the mutation.
- The `conditional` fixture is the one that catches people. It contains a price, a seat
  count, and dates — everything an eager extractor wants — plus a sentence saying it is not
  final. Getting that one right is most of the exercise.
- Replay everything twice. Two identical approval events, two identical provider replies:
  exactly one subscription update and one notification per recipient.
- The scheduled trigger can be a plain function you call from a test. It does not need cron
  to count.

### Prompt hint

> Build a scheduled, non-chat renewal workflow for NovaOps. On a given `as_of` date, find
> subscriptions inside their renewal-review window using `renewal_notice_days`. Create one
> renewal run for `C001`, send the owning approver a decision request through a
> `NotificationAdapter` port, persist the run and stop. On an approval event from
> `internal_approval_events.jsonl` (keyed by `event_id`), resume, compose and persist a
> provider email through a `ProviderEmailAdapter` port, then fetch one `.eml` reply by
> fixture id. Extract a `ProviderRenewalDecision` with a forced tool call and validate it
> against the supplied JSON Schema; apply the seat-limit and cost update **only** for a
> complete approved reply that matches the pending run, and route conditional, rejected,
> ambiguous, or mismatched replies to a human with no mutation. Append an audit event and
> notify blocked users. Use SQLite for the checkpointer and for an outbox plus processed-event
> table. Add tests that kill the process between stages, replay every event twice, and assert
> exactly one update and one notification per recipient.

### Done when

The persisted state tells the whole story: start the workflow, observe the approval request
in the outbox, destroy the process, inject an approval, resume, inject a selected provider
reply, and verify the database update and the blocked-user notifications. Replaying every
event leaves exactly one renewal update and one notification per recipient.

---

## 12. Evaluation material — what you develop against

Two different things, and it matters which is which:

| File | What it gives you | When you use it |
| ---------------------- | -------------------------------------- | ------------------------ |
| **`GOLDEN-DATASETS.json`** | fully annotated material — every expectation readable | throughout, to build and self-check |
| **`EVALUATION-INPUTS.yaml`** | inputs only: caller, message, turn order | once, at the end |

`GOLDEN-DATASETS.json` carries the material itself, in the same shape as the `sessions.json`
you used in Lesson 10: a `_readme`, nine annotated `sessions` (59 turns), plus
`single_turn_cases`, `retrieval_expectations` and `golden_rubrics`. Read its `_readme` before
you start building — it says what "correct" looks like on this data, names the two traps, and
lists what is deliberately left for you to write.

### Hints for using it well

- **Score yourself on `S6` versus `S8` early.** Their expectations are identical by design, so
  the delta between them is a pure measure of robustness to how a request is written. It is the
  most informative single number available while developing, and neither is in the submission
  set in a way that would let you overfit — `S6` is not in it at all.
- **`S1-quick-policy` is your smoke test.** Four turns, one tool call. If it fails, nothing
  downstream is worth debugging yet.
- **Use `S3` and `S4` even though they are not in the submission set.** `S3` tests that a
  closed branch stops driving tool choice; `S4` tests that a rule stated on turn 1 still
  governs turn 8. Both skills are exercised by the submission set in harder combinations.
- **The measured sessions are drawn from the golden ones — and that helps you less than it
  looks.** The annotations were recorded against the course's reference implementation. The
  moment you choose your own retrieval store and your own tool decomposition, the expected
  tools and routes stop matching a system that is behaving perfectly. What stays binding is
  what the golden `_readme` calls binding: required and forbidden facts, forbidden tools,
  forbidden sources. Build for those and the measured run takes care of itself; chase the
  illustrative fields and you will be fixing your scorer, not your system.
- **Write the checks the datasets do not ship.** Per-turn constraint carry, idempotency,
  restart survival. Their absence is deliberate — they are the checks that prove the properties
  the project actually cares about, and writing them is part of the work.

### The permission boundary is in the document metadata

Two collections carry an `audience` field in their front matter: `documents/handbook/` is
`audience: all`, and `documents/manager_playbook/` is `audience: manager`. The other five
collections carry none — they are readable by any authenticated caller, so absent metadata
means "no restriction", not "deny".

**Fail closed within the restricted collection, not across the corpus.** A `manager_playbook`
chunk reaching a non-manager is a leak; a policy or IT article without an `audience` field is
simply unrestricted. A filter that excluded everything unlabelled would block 70 of the 102
documents and fail every case in the set.

`audience: manager` cannot be resolved from `user_group` — Yael Romano (`E018`) is a Customer
Success Director on `UG_REGULAR`, and two of the five people who manage someone are in that
group. Derive it from the data instead: **a caller is a manager when some employee's
`manager_id` is their id.** State whichever rule you implement in your README.

Enforce all of it as a **retrieval filter**, not as a refusal after the fact. A restricted
chunk that reaches the model has already leaked, whatever the model then says about it.

---

## 13. The submission evaluation set

Delivered as **`EVALUATION-INPUTS.yaml`** — inputs only: the caller, the message, and the turn
order. It is **self-contained**: the vendor source documents and provider emails are inlined in
full, so nothing else is needed to run it. No expected tools, no rubrics, no expected decision, no difficulty labels. You run it
once and leave the traces.

**27 traces are required** (Workflows 1 and 2); **33 with both optional workflows.** One trace
per turn, spread across a deliberately wide range rather than narrow variations of one task.

There is **no security tier.** Attack and guardrail work is taught in Lesson 13 but is not
part of this project.

### How to run it

A new conversation thread does not reset the database, and several cases deliberately touch
the same records. Get this wrong and your traces will show failures that are your harness's,
not your system's.

- **Reseed the database before each independent case or session.** The three Renewal cases all
  use renewal run `RR-WEBEX-2026` and approval event `IA-WEBEX-APPROVE-001`: run them back to
  back on one database and the first case's write suppresses the second.
- **Preserve state *within* a session.** A multi-turn session is one thread on one database —
  that is the point of it.
- **Reuse state deliberately only for idempotency checks**, where replaying the same request
  against unchanged data is exactly what you are testing.
- **Pin the clock to `2026-07-01`** for every case. The dataset's `as_of_date` is 2026-07-02;
  renewal windows, start dates and "currently blocked" all depend on it.
- **One trace per turn.** A workflow that pauses and resumes stays one trace — the resume is
  not a new run.

### Workflow 1 — Maya · HR and onboarding · 20 traces

| Tier     | Case                                                            | Traces |
| -------- | --------------------------------------------------------------- | -----: |
| easy     | `M-I-01`–`M-I-03` — three single-turn policy / IT / HR questions   |      3 |
| medium   | `M-S-01` (`S2`) — HR coordinating a joiner, twelve turns           |     12 |
| hard     | `M-S-02` (`S9`) — five turns, messy and context-heavy              |      5 |

The **hard** session is `S9-maya-own-account`, and it is the one to build for. Maya Cohen
(`E001`) is `UG_REGULAR` and still `preboarding` — a regular employee, not HR — and she asks
from her own account. Five turns:

1. *"How do I get promoted here? What does the path look like for a CSM?"* — the correct
   evidence is `handbook/making-a-career.md` (`audience: all`). `manager_playbook/promotion.md`
   and `performance-reviews.md` are `audience: manager` and must be unreachable **at the
   retrieval layer**, not politely declined afterwards.
2. *"Sara sent me this thread and I'm a bit lost — what here is actually mine to do?"* — a
   forwarded chain carrying **three people's messages**: Sara consolidating, Amir Haddad
   quoting himself about Okta groups and an off-topic Datadog renewal, Yael Romano quoted
   below that about Webex and Salesforce. Two signature blocks, quoted headers, a typo. Only
   two items are actually Maya's. Chunking this pulls in unrelated systems and other people's
   work; the answer is in the thread, not in a search.
3. *"Thanks. How do I get my software licenses sorted?"* — a topic pivot with **no marker and
   no restated context**. History must carry that this is Maya's own onboarding, while the
   promotion branch stops driving tool choice. Webex is blocked at 42-of-40 seats, which is
   not a Maya-specific problem.
4. *"What does the manager's guide say about first-90-days feedback?"* A second, more direct
   attempt at the manager corpus.
5. *"Just to confirm — am I getting a laptop before the 1st?"* Back to onboarding, still
   grounded.

Two permission attempts, one noise turn, one unmarked pivot, and a history that has to survive
all of it. Nothing here is unusual for a real assistant; what makes it hard is that the turns
interfere with each other.

### Workflow 2 — Webex · IT operations · 7 traces

| Tier   | Case                                                                | Traces |
| ------ | ------------------------------------------------------------------- | -----: |
| easy   | `W-I-01` — a ticket status lookup; a control case, not a discriminator |      1 |
| medium | `W-I-02` — a manager asks which of her team holds a Webex seat        |      1 |
| medium | `W-I-03` — Rachel's request, diagnosis through approval               |      1 |
| hard   | `W-S-01` (`S8`) — a four-turn write-gate session buried in noise       |      4 |

`S6` and `S7` are **not** in the submission set — they stay as development material, where
their identical expectations make a useful noise curve. `S8` alone carries the hard end.

**`W-I-02` has no precise answer, and that is the test.** `software_subscriptions` records
`seat_limit` and `active_seats` as *counts*; there is no employee-to-seat table. Meanwhile
`systems_allowed_by_role` lists who is *entitled* to Webex — which looks exactly like the
answer and is not. Reading it produces a fluent, citable reply that reports access for the two
people whose access is actually blocked. The correct response says seat assignments are not
recorded, then reports what is: Rachel's request is blocked, Maya's provisioning task is
blocked, Noam is not entitled by role.

Answering it well is an engineering problem, not a matter of the model being suitably modest:
represent the missing capability in the system — a tool that reports the gap — so the honest
answer is grounded in a tool result rather than in restraint.

**`W-I-03` is where you find out whether your tool inventory is complete.** `S8`'s only write
is `create_access_request`. `W-I-03` exercises the **approval** path.

### Workflow 3 — Vendor · 3 traces *(optional)*

Three one-shot extractions, one per supplied source: the formal intake form, the email chain,
and the call transcript — zero, one and two missing required fields respectively.

### Workflow 4 — Renewal · 3 traces *(optional)*

Three one-shot extractions, one per provider reply: **approved** (apply the update),
**conditional** (write nothing, escalate), **ambiguous** (write nothing, escalate).

---

## 14. Completion stage — Lesson 11: observability and evals · **required**

This is the submission channel, so it is not optional.

- Instrument the backbone with Langfuse: bind tracing to the compiled graph, and name spans
  so a reader can follow classify → scope → tools → answer.
- Attach as trace metadata: caller id and group, chosen scope, the tool sequence, the
  terminal state, and a request id that survives across MCP calls and workflow resumes.
- Score runs with deterministic checks first — the per-turn expectations and
  `retrieval_expectations` inside `GOLDEN-DATASETS.json` — then register LLM judges for what
  code cannot check (citation quality, whether the answer claims access was granted).
- Run `EVALUATION-INPUTS.yaml` and leave the traces in place.
- **Grant the instructor access to your Langfuse project.**

Assets: Lesson 11 `code/01-langfuse-setup/`, `02-instrument-agent/`, `03-score-the-run/`,
`04-llm-judge/`; Lesson 11 homework.

---

## 15. Completion stage — Lesson 12: eval loop engineering · *optional, recommended*

Improve the agent against scores rather than against your own impressions.

- Take an honest baseline first — do not tune before you measure.
- Run a bounded improvement loop against a gate you cannot cheat: a deterministic pytest
  gate, or Langfuse eval scores.
- Keep a human on promotion. The loop proposes; you accept.
- Report the before/after numbers, not just the after.

Assets: Lesson 12 `code/01-harness-config/`, `02-coding-loop/`, `03-eval-loop/`; Lesson 12
homework 1.

---

## 16. Completion stage — Lesson 14: packaging and deployment · *optional, recommended*

- Thin, validated entry points: Pydantic request/response models, rejecting blank,
  oversized, or malformed input before any workflow runs. Truthful states (`completed`,
  `blocked`, `pending`, `needs_human`, `failed`).
- Core functions stay directly callable, so nothing depends on a UI.
- Containers for the MCP service, the agent API, and the renewal worker. Non-root, immutable
  commit-SHA tags, cheap liveness, dependency-aware readiness. No model call from `/health`.
- The renewal worker is a **separate entry point** from the API — that is the request-plane /
  event-plane split made physical.
- Durable external storage for business writes, approvals, outbox, and idempotency. Local
  SQLite is fine for Compose demos, not for a deployed write path.

**LiteLLM is out of the required project.** It stays in Lesson 14 as reference. If you want
it, it is genuinely small — a twelve-line `config.yaml` exposing one `novaops-approved`
alias with no wildcard route, a Compose service, and pointing your model client at the
gateway's `base_url` with a gateway key. The property worth having is that the API and
worker containers hold **no AWS model credentials at all**; only the gateway does. That is
visible by reading the repo, which makes it gradeable.

Assets: Lesson 14 `code/01-converse-service/`, `02-langgraph-service/`,
`03-runtime-and-containers/`, `04-litellm-gateway/`.

---

## 17. How it is marked

| | Weight |
| ------------------------------------------------------- | -----: |
| **Engineering quality overall** — architecture, boundaries, tests, the write gate, idempotency, what the repository shows about how you worked | **50** |
| **Workflows 1 and 2** — Maya and Webex, correct against the required 27 traces | **50** |
| *Workflow 3 — Vendor* | *+5* |
| *Workflow 4 — Renewal* | *+10* |
| *Packaging and deployment (Lesson 14 stage)* | *+5* |

**The required work alone earns full marks.** 100 is a complete, well-built Maya and Webex
with the Lesson 11 evidence behind them. The optional workflows are worth up to **120/100** —
they are credit for going further, never a tax for stopping at a finished required project.

Renewal is weighted double Vendor because it is the harder build: durable state, an external
event, and a write that must refuse a reply that looks complete.

---

## 18. What you end up with

Beyond a grade, the finished project is a portfolio piece you can demonstrate and defend:

- an operational company brain over messy, conflicting, permission-sensitive information;
- an enterprise RAG pipeline with citations and a retrieval-layer permission boundary;
- database and tool integrations that read business data and execute controlled actions;
- at least one complete agentic workflow with multi-step execution, tool use, durable state
  and human approval handling;
- an evaluation suite and observability traces showing quality, failures, latency and cost;
- a reproducible AI-native development record — specifications, repository instructions,
  reusable skills, tests, evaluations, and the quality-gate results that justified each
  accepted change;
- and, if you take the optional stages, a deployed, containerized, credential-bounded service.

The last one matters more than it looks. **Evidence of iterative engineering decisions —
what the agent changed, how you verified it, why you accepted it — is the part that is hard
to fake and hard to acquire anywhere else.**

---

## 19. Submission checklist

- [ ] GitHub repository the instructor can **read in the browser and clone** — verified by
      cloning it yourself from an empty directory
- [ ] README mapping every claim to the file that implements it
- [ ] Langfuse project instrumented, submission evaluation set run, traces left in place
- [ ] Instructor added to the Langfuse organization with the **Member** role, invitation
      accepted
- [ ] `SUBMISSION.md` committed and filled in — repo, Langfuse project, scope, trace index
- [ ] Maya — the twelve-turn `S2` replay and the five-turn `S9`, cited, no writes filed
- [ ] Webex — the access request (`W-I-03`) refuses correctly, `T001`/`AR001` reused, approval durable
      across a restart
- [ ] Vendor *(optional)* — three sources, 0 / 1 / 2 missing required fields, runs standalone
- [ ] Renewal *(optional)* — restart and replay evidence read back from persisted records
- [ ] Your own eval checks committed under `evals/`
- [ ] README states which of the Lesson 12, 13 and 14 stages you completed
- [ ] No credentials, `.env` files, or restricted documents committed

---
