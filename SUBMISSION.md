# NovaOps final project — submission

Fill this in and commit it to your repository as `SUBMISSION.md`. It is the first thing read,
and it is how every trace gets found.

---

## 1. Repository

| | |
| ------------------- | ------------------------------------------------ |
| **Repository URL**  | `https://github.com/<you>/<repo>` |
| **Access**          | public / instructor added as collaborator *(delete one)* |
| **Commit reviewed** | `<full sha>` |

## 2. Langfuse

| | |
| ------------------ | --------------------------------------------- |
| **Host region**    | `cloud.langfuse.com` EU / US *(delete one)* |
| **Project name**   | |
| **Instructor role**| Member *(required — traces are read through the API)* |
| **Invitation accepted** | yes / no |

## 3. Scope completed

| Workflow | Built | Notes |
| --------------------------- | ------ | ----- |
| 1 — Maya · HR and onboarding | required | |
| 2 — Webex · IT operations    | required | |
| 3 — Vendor · CRM extraction  | optional, +5 | |
| 4 — Renewal · contract renewal | optional, +10 | |

| Optional stage | Done | Evidence |
| ------------------------------- | -------- | -------- |
| Lesson 12 — loop engineering     | yes / no | |
| Lesson 14 — packaging and deploy | optional, +5 | |

## 4. Durable-behavior evidence

Some required behavior cannot be seen in a single trace. Point at the commit, test, or trace
that proves each — one line, or "not attempted".

| Check | Evidence |
| ------------------------------------------------------------- | -------- |
| Replaying a request creates no second ticket or access request | |
| A pending approval survives the process being killed and restarted | |
| The write gate releases only against a recorded approval | |
| *Renewal (optional): every event replayed twice leaves one update and one notification per recipient* | |

## 5. Trace index

One row per item in `EVALUATION-INPUTS.yaml` — 27 required, 33 with both optional workflows.
**Fill in the trace id column only**; the ids and turn numbers are already correct. Leave a row
blank if you did not run it.


### Maya - HR and onboarding

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `M-I-01` | — | |
| `M-I-02` | — | |
| `M-I-03` | — | |
| `M-S-01` | 1 | |
| `M-S-01` | 2 | |
| `M-S-01` | 3 | |
| `M-S-01` | 4 | |
| `M-S-01` | 5 | |
| `M-S-01` | 6 | |
| `M-S-01` | 7 | |
| `M-S-01` | 8 | |
| `M-S-01` | 9 | |
| `M-S-01` | 10 | |
| `M-S-01` | 11 | |
| `M-S-01` | 12 | |
| `M-S-02` | 1 | |
| `M-S-02` | 2 | |
| `M-S-02` | 3 | |
| `M-S-02` | 4 | |
| `M-S-02` | 5 | |

### Webex - IT operations

| Item | Turn | Trace ID |
| ---- | ---- | -------- |
| `W-I-01` | — | |
| `W-I-02` | — | |
| `W-I-03` | — | |
| `W-S-01` | 1 | |
| `W-S-01` | 2 | |
| `W-S-01` | 3 | |
| `W-S-01` | 4 | |

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

Two or three sentences, optional. Known gaps, a deliberate deviation and why, something you
would do differently. Honesty here costs nothing and helps — a stated limitation reads better
than one discovered while marking.

