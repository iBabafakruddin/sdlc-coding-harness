# Skill: Spring Security Best Practices
- Configure stateless `SecurityFilterChain` bean (`SessionCreationPolicy.STATELESS`) for REST APIs.
- Use `@EnableMethodSecurity` and `@PreAuthorize("hasRole(...) or #id == authentication.principal.id")` on sensitive service methods.
- Hash passwords exclusively with `BCryptPasswordEncoder` or `Argon2PasswordEncoder`.
- Configure strict CORS allowlists and validate JWT signature, expiration (`exp`), and issuer (`iss`).
