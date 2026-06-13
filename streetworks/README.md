# Street Manager road-closure feed — Oxted & Hurst Green

A small production service that ingests **DfT Street Manager open data**, filters
it to **Oxted and Hurst Green (Surrey)**, maintains the **current state** of
road/street works and closures, and serves them as live GeoJSON for a Leaflet
map and a list view.

It lives alongside the Bugle collectors but is **self-contained**: its own
FastAPI app, its own (optional) Postgres/PostGIS store, its own deps.

---

## How the data actually arrives

Street Manager open data is a **push feed over AWS SNS** (publisher/subscriber).
It is **not** a pollable REST API and there is no anonymous public file dump. The
service exposes a public **HTTPS POST** endpoint (`/sns`) that AWS SNS calls when
events occur.

- Three production SNS topics, region `eu-west-2`, account `287813576808`:
  - `arn:aws:sns:eu-west-2:287813576808:prod-permit-topic`
  - `arn:aws:sns:eu-west-2:287813576808:prod-activity-topic`
  - `arn:aws:sns:eu-west-2:287813576808:prod-section-58-topic`
- The feed is **event-driven deltas**, not snapshots. Current state is assembled
  by accumulating events; **the DB starts empty and fills as events arrive.**
- Each HTTP call is an **SNS envelope** (`Type` = `SubscriptionConfirmation`,
  `Notification`, or `UnsubscribeConfirmation`). For a `Notification`, the
  `Message` field is itself a JSON string containing `event_type` and
  `object_data`.
- Coordinates in `object_data` are WKT in **British National Grid (EPSG:27700)**;
  we convert to **WGS84 (EPSG:4326)** for the map and keep both.

### ⚠️ Cold-start caveat

Because the feed is deltas-only and there is **no anonymous backfill**, the map
is **empty until live events arrive** and will only ever show works that changed
*after* the subscription was confirmed. A gated hourly CSV "Data Export" exists
behind JWT auth — it is treated as an **optional future backfill only** and is
not implemented or depended on here.

---

## The two-stage filter (how it's scoped to the area)

1. **Stage 1 — authority.** Keep a record only if the highway authority is Surrey
   County Council, by the SNS `ha_org` attribute **or** the body field
   `highway_authority_swa_code` equalling `SURREY_SWA_CODE`. (In two-tier England
   the *county* is the street authority, so all Oxted/Hurst Green permits sit
   under Surrey CC — not Tandridge DC.)
2. **Stage 2 — geography.** After converting to WGS84, keep only records whose
   representative point falls inside the configured bounding box. An optional
   USRN allow-list can refine this further once real USRNs are known.

---

## Configuration (environment variables)

| Variable | Default | Meaning |
| --- | --- | --- |
| `SURREY_SWA_CODE` | `0000` (placeholder) | Surrey CC's Street Works Authority code. **Drop the real value in when known — not a blocker.** |
| `BBOX_MIN_LAT` / `BBOX_MAX_LAT` | `51.225` / `51.275` | Latitude band covering Oxted & Hurst Green |
| `BBOX_MIN_LON` / `BBOX_MAX_LON` | `-0.045` / `0.025` | Longitude band |
| `SNS_VERIFY_SIGNATURES` | `true` | Verify SNS message signatures. **Leave on in production.** |
| `HEALTH_MAX_SILENCE_HOURS` | `6` | `/healthz` reports `degraded` (503) if no message has arrived in this many hours |
| `DATABASE_URL` | _unset_ | Postgres/PostGIS DSN. When unset, an **in-memory store** is used (fine for dev/tests; state is lost on restart) |

---

## Run it locally

```bash
pip install -e ".[streetworks]"          # service deps (FastAPI, pyproj, …)
uvicorn streetworks.api:app --reload      # http://127.0.0.1:8000
```

- Map + list: <http://127.0.0.1:8000/>
- GeoJSON of active closures: <http://127.0.0.1:8000/closures>
- Health: <http://127.0.0.1:8000/healthz>
- SNS webhook (what AWS posts to): `POST /sns`

With no `DATABASE_URL` the in-memory store is used, so the map is empty until you
POST an SNS `Notification` to `/sns`. The tests under `tests/test_streetworks_*`
show the exact envelope shape.

### With Postgres + PostGIS

