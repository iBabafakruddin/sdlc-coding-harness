## SDLC agent harness

This project is delivered by a team of Claude sub-agents that follows an agile flow:
intake → grooming → sprint planning → development on per-feature branches → quality gate →
code/security review → merge → QA build → QA testing → bug fixes → sprint close.
Tickets are markdown files in `.sdlc/board/` (a local Jira).

**Read first:** `.sdlc/process/workflow.md` (process, single source of truth) ·
`.sdlc/project-profile.md` (this codebase: stack, commands, conventions — created by `/sdlc-init`) ·
`.sdlc/config.json` (team, branches, gates, approvals).

| Command | What it does |
|---|---|
| `/sdlc-init` | Onboard this codebase once: board, project profile, test/lint/build commands |
| `/sdlc-feature <request>` | Whole lifecycle for a feature (`until groomed` / `until merged` / `until qa` to stop early) |
| `/sdlc-sprint [SPRINT-xx]` | Plan a sprint from the READY backlog, or resume one |
| `/sdlc-status` | Standup, board and branch summary, decisions needed |

Agents: business-analyst · tech-lead · scrum-master · developer · code-reviewer · security-reviewer · devops-engineer · qa-engineer.

Rules:
- The main session orchestrates; role work is delegated to the matching agent.
- Tickets change only via `python .sdlc/tools/board.py`: `move` (status, validated + logged), `set` (fields), `section` (body text), `comment` / `resolve` / `verdict` (PR reviews). Sub-agents get the project root in every prompt.
- Branches and worktrees only via `python .sdlc/tools/git_flow.py`: every feature gets `feature/REQ-…`, every story `story/STORY-…` in its own worktree; the main checkout stays on the main branch. Nobody commits to the main branch directly (only the orchestrator's `chore:` commits of profile/config/ADRs). Never rebase; `git_flow.py sync` merges.
- Harness files (`.claude/agents`, `.claude/skills`, `.sdlc/tools`, `.sdlc/process`) change only when the human asks; upgrade them with the template's `install.py`.
- Blocked or loop limit hit → ask the human; never invent business rules.
