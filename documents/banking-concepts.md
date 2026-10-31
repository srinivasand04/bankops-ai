# Banking concepts used in BankOps AI

This page explains the operational-risk and IT-service-management concepts behind the platform. It is
an educational summary; individual banks define their own policies, thresholds and regulatory
obligations.

## Technology operational risk

Operational risk is the risk of loss from inadequate or failed processes, people and systems, or from
external events. Technology incidents are a major source: a failed payment platform causes customer
harm, financial loss, regulatory scrutiny and reputational damage. Operational resilience frameworks
expect banks to identify important business services, map their dependencies and stay within impact
tolerances during disruption.

## Incident vs problem

- **Incident**: an unplanned interruption or degradation of a service. Goal: restore service quickly.
- **Problem**: the underlying cause of one or more incidents. Goal: find and remove the root cause.
  BankOps AI's *repeated incidents* analytic and RCA/CAPA records are the bridge to problem management.

## Severity vs priority

- **Severity** measures impact (P1 Critical … P4 Low) and drives the SLA targets.
- **Priority** orders the work queue. BankOps AI derives it from severity and the application's
  business criticality (Tier 1 services are raised one level) unless set explicitly.

## SLA metrics

| Term | Meaning in BankOps AI |
|---|---|
| Response SLA | time from logging the incident to acknowledgement (first move out of OPEN) |
| Resolution SLA | time from logging to RESOLVED |
| MTTA | mean time to acknowledge |
| MTTR | mean time to resolve, from when business impact began (`started_at`) |
| SLA compliance | met ÷ (met + breached), pending items excluded |

Demonstration targets: P1 15 min / 60 min, P2 30 min / 4 h, P3 4 h / 24 h, P4 8 h / 72 h. These are
configurable (`SLA_TARGETS`) and are **not** universal banking requirements.

## Root cause analysis (RCA)

A structured RCA separates **confirmed facts** (verified evidence) from **hypotheses** (plausible
explanations still being tested), records supporting and missing evidence, contributing factors and
business impact. In BankOps AI only a human incident manager can promote a hypothesis to a confirmed
root cause — an AI suggestion is never treated as fact.

## CAPA

- **Corrective action**: fixes the immediate incident (e.g. roll back release 2.4.1).
- **Preventive action**: stops recurrence (e.g. add connection-pool load tests to the release gate).
Each is tracked with owner, team, due date and status; overdue actions are flagged.

## Change correlation

A large share of production incidents follow changes. Linking incidents to change records, and
measuring the gap between deployment and incident start, is a core change-risk signal. In regulated
banks, rolling back production requires change approval (often an emergency CAB) — so BankOps AI
recommends rollbacks but never performs them.

## Segregation of duties and human-in-the-loop

The person (or system) that proposes a consequential action should not be the one who approves it.
BankOps AI's AI agents may investigate, analyse and recommend; closing incidents, confirming root
causes, approving RCAs and any production change require an authorised human.

## Synthetic applications

| App | Criticality | Role |
|---|---|---|
| Payment Processing | Tier 1 | customer payments, REST API |
| Core Banking | Tier 1 | accounts, balances, ledger |
| Customer Services | Tier 2 | customer/account/transaction status APIs |
| Transaction Reconciliation | Tier 2 | batch matching of payments vs ledger |
| Reporting & Data Warehouse | Tier 3 | financial and regulatory reporting |
