# Skill: TypeScript & JavaScript Coding Standards
- Enable `"strict": true` mindset: zero `any` types; use `unknown` + type guards or Zod schemas at API boundaries.
- Prefer immutable array/object operations (`map`, `filter`, spread) over in-place mutation.
- Keep module exports named and explicit; avoid circular barrel (`index.ts`) imports.
