# Skill: Python Backend Layered Package Architecture (FastAPI / Flask / Django REST)
Organise code by LAYER, never by feature, under one application package (e.g. `backend/app/`), with `main.py` (app factory / startup) at its root:
- `api/routes` — route handlers = controllers (FastAPI `APIRouter`, Flask `Blueprint`, DRF views): parse/validate input via schemas, call a service, map to response schemas. No business logic, no DB/ORM access.
- `services` — business logic as plain classes/functions (`auth_service.py`); framework-agnostic, receive repositories via constructor/dependency injection.
- `repositories` — data access / DAOs (`user_repository.py`), the only layer that talks to the ORM or SQL.
- `models` — ORM models (SQLAlchemy / Django models); `domain` — pure domain objects/enums when needed.
- `schemas/request` and `schemas/response` — Pydantic models / serializers = DTOs (`LoginRequest`, `LoginResponse`, `ErrorResponse`). Routes never return ORM models.
- `mappers` — model <-> schema conversion when not trivial.
- `exceptions` — custom exception TYPES only (`InvalidCredentialsError`). No handlers here.
- `aop` — ALL cross-cutting concerns (Python's AOP = middleware, exception handlers, decorators, dependencies), one module per concern:
  - `exception_handlers.py` — the single place mapping exceptions to error responses, registered on the app at startup (owns ERROR/WARN logging of failures).
  - `logging_middleware.py` — request entry/exit with duration at DEBUG (slow requests at WARN) and the `X-Request-Id` correlation ID via `contextvars`.
  - `security.py` (when needed) — auth dependencies/decorators (e.g. `get_current_user`, `require_role`) and audit logging.
  - `decorators.py` (when needed) — e.g. `@timed`, `@audited` for service methods.
- `core` — `config.py` (settings from env via `pydantic-settings`/os.environ, no hardcoded secrets), `logging_config.py` (handlers, format, levels — configured once at startup), `security.py` primitives (password hashing).
- `utils` — small stateless helpers only; never a dumping ground.
Rules:
- Dependency direction is `api -> services -> repositories`; lower layers never import higher ones; `aop` may wrap any layer but no layer imports `aop` except app startup and route dependencies.
- Every route, service and repository module has `logger = logging.getLogger(__name__)` used per the `backend-logging` skill.
- Each layer package has an `__init__.py`. Create only the packages a story needs.
- Tests mirror the layer of the code under test: `tests/api/test_auth_routes.py`, `tests/services/test_auth_service.py`, `tests/repositories/...`.
- Planner: every `.py` path in `files_to_modify` MUST follow this layout; the backend story that adds the first endpoint also owns `aop/exception_handlers.py`, `aop/logging_middleware.py` and `core/logging_config.py`. Reviewer: reject diffs that group modules by feature, put handlers/middleware outside `aop`, or omit loggers.
