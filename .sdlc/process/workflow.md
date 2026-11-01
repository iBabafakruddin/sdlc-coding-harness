# SDLC Workflow — Single Source of Truth

This file defines how the agent team works. Every agent and skill follows it.
If anything here conflicts with an agent or skill file, **this file wins**.

## 1. The team (who does what)

| Role (human equivalent) | Agent | Primary skill | Owns |
|---|---|---|---|
| Business Development / Product Owner | `business-analyst` | `requirement-intake` | `.sdlc/board/requirements/REQ-*` |
| Tech Lead / Architect | `tech-lead` | `story-grooming` | `.sdlc/board/stories/STORY-*` (draft → READY), ADRs |
| Scrum Master | `scrum-master` | `sprint-management` | `.sdlc/board/sprints/SPRINT-*`, standups, retros, `.sdlc/board/BOARD.md` |
| Developer (1..n) | `developer` | `story-development` | code on `feature/*` / `bugfix/*` branches, `.sdlc/board/prs/PR-*` |
| Code Reviewer (peer dev) | `code-reviewer` | `pr-review` | review comments inside `PR-*` |
| Security Reviewer (AppSec) | `security-reviewer` | `appsec-review` | security findings inside `PR-*` |
| DevOps / Build & Release | `devops-engineer` | `ci-quality-gates` | quality gate reports, merges to `main`, QA builds |
| QA Engineer | `qa-engineer` | `qa-testing` | test plans, `.sdlc/board/bugs/BUG-*`, QA sign-off |

The **orchestrator** is the main Claude session running the `/sdlc-feature` or
`/sdlc-sprint` skill. Sub-agents cannot spawn other sub-agents, so only the
orchestrator delegates. Agents talk to each other **through the board files**,
never by assuming what another agent did.

## 2. Lifecycle (end to end)

```
 Idea ──► [BA] REQ (NEW → REFINED)
          │
          ▼
       [TL] Grooming ──► STORY (DRAFT → READY)  + points, deps, test notes, APIs, risks
          │                REQ → GROOMED
          ▼
  (human approval gate: after_grooming)
          │
          ▼
       [SM] Sprint planning ──► SPRINT (PLANNED → ACTIVE), stories READY → OPEN, assigned
          │
          ▼
       [DEVOPS/orchestrator] feature branch feature/REQ-xxx from main (own worktree)
          │
          ▼
       [DEV ×n, parallel] OPEN → ANALYSIS → IN_PROGRESS: story/STORY-xxx branch off the feature
          │      branch, in the developer's own worktree; code + unit tests; commit
          │      → PR-* (story branch → feature branch) → story IN_REVIEW
          ▼
       [DEVOPS] quality gates (lint, unit tests, coverage, build, static checks)
       [REVIEWER] code review      [SECURITY] if story has security tag
          │   └─ comments ► PR CHANGES_REQUESTED, story CHANGES_REQUESTED ► DEV fixes ► loop
          ▼
       PR APPROVED (all gates green + reviewer approved + security approved if needed)
          │
          ▼
       [DEVOPS] merge story branch → feature branch ► PR MERGED, story MERGED, story worktree removed
          │
          ▼  (all stories of the REQ MERGED)
       [DEVOPS] feature PR feature/REQ-xxx → main: sync main in, gate, integration review
  (human approval gate: before_merge_to_main)
          ▼
       [DEVOPS] merge feature → main ► REQ integrated
          │
          ▼  (sprint features integrated)
       [DEVOPS] build QA branch qa/SPRINT-xx from main ► QA-xx (BUILDING → IN_TEST)
          │
  (human approval gate: before_qa_release)
          ▼
       [QA] integration / acceptance tests ► stories IN_QA → DONE
          │   └─ failures ► BUG-* (OPEN) ► SM triage ► DEV fixes (bugfix branch → PR → same review loop)
          │                 ► QA retest ► BUG CLOSED
          ▼
       [SM] Sprint review + retrospective ► SPRINT CLOSED, REQ DONE, metrics
```

## 3. Status state machines

Enforced by `python .sdlc/tools/board.py move <ID> <STATUS>`. Never hand-edit `status:`.

**REQ**: `NEW → REFINED → GROOMED → IN_DELIVERY → DONE`; any → `ON_HOLD | REJECTED`

