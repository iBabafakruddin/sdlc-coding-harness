---
id: REQ-101
title: Spring Boot Order API + Redis Cache + React Order Table
priority: high
source: local-folder
---

# Feature: Order Management & Caching

## Context
Users need to create and view orders with low latency.

## Acceptance Criteria
1. Create a Spring Boot `OrderController` (`POST /api/v1/orders`, `GET /api/v1/orders/{id}`) backed by JPA `OrderEntity` and PostgreSQL migration.
2. Cache `GET /api/v1/orders/{id}` responses in Redis with a 10-minute TTL and evict on update.
3. Build a React `OrdersTable` component with loading/error states and unit tests.
