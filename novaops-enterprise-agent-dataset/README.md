# NovaOps enterprise dataset

The world your final project runs on: a 70-person B2B SaaS company that does not exist.
Everything here is synthetic and generated from one controlled world model — and
deliberately messy, because the traps are the point.

## What is here

| Folder | Contents | Used by |
| ------------- | ---------------------------------------------------------- | --------- |
| `documents/` | The corpus, 102 files across seven collections (below) | Workflows 1, 2, 4 |
| `database/` | `schema.sql`, `seed.sql`, `seed.json` — employees, contracts, subscriptions, tickets, access requests, approvals, assets, onboarding tasks, audit log | all workflows |
| `workflows/` | Material belonging to exactly one workflow each — see its own README | Workflows 3, 4 *(both optional)* |

`documents/` and `database/` are shared: every workflow reads them. `workflows/vendor/` and
`workflows/renewal/` are not — each belongs to one optional workflow, and neither is agent
work.

Your evaluation material is not in here — it is `../GOLDEN-DATASETS.json` (annotated, develop
against it) and `../EVALUATION-INPUTS.yaml` (the measured set, inputs only).

### `documents/` collections

Every document carries `audience` front matter, and that field is load-bearing: it is how
permission-aware retrieval is enforced.

| Collection | Files | `audience` | Notes |
| ------------------ | ----: | ---------- | ---------------------------------------- |
| `policies/` | 12 | all | HR and IT policy |
| `it_kb/` | 15 | all | IT knowledge base articles |
| `handbook/` | 15 | all | Careers, benefits, ways of working |
| `manager_playbook/` | 17 | **manager** | **Restricted.** Regular employees must never retrieve these |
| `employment/` | 17 | — | Offer letters, onboarding summaries, contractor addenda |
| `contracts/` | 20 | — | Vendor agreements with real seat limits and renewal dates |
| `internal_memos/` | 6 | — | Where a memo quietly overrides a standing policy |

## The messiness is deliberate

A Webex subscription runs 42 active seats against a 40-seat contractual limit. A memo has
changed an approval threshold that a policy still states. A contract's owner department
disagrees between the database and the document. Two employees share a first name. None of
it is accidental, and none of it is noise — each one is a trap a naive system walks into.

## Not shipped here

Generation inputs and provenance — raw third-party sources, the world model, build manifests
and maintenance scripts — are instructor-side and not part of your project. Neither are the
reference implementation's tool specifications: what your tools are called and how they
decompose is your design decision, not a form to fill in.
