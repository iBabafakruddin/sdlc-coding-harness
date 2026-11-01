---
name: sdlc-feature
description: Orchestrator — run a feature request through the whole agent team end to end — requirement intake, grooming, sprint planning, a feature branch per requirement with one branch + worktree per story, quality gates, code and security review loops, story merges into the feature branch, feature integration into main, QA build, QA testing, bug-fix loop and sprint close. Use when the user asks for a new feature ("I need a login page") or types /sdlc-feature <request>. Optional stop point - add "until groomed", "until merged" or "until qa".
---

# /sdlc-feature — end-to-end delivery orchestrator

You (the main session) are the **delivery manager**. You do not do role work yourself — you delegate every role step to its sub-agent with the `Agent` tool, check the board between steps, enforce loops and limits, and talk to the human. Sub-agents cannot spawn sub-agents, so all delegation happens here.

Request: `$ARGUMENTS`

## Ground rules
- Process: `.sdlc/process/workflow.md`. Config: `.sdlc/config.json` (read it now). Codebase: `.sdlc/project-profile.md`.
- Source of truth = the board. After every agent returns, verify with `python .sdlc/tools/board.py show <ID>` / `list`, and branches with `python .sdlc/tools/git_flow.py status` — trust these, not the agent's summary.
- Delegation prompts are short: **project root** (absolute path — sub-agents start in your cwd, which may not be the project), ticket id(s), role id (e.g. `dev-1`), cycle number when relevant, and "Follow your skill. Use `--by <role>` on every board command." The agent files carry the rest (board location, parallel boundaries, gate conventions). If your own cwd is not the project, `cd` there first.
- Status moves after reviews are **yours** (reviewers only record verdicts): see Phase 5 step 2.
- One short progress line to the human per phase ("Grooming done: 4 stories, 14 pts").
- An agent reports BLOCKED or a question → ask the human (`AskUserQuestion` or plain text), then re-run the agent with the answer. Never invent the answer.
- Stop point: `until groomed|merged|qa` in the request → stop after that phase and report.

## Phase 0 — Preflight
```bash
python .sdlc/tools/board.py init
git status --short
python .sdlc/tools/git_flow.py status
```
- No `.sdlc/project-profile.md` → run `/sdlc-init` steps first (tech-lead onboarding).
- The main checkout must be on `git.main_branch`, and harness files must be committed there (worktrees are created from it). Uncommitted product changes in the main checkout → ask the human before continuing.
- Profile, config, ADRs, `.gitattributes` changes go to main as a `chore:` commit by you (the only allowed direct commit on main, workflow §9).

## Phase 1 — Requirement (business-analyst)
"New client request: <verbatim request>. Create and refine the REQ."
Blocking questions → ask the human, send the answers back. Done when the REQ is `REFINED`; show scope + assumptions in ≤ 8 lines.

## Phase 2 — Grooming (tech-lead)
"Groom REQ-xxx into READY stories."
Verify `python .sdlc/tools/board.py validate` passes and the REQ is `GROOMED`.
Several REQs at once: check the grooming put shared groundwork in a foundation REQ (or the first REQ) and that `validate` shows no cross-REQ dependency problem you can't schedule — the dependent REQ's stories can start only after the foundation REQ is integrated into main (workflow §9). Plan the order with the human.
**Gate `after_grooming`**: show `story | pts | depends_on | labels`, total points, risks; ask approve / change.

## Phase 3 — Sprint planning (scrum-master)
Active sprint exists → ask: add to it or plan a new one.
"Plan a sprint with the READY stories of REQ-xxx" (or "add … to SPRINT-xx"). Verify `capacity` shows no OVER; tell the human what didn't fit.

## Phase 4 — Feature branch
`git.strategy` is `feature` (default):
```bash
python .sdlc/tools/git_flow.py feature-start REQ-xxx
```
→ `feature/REQ-xxx-<slug>` from main, in its own worktree. (Strategy `story`: skip; stories branch from main.)

## Phase 5 — Development waves
Waves from `depends_on`: wave 1 = stories with no unmet deps; wave n+1 = stories whose deps are MERGED into the feature branch.

For each wave:
1. **Develop** — Agent `developer`, prompt "`STORY-xxx as <assignee>`". The developer creates its own branch + worktree with `git_flow.py start`, so developers never share files:
   - `workflow.parallel_developers: true` → launch all stories of the wave in **one message** (parallel agents). Don't use the Agent tool's own worktree isolation — `git_flow.py` already gives each story its worktree.
   - otherwise one at a time.
