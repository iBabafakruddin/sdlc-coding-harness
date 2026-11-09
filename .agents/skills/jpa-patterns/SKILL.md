# Skill: JPA & Hibernate Patterns
- Default all `@ManyToOne` and `@OneToOne` associations to `FetchType.LAZY` (`@OneToMany` is lazy by default).
- Prevent N+1 queries using `@EntityGraph`, `JOIN FETCH` JPQL queries, or DTO projections.
- Put `@Transactional(readOnly = true)` at the service class level and override with `@Transactional` only on mutating methods.
- Avoid `@Data` (Lombok) on `@Entity` classes; implement `equals`/`hashCode` using business keys or database ID safely (`getClass()`).
- Use optimistic locking (`@Version`) on entities subject to concurrent updates.
