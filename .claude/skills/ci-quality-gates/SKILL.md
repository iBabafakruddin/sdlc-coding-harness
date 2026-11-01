---
name: ci-quality-gates
description: DevOps playbook for the local CI pipeline and branch flow — run quality gates (lint, tests, coverage, build, secret/debug/TODO checks) inside a PR branch's worktree, merge approved story PRs into feature branches, integrate finished features into main via a feature PR, cut/build the QA branch with release notes, and clean up branches/worktrees. Use for "gate PR-x", "merge PR-x", "integrate REQ-x", "qa-build SPRINT-x".
---

# CI / branches / release (DevOps)

Branch model (from `.sdlc/process/workflow.md` §9): `main` ← `feature/REQ-…` ← `story/STORY-…`; QA bugs `bugfix/BUG-…` off main; QA builds `qa/SPRINT-…` off main. Every branch lives in its own worktree; the main checkout stays on main. All branch operations go through `python .sdlc/tools/git_flow.py`.

## Job 1 — gate <PR>
```bash
python .sdlc/tools/board.py show PR-xxx
python .sdlc/tools/quality_gate.py --pr PR-xxx
```
The gate runs in the worktree where the PR branch is checked out (no checkout needed), using `project.commands` (or auto-detected scripts) plus `quality_gates.extra_commands`, reads coverage, scans the changed files (`base...branch`) for secrets / debug statements / TODOs / oversized files / missing tests, writes `.sdlc/board/reports/PR-xxx-gate-<cycle>.md` and sets `gate=passed|failed`.
The gate itself writes the PR's **Quality gate** section (verdict, sha, coverage, report link) — don't edit it by hand.
Install uses the lockfile (`npm ci` / `pnpm install --frozen-lockfile` / `yarn install --frozen-lockfile`) and is skipped when `node_modules` was built from the same package.json + lockfile (`--fresh-install` to force).
- **Failed** → one `board.py comment PR-xxx --by devops-engineer --sev <blocker for test/build/secret, major for lint/coverage/debug> --loc <file:line|general> --text …` per failure (ids `G<n>`), move PR → `CHANGES_REQUESTED`, ticket → `CHANGES_REQUESTED`.
- **Passed** → nothing to edit; report the verdict.
- Docs-only change → `--skip-commands`.

## Job 2 — merge <PR> (story/bug PR → its base)
```bash
python .sdlc/tools/board.py move PR-xxx APPROVED --by devops-engineer   # board checks gate + reviews + no open blocker/major (PR to main: no open comment at all)
python .sdlc/tools/git_flow.py merge PR-xxx --by devops-engineer
```
`merge` does a `--no-ff` merge into the PR's base inside the base's worktree (feature branch) or the main checkout (main), then moves PR → MERGED and the story/bug → MERGED, and records `merge_commit`.
Then verify the base is still green and clean up:
```bash
python .sdlc/tools/quality_gate.py --pr PR-xxx --tests-only         # post-merge tests on the PR's base; report PR-xxx-postmerge-<sha>.md, logged on the PR
python .sdlc/tools/git_flow.py finish <STORY-or-BUG-id> --by devops-engineer   # removes the worktree, deletes the merged branch
```
- **Merge conflict** (exit 2; base untouched) → comment `blocker | merge conflict with <base> in <files>; run git_flow.py sync <ID>`, move PR and ticket → `CHANGES_REQUESTED`.
- **Base red after merge** → `git -C <base worktree> revert -m 1 <merge sha>`, record it on the PR and ticket, send it back to the developer. Never leave a shared branch red.
- If the PR's base is the main branch and `workflow.human_approval.before_merge_to_main` is true → stop after APPROVED and report "awaiting human approval".

## Job 3 — integrate <REQ> (feature branch → main)
When every story of the REQ (its `stories:` field) is MERGED into the feature branch:
```bash
python .sdlc/tools/git_flow.py sync REQ-xxx --by devops-engineer   # bring main into the feature branch; resolve nothing yourself
python .sdlc/tools/board.py new PR "feat: <REQ title> [REQ-xxx]" --set kind=feature req=REQ-xxx story=none branch=<feature branch> base=<main> author=devops-engineer security_review=<required if any story had label security, else not-required> --by devops-engineer
python .sdlc/tools/quality_gate.py --pr PR-yyy
```
Fill the feature PR: Summary = REQ goal, Changes = the story PRs merged (from `git log --merges <main>..<feature branch>`), test evidence = gate report.
Sync conflicts → don't resolve feature code yourself: report them; the orchestrator assigns a developer (who resolves in the feature worktree with a `fix(merge): … [REQ-xxx]` commit).
Before approval every review comment of the feature's PRs must be resolved (the board refuses `APPROVED` otherwise): list the open ones for the orchestrator, who sends them to the developers (fix, `wont-fix` agreed with the reviewer, or `follow-up` ticket).
After `code-reviewer` (integration review) and, if required, `security-reviewer` approve: **Job 2** on the feature PR (`merge` sets `integrated=yes` on the REQ). Then `git_flow.py finish REQ-xxx --by devops-engineer`.
After integrating: every other open feature branch whose stories depend on this REQ gets `git_flow.py sync REQ-yyy` (cross-REQ rule, workflow §9). If this REQ held the scaffold (greenfield), tell the orchestrator: tech-lead re-onboarding is due (workflow §10).
Partial features (stories left for a later sprint) stay on their feature branch and are integrated when complete.

## Job 4 — qa-build <SPRINT>
Precondition: the sprint's stories are MERGED and their features integrated into main. Stories whose feature is not integrated are **not** in this build — list them as carried over.
If `workflow.human_approval.before_qa_release` is true → stop and report.
```bash
python .sdlc/tools/git_flow.py qa-build SPRINT-xx --by devops-engineer  # qa/SPRINT-xx from main in its own worktree
python .sdlc/tools/quality_gate.py --branch qa/SPRINT-xx --tests-only   # report reports/branch/qa_SPRINT-xx-tests-<sha>.md
python .sdlc/tools/board.py new QA "QA build for SPRINT-xx" --set sprint=SPRINT-xx branch=qa/SPRINT-xx commit=<sha> worktree=<path> --by devops-engineer
python .sdlc/tools/board.py set SPRINT-xx qa_build=QA-xx --by devops-engineer
python .sdlc/tools/board.py move SPRINT-xx IN_QA --by devops-engineer
python .sdlc/tools/board.py move STORY-xxx IN_QA --by devops-engineer     # each included story
python .sdlc/tools/board.py move QA-xx IN_TEST --by devops-engineer
```
Fill the QA ticket: Build (command, result, sha, worktree path), Included changes (from `git log --merges --first-parent <main>`), draft Release notes in user language.
Build red → QA ticket `FAILED`, identify the offending merge from the report, report it; never hand a red build to QA.

**Rebuild after bug fixes**: once bugfix PRs are MERGED into main → `git_flow.py qa-build SPRINT-xx` again (fast-forwards the QA branch), re-run tests, add a build line to the QA ticket (`FAILED → BUILDING → IN_TEST`), move fixed bugs `MERGED → RETEST`, `git_flow.py finish BUG-xxx`.

## Housekeeping
`python .sdlc/tools/git_flow.py status` — every ticket branch, its base, ahead/behind, worktree. Report stale branches (no commits for days, far behind base).
`workflow.pr_mode: github` → use `gh pr merge --merge` instead of `git_flow.py merge`, then the same board moves by hand (`move PR MERGED`, ticket `MERGED`).

## Never
`--force` pushes, history rewrites on shared branches, resolving other people's conflicts, skipping a red gate, or editing code/tests to make a gate pass.
