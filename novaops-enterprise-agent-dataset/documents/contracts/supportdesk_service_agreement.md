# SupportDesk Support Agreement

vendor_name: SupportDesk
system_name: SupportDesk
contract_type: Support agreement
contract_start_date: 2025-09-30
contract_end_date: 2026-09-29
renewal_type: auto-renewal
renewal_notice_days: 30
seat_limit: 35
current_seats_reference: database.software_subscriptions.active_seats = 31
annual_cost: 13200
owner_department: Customer Success
support_sla: Standard support next business day
data_sensitivity: Confidential
approval_required_for_expansion: CS manager approval for agent seats
termination_terms: Cancel or renew according to notice period; stricter order-form term wins.
liability_cap: 12 months fees unless stated otherwise
security_review_required: no
risky_clause: Agent seats shared between CS and IT; owner in DB is IT by mistake.
operational_notes: Agent seats shared between CS and IT; owner in DB is IT by mistake.
near_renewal_as_of_2026_07_02: yes

## Operational Summary

This synthetic contract governs NovaOps use of SupportDesk. Contract limits override general policy. Expansion requests must include business justification, current seat usage, owner approval, and any required IT or Finance approval.

## Support SLA

Standard support next business day.

## Renewal Notes

Renewal is `auto-renewal` with 30 days notice. Risk note: Agent seats shared between CS and IT; owner in DB is IT by mistake.

## Known Database Mismatch

The database owner field is intentionally stale. Use this contract and `contract_owner_cleanup_memo.md` as source of truth.

