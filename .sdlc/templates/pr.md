---
id: PR-000
title: <conventional title, e.g. feat(auth): login page [STORY-000]>
type: pr
kind: story
status: OPEN
story: STORY-000
req: none
branch: none
base: none
author: dev-1
review_cycle: 1
gate: pending
code_review: pending
security_review: not-required
merge_commit: none
---

# PR-000: <title>

## Summary
What this PR does, linked to acceptance criteria (AC-1 … AC-n).

## Changes
| File | Change |
|------|--------|

## How to test
Commands to run, test data, URLs.

## Developer test evidence
Unit test command + result summary (counts, coverage of changed files).

## Checklist (author)
- [ ] Acceptance criteria covered
- [ ] Unit tests added/updated and passing locally
- [ ] No debug statements, no commented-out code, no secrets
- [ ] Docs updated if behaviour changed

## Quality gate
_Written by `quality_gate.py --pr` (one line per cycle: verdict, sha, coverage, report link)._

## Review comments
| ID | Cycle | Reviewer | File:line | Severity | Comment | Status |
|----|-------|----------|-----------|----------|---------|--------|

Rows are added with `board.py comment` (ids: C code review, S security, G gate, Q QA) and updated with `board.py resolve`.
Severity: `blocker` (must fix), `major` (must fix), `minor` (should fix), `nit` (optional).
Status: `open`, `fixed` (author), `verified` (reviewer), `wont-fix` (needs reviewer agreement), `follow-up (<ticket>)`.
Before a PR to main is approved, no comment of that feature may be `open`.

## Review verdicts
_Written by `board.py verdict` (cycle, reviewer, verdict, reason)._

## Activity
