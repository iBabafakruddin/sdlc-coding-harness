---
name: appsec-review
description: Security-reviewer playbook — OWASP Top 10 / ASVS-based review of a PR diff for auth, session, input-handling, secrets, PII and dependency risks, recorded as findings and a verdict in the PR ticket. Use for PRs with security_review=required (stories labelled security) and before QA releases.
---

# Application security review

## 1. Scope
```bash
python .sdlc/tools/board.py show PR-xxx
git diff <base>...<branch>
```
Also read code the diff *calls into* (auth helpers, middleware, DB layer) — vulnerabilities often live at the seams.

## 2. Checklist (apply what is relevant)
**Authentication & sessions**
- Passwords hashed with bcrypt/argon2/scrypt (never plain, MD5, SHA-1/256 alone); constant-time comparison
- Generic auth error messages — no user enumeration via message, status code or timing
- Brute-force protection (lockout / throttling) if the REQ requires it
- Session tokens: random, HttpOnly + Secure + SameSite cookies, or JWT with strong secret, `exp`, verified signature and algorithm pinned
- Logout / expiry actually invalidate the session

**Input & output**
- Validation on the server side, not only the client
- SQL/NoSQL injection: parameterised queries only
- XSS: no `dangerouslySetInnerHTML`/`innerHTML`/`v-html` with user data; output encoding
- Open redirects (e.g. `?next=` after login must be same-origin)
- CSRF protection on state-changing cookie-authenticated endpoints
- File uploads: type/size limits, no path traversal

**Data**
- No secrets in code, config committed, logs, or error responses
- PII minimised; passwords/tokens never logged
- Proper authorization checks on every endpoint (not only authentication)

**Dependencies**
- New dependencies are maintained and needed; run `npm audit --omit=dev` / `pip-audit` if available and report high/critical

## 3. Record
One `board.py comment PR-xxx --by security-reviewer --sev <sev> --loc <file:line> --text "…"` per finding (ids `S<n>` are automatic), severity:
- `blocker` — exploitable now (injection, auth bypass, secret leak, plaintext password)
- `major` — weakness likely exploitable or missing required control (no rate limit when required, enumeration)
- `minor` — hardening (headers, cookie flags in dev-only code)

Then:
```bash
python .sdlc/tools/board.py verdict PR-xxx <approved|changes-requested> --by security-reviewer --note "<one line>"
```
Re-review: `board.py resolve PR-xxx S2 verified|open --by security-reviewer`. You never move PR or story status — the orchestrator does.

Only report what you can point to in code with a plausible attack. No generic advice lists.