**STORY**:
```
DRAFT → READY → OPEN → ANALYSIS → IN_PROGRESS → IN_REVIEW → MERGED → IN_QA → DONE
                                      ▲              │                  │
                                      └─ CHANGES_REQUESTED ◄┘           │
                          ANALYSIS ◄──────────── REOPENED ◄─────────────┘
any active state ⇄ BLOCKED
```

**BUG**: `OPEN → TRIAGED → IN_PROGRESS → IN_REVIEW → MERGED → RETEST → CLOSED`;
`IN_REVIEW → CHANGES_REQUESTED → IN_PROGRESS`; `RETEST → REOPENED → IN_PROGRESS`; `OPEN|TRIAGED → REJECTED`

**PR**: `OPEN → CHANGES_REQUESTED → OPEN` (after fixes), `OPEN → APPROVED → MERGED`; any → `CLOSED`.
`CHANGES_REQUESTED → OPEN` starts the next review cycle: `board.py` bumps `review_cycle` and resets `gate`,
`code_review` (and `security_review` unless `not-required`) to `pending`.

**SPRINT**: `PLANNED → ACTIVE → IN_QA → CLOSED`; `ACTIVE → CLOSED` when the sprint ends before its features
reach QA (needs `--note`). Before closing, every story that is not yet MERGED is carried over
(`set sprint=<next>`) or moved back to `READY` (only from OPEN). MERGED stories stay in the sprint.
`ACTIVE` snapshots `committed`; `CLOSED` snapshots `dev_complete` and `completed`, so carry-overs never rewrite history.

**QA (release build)**: `BUILDING → IN_TEST → PASSED | FAILED`; `FAILED → BUILDING`

**Who moves what** (reviewers never move statuses; they only record verdicts):

| Move | By |
|---|---|
| STORY `OPEN → ANALYSIS → IN_PROGRESS → IN_REVIEW`, PR `CHANGES_REQUESTED → OPEN`, STORY `CHANGES_REQUESTED → IN_PROGRESS` | developer |
| PR + STORY `→ CHANGES_REQUESTED` after gate/reviews of a cycle are in | orchestrator (devops on gate failure or merge conflict) |
| PR `→ APPROVED → MERGED`, STORY/BUG `→ MERGED` | devops-engineer (merge job) |
| `code_review` / `security_review` fields | `board.py verdict` by the reviewer |

## 3a. Editing tickets

- Frontmatter: `board.py set`. Status: `board.py move`. Never hand-edit either.
- Body sections (Developer analysis, Implementation notes, Quality gate, QA results, …):
  `board.py section <ID> "<Heading>" --text "…"` or `--file <path>` (`--append` to add). Prefer this over
  editing the markdown; if you must use Edit, Read the file first and keep frontmatter and `## Activity` intact.
- Review comments: `board.py comment PR-x --by <role> --sev <blocker|major|minor|nit> --loc <file:line|general> --text "…"`
  (ids are automatic: `C` code review, `S` security, `G` gate, `Q` QA). A comment may point at any repo file,
  also one outside the diff (e.g. an ADR to amend). Status changes: `board.py resolve PR-x C3 fixed|verified|wont-fix|follow-up [--ticket STORY-y]`.
- Verdicts: `board.py verdict PR-x approved|changes-requested --by <reviewer> --note "…"`.
- All board writes take a lock, so parallel agents can't overwrite each other.
- The board lives only in the **main checkout** (`<project>/.sdlc/board/`): ticket files are not in worktrees.
  The tools work from any worktree (they find the main checkout); open ticket files by their absolute path in the main checkout.
- Every agent works on the **project root** it was given. The tools refuse to run on the harness template, and
  `SDLC_ROOT=<project>` makes them refuse any other project.

## 4. Definition of Ready (story may move DRAFT → READY)

