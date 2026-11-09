# Skill: Zero-Downtime Database Migrations (Flyway / Liquibase / Alembic)
- Follow Expand-and-Contract: never rename or drop an active column in a single migration while old app code is running.
- Add new nullable columns or tables first, backfill in batches, then apply `NOT NULL` constraints (`NOT VALID` -> `VALIDATE CONSTRAINT` in Postgres).
- Name migration scripts deterministically (`V1__create_users_table.sql`) and never modify an already-applied migration.
