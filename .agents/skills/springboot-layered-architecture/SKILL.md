# Skill: Spring Boot Layered Package Architecture
Organise code by LAYER, never by feature. Under the base package (the one holding `*Application.java`, e.g. `com.example.app`):
- `controller` — `@RestController` only: map HTTP <-> DTOs, `@Valid`, delegate to a service. No business logic, never inject repositories.
- `service` — service interfaces (`AuthService`); `service/impl` — `@Service` implementations (`AuthServiceImpl`) holding business logic and `@Transactional`.
- `repository` — Spring Data repositories / DAOs (`@Repository`, `JpaRepository`).
- `entity` — JPA `@Entity` classes; `model` — non-persistent domain objects/enums.
- `dto/request` — inbound request records (`LoginRequest`); `dto/response` — outbound response records (`LoginResponse`, `ErrorResponse`).
- `mapper` — entity <-> DTO mapping. Controllers never receive or return entities.
- `exception` — custom exception TYPES only (`InvalidCredentialsException`, `ResourceNotFoundException`). No handlers here.
- `aop` — ALL cross-cutting concerns, one class per concern:
  - `GlobalExceptionHandler` — the single `@RestControllerAdvice` mapping exceptions to error DTOs (owns ERROR/WARN logging of failures).
  - `LoggingAspect` — `@Aspect @Component` `@Around` controller/service pointcuts: DEBUG entry/exit with duration, WARN when slower than a threshold; never logs arguments that may hold secrets.
  - `SecurityAspect` (when needed) — `@Aspect` for method-level checks/auditing beyond `@PreAuthorize`, e.g. audit-logging access to sensitive services.
  - `RequestIdFilter` (when needed) — puts a correlation ID into the MDC and the `X-Request-Id` response header.
  - `@Aspect` needs the AOP starter in the build file: Spring Boot 4.x `org.springframework.boot:spring-boot-starter-aspectj`; Spring Boot 3.x `spring-boot-starter-aop`.
- `config` — `@Configuration` / `@ConfigurationProperties` classes (`SecurityConfig`, `CorsConfig`).
- `security` — security components (`UserDetailsService` impls, auth filters, token utilities).
- `util` — small stateless helpers only; never a dumping ground.
Rules:
- Dependency direction is `controller -> service -> repository`; lower layers never import higher ones. `aop` may observe any layer, but no layer depends on `aop`.
- Every controller, service and repository class has an SLF4J logger used per the `backend-logging` skill.
- One top-level public type per file. Create only the packages a story needs; no empty packages.
- Tests mirror the main package of the class under test (`src/test/java/<base>/controller/AuthControllerTest.java`).
- Planner: every `.java` path in `files_to_modify` MUST follow this layout; the backend story that adds the first endpoint also owns `aop/GlobalExceptionHandler.java`, `aop/LoggingAspect.java` and the build file if the AOP starter is missing. Reviewer: reject diffs that put classes in a feature package, put handlers/aspects outside `aop`, or omit loggers.
