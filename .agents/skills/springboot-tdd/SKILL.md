# Skill: Spring Boot TDD & Slice Testing
- Use `@WebMvcTest` + `MockMvc` for fast controller slice tests (validation, HTTP status codes, JSON serialization).
- Use `@DataJpaTest` + Testcontainers (`@ServiceConnection` Postgres) for repository and custom query verification.
- Use JUnit 5 `@ExtendWith(MockitoExtension.class)` (`@Mock`, `@InjectMocks`) for isolated unit tests of `@Service` classes.
- Follow Arrange-Act-Assert (`given`/`when`/`then` with AssertJ `assertThat(...)`).
