# Skill: PostgreSQL Optimization Patterns
- Always index foreign key columns and columns used in `WHERE`, `JOIN`, and `ORDER BY` clauses.
- Use `BIGINT GENERATED ALWAYS AS IDENTITY` or UUIDv7 for primary keys; use `TIMESTAMPTZ` (never `TIMESTAMP` without timezone).
- Use `JSONB` with GIN indexes only for semi-structured attributes; keep core relational fields normalized.
- Use keyset/cursor pagination (`WHERE (created_at, id) < (:lastCreated, :lastId) ORDER BY created_at DESC, id DESC LIMIT :limit`) over large `OFFSET`.
