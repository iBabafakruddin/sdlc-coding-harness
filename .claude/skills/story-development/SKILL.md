---
name: story-development
description: Developer playbook for working one story or bug on its own git branch and worktree — analysis, branch/worktree creation via git_flow, implementation, unit tests, local verification, conventional commits, raising a PR against the feature branch, syncing with the base, and fixing review comments or QA bugs. Use whenever a developer picks up an OPEN/REOPENED story, a TRIAGED bug, or a PR with CHANGES_REQUESTED.
---

# Story development (Developer)

You are `<dev-id>` working `<ID>` (STORY or BUG). Every board command gets `--by <dev-id>`.
Read `.sdlc/project-profile.md` first: it has the stack, conventions and the exact lint/test/build commands.
Run board/git_flow commands from the **project root** the orchestrator gave you. Ticket files live only in `<project root>/.sdlc/board/` — not in your worktree; read them there (absolute path) or with `board.py show`, and write them only with board.py.
Write files with the Write tool, not shell heredocs (they mangle quotes and backslashes on Windows / Git Bash).

## Branch model (why you never touch the main checkout)
- Each **feature** (REQ) has an integration branch `feature/REQ-xxx-…` created from the main branch.
- Each **story** you work on gets its own branch `story/STORY-xxx-…` created from that feature branch, checked out in **its own worktree folder**. QA bugs get `bugfix/BUG-xxx-…` from the main branch.
- Your PR goes **story branch → feature branch**. The devops engineer later merges the finished feature into main.
- The main checkout stays on the main branch and is shared by everyone: don't `git checkout` other branches there and don't edit code there.

## 0. Pick up
```bash
python .sdlc/tools/board.py show <ID>
```
- Every id in `depends_on` must be MERGED (into the feature branch) or DONE — and if it belongs to another REQ, that REQ must be integrated into main (`git_flow.py start` refuses otherwise). Otherwise:
  `python .sdlc/tools/board.py move <ID> BLOCKED --by <dev> --note "waiting for STORY-00x"` and stop.
