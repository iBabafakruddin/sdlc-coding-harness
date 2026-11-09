# Skill: RESTful API & System Design
- Use plural nouns for resources (`/api/v1/orders/{orderId}/items`), standard HTTP methods, and proper status codes (`200`, `201`, `204`, `400`, `401`, `403`, `404`, `409`, `422`, `429`).
- Standardize error responses using RFC 7807 (`type`, `title`, `status`, `detail`, `instance`, `errors`).
- Enforce pagination (`limit`, `cursor` or `page`/`size`) and max page size caps on all collection endpoints.
