# NEXUS self-check — auth, paths, dashboard and tests

Date: 2026-07-27. Scope: repository and local processes only.

## Anonymous endpoint matrix (patched server on `127.0.0.1:8002`)

All of the following returned `401` without a token:

- `/api/metrics`
- `/api/metrics/current`
- `/api/metrics/history`
- `/api/metrics/history/multi`
- `/api/metrics/flow`
- `/api/metrics/timeline`
- `/api/metrics/analytics`
- `/api/dashboard/status`
- `/api/dashboard/alerts`
- `/api/dashboard/stream`
- `POST /api/chat`
- `POST /api/dashboard/ask`
- `POST /api/files/read`
- `POST /api/terminal/execute`

The same authenticated server returned `200` for current metrics, history,
flow, analytics, dashboard status and dashboard alerts.

## Path and terminal probes

- Traversal `..\\README.md` under the project root: request reached the route
  but returned an outside-project-root error; no file content leaked.
- Absolute `C:\\Windows\\win.ini`: blocked as a system path.
- Absolute `C:\\Users\\rodri\\Desktop\\nexus\\README.md`: readable because
  the current policy allows absolute paths under the user home/cwd roots.
- Harmless `echo NEXUS_AUDIT_SAFE`: executed and returned `200`.
- `project_path=C:\\Users\\rodri\\Desktop` with `cd`: accepted, showing that
  terminal scope is not tied to the registered/current project.

## Dashboard reality rubric

For the main `/dashboard` route, the visible metric surfaces were classified
from their data source rather than their visual appearance:

- Real/derived from backend telemetry: header model/uptime/freshness, four KPI
  cards, CPU/RAM/disk gauges, agent activity and queue counters, provider status,
  and MCP status.
- Estimated/derived: p95 is approximated from latency samples; usage cost is
  calculated from a rough static price table; unknown-provider token usage can
  be estimated when the provider does not report usage.
- Placeholder/uninstrumented: `/api/metrics/flow` explicitly returns
  `available: false`, empty `nodes` and `links`; the main DashboardClient does
  not render the documented RequestFlow or TokenTimeline widgets.

Using visible data surfaces as the denominator, the defensible summary is:
approximately 60% real/derived telemetry, 25% estimated/heuristic, and 15%
placeholder or absent. This is not a pixel-area claim.

## Red and green checks

- Red before auth correction: anonymous `/api/models/catalog` and
  `/api/metrics/current` returned `200`; the old API test fixture also disabled
  auth globally.
- Green after correction: anonymous metrics/dashboard matrix above is `401`;
  authenticated reads are `200`; backend `compileall` and frontend
  `npm run type-check` pass.
- The backend metrics test file remains red against the new contract because
  it still calls `/api/metrics/current` without auth and asserts `200`.
- Frontend Vitest reports `16` files / `62` tests passing, but several are
  explicit `expect(true).toBe(true)` placeholder tests.

## Secret and URL scan

No bearer token or JWT was stored in the saved SSE/log evidence. The repository
does not track `.env`, `backend/.env` or `frontend/.env.local`; local ignored
files do contain configured secrets, so they must not be committed or copied
into logs. No token-bearing URL was found in the scanned source/log artifacts.
