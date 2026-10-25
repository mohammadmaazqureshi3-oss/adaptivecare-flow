# 0002 — The gateway enforces roles; services trust its identity headers

**Status:** accepted · **Sprint:** 1 · **Stories:** AUTH-03 · **NFRs:** NFR-SEC-01, NFR-SEC-02

## Context
Every service needs to know who is acting (for example the designer records the author
of each version), and every route must enforce the permission matrix in plan Section 10.

## Decision
1. The permission matrix lives in one place, `services/gateway/gateway/permissions.py`.
   Each route has its service and allowed roles. Unknown routes get 404 (deny by default).
2. The gateway checks the access token (HS256, 15 minutes) and the role, then forwards the
   request with `X-User-Id`, `X-User-Email` and `X-User-Role`.
3. Services behind the gateway trust these headers. They are reachable only on the Compose
   network; no service port except the gateway's is published to the host.
4. The auth service checks the admin role again on `/users` (defence in depth), because it
   holds the signing secret anyway.
5. The web app keeps the access token in memory and the refresh token (8 hours) in
   `sessionStorage`, so it survives a reload but not closing the tab.

## Consequences
- The matrix is tested in one place: every route × every role (`test_nfr_sec02_permission_matrix`).
- A role change takes effect at the user's next refresh, within 15 minutes.
- Limitation (for the report): a compromised container on the internal network could forge
  the headers. Mutual TLS or signed internal tokens would close this. An `httpOnly` refresh cookie
  would protect the refresh token from injected scripts better than `sessionStorage`.
  Both are listed as future work.
