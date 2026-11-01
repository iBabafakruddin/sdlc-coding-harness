---
name: pr-review
description: Code-reviewer playbook for reviewing a local PR ticket — diff against base, acceptance-criteria coverage, correctness, tests, design, readability, performance, and best practices — recording file:line comments with severities and an APPROVED / CHANGES_REQUESTED verdict. Use when a PR is OPEN (first review or re-review after fixes).
---

# Pull request review (Code Reviewer)

## 1. Load context
```bash
python .sdlc/tools/board.py show PR-xxx
python .sdlc/tools/board.py show <story>
git log --oneline <base>..<branch>
git diff --stat <base>...<branch>
git diff <base>...<branch>
```
All branches are visible from the main checkout, so `git diff` works there; to open full files of the branch use its worktree (`python .sdlc/tools/git_flow.py where <branch>`). Don't check branches out.
Check the PR targets the right base: story/bug PR → the ticket's `base` (feature branch, or main for bugs); `kind=feature` PR → main. For a **feature PR** do an *integration review*: consistency across the stories (shared contracts, duplicated helpers, conflicting migrations), the merged result of main + feature, and leftovers (debug code, flags) — not a line-by-line re-review of already approved stories.
Read the story ACs, technical breakdown and API contract (conventions: `.sdlc/project-profile.md`). Read the latest gate report `.sdlc/board/reports/PR-xxx-gate-<cycle>.md`.
If `gate` is `failed`, don't do a full review: `board.py verdict PR-xxx changes-requested --by code-reviewer --note "fix the quality gate first"` and stop.

## 2. Review checklist
**Correctness**
- Every AC is implemented *and* has a test that would fail without it
- Error paths, empty/null/boundary inputs, async errors, race conditions
- API matches the contract exactly (status codes, field names, error shape)

**Tests**
- Tests assert behaviour, not implementation details; no tests that can't fail
- No skipped / focused tests (`.skip`, `.only`, `xit`, `@pytest.mark.skip` without reason)

**Design & maintainability**
- Follows existing patterns and folder structure; no duplicated logic that already exists
- Functions small and single-purpose; clear names; no dead or commented-out code
- No unrelated changes snuck in (scope creep)

**Security basics** (deep review is the security-reviewer's job)
- Input validated at the boundary; no secrets; no sensitive data in logs or errors

**Performance**
- No N+1 queries / loops over network calls; no unbounded lists; no unnecessary re-renders in hot paths

**Housekeeping**
- Conventional commits with ticket id; docs/README updated if behaviour changed

## 3. Write comments
One command per comment (ids `C1`, `C2`, … are assigned automatically; the file is locked, so a parallel security review can't collide):
```bash
python .sdlc/tools/board.py comment PR-xxx --by code-reviewer --sev major --loc app/src/auth/login.ts:42 --text "Password compared with ==; use the hash compare helper in auth/hash.ts"
```
`--loc` may be any repo file, also one outside the diff (e.g. `docs/adr/0002-auth.md` that should be amended), or `general`.
Severity: `blocker` (broken / unsafe / AC missing), `major` (bug risk, missing test, contract mismatch), `minor` (maintainability), `nit` (style/preference — say "nit:").
Be specific, propose the fix, and acknowledge good work in the verdict line when deserved.

## 4. Re-review (cycle > 1)
- For each `fixed` comment: verify in the code → `board.py resolve PR-xxx C3 verified --by code-reviewer`, or `… open --note "<why>"`.
- For `wont-fix`: accept (leave it; explain in your verdict note) or insist (`resolve … open --note`).
- Review only the new diff (`git diff <last-reviewed-commit>..<branch>`) plus regressions. Don't raise new nits on unchanged code.

## 5. Verdict
```bash
python .sdlc/tools/board.py verdict PR-xxx changes-requested --by code-reviewer --note "2 major, 1 minor"   # any open blocker/major
python .sdlc/tools/board.py verdict PR-xxx approved --by code-reviewer --note "<one line>"                 # otherwise
```
`verdict` sets `code_review` and appends to **Review verdicts**. **You never move PR or story status** — the orchestrator moves them once gate and all reviews of the cycle are in; devops moves APPROVED → MERGED.
- **PR into main** (feature or bugfix PR): every comment of the feature must be resolved — `minor`/`nit` too (`fixed`/`verified`, `wont-fix`, or `follow-up --ticket`). List any still open in your report.
- If `review_cycle` ≥ `workflow.max_review_cycles` and you still request changes, say **ESCALATE** in your report.