Every item is checked by `board.py move … READY` (template placeholders don't count as filled):

- [ ] User story in "As a / I want / So that" form, linked to a REQ
- [ ] Acceptance criteria in Given/When/Then, each one testable: `- AC-1: Given …` or `- AC-1 (FR-2): Given …`
- [ ] Story points set (Fibonacci: 1, 2, 3, 5, 8). 13+ is refused: split it. **8 needs a reason not to split** in Estimate rationale
- [ ] Technical breakdown: at least one row with area + change (frontend, backend, DB, config, infra)
- [ ] Dependencies (`depends_on`) and external blockers listed (`none` is an answer)
- [ ] API contract: the contract, or `None`
- [ ] Test approach: unit tests to add + QA scenarios (`TC-STORY-x-n`)
- [ ] Security / NFR notes. A story that mentions auth, login, password, token, session, cookie, secret, PII,
      roles/permissions or encryption needs label `security` (or `no-security` when TL confirms it isn't security relevant)
- [ ] Estimate rationale

A REQ may move to `GROOMED` only when `stories:` lists its stories, each with `req:` pointing back and none still DRAFT.

## 5. Definition of Done (story may move IN_QA → DONE)

- [ ] All acceptance criteria verified by QA with evidence
- [ ] Unit tests added; the quality gate's **total line coverage** of the workspace ≥ `quality_gates.coverage_min`
- [ ] Quality gate report green on the final PR revision
- [ ] PR approved by `code-reviewer` (and `security-reviewer` when tagged)
- [ ] Merged to `main` with no open review comments. Story PRs may merge into the feature branch with
      `minor`/`nit` comments open; before the **feature PR (or bugfix PR) to main** is approved, each of them is
      `fixed`/`verified`, `wont-fix` (reviewer agreed) or `follow-up` with a ticket (enforced by `board.py`)
- [ ] No open BUG with severity `critical` or `major` linked to the story
- [ ] Docs / README / API docs updated where behaviour changed

**Velocity**: *dev-complete* = points of sprint stories that reached MERGED (or later); *done* = points that reached
DONE after QA. A REQ spanning several sprints shows dev-complete progress every sprint and done points once QA signs off.
`board.py metrics` reports both.

## 6. Conventions

- **IDs**: `REQ-001`, `STORY-001`, `BUG-001`, `PR-001`, `SPRINT-01`, `QA-01`. Get the next id with `python .sdlc/tools/board.py next-id STORY`.
- **Files**: `.sdlc/board/<type>/<ID>-<kebab-slug>.md`, created from `.sdlc/templates/`.
- **Branches & worktrees**: see §9. Created only by `python .sdlc/tools/git_flow.py`.
- **Commits**: Conventional Commits with the ticket: `feat(auth): add login form validation [STORY-001]`.
- **Code location**: product code lives in `project.workspace` (default `.` = repo root). Stack, conventions and commands: `.sdlc/project-profile.md`.
- **Activity log**: every status change appends a line to the ticket's `## Activity` section (done automatically by `board.py move`). Agents add a one-line `--note` saying *what* and *why*.
- **Traceability**: REQ → STORY (`req:`) → branch/commits (`[STORY-x]`) → PR (`story:`) → QA test cases (`TC-STORY-x-n`) → BUG (`story:`).
  Related requirements: REQ `related: [REQ-002, …]`.
- **Vocabulary**: we never rebase. "Update your branch" means `git_flow.py sync <ID>` (a merge).
- **Static-check conventions** (plan them in the first stories): log through a logger module, not `console.log`/`print`
  (debug statements fail the gate); test credentials come from fixture helpers (literals in tests are a `minor`
  finding, real-looking keys anywhere are a `blocker`). A line that must stay (e.g. a CLI banner) may carry the
  inline comment `sdlc:allow`; the gate records the waiver and the reviewer must agree with it.
- **Shell**: write multi-line files with the Write tool, not heredocs (they break on Windows / Git Bash). Quote list values: `labels=[backend,security]` (no spaces).

## 7. Loop limits and escalation

- Review loop: if a PR reaches `workflow.max_review_cycles` cycles of CHANGES_REQUESTED, stop and escalate to the human with a summary.
- QA loop: if a story is REOPENED more than `workflow.max_qa_cycles` times, escalate.
- Any agent that is blocked (missing info, missing API, failing environment) moves the ticket to `BLOCKED` with a note that states exactly what is needed, and reports it back. Agents never invent business rules — they ask (via the orchestrator).
- **Acceptance criteria are a contract.** A developer who thinks an AC is wrong or wants to implement it
  differently stops before coding that part and reports it (story `BLOCKED` with the question); the tech lead
  amends the AC (`board.py section`) or confirms it. No silent deviations.

## 8. Human approval gates

Configured in `.sdlc/config.json → workflow.human_approval`. When a gate is `true`,
the orchestrator stops and asks the human before continuing past that point.
`after_grooming` (scope & estimates), `before_merge_to_main` (feature/bugfix into main), `before_qa_release` (QA build).

## 9. Branching model

`git.strategy: "feature"` (default):

```
main ─────●──────────────────────────────────●────────► qa/SPRINT-01 (QA build)
          │                                  ▲  feature PR (--no-ff)
          └─► feature/REQ-001-login-page ─●──●──●
                   │                      ▲     ▲
                   ├─► story/STORY-001 ───┘     │   dev-1 · worktree ../<repo>-worktrees/STORY-001
                   └─► story/STORY-002 ─────────┘   dev-2 · worktree ../<repo>-worktrees/STORY-002

QA bugs:  main ─► bugfix/BUG-001-… ─► PR ─► main ─► qa/SPRINT-01 fast-forwarded
```

| Work | Branch | From | PR into | Worktree |
|---|---|---|---|---|
| Requirement / feature | `feature/REQ-xxx-slug` | main | main (feature PR, after all stories) | `<worktree_root>/REQ-xxx` |
| Story | `story/STORY-xxx-slug` | its REQ's feature branch | feature branch | `<worktree_root>/STORY-xxx` |
| QA bug | `bugfix/BUG-xxx-slug` | main | main | `<worktree_root>/BUG-xxx` |
| QA build | `qa/SPRINT-xx` | main (fast-forwarded on rebuild) | — | `<worktree_root>/qa-SPRINT-xx` |
| QA automation | `qa-tests/SPRINT-xx` | main | main | `<worktree_root>/qa-tests-SPRINT-xx` |

`git.strategy: "story"`: no feature branches; stories use `feature/STORY-xxx-slug` from main and PR straight into main.

Rules:
- The **main checkout always stays on the main branch**. Nobody checks out other branches there or commits there directly; it's used for the board, merges into main, and reading.
  **One exception**: the orchestrator may commit harness/onboarding files on main with a `chore:` commit
  (`.sdlc/project-profile.md`, `.sdlc/config.json`, ADRs under `docs/adr/`, `.gitattributes`, `.gitignore`),
  because worktrees are cut from main and must see them. Never product code.
- Each developer works **only in its ticket's worktree**, so parallel developers never share files. `git_flow.py start` creates/resumes it; `finish` removes it after merge.
- Developers bring in teammates' merged work with `git_flow.py sync <ID>` (merges the base into their branch). No rebases of shared branches, no force pushes.
- Only the devops-engineer merges (`git_flow.py merge PR-xxx`, always `--no-ff`).
- `.sdlc/board/` is **intentionally git-ignored** (like Jira, it lives outside the code): ticket edits never
  conflict across branches and all worktrees share the main checkout's board. It has no git history, so back
  it up with `python .sdlc/tools/board.py export [--to <folder>]` (zip; the scrum master does it at sprint close).
- `git.push_branches: true` pushes every branch to `git.remote`; `workflow.pr_mode: "github"` mirrors PRs with `gh`.

**Cross-REQ dependencies.** A story branch sees only its own feature branch, which was cut from main. So a
story that `depends_on` a story of *another* REQ can start only when that REQ is integrated into main **and** its
own feature branch is synced (`git_flow.py sync REQ-x`). `git_flow.py start` refuses otherwise, `feature-start`
warns, and `board.py validate` lists them. When grooming several related REQs:
- put shared groundwork (scaffold, data layer, auth foundation) in its own **foundation REQ** (or in the first REQ),
- plan and integrate that REQ first (its feature PR to main can go before the other REQs' stories start),
- or, if the work is small, groom the dependent stories under the same REQ.

## 10. Greenfield bootstrap

1. `/sdlc-init` on an empty repo records the *intended* stack and commands in `.sdlc/project-profile.md`
   marked "not run (greenfield)"; `project.commands` stays empty.
2. The first story is a scaffold (label `infra`, owned by a developer like any story).
3. When the scaffold's REQ is integrated into main, the orchestrator has the **tech-lead re-run onboarding**:
   run each command once, fill `project.commands` (lockfile-respecting install, e.g. `npm ci`), update the
   profile, commit both on main (`chore:` exception above), then `git_flow.py sync` every open feature branch.
   Until then the gate auto-detects commands from `package.json` / `pyproject.toml`.
