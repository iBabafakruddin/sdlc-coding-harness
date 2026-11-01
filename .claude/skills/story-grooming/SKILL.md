---
name: story-grooming
description: Tech-lead playbook for backlog grooming — split a REFINED requirement into READY user stories with technical breakdown, impacted files, story points, dependencies, API contracts, test approach and risks, plus ADRs for architecture decisions. Use after requirement intake and before sprint planning.
---

# Story grooming (Tech Lead)

Goal: every story is READY per the Definition of Ready (`.sdlc/process/workflow.md` §4) and a developer can start without asking a question.

## 1. Understand
- Read the REQ fully, especially **Out of scope**, **Assumptions**, **NFRs**.
- Read `.sdlc/config.json` (`project.workspace`, `project.tech_stack`).
- Survey the workspace: folder structure, package manifest, frameworks, routing, state, API layer, DB, existing tests and test runner, lint config. Note the *patterns* new code must follow.
- Check existing stories for overlap: `python .sdlc/tools/board.py list --type STORY`.

## 2. Architecture (only if needed)
- Empty workspace, a new library, a new service, a data-model change, or an auth mechanism → write an ADR: `docs/adr/ADR-<nnn>-<slug>.md` with **Context / Decision / Alternatives considered / Consequences**.
- Empty workspace → first story is **"Project scaffold"**: app skeleton, test runner with coverage (`json-summary` reporter for JS so the gate can read `coverage/coverage-summary.json`; `pytest-cov` for Python), lint, `build` script, README run instructions. Every other story `depends_on` it.

## 3. Split
Use vertical slices (UI + API + data for one behaviour), not horizontal layers. INVEST: Independent, Negotiable, Valuable, Estimable, Small, Testable.

Example — "Login page" REQ might become:
| Story | Pts | Depends on | Labels |
|---|---|---|---|
| Project scaffold (only if empty) | 3 | – | infra |
| Login API: POST /api/auth/login with validation + hashed password check | 5 | scaffold | backend, security |
| Login page UI: form, client validation, error states, a11y | 3 | scaffold | frontend |
| Wire UI to API, session/token handling, redirect after login | 3 | API, UI | frontend, security |
| Lockout after 5 failed attempts | 2 | API | backend, security |

Create each one:
```bash
python .sdlc/tools/board.py new STORY "<title>" --set req=REQ-xxx priority=<p> --by tech-lead
```

## 4. Fill each story (all sections of the template)
- **User story** — As a / I want / So that.
- **Acceptance criteria** — `- AC-n: Given … when … then …` or with a requirement tag `- AC-n (FR-2): Given …`. Cover happy path, validation errors, edge cases, permission/security behaviour.
- **Technical breakdown** — table of area / change / *real* files or modules (existing ones by path, new ones by proposed path).
- **API contract** — method, path, request, every response code with body. Frontend and backend stories must reference the *same* contract.
- **Dependencies & blockers** — `depends_on: [STORY-001, STORY-002]` in frontmatter + prose; external blockers (keys, designs, third-party access).
- **Test approach** — unit tests to add (by module); QA scenarios `- TC-STORY-xxx-n: …` mapping to ACs.
- **Security / NFR notes** — and add label `security` for auth, sessions, input parsing, uploads, secrets, PII (the board refuses READY when such words appear without it; `no-security` label only with a reason here).
- **API contract** — write `None` when there is no endpoint (the template text is refused).
- **Dependencies & blockers** — `- Depends on: none` / `- External blockers: none` are valid answers; empty lines are not.
- **Estimate rationale** — complexity, uncertainty, effort.

Write sections with `python .sdlc/tools/board.py section STORY-xxx "<Heading>" --file <file written with the Write tool> --by tech-lead`.
Set fields (no spaces inside lists — the shell splits them): `python .sdlc/tools/board.py set STORY-xxx points=5 labels=[backend,security] depends_on=[STORY-001] --by tech-lead`
Then link them: `board.py set REQ-xxx stories=[STORY-001,STORY-002] --by tech-lead` (REQ → GROOMED requires it).
**Cross-REQ**: a story may depend on another REQ's story only if that REQ will be integrated into main first. Prefer a foundation REQ for shared groundwork (workflow §9).

## 5. Estimate (Fibonacci)
| Pts | Meaning |
|---|---|
| 1 | Trivial, one file, obvious tests |
| 2 | Small, a few files, known pattern |
| 3 | Moderate, one layer end to end, some edge cases |
| 5 | Multiple layers or a new pattern, real edge cases |
| 8 | Large / uncertain → split it, or justify in the rationale |
| 13 | Not allowed in a sprint; must be split |

Unknowns you cannot estimate → create a **Spike** story (1–2 pts, timeboxed, output = decision recorded in ADR).

## 6. Make READY
```bash
python .sdlc/tools/board.py move STORY-xxx READY --by tech-lead --note "groomed: 5pt, deps STORY-001"
```
The board refuses READY if the DoR guard fails — fix the story, don't `--force`.

Then link and close grooming:
```bash
python .sdlc/tools/board.py set REQ-xxx stories=[STORY-001,STORY-002,STORY-003] --by tech-lead
python .sdlc/tools/board.py move REQ-xxx GROOMED --by tech-lead --note "5 stories, 16 pts"
python .sdlc/tools/board.py validate
```

## Self-check
- [ ] Every FR in the REQ maps to at least one AC in some story
- [ ] No dependency cycles (`validate` passes)
- [ ] Every story ≤ 8 points and has ≥ 1 QA scenario
- [ ] Shared contracts (API shapes, component props) are identical across stories
