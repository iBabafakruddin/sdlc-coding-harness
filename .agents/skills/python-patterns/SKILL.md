# Skill: Idiomatic Python & FastAPI/Backend Patterns
- Enforce full type annotations (`from __future__ import annotations`, `typing`, `pydantic.BaseModel` / `dataclasses`).
- Use context managers (`with` / `async with`) for DB sessions, file handles, and HTTP clients (`httpx.AsyncClient`).
- Keep business logic pure and decoupled from web frameworks; raise domain-specific exceptions mapped at the boundary.
