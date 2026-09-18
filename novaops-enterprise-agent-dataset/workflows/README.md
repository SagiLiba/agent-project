# Workflow-specific data

`documents/` and `database/` are shared — every workflow reads them. The two folders here are
different: each belongs to exactly one workflow, and both of those workflows are **optional**.

| Folder | Workflow | Shape |
| ---------- | ------------------------------ | ------------------------------------------ |
| `vendor/` | 3 — Vendor · CRM extraction | standalone, synchronous. One model call per source |
| `renewal/` | 4 — Renewal · contract renewal | standalone, asynchronous. Schedule-triggered, pauses, resumes |

Neither is agent work. Workflow 3 takes a document and returns a validated record; Workflow 4
is started by a clock, not a person. If your agent graph has to exist for either of them to
run, the boundary is in the wrong place.

The two are not the same kind of material, which is worth noticing before you build:

- **`vendor/sources/` are real inputs.** A procurement application genuinely receives an
  intake form, a forwarded thread, or call notes. Nothing is being stood in for.
- **`renewal/provider_replies/` are mocks.** They stand in for a live vendor mailbox behind a
  replaceable `ProviderEmailAdapter` port, and `internal_approval_events.jsonl` stands in for
  a Slack or email approval. Your tests always inject the mocks; a real adapter is optional.
