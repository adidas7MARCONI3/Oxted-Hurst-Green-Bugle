# Oxted-Hurst-Green-Bugle

An automated hyperlocal newspaper for Oxted and Hurst Green, Surrey (RH8). It
pulls exclusively from official data sources and uses Claude to summarise
content into plain English. See [PRD.md](PRD.md) for the full product spec.

## Configuration

Collectors read their secrets from environment variables (see
[`.env.example`](.env.example) for the full list — copy it to `.env`). Query
parameters that aren't secret live in [`config/settings.yaml`](config/settings.yaml).

| Variable | Used by | Notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | Summariser | Claude API key |
| `DARWIN_API_KEY` | Trains | National Rail Darwin OpenLDBWS |
| `STREET_MANAGER_OPEN_DATA_URL` | Roads | _Optional_ — DfT Street Manager Open Data feed URL (keyless, see below) |
| `PLAY_CRICKET_API_KEY` | Sport | Play-Cricket API |
| `BINS_UPRN` | Bins | Your property's UPRN |
| `TWILIO_*` / `RESEND_API_KEY` | Alerts | SMS / email alerts |

### Roads — DfT Street Manager Open Data (keyless)

The roads collector uses the official **DfT Street Manager Open Data** feed —
the free, public register of UK street and road works. **No API key is
required.** (The live Street Manager API v3 needs a registered-organisation
key; the open-data archive is the keyless route to the same official data.)

* **Feed:** `https://opendata.streetmanager.service.gov.uk/permit/latest.json`
* **Auth:** none — public open data
* **Override:** set `STREET_MANAGER_OPEN_DATA_URL` to pin a specific dated file
* **Docs:** <https://department-for-transport-streetmanager.github.io/street-manager-docs/open-data/>

The open-data feed is national, so it is filtered to Oxted **client-side**:
within **3 km of Oxted town centre** (lat `51.2567`, long `-0.0049`) when a
record carries WGS84 coordinates, otherwise by an area-name match (Oxted /
Hurst Green / Limpsfield / RH8). Each closure item records the street name,
start/end dates (formatted `Mon 8 June – Fri 12 June`), work type, promoter
(who is doing the work), work category (Emergency / Minor / Standard / Major)
and current status (Planned / In progress / Completed), plus two deep links:
one.network for the USRN (`https://one.network/?USRN={usrn}`) and Street
Manager public search
(`https://streetmanager.dft.gov.uk/works/{work_reference_number}`).

If the feed can't be reached the collector logs a notice and yields no items
rather than failing the run.

## Road closures — Street Manager SNS service (`streetworks/`)

The live road/street-works closure map for Oxted & Hurst Green is a **separate,
self-contained FastAPI service** in [`streetworks/`](streetworks/README.md). It
receives **DfT Street Manager open data** as a push feed over **AWS SNS**
(publisher/subscriber) — not a pollable URL — applies a two-stage Surrey-CC +
bounding-box filter, accumulates event deltas into current state (Postgres +
PostGIS, or in-memory for dev), and serves GeoJSON to a Leaflet map.

> **Note:** this supersedes the keyless-poll assumption in the older
> `collectors/roads.py`. That collector is left in place so the existing Bugle
> build keeps working, but the SNS service is the road-data path going forward.
> See [`streetworks/README.md`](streetworks/README.md) for local run, deploy, env
> vars (`SURREY_SWA_CODE`, the bbox) and the manual gov.uk registration step.

```bash
pip install -e ".[streetworks]"
uvicorn streetworks.api:app --reload      # map at http://127.0.0.1:8000/
```

## Running collectors

```bash
pip install -e .
python scripts/collect_all.py                 # all sources
python scripts/collect_all.py --sources roads # just roads
pytest                                        # unit tests (no network/keys)
```
