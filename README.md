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
| `PLAY_CRICKET_API_KEY` | Sport | Play-Cricket API |
| `BINS_UPRN` | Bins | Your property's UPRN |
| `TWILIO_*` / `RESEND_API_KEY` | Alerts | SMS / email alerts |

## Roadworks & closures

The **Roadworks & closures** section on the site is a **static embed** of the
[one.network Surrey roadworks map](https://one.network/custom/surrey/) with a
visible fallback link. There is **no API, no data collection and no secrets**
behind it — it isn't part of the collector pipeline, so nothing needs to run on
a schedule to keep it current.

> The previous DfT Street Manager integration (the keyless open-data `roads`
> collector and the SNS push-feed `streetworks/` service) has been removed in
> favour of this static embed.

## Running collectors

```bash
pip install -e .
python scripts/collect_all.py                 # all sources
python scripts/collect_all.py --sources crime # just one source
pytest                                        # unit tests (no network/keys)
```
