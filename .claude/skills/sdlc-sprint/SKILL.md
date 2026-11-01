---
name: sdlc-sprint
description: Orchestrator — plan and run a sprint from the existing READY backlog (planning, development and review loops, merge, QA build, QA/bug loop, close) without new requirement intake. Use when the user says "start next sprint", "run the sprint", or /sdlc-sprint, optionally with a sprint id to resume an ACTIVE sprint.
---

# /sdlc-sprint — run a sprint from the backlog

Argument: `$ARGUMENTS` (empty = plan a new sprint; `SPRINT-xx` = resume that sprint).

Same ground rules as the `sdlc-feature` skill (read `.claude/skills/sdlc-feature/SKILL.md`): you delegate every role step, verify on the board, respect `workflow.human_approval`, `max_review_cycles`, `max_qa_cycles`.

## Steps
1. Preflight: `python .sdlc/tools/board.py init`, `python .sdlc/tools/board.py validate`, clean `main`.
2. **New sprint** → Agent `scrum-master`: "Plan the next sprint from the READY backlog." Show the human the committed list and capacity; ask to confirm if `after_grooming` gate is on.
   **Resume** → `python .sdlc/tools/board.py list --sprint SPRINT-xx` and pick up each story from its current status:
   | Status | Next step |
   |---|---|
   | OPEN / ANALYSIS / IN_PROGRESS / REOPENED | developer |
   | IN_REVIEW | review loop from the gate |
   | CHANGES_REQUESTED | developer fix, then review loop |
   | BLOCKED | read the Activity note; resolve with the human or the tech-lead |
   | MERGED | merged into its feature branch; integrate the REQ when all its stories are MERGED, then QA build |
   | IN_QA | QA loop |
3. Run **Phase 4 → Phase 9** of `sdlc-feature` (feature branch per REQ via `git_flow.py feature-start`, one branch + worktree per story) for all stories in the sprint (waves by `depends_on`).
4. Final report in the same format, per REQ.
