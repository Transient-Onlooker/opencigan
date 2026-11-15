# Opensigan Client Examples & SDK Guide

Opensigan provides lightweight TypeScript and Python API clients for programmatic integration, local automation, and LLM agent tool use.

## Key Architectural Rules

1. **School ID Separation**
   - **Comcigan School ID**: `학교코드:학교명` (e.g. `2:봄빛고등학교`). Used for timetable queries, iCalendar subscriptions, and timetable change history.
   - **NEIS School ID**: `시도교육청코드:학교코드` (e.g. `B10:1234567`). Returned by NEIS school search and passed to meals.
   - Never mix the two ID types; passing a NEIS ID to `/timetable` or a Comcigan ID to `/meals` results in HTTP 400 `invalid_request`.
2. **Timetable Date Constraints**
   - For JSON timetable, `week` must be the Monday date (`YYYY-MM-DD`) of the **current week** or the **next week** in `Asia/Seoul` time.
   - Any other day of the week or dates outside the 2-week window will be rejected with HTTP 400 `invalid_request`.
   - History accepts any ISO Monday; it returns observations retained for 30 days, not complete past timetables. Pass `nextCursor` as `cursor` for the next page; unconfigured history returns `503 history_disabled`.
3. **Meal Query Range Limits**
   - The `from` and `to` query range can span at most **7 days** inclusive (`(to - from).days <= 6`).
4. **Rolling Calendar Feeds (.ics)**
   - `/api/v1/timetable.ics` supports rolling schedules (`weeks=1` or `weeks=2`), display modes (`periods`, `summary`, or `timed`), and HTTP 304 conditional revalidation with `If-None-Match` / `ETag`.
   - In `timed` mode, client applications can pass an optional `times` query string formatted as comma-separated `period:HHMM-HHMM` entries (e.g. `1:0900-0950,2:1000-1050`). Periods must be 1..20, unique, and strictly nonoverlapping in chronological order.
   - Bell times are interpreted as KST (`Asia/Seoul`) inputs and converted to UTC in the output iCalendar feed (`DTSTART`/`DTEND` in `YYYYMMDDTHHMMSSZ`).
   - Any periods missing from `times` remain explicitly labelled all-day events (`DTSTART;VALUE=DATE` with description note `교시 시각 미설정`).
   - Privacy & Security: Obtain user consent before exporting local times; subscription URLs are visible to the server and calendar sync providers. No profile or bell-schedule data is stored on the server.
5. **Privacy Guardrail**
   - Never send student names, personal allergy lists, or profile information to the API.

JSON timetable and ICS apply `teacher` as a case-insensitive substring (1–50 characters), combined with grade/class filters. ICS requires grade/class and defaults to all-day events (`periods` or `summary`); `timed` mode maps supplied bell times to UTC. NEIS search/meals need the server-side NEIS key. School IDs and dates in snippets are synthetic; replace dates with the current/next KST Monday and use IDs from search.

---

## TypeScript Client (`clients/ts`)

The TypeScript client uses standard `fetch` with zero runtime dependencies. It supports custom base URLs, configurable timeouts, cancellation signals, and structured error handling.

Target Node 22.6+ (type stripping flag) or modern browsers with `AbortSignal.any` and `AbortSignal.timeout`. Timeouts include reading the response body. Caller aborts retain the caller's abort reason. A running API is required; configure `OPENCIGAN_API_BASE_URL` for both runnable examples.

### Installation / Usage

```ts
import { OpensiganClient, OpensiganError } from './clients/ts/index.ts';

const client = new OpensiganClient({
  baseUrl: 'http://127.0.0.1:8000',
  timeoutMs: 10000,
});

// 1. Search school
const search = await client.searchSchools('봄빛');
const schoolId = search.schools[0].id; // "2:봄빛고등학교"

// 2. Fetch timetable with filters
const timetable = await client.getTimetable(schoolId, '2026-11-16', {
  grade: 1,
  class: 2,
  teacher: '교사A',
});

// 3. Calendar subscription URL
const icsUrl = client.getTimetableIcsUrl(schoolId, 1, 2, { weeks: 2, mode: 'periods' });
const timedIcsUrl = client.getTimetableIcsUrl(schoolId, 1, 2, {
  weeks: 2,
  mode: 'timed',
  times: '1:0900-0950,2:1000-1050',
});

// 4. Fetch meals (up to 7 days)
const meals = await client.getMeals('B10:1234567', '2026-11-16', '2026-11-20');
```

---

## Python Client (`clients/python`)

The Python client (`opensigan`) uses Python standard library `urllib` only (zero third-party dependencies).

For scripts outside the example, add `clients/python` to `PYTHONPATH`. Its timeout is a socket-operation timeout, not a total elapsed deadline for a slowly streaming response.

### Installation / Usage

```python
from opensigan import OpensiganClient, OpensiganError

client = OpensiganClient(base_url="http://127.0.0.1:8000", timeout=10.0)

# 1. Search school
res = client.search_schools("봄빛")
school_id = res["schools"][0]["id"]

# 2. Fetch timetable
try:
    timetable = client.get_timetable(school_id, "2026-11-16", grade=1, classroom=2)
    print(timetable["records"])
except OpensiganError as e:
    print(f"Error ({e.status}, {e.code}): {e}")

# 3. Calendar subscription URL
ics_url = client.get_timetable_ics_url(school_id, grade=1, classroom=2, weeks=2, mode="periods")
timed_ics_url = client.get_timetable_ics_url(
    school_id, grade=1, classroom=2, weeks=2, mode="timed", times="1:0900-0950,2:1000-1050"
)

# 4. Fetch meals
meals = client.get_meals("B10:1234567", "2026-11-16", "2026-11-20")
```

---

## Running the Examples

### TypeScript Example
```bash
# Node 22.6+ with built-in type stripping
node --experimental-strip-types examples/ts/example.ts
```

### Python Example
```bash
python examples/python/example.py
```

Both examples accept an optional school-name search as the final argument. They show the first result for demonstration; confirm the NEIS school match before using it in an application. They report request failure with a nonzero exit status when the API is unavailable.

---

## Error Handling Reference

Both clients raise structured error types (`OpensiganError`) containing:
- `status`: HTTP status code (e.g. 400, 404, 429, 503)
- `code`: API machine-readable error code (`invalid_request`, `not_found`, `upstream_unavailable`, `history_disabled`, `rate_limited`)
- TypeScript `isTimeout` / Python `is_timeout`: timeout flag
- TypeScript `isNetworkError` / Python `is_network_error`: connection/read failure flag
- Client-only `invalid_response`: malformed/empty JSON or a non-object success response; `status` preserves the HTTP status.
- Client-only `invalid_config`: invalid absolute HTTP(S) base URL or timeout. Base URLs may include a deployment prefix; credentials, query strings and fragments are rejected. Timeouts must be positive finite seconds (Python), or integer milliseconds 1–2147483647 (TypeScript).

Run boundary tests from the repository root:

```bash
node --experimental-strip-types clients/ts/tests/client.test.ts
python -B clients/python/tests/test_client.py
python -B clients/python/tests/test_backend_contract.py
```
