# Skill: Backend & Redis Caching Patterns
- **Redis Cache-Aside**: Check Redis cache first -> on miss query DB -> populate Redis with explicit TTL + jitter to prevent cache stampede.
- **Cache Invalidation**: Evict or update cache keys atomically after DB transaction commit (`@TransactionalEventListener(phase = AFTER_COMMIT)`).
- **Rate Limiting & Locks**: Use Redis token bucket / sliding window for API rate limits and Redlock / `SET resource val NX PX ttl` for distributed locks.
- **Idempotency**: Support `Idempotency-Key` headers stored in Redis (24h TTL) for mutating POST/payment endpoints.
