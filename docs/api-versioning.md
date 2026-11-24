# OpenCigan Public API Versioning and Compatibility Policy

This document is the code-level contract policy for public API paths under `/api/v1/`. Internet exposure is a separate decision; see [operations docs](operations/README.md) and release records.

## Version identity

- The path prefix `/api/v1/` is the contract version. The OpenAPI document declares openapi 3.1.0 and info.version 1.0.0.
- Response bodies carry no version field. A new contract gets a new prefix, and the old prefix stays available under this policy unless a breaking change is recorded under Compatibility rules.
- JSON responses default to `Cache-Control: no-store`. The calendar feeds are exceptions: `/api/v1/timetable.ics` and `/api/v1/timetable/history.rss` send a SHA-256 ETag and `Cache-Control: private, max-age=0, must-revalidate`, and honor `If-None-Match` with 304 Not Modified when the feed is unchanged.
- CORS exposes `Retry-After` on all paths and `ETag` on the two feed paths.

## Error contract

- Errors are JSON objects with `error` (user-facing sentence) and `code` (stable lowercase identifier).
- Codes present in the contract include `invalid_request` (400), `method_not_allowed` (405), `not_found` (404), `rate_limited` (429, with `Retry-After`), `service_overloaded` (503), `upstream_unavailable` (503), and feature-gate codes such as `timetable_unavailable`, `history_stats_disabled`, `analytics_disabled`, `webhooks_disabled`, `access_logs_disabled`, `access_logs_unavailable`.
- The code set grows. Clients must tolerate unknown codes and surface the error sentence instead.

## Compatibility rules

1. Additive change: new query parameter, new response field, clearer error text, or documentation update. Existing clients keep working.
2. Breaking change: removing or renaming a field, changing a type, or changing meaning or aggregation order. These require a new path prefix (for example `/api/v2/...`) or a clearly announced release, plus a note in this document before the change ships.
3. Unspecifiable edges: live school and textbook data, upstream service response drift, and stale flags caused by caching. The service does not promise stability for those beyond the documented schema.
4. Deployment status, rate-limit thresholds, and monitoring are not contract promises until a decision is recorded here.

## Client identification

- Callers send a self-identified User-Agent instead of relying on a library default. The shipped TypeScript and Python clients are examples.
- Request volume, latency, and errors are service-side observations. They do not block clients by default.

## Status

This document does not replace the machine contract in openapi.yaml. A PR that changes contract behavior updates both.
