# Skill: Backend Logging (levels, placement, safety)
Every controller, service, repository/DAO and cross-cutting (aop) class declares its own logger:
- Java/SLF4J: `private static final Logger log = LoggerFactory.getLogger(AuthServiceImpl.class);` (no `System.out`, no `printStackTrace`).
- Python: `logger = logging.getLogger(__name__)` at module top (no `print`); configure handlers/format once at startup in `core/logging_config.py`.
Levels — pick by audience and frequency:
- ERROR: unexpected failure that needs a human (unhandled exception, dependency down). Log ONCE with the stack trace, at the boundary that handles it (the global exception handler), not at every layer. Java: `log.error("Login failed unexpectedly for requestId={}", rid, ex)`; Python: `logger.exception(...)`.
- WARN: expected-but-notable or recoverable events: failed login / 401, 403 access denied, validation rejected (400), retries, fallbacks, deprecated usage.
- INFO: business milestones and state changes, low volume: startup config summary, successful login, entity created/updated/deleted, scheduled job start/finish.
- DEBUG: developer flow detail: method entry/exit and timing (from the logging aspect/middleware), branch decisions, query parameters (non-sensitive).
- TRACE: payload-level detail; off everywhere except local debugging.
Placement:
- Controllers: DEBUG on request received (endpoint + non-sensitive identifiers). Don't duplicate the global handler's error logs.
- Services: INFO for business outcomes, WARN for rejected business rules, DEBUG for decisions. Never log-and-rethrow the same exception.
- Repositories/DAOs: DEBUG for queries and row counts; let exceptions propagate.
- Cross-cutting `aop` package: a logging aspect/middleware logs method or request entry/exit with duration at DEBUG (slow calls over a threshold at WARN); the global exception handler owns ERROR logging for unexpected errors and WARN for client errors.
Safety and format:
- NEVER log passwords, tokens, secrets, session IDs, full card/bank numbers or request bodies containing them; mask PII (e.g. `d***@example.com`). Log usernames only where needed for audit.
- Use parameterized messages (`log.info("User {} logged in", username)`; Python `logger.info("User %s logged in", username)`), never string concatenation/f-strings in log calls.
- Add a correlation/request ID to every log line (Java MDC set in a filter/aspect; Python `contextvars` + logging filter) and return it in an `X-Request-Id` response header.
- Default level INFO for the app package, WARN for frameworks; make levels configurable per environment (`logging.level.*` / env vars).
- Tests should not assert on log output except for security-relevant rules (e.g. password never logged).
