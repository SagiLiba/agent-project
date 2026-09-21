# NovaOps final project — submission

Fill this in and commit it to your repository as `SUBMISSION.md`. It is the first thing read,
and it is how every trace gets found.

---

## 1. Repository

| | |
| ------------------- | ------------------------------------------------ |
| **Repository URL**  | `https://github.com/SagiLiba/agent-project` |
| **Access**          | public |
| **Commit reviewed** | `42662b0a46a398efc4c9a35a928fde780cdebb8e` |

## 2. Langfuse

| | |
| ------------------ | --------------------------------------------- |
| **Host region**    | `cloud.langfuse.com` (EU) |
| **Project name**   | `My Project` (organization: `liba's Organization`) |
| **Instructor role**| Member *(required — traces are read through the API)* |
| **Invitation accepted** | no — not yet sent, will be added before the deadline |

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
| `M-I-01` | — | `a924d3b6f6bb15fd1d40796286dfb73a` |
| `M-I-02` | — | `5bae1f6d5ae9b039081d29e662b3237b` |
| `M-I-03` | — | `deb58f2d2d0ddfc621debca63782bc91` |
| `M-S-01` | 1 | `010f8cf92558fff5ffee25cdeee3ce0e` |
| `M-S-01` | 2 | `51255b286aecc5f29800cfcf2956466e` |
| `M-S-01` | 3 | `53a80f5aa2ec6ac0941ccee7861a38b6` |
| `M-S-01` | 4 | `130d61c7d29cb1349da45c8264651d13` |
| `M-S-01` | 5 | `7b231edbce168b9561557d5b7579da82` |
| `M-S-01` | 6 | `81b7bbae983b7ec0c4d8676bdb7fbc3c` |
| `M-S-01` | 7 | `882266419b612f7c049b6416e2f5650a` |
| `M-S-01` | 8 | `d80cff891a5fb2f5e41a6253afc462d1` |
| `M-S-01` | 9 | `744d5e06ecac192560a3dee1f5638d25` |
| `M-S-01` | 10 | `e086871619e44256958ec0d191b0cd10` (paused → resumed, approved) |
| `M-S-01` | 11 | `55069f854296d043353adffa67ceaf98` |
| `M-S-01` | 12 | `0cd06b84ab3368dcdaf5645ab8618138` |
| `M-S-02` | 1 | `9d254c0b25ed87b45147558f14bd68ce` |
| `M-S-02` | 2 | `e8c28563852481a86694820746a2c6d5` |
| `M-S-02` | 3 | `1a48d0152c1153193f89faf635153838` |
| `M-S-02` | 4 | `4d52a9d081cfd1551051fe1705b2c50e` |
| `M-S-02` | 5 | `6840b97b11e735a7701bb1cc506fa468` |

### Webex - IT operations

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `W-I-01` | — | `3825baaecf0c68e854736b16711a722d` |
| `W-I-02` | — | `4406c115df6b2f9c76be5279522cac6f` |
| `W-I-03` | — | `675c497f1b1ed8f5ac8827b8b17262b4` |
| `W-S-01` | 1 | `405b06c71119b3e22ade26cc56888166` |
| `W-S-01` | 2 | `d8e3dd8f08c221225bddbe0b3187a153` |
| `W-S-01` | 3 | `9e45e8ad46c06c70ab772e3af93dee75` |
| `W-S-01` | 4 | `dbdd5d80afe5673eef68dd66d7a19531` (paused → resumed, approved) |

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
Vendor, Renewal, Lesson 12 and Lesson 14 were explicitly scoped out, not abandoned mid-attempt.
One deliberate architectural divergence from `GOLDEN-DATASETS.json`'s reference decomposition
is documented and reasoned about in `evals/golden.py` (`_ARCHITECTURE_OVERRIDES`): this project
is one graph with a `scope` field and a single `approval_gate` guarding the one write tool for
either scope, rather than Maya handing writes off to a separate graph — so `create_access_request`
firing on `M-S-01` turn 10, gated by the same interrupt-based approval, is the intended path, not
an accidental write. LLM-as-judge evaluators (`evals/register_judges.py`) are written but not
registered — that needs a Langfuse LLM Connection with my own model credentials, a cost/model
decision not made without asking first, and not required by the checklist below (deterministic
checks under `evals/` satisfy that item on their own).

