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
