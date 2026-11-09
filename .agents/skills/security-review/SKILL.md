# Skill: OWASP AppSec Review Checklist
- Parameterize all SQL/JPQL queries (0 string concatenation).
- Sanitize and validate all untrusted inputs (path params, query strings, headers, JSON bodies, file uploads).
- Enforce object-level authorization (BOLA/IDOR check: verify the authenticated user owns the requested resource ID).
- Ensure zero secrets, tokens, or PII are logged or committed.
