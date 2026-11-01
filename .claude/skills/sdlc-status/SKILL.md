---
name: sdlc-status
description: Show delivery status — run the scrum-master's daily standup over the board, refresh .sdlc/board/BOARD.md, and summarise progress, blockers, open PRs/bugs and what needs a human decision. Use for "status", "standup", "where are we", "what's blocked", or /sdlc-status.
---

# /sdlc-status — standup & board

1. Refresh and check the board yourself:
   ```bash
   python .sdlc/tools/board.py render
   python .sdlc/tools/board.py validate
   python .sdlc/tools/board.py list --type SPRINT
   python .sdlc/tools/git_flow.py status
   ```
2. If a sprint is ACTIVE or IN_QA → Agent `scrum-master`: "Daily standup for SPRINT-xx." Otherwise summarise the backlog yourself (`list --type STORY --status READY,DRAFT`, `list --type REQ`).
3. Reply to the human in ≤ 15 lines:
   - Sprint, days left, points done / committed
   - Per status: counts and ids
   - Blocked items with the exact blocker
   - Open PRs (branch → base, cycle, waiting on whom) and open bugs by severity
   - Branches: feature branches and their stories, anything far behind its base or stale
   - Decisions needed from the human
   - Link: `.sdlc/board/BOARD.md`