```bash
createdb streetworks
psql "$DATABASE_URL" -f streetworks/db/schema.sql   # one-off migration
export DATABASE_URL=postgresql+psycopg://user:pass@localhost/streetworks
uvicorn streetworks.api:app
```

The schema is idempotent and safe to re-run. Upserts are order-tolerant: an event
only updates state when its `(version, event_time)` is newer-or-equal to what is
stored, so a replayed or out-of-order stream converges to the same answer.

---

## The read API — `GET /closures`

Returns a GeoJSON `FeatureCollection` of **active** closures (proposed or in
progress) by default. Filters (all optional query params):

| Param | Example | Notes |
| --- | --- | --- |
| `status` | `in_progress` | `proposed` / `in_progress` / `completed` / `inactive`. Overrides the active-only default. |
| `traffic_management_type` | `Road closure` | Exact match on the closure type |
| `work_category` | `Major` | Exact match |
| `start_date` / `end_date` | `2026-06-08` | ISO date; inclusive overlap with the proposed window |

Each feature carries the geometry in WGS84 plus all the stored properties
(references, promoter, street, USRN, dates with separate time fields, both
geometries, status, …).

---

## Status lifecycle

Events drive a small state machine (`streetworks/events.py`):

```
permit submitted/granted, activity created  → proposed   (active)
work-start, section-58-in-force             → in_progress(active)
work-stop, section-58-ended                 → completed
permit cancelled/revoked/refused            → inactive
work-start-reverted                         → roll back to proposed
work-stop-reverted                          → roll back to in_progress
```

Event-type spellings are normalised (`WORK_START`, `work-start`, `Work Start` →
one enum), so cosmetic differences across topics/versions don't matter.

---

## Deployment & the manual gov.uk registration step

1. Deploy the service somewhere with a **stable public HTTPS URL** (the webhook
   must be reachable by AWS SNS). Point it at a Postgres/PostGIS database via
   `DATABASE_URL` and set the real `SURREY_SWA_CODE`.
2. Apply the migration: `psql "$DATABASE_URL" -f streetworks/db/schema.sql`.
3. **The website owner registers for the feed manually** via the gov.uk page
   *"Find and use roadworks data"* and supplies the public endpoint URL
   (`https://your-host/sns`). This step is performed by a human after deploy and
   is **not** automated.
4. On first contact AWS SNS sends a `SubscriptionConfirmation`; the service
   validates the topic ARN and GETs the `SubscribeURL` to confirm. After that,
   `Notification`s flow in and the map begins to populate.

Operations notes: unparseable/rejected payloads are logged with a reason (the
hook for a dead-letter queue); out-of-area records are dropped silently-by-design
but counted in the logs; `/healthz` returns `503 degraded` if the feed goes quiet
for `HEALTH_MAX_SILENCE_HOURS`, which an external monitor can alert on.

---

## Assumptions & decisions recorded here (per the brief)

- **This service supersedes the earlier keyless-poll roads collector**
  (`collectors/roads.py`). That collector assumed a pollable open-data JSON URL;
  the authoritative model is the SNS push feed implemented here. The old
  collector is left untouched so the existing Bugle build and its tests keep
  working; this service is the road-data path going forward.
- **`SURREY_SWA_CODE` defaults to the placeholder `0000`.** Everything is built
  around the env var; the real code drops in with no code change. Tests and the
  bundled fixtures use `0000` so they're self-consistent.
- **Store backend.** Postgres + PostGIS is the production store (schema +
  migration provided). The default in-memory store keeps the service and the test
  suite runnable with zero infrastructure; it is not durable.
- **Geometry support.** WKT `POINT` and `LINESTRING` are converted; other WKT
  types are rejected (logged) rather than guessed at.
- **Bounding box over polygon.** Stage 2 uses a rectangular bbox by default; a
  precise polygon/USRN allow-list is supported in code as a later refinement.

---

## Tests

```bash
pip install -e ".[dev]"
pytest tests/test_streetworks_acceptance.py tests/test_streetworks_unit.py
```

The **acceptance test** (`tests/test_streetworks_acceptance.py`) is the headline:
a sample SNS `Notification` for a permit `work-start` on an Oxted street flows
end-to-end — signature path stubbed → parsed → Stage 1 SWA filter → coords
converted → Stage 2 bbox filter → upserted → returned by `GET /closures` as
GeoJSON with the correct status and geometry — and a Surrey permit outside the
box (Guildford) is excluded.
