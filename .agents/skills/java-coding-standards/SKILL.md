# Skill: Java Coding Standards (Java 17/21+)
- Use `record` for DTOs, value objects, and immutable events.
- Prefer constructor injection (`final` fields) over `@Autowired` field injection.
- Use `Optional<T>` for return types that may be absent; never pass `Optional` as a method parameter or entity field.
- Use `Stream` pipelines cleanly; avoid deeply nested lambdas or side-effects inside `.map()`/`.forEach()`.
- Use `sealed` interfaces and pattern matching (`switch` expressions) for domain state machines.
