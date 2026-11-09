# Skill: Spring Boot Production Patterns
- Layer strictly: `Controller` (HTTP/DTO validation) -> `Service` (business logic & `@Transactional`) -> `Repository` (persistence).
- Never return JPA `@Entity` objects directly from `@RestController`; map to/from immutable Java `record` DTOs.
- Validate all request bodies with `@Valid` / Jakarta Bean Validation (`@NotBlank`, `@Email`, `@Size`, `@Positive`).
- Centralize error handling via `@RestControllerAdvice` returning `ProblemDetail` (RFC 7807).
- Use `@ConfigurationProperties(prefix = "...")` with `@Validated` instead of scattered `@Value` annotations.
