---
name: sprint-management
description: Scrum-master playbook for sprint planning (capacity, commitment, assignment, ordering), daily standup summaries, bug triage, board hygiene, sprint review, retrospective and velocity metrics on the local board. Use when planning, running or closing a sprint, or when asked for project status.
---

# Sprint management (Scrum Master)

Team and capacity come from `.sdlc/config.json → team`. Process from `.sdlc/process/workflow.md`.

## A. Sprint planning
1. Make sure no other sprint is ACTIVE: `python .sdlc/tools/board.py list --type SPRINT`.
2. Create the sprint:
   ```bash
   python .sdlc/tools/board.py new SPRINT "Sprint <n>" --set start=<next working day> end=<start + sprint_length_days working days - 1> --by scrum-master
   ```
   Start is today only if today is a working day (Mon–Fri) and planning happens before noon; otherwise the next working day.
3. Candidate stories: `python .sdlc/tools/board.py list --type STORY --status READY` (plus unfinished stories carried over).
4. **Order** by: priority (critical → low), then dependency order (a story never goes before what it `depends_on`), then smaller first when equal.
5. **Commit** stories top-down. A story fits only if **both** hold: total committed ≤ team capacity (Σ developer capacity × focus_factor) **and** some developer still has room for it (per-developer capacity × focus_factor). The per-developer rule wins: when stories don't pack (e.g. 5-pt stories into 8-pt developers) commit less, don't overload. Skip a story whose dependency is not MERGED/DONE and not in this sprint, or whose dependency belongs to another REQ that won't be integrated into main first (workflow §9).
   Going over is a human decision: report the options (drop X / overload dev-n by k pts) and record the answer in **Decisions / planning conflicts**.
6. **Assign**: match labels to developer `strengths`; balance load; keep dependent chains with the same developer when possible (less hand-off). A label no developer lists as a strength (e.g. `infra`) goes to the least-loaded developer — note it under Risks.
7. Apply per story:
   ```bash
   python .sdlc/tools/board.py set STORY-xxx sprint=SPRINT-01 assignee=dev-1 --by scrum-master
   python .sdlc/tools/board.py move STORY-xxx OPEN --by scrum-master --note "committed to SPRINT-01"
   ```
8. Check: `python .sdlc/tools/board.py capacity SPRINT-01` — no developer `OVER`.
9. Fill the sprint file with `board.py section SPRINT-01 "<Heading>" --file …`: goal, capacity table, committed stories table (with **Order**, which tells the orchestrator what can run in parallel: same order number = parallelisable), risks, decisions. Set the `capacity` field.
10. `python .sdlc/tools/board.py move SPRINT-01 ACTIVE --by scrum-master` (snapshots `committed` and `stories`); move linked REQs `GROOMED → IN_DELIVERY`.

## B. Daily standup
For each developer in the sprint: read tickets assigned to them and the last Activity lines. Append to the sprint file under **Daily standups**:
```
### <date>
| Dev | Yesterday | Today | Blockers |
|-----|-----------|-------|----------|
```
Flag: anything BLOCKED, any PR with `review_cycle` ≥ max − 1, stories untouched since the last standup, and points remaining vs days remaining (burndown).

## C. Bug triage
For each BUG in OPEN:
- Validate severity against the definitions in `.claude/agents/qa-engineer.md`; correct it with a note if wrong.
- Link `story` and `sprint`, assign (prefer the story's developer), then `move BUG-xxx TRIAGED`.
- `critical` bugs jump the queue — tell the orchestrator to schedule them first.
- Not a bug (works as specified) → `REJECTED` with the AC reference; if the spec is wrong, raise it to the BA as a new REQ.

## D. Board hygiene (every time you run)
```bash
python .sdlc/tools/board.py validate
python .sdlc/tools/board.py render
```

## E. Sprint review & close
1. Review table: committed vs dev-complete (MERGED) vs DONE per story, with links to PRs and QA results.
2. Stories not yet MERGED: carry over (`set sprint=SPRINT-<next>`; keep assignee and branch) or, if still OPEN, move back to READY with `set sprint=none assignee=none`. MERGED / IN_QA stories stay in this sprint (their QA happens with the feature). REOPENED stories carry over.
3. **Retrospective** in the sprint file — base it on evidence from the Activity logs:
   - Went well (e.g. first-pass PR approvals)
   - To improve (e.g. review cycles, reopened stories, gate failures, blocked time)
   - **Action items** — concrete, owned, and if it's a process change, propose the exact edit to `.sdlc/process/workflow.md`, a skill, or `.sdlc/config.json`.
4. `python .sdlc/tools/board.py metrics` → paste into Sprint review.
5. `python .sdlc/tools/board.py export` (the board is not in git; this zip is its backup).
6. `python .sdlc/tools/board.py move SPRINT-01 CLOSED --note "…"` (from IN_QA, or straight from ACTIVE when the sprint's features haven't reached QA yet — the note says why). Closing snapshots `dev_complete` and `completed`. REQs whose stories are all DONE → `DONE`.
