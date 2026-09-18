# Workflow 3 — Vendor CRM extraction

One raw model call per source, plus deterministic validation. No agent, no framework, no
tools. Standalone: it must run without your agent graph existing.

## What is here

- `sources/` — the same vendor described three ways, with progressively less of the required
  information present:

  | File | Missing required fields |
  | -------------------------------- | ---: |
  | `formal_vendor_intake.md` | 0 |
  | `procurement_email_chain.md` | 1 |
  | `discovery_call_transcript.md` | 2 |

- `schemas/vendor_extraction_result.schema.json` — the contract. It distinguishes **required**
  from **optional** fields, and that distinction is the whole exercise.

## The assertion is the counts

0 / 1 / 2 is what you test against; no separate rubric is needed. Every schema key appears in
the output with `null` where the source is silent — but only a missing **required** field
belongs in `missing_required_fields` and earns a follow-up question. An optional field that is
absent is not a gap.

All three sources contain irrelevant detail — marketing lines, scheduling, anecdotes. None of
it belongs in the record, and none of it should be inferred from a vendor's name or category.
