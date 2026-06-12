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
| `STREET_MANAGER_API_KEY` | Roads | DfT Street Manager API v3 (see below) |
| `PLAY_CRICKET_API_KEY` | Sport | Play-Cricket API |
| `BINS_UPRN` | Bins | Your property's UPRN |
| `TWILIO_*` / `RESEND_API_KEY` | Alerts | SMS / email alerts |

### Roads — DfT Street Manager API v3

The roads collector uses the official **DfT Street Manager API v3**, the UK
government register of street and road works.

* **Base URL:** `https://api.streetmanager.dft.gov.uk/street-manager-api/v3`
* **Auth:** Bearer token from the `STREET_MANAGER_API_KEY` environment variable
* **Works search:** `GET /works?latitude=51.2567&longitude=-0.0049&radius=3000`
* **Docs:** <https://department-for-transport-streetmanager.github.io/street-manager-docs/api-documentation/>

Works are filtered to within **3 km of Oxted town centre** (lat `51.2567`,
long `-0.0049`). Each closure item records the street name, start/end dates
(formatted `Mon 8 June – Fri 12 June`), work type, promoter (who is doing the
work), work category (Emergency / Minor / Standard / Major) and current status
(Planned / In progress), plus two deep links: one.network for the USRN
(`https://one.network/?USRN={usrn}`) and Street Manager public search
(`https://streetmanager.dft.gov.uk/works/{work_reference_number}`).

If `STREET_MANAGER_API_KEY` is unset the collector logs a notice and yields no
items rather than failing the run.

## Running collectors

```bash
pip install -e .
python scripts/collect_all.py                 # all sources
python scripts/collect_all.py --sources roads # just roads
pytest                                        # unit tests (no network/keys)
```