2. **Review loop** per PR (cycle = `review_cycle`):
   a. Agent `devops-engineer`: "gate PR-xxx". Failed → devops moves PR + story to CHANGES_REQUESTED → d.
   b. Agent `code-reviewer`: "review PR-xxx cycle n".
   c. `security_review` is not `not-required` → Agent `security-reviewer`: "review PR-xxx cycle n". It may run in parallel with b (board writes are locked; ids `C`/`S` don't collide).
   d. **You** read `board.py show PR-xxx`: any verdict `changes-requested` →
      `board.py move PR-xxx CHANGES_REQUESTED --by orchestrator --note "<counts>"` and the same for the story; then Agent `developer`: "fix review comments on PR-xxx for STORY-xxx as <dev>", back to a.
   e. Gate passed and all verdicts approved → Agent `devops-engineer`: "merge PR-xxx" (moves APPROVED, merges story branch → feature branch, post-merge tests, finishes the story branch).
   f. `review_cycle` > `workflow.max_review_cycles` → stop that story; summarise open comments; ask the human (accept / guide / de-scope).
3. Merge conflicts → developer runs `git_flow.py sync` and resolves, back to 2a.
4. **Greenfield**: when the scaffold story is merged and its REQ integrated, Agent `tech-lead`: "re-run codebase onboarding (workflow §10)"; commit profile + config on main (`chore:`), then devops syncs open feature branches.

## Phase 6 — Integrate the feature into main
When every story of the REQ is MERGED into the feature branch: first clear open `minor`/`nit` comments on its story PRs (developer fixes them in a short follow-up story/bugfix, or they are resolved `wont-fix` with the reviewer, or `follow-up` with a ticket) — the board refuses the feature PR otherwise. Then Agent `devops-engineer`: "integrate REQ-xxx" (sync main into the feature branch, feature PR, gate). Then Agent `code-reviewer`: "integration review of PR-yyy" (+ `security-reviewer` if required). Fix loop as in Phase 5 if needed (sync conflicts → a developer resolves them in the feature worktree).
**Gate `before_merge_to_main`**: ask the human. Then Agent `devops-engineer`: "merge PR-yyy" → REQ `integrated: yes`.
If some stories of the REQ are in a later sprint, the feature branch waits; tell the human.
After merging: Agent `devops-engineer`: "sync REQ-yyy" for every open REQ whose stories depend on this one, so they can start.

Stop point `until merged` ends here.

## Phase 7 — QA build
When the sprint's features are integrated: **Gate `before_qa_release`** → ask. Agent `devops-engineer`: "qa-build SPRINT-xx". Verify QA ticket `IN_TEST`.

## Phase 8 — QA and bug-fix loop
1. Agent `qa-engineer`: "Test QA-xx." (A `qa-tests/*` PR goes through gate + light review + merge to main.)
2. Bugs → Agent `scrum-master`: "Triage open bugs for SPRINT-xx."
3. Each TRIAGED bug (critical first, parallel when independent): Agent `developer`: "`BUG-xxx as <assignee>`" (`bugfix/` branch from main) → Phase 5 review loop → merge into main.
4. Agent `devops-engineer`: "rebuild QA for SPRINT-xx; move fixed bugs to RETEST."
5. Agent `qa-engineer`: "Retest bugs in RETEST and re-verify reopened stories on QA-xx."
6. Repeat until QA `PASSED`, or a story exceeds `workflow.max_qa_cycles` → ask the human.

## Phase 9 — Close (scrum-master)
"Close SPRINT-xx: sprint review, retrospective, metrics, board export." (Sprint has other unfinished work → "review + retro for REQ-xxx" only. A sprint whose features did not reach QA closes from ACTIVE with a note; its MERGED stories count as dev-complete.) Afterwards `python .sdlc/tools/git_flow.py status` should show no leftover branches for this REQ; ask devops to `finish` any that remain.

## Final report
```
Feature: <REQ id> <title> — <DONE | stopped at phase n>
Branches: feature <branch> → main @ <sha>; stories <branch → PR → status>
Quality: review cycles avg <n>, gate failures <n>, bugs <by severity>
QA build <id> <PASSED/FAILED>
Retro action items: <list>
Needs your decision: <list or none>
```
Point the user to `.sdlc/board/BOARD.md`.
