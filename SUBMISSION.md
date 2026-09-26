# NovaOps final project — submission

Fill this in and commit it to your repository as `SUBMISSION.md`. It is the first thing read,
and it is how every trace gets found.

---

## 1. Repository

| | |
| ------------------- | ------------------------------------------------ |
| **Repository URL**  | `https://github.com/SagiLiba/agent-project` |
| **Access**          | public |
| **Commit reviewed** | `ad70ad0001d3781eef940d5eceeb50ccdff37107` |

## 2. Langfuse

| | |
| ------------------ | --------------------------------------------- |
| **Host region**    | `cloud.langfuse.com` (EU) |
| **Project name**   | `My Project` (organization: `liba's Organization`) |
| **Instructor role**| Member *(required — traces are read through the API)* |
| **Invitation accepted** | yes |

## 3. Scope completed

| Workflow | Built | Notes |
| --------------------------- | ------ | ----- |
| 1 — Maya · HR and onboarding | required, built | 12-turn `S2` + 5-turn `S9` replay, all assertions pass — `src/agent/maya_replay_test.py` |
| 2 — Webex · IT operations    | required, built | control case, "no precise answer" hard case, seat-blocked refusal, 4-turn adversarial write-gate session + process-restart proof, all pass — `src/agent/webex_replay_test.py` |
| 3 — Vendor · CRM extraction  | not attempted | scope decision — only the two required workflows were built |
| 4 — Renewal · contract renewal | not attempted | scope decision — only the two required workflows were built |

| Optional stage | Done | Evidence |
| ------------------------------- | -------- | -------- |
| Lesson 12 — loop engineering     | no | not attempted |
| Lesson 13 — security and guardrails | no | not attempted |
| Lesson 14 — packaging and deploy | no | not attempted |

## 4. Durable-behavior evidence

Some required behavior cannot be seen in a single trace. Point at the commit, test, or trace
that proves each — one line, or "not attempted".

| Check | Evidence |
| ------------------------------------------------------------- | -------- |
| Replaying a request creates no second ticket or access request | Code-level idempotency in `src/server/db.py` (`create_access_request`, `create_ticket`); proven by `src/agent/webex_replay_test.py`'s turn-5 replay — "confirmed idempotent: still exactly 1 row (AR001)" (commit `7ba29d7`) |
| A pending approval survives the process being killed and restarted | `AsyncSqliteSaver` checkpointer in `src/agent/graph.py`; proven by `webex_replay_test.py`'s "process-restart proof" — pause on one `graph` object, resume on a fresh graph+checkpointer, AR001 still reused (commit `7ba29d7`) |
| The write gate releases only against a recorded approval | `approval_gate` node in `src/agent/graph.py` + `db.approval_is_recorded`/`record_approval` (hardened commit `46d71ae`); `select_tools` (`src/agent/policy.py`) structurally cannot itself release a write. Proven by `webex_replay_test.py`'s 4-turn adversarial session: two prompt-injection baits ("go ahead and close it" in a forwarded thread; a "copied checklist" naming `create_access_request`) held off across turns 1–3, turn 4's genuine go-ahead released it |
| *Renewal (optional): every event replayed twice leaves one update and one notification per recipient* | not attempted |

## 5. Trace index

One row per item in `EVALUATION-INPUTS.yaml` — 27 required, 33 with both optional workflows.
**Fill in the trace id column only**; the ids and turn numbers are already correct. Leave a row
blank if you did not run it.


### Maya - HR and onboarding

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `M-I-01` | — | `31fd07ad90ace7d3e30f8f91daa92b4a` |
| `M-I-02` | — | `d2751dc17b02d7209d6f3a6d67276caa` |
| `M-I-03` | — | `c7925ebccb0e25a37da8c2c2135fa1e4` |
| `M-S-01` | 1 | `ad5b6247be54c7300ce60241a95631f6` |
| `M-S-01` | 2 | `b95cd7c6e2dbc7230f008be263e57f6f` |
| `M-S-01` | 3 | `7eb2f07c224eee0b48c72ab05482ab7a` |
| `M-S-01` | 4 | `e43b057ee98f085f9fc3a7eb3b1c255a` |
| `M-S-01` | 5 | `5e2b7f4f92ebe1aceaa3116a727f90aa` |
| `M-S-01` | 6 | `36bd647c9731bd831527143645394bef` |
| `M-S-01` | 7 | `153fea14ba2a453b037c53b86b16091c` |
| `M-S-01` | 8 | `784a9b5dfa6a70f4fb5a4ec1d0b9d066` |
| `M-S-01` | 9 | `530317f1837d871c20bbad914a952826` |
| `M-S-01` | 10 | `2d343bef922af04fdb81b78f6b89b42c` (paused → resumed, approved) |
| `M-S-01` | 11 | `fb9f9fb551b5953e696a73800a1f3c93` |
| `M-S-01` | 12 | `b9900b62b2d9a935f24898e8adfe3eec` |
| `M-S-02` | 1 | `b889bc4e2cf1c6297f69102e8c7c8572` |
| `M-S-02` | 2 | `eb14ee94dec9e2cc5f8f5b3e75ab2c71` |
| `M-S-02` | 3 | `cfee74ffd0673389024b8f09e2fe6324` |
| `M-S-02` | 4 | `886f9dbbb4980c1d4c6fd9af75f3b37f` |
| `M-S-02` | 5 | `0a7761245ddd71c4f65cee9c9b70e4a1` |

### Webex - IT operations

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `W-I-01` | — | `7a72d4ad659ec39ab093a33b508f629d` |
| `W-I-02` | — | `0b3bb73de0f88a574fef439d5d889077` |
| `W-I-03` | — | `f778cdc5474892c73345230d41b6cdbc` |
| `W-S-01` | 1 | `a1c86a7074c1b6f4357732da019c1249` |
| `W-S-01` | 2 | `56ce1626adc1567d2101394ecbc4c62c` |
| `W-S-01` | 3 | `1c0657b0535077d6970d80101fe1d513` |
| `W-S-01` | 4 | `e6827852d92da85dde0538c6225f623e` (paused → resumed, approved) |

### Vendor - CRM extraction  *(optional)*

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `V-I-01` | — | |
| `V-I-02` | — | |
| `V-I-03` | — | |

### Renewal - contract renewal  *(optional)*

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `R-I-01` | — | |
| `R-I-02` | — | |
| `R-I-03` | — | |

---

## 6. Anything I should know

Only the two required workflows and Lesson 11 (observability, required) were built by design —
Vendor, Renewal, Lesson 12, Lesson 13, and Lesson 14 were explicitly scoped out, not abandoned mid-attempt.
One deliberate architectural divergence from `GOLDEN-DATASETS.json`'s reference decomposition
is documented and reasoned about in `evals/golden.py` (`_ARCHITECTURE_OVERRIDES`): this project
is one graph with a `scope` field and a single `approval_gate` guarding the one write tool for
either scope, rather than Maya handing writes off to a separate graph — so `create_access_request`
firing on `M-S-01` turn 10, gated by the same interrupt-based approval, is the intended path, not
an accidental write. LLM-as-judge evaluators (`evals/register_judges.py`) are written but not
registered — that needs a Langfuse LLM Connection with my own model credentials, a cost/model
decision not made without asking first, and not required by the checklist below (deterministic
checks under `evals/` satisfy that item on their own).

