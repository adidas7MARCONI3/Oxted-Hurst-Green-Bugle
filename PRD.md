# Product Requirements Document — Oxted & Hurst Green Bugle

> **Single source of truth.** This document defines the product. All development
> decisions should be made in accordance with it. If a proposed change conflicts
> with this PRD, the PRD wins until it is updated.

## Overview

The **Oxted & Hurst Green Bugle** is an automated hyperlocal newspaper for Oxted
and Hurst Green, Surrey (RH8 postcode). It pulls exclusively from official data
sources and uses Claude AI to summarise content into plain English.

## Area Facts

| Field | Value |
| --- | --- |
| Area | Oxted and Hurst Green, Surrey |
| Postcode | RH8 |
| Coordinates | 51.2567° N, 0.0049° W |
| Local authority | Tandridge District Council (LPA code: `TAN`) |
| Train stations | Oxted (`OXT`) and Hurst Green (`HUR`), Southern Oxted line |
| Sports clubs | Oxted & Limpsfield CC, Oxted FC, Oxted HC (Men's Premier Division) |

## Data Sources

> **Official sources only.** Never scrape community aggregators such as Love Oxted.

| Section | Source |
| --- | --- |
| Crime | [data.police.uk](https://data.police.uk) free API |
| Planning | planning.data.gov.uk API + Tandridge portal scraper |
| Courts | National Archives Find Case Law API (search for Oxted, Hurst Green, Tandridge) |
| Council | Tandridge DC + Oxted Parish Council + Surrey CC scrapers |
| Property | HM Land Registry SPARQL endpoint (RH8 postcodes) |
| Trains | National Rail Darwin API (stations `OXT` and `HUR`; alert on 10+ min delays or cancellations; weekdays 5am–10am only) |
| Bins | Tandridge SOAP API (Blue week = recycling fortnightly, Grey week = rubbish fortnightly, food caddy weekly) |
| Events | Barn Theatre + Master Park + Oxted School official sites only. Community submissions via form, reviewed before publishing. **Never scrape Love Oxted.** |
| Sports | Play-Cricket API (site ID `12864`), FA Full-Time scraper, hockeyfixtures.co.uk scraper |

## Editorial Principles

1. **Official sources only** — no rumours, no social media, no unverified information.
2. **No editorial agenda** — report facts neutrally.
3. **Plain English always** — Claude summarises into readable language.
4. **Attribution mandatory** — always link to the original source.
5. **Not a social platform** — no comments, no user accounts.
6. **Local advertising may be considered in future** — local businesses only,
   clearly labelled, with no influence on editorial.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Backend | Python collectors running on GitHub Actions cron |
| AI | Claude API (`claude-sonnet`) for summarisation |
| Storage | JSON files committed to the GitHub repo |
| Frontend | Single static HTML file |
| Hosting | GitHub Pages |
| SMS alerts | Twilio (~4p per SMS) |
| Email alerts | Resend (free tier) |
| Event submissions | Formspree |

## Alert System

- **Train disruptions** — SMS + email when delay ≥ 10 minutes or a cancellation
  occurs; weekdays 5am–10am; checked every 5 minutes.
- **Bin day reminders** — SMS + email the evening before collection day.

## Site Sections

Front page · Planning · Property · Crime · Council · Courts · Environment ·
Trains · Sport · Bins · What's On

## Future Backlog

> Not in current scope.

- Progressive Web App (PWA) — do this **before** any native app.
- Native iPhone app (React Native) — only after the PWA and a proven user base.
- More sports: Oxted Rugby Club, junior football.
- Postcode-level planning alerts.
- Weekly email digest.
- Road works and Surrey Highways data.
- School term dates.

## What the Site Is NOT

- Not a replacement for journalists.
- Not a social platform or forum.
- Not a real-time news wire (except train alerts).
- Not a source for national news.
- Not for political campaigning.
- **Advertising:** local businesses only, clearly labelled, never influences editorial.
