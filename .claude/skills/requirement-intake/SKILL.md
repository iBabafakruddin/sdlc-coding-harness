---
name: requirement-intake
description: Business-analyst playbook for turning a raw client request or feature idea into a refined REQ ticket on the local board (goal, scope, FR/NFR, assumptions, open questions). Use when a new feature, change request or client ask arrives, before any grooming or coding.
---

# Requirement intake (Business Analyst)

Goal: a REQ ticket the tech lead can groom without going back to the client.

## Steps

1. **Read the process** — `.sdlc/process/workflow.md` (sections 2, 3, 6) if you haven't this session.

2. **Check for duplicates**
   ```bash
   python .sdlc/tools/board.py list --type REQ
   ```
   Grep `.sdlc/board/requirements/` and `.sdlc/board/stories/` for the key nouns. If an existing REQ covers it, add to that REQ's **Raw request** history instead of creating a new one, and say so in your report.

3. **Create the ticket**
   ```bash
   python .sdlc/tools/board.py new REQ "<short title>" --set priority=<low|medium|high|critical> requested_by="<who>" --by business-analyst
   ```
   It prints the id and path. Fill each section with `board.py section REQ-xxx "<Heading>" --text "…"` (or `--file`). If you edit the markdown instead, Read the file first, then Edit (never Write over it), and keep the frontmatter and the `## Activity` lines intact.
   Related requirements (same client session, shared code): `board.py set REQ-xxx related=[REQ-001,REQ-002]` and a line in **Related requirements**. Human answers to open questions go into **Decisions (confirmed by human)**.

4. **Fill every section**
   - **Raw request** — paste the client's words verbatim as a quote.
   - **Business goal** — the *why* and a measurable success signal ("users can sign in in < 3 clicks", "reduce support tickets about passwords").
   - **Users / personas** — who, and what they already know.
   - **Scope** — be explicit about **out of scope**; this is where most later disputes come from. For "login page": is sign-up in scope? forgot password? SSO? remember me? MFA?
   - **Functional requirements** — numbered `FR-n`, each one observable behaviour, no implementation detail.
   - **Non-functional** — security, performance, accessibility (WCAG AA default), supported browsers/devices, i18n, logging/audit.
   - **Assumptions** — `A-n` for every default you chose instead of asking.
   - **Open questions** — `Q-n` that genuinely change scope or cost.

5. **Decide: refine or ask**
   - If open questions would change the scope or the estimate by more than ~30%, stop: leave the REQ in `NEW` and return the questions to the orchestrator.
   - Otherwise move it on:
     ```bash
     python .sdlc/tools/board.py move REQ-xxx REFINED --by business-analyst --note "FR-1..n captured, k assumptions"
     ```

## Quality bar (self-check before moving)
- [ ] Someone who never met the client can tell what "done" looks like
- [ ] Every FR is testable (could become a Given/When/Then)
- [ ] Out-of-scope list is non-empty
- [ ] Security NFRs considered for anything involving users, data or money
- [ ] No technical design (frameworks, tables, endpoints) — that's grooming

## Common defaults (record as assumptions when used)
| Topic | Default |
|---|---|
| Accessibility | WCAG 2.1 AA, keyboard navigable |
| Browsers | Last 2 versions of Chrome, Edge, Firefox, Safari; mobile responsive |
| Passwords | min 8 chars, stored hashed (bcrypt/argon2), never logged |
| Auth errors | Generic message ("Invalid <identifier> or password", e.g. email or username — whatever the login uses), no user enumeration |
| Rate limiting | Lockout / throttling after 5 failed attempts |
| Performance | Page interactive < 2s on broadband, API p95 < 500ms |
