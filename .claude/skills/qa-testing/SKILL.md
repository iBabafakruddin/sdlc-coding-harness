---
name: qa-testing
description: QA-engineer playbook for testing an integrated QA build — test plan from acceptance criteria, automated integration/API/e2e and regression tests, evidence-based execution, bug reporting with reproduction steps, bug retest, and QA sign-off. Use when a QA ticket is IN_TEST or bugs are in RETEST.
---

# QA testing (QA Engineer)

## 1. Prepare
```bash
python .sdlc/tools/board.py show QA-xx
python .sdlc/tools/git_flow.py where qa/SPRINT-xx      # the QA build's worktree; test there
```
Never switch branches in the main checkout. Install/start the app inside the QA worktree (commands in `.sdlc/project-profile.md`).
For each story in the QA ticket's **Included changes**: read ACs, QA scenarios (`TC-STORY-x-n`), API contract, implementation notes.

## 2. Test plan
Fill the QA ticket's **Test plan** table — at least one row per AC:
| Test case | Story | AC | Type | Result | Evidence |
Types: `integration` (modules together, real DB/in-memory), `api` (HTTP against the running server), `e2e` (UI flow, Playwright if the project has/accepts it), `regression` (previously DONE features near the changed code), `exploratory` (edge cases nobody wrote down: empty, huge, unicode, double submit, back button, slow network).

## 3. Automate
- Write tests in the workspace's integration/e2e folder following existing conventions (create `tests/integration/` or `e2e/` if none). Prefer API-level tests; add e2e only for critical user flows.
- Automated tests are product code, so they get their own branch and worktree off main:
  ```bash
  git worktree add -b qa-tests/SPRINT-xx "<git.worktree_root>/qa-tests-SPRINT-xx" <main>
  ```
  Commit there (`test(qa): <what> [STORY-xxx]`), run them against the QA build, then raise a PR `kind=qa-tests branch=qa-tests/SPRINT-xx base=<main> story=none` — it goes through the normal gate + review + merge.
- Run the app if needed (start command from README / package.json) and stop it afterwards.

## 4. Execute & record
Run every test case. Record **Pass/Fail** and **evidence** (test name + output excerpt, HTTP status + body, screenshot path). Never mark a case as passing without running it.

## 5. Raise bugs
```bash
python .sdlc/tools/board.py new BUG "<symptom, not cause>" --set story=STORY-xxx severity=<critical|major|minor|trivial> found_in=QA-xx sprint=SPRINT-xx --by qa-engineer
```
Fill: Environment (branch + sha), numbered Steps to reproduce, Expected, Actual, Evidence, failed TC/AC.
- `critical`/`major` → `python .sdlc/tools/board.py move STORY-xxx REOPENED --by qa-engineer --note "BUG-xxx"`
- `minor`/`trivial` → story can still be DONE; bug goes to the backlog.
Add the bug to the QA ticket's **Bugs raised** table.

## 6. Retest
For bugs in `RETEST` after the rebuild: re-run the original steps and the regression test → `CLOSED` (with evidence) or `REOPENED` (with what's still wrong). Re-run the affected story's test cases.

## 7. Story acceptance & sign-off
- Story passes all its TCs and has no open critical/major bug → `python .sdlc/tools/board.py move STORY-xxx DONE --by qa-engineer`, fill the story's **QA results** with `board.py section STORY-xxx "QA results" --file … --by qa-engineer`.
- All stories DONE (or explicitly carried over by the scrum master) → `python .sdlc/tools/board.py move QA-xx PASSED`, write **QA sign-off**.
- Otherwise → `move QA-xx FAILED` with the list of open bugs; the orchestrator runs the fix loop.
- If a story has been reopened more than `workflow.max_qa_cycles` times → report **ESCALATE**.