- Bugs start from TRIAGED (skip ANALYSIS; put the root cause in the bug's **Root cause** section).

## 1. Analysis (`OPEN|REOPENED → ANALYSIS`)
```bash
python .sdlc/tools/board.py move <ID> ANALYSIS --by <dev>
```
Read the story, the files in the technical breakdown, their neighbours and existing tests. Write **## Developer analysis**: approach (2–6 bullets), files to create/modify, unit tests mapped to AC-n, risks, questions:
```bash
python .sdlc/tools/board.py section <ID> "Developer analysis" --file <scratch file you wrote with Write> --by <dev>
```
A blocking question → `BLOCKED` with the exact question, stop. **An AC you'd implement differently is a blocking question** — never deviate silently.
For REOPENED stories start from the linked BUG(s) and reproduce first.

## 2. Branch + worktree (`ANALYSIS → IN_PROGRESS`)
```bash
python .sdlc/tools/git_flow.py start <ID> --dev <dev>
```
It creates (or resumes) your branch from the right base and prints the **worktree path**. It records `branch`, `base`, `worktree` on the ticket.
```bash
python .sdlc/tools/board.py move <ID> IN_PROGRESS --by <dev> --note "approach: <one line>"
```
From now on **every** file read/edit and every command for code happens inside that worktree path (use absolute paths with Read/Edit/Write, `cd "<worktree>"` in Bash). The tools also work when run from the worktree (they find the main checkout's board), but the ticket *files* are only in the main checkout.
Install dependencies in the worktree if the project needs it (the `install` command from the profile).

## 3. Implement
- Follow the conventions in the project profile and the surrounding code.
- Small, focused commits **in the worktree**, Conventional Commits with the ticket id:
  `feat(auth): validate email format on login form [STORY-003]`, `fix(auth): … [BUG-002]`, `test(…)`, `refactor(…)`.
- No commented-out code, no debug prints (`console.log`/`print` fail the gate — use the project's logger), no TODO without a ticket id, no secrets (env vars + `.env.example`). Test credentials come from a fixture helper, not inline literals. A line that truly must stay gets `sdlc:allow` with a reason; the reviewer has to agree.
- Implement exactly the story's API contract. If it must change, stop and report — another story shares it.
- Stay in scope. Other problems you notice go into your report, not this branch.

## 4. Developer testing
- At least one unit test per acceptance criterion plus edge/error cases; name tests after behaviour.
- Run lint, typecheck, tests with coverage and build in the worktree (commands from the profile). Fix until green.
- Pull in teammates' merged work before raising the PR:
  ```bash
  python .sdlc/tools/git_flow.py sync <ID>
  ```
  Conflicts → resolve in the worktree, `git add`, `git commit --no-edit`, re-run tests.
- Pre-check (same as CI; report goes to `.sdlc/board/reports/precheck/`): `python .sdlc/tools/quality_gate.py --branch <branch> --base <base>`.

## 5. Raise the PR (`IN_PROGRESS → IN_REVIEW`)
Everything committed (`git status` clean in the worktree), then:
```bash
python .sdlc/tools/board.py new PR "<conventional title> [<ID>]" --set kind=<story|bug> story=<ID> req=<REQ-id or none> branch=<branch> base=<base> author=<dev> security_review=<required|not-required> --by <dev>
```
Use the ticket's own `branch` and `base` values (the board rejects a mismatch). `security_review=required` when the story has label `security`.
Fill the PR's Summary (map to ACs), Changes table, How to test, Developer test evidence (commands, counts, coverage) and author checklist, and the story's **Implementation notes**, each with `board.py section PR-xxx "<Heading>" --file … --by <dev>`. Then:
```bash
python .sdlc/tools/board.py set <ID> pr=PR-xxx --by <dev>
python .sdlc/tools/board.py move <ID> IN_REVIEW --by <dev> --note "PR-xxx: <branch> → <base>"
```
`workflow.pr_mode: github` → also `git push -u origin <branch>` and `gh pr create --base <base> --head <branch>` with the same title/body; put the URL in the PR ticket.

## 6. Fix review comments (`CHANGES_REQUESTED → IN_PROGRESS`)
```bash
python .sdlc/tools/git_flow.py start <ID> --dev <dev>       # resumes: prints the same worktree
python .sdlc/tools/board.py move <ID> IN_PROGRESS --by <dev> --note "addressing PR-xxx cycle <n>"
```
- Fix every `open` blocker/major comment (`C` code, `S` security, `G` gate); fix minors unless you disagree. Disagree → `board.py resolve PR-xxx C4 wont-fix --note "<reason>"`; the reviewer decides. Work that belongs elsewhere → `resolve … follow-up --ticket <STORY/BUG>` (the tech lead/SM creates that ticket).
- Merge conflict reported by devops → `git_flow.py sync <ID>` and resolve.
- Commit `fix(review): <what> [<ID>]`; re-run tests; then per fixed comment `board.py resolve PR-xxx C1 fixed --by <dev>`.
```bash
python .sdlc/tools/board.py move PR-xxx OPEN --by <dev> --note "fixed C1,C2,S1"   # board bumps review_cycle, resets gate + reviews
python .sdlc/tools/board.py move <ID> IN_REVIEW --by <dev>
```

## 7. QA bugs
Same flow from step 2 (`git_flow.py start BUG-xxx --dev <dev>` gives a `bugfix/` branch off main). Write **Root cause** and **Fix**, add a regression test that fails before the fix and passes after; PR `kind=bug`, base = the bug's `base`.

## Never
- Commit on the main branch or a feature branch directly, merge anything, push to main, or `--force` anything
- Check out branches in the main checkout, or edit files outside your worktree (except board tickets via board.py / your own ticket files)
- Delete/skip/weaken tests to get green
