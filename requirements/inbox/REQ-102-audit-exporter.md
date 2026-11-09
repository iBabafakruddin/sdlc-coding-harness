---
id: REQ-102
title: Python Audit Log Exporter & Angular Admin Filter
priority: medium
source: local-folder
---

# Feature: Compliance Audit Exporter

## Acceptance Criteria
1. Build a Python service (`workers/audit_exporter.py`) that queries PostgreSQL audit records and exports paginated JSON/CSV summaries with `pytest` coverage.
2. Create an Angular standalone filter component (`AuditFilterComponent`) using Signals to filter by date range and actor.
