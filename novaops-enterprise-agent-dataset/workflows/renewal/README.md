# Workflow 4 — event-driven contract renewal

Nobody chats with this one. A schedule starts it, it stops to wait for a human, an inbound
event restarts it, and it must survive the process dying in between. Standalone: it shares
`documents/` and `database/` with the agent and nothing else.

## What is here

These are **mocks behind two replaceable ports**, not business data. The business facts live
in `database/` (contract `C001`, subscription `SUB001`, the blocked access request) and in
`documents/contracts/webex_vendor_agreement.md`.

- `internal_approval_events.jsonl` — an approve and a reject decision, each with an
  `event_id` that is its idempotency key. Consumed through a `NotificationAdapter` port.
- `provider_replies/*.eml` — four vendor replies: **approved**, **conditional**, **rejected**,
  **ambiguous**. Consumed through a `ProviderEmailAdapter` port.
- `provider_reply_manifest.json` — stable fixture ids and demo selection weights. Selection
  may be random for a demo, but must accept an explicit id or seed so tests are deterministic.
- `provider_renewal_decision.schema.json` — the extraction contract for a reply.

## The one that catches people

`webex_renewal_conditional.eml` carries a price, a seat count and dates — everything an eager
extractor wants — and a sentence saying it is **not final approval**. Applying it is the
failure this workflow is built to expose.

The provider email is untrusted external text whose extracted contents gate a database write.
Extract it as a *proposal*, then let deterministic code decide: only a complete, approved
reply that matches the pending run may mutate anything. Conditional, rejected, ambiguous and
mismatched replies all return to a human with no write.
