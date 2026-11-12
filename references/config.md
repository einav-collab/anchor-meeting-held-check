# Anchor Meeting Check: Config

Edit these values to change the routine's behavior. The skill reads them by name.

| Setting | Value | Notes |
|---|---|---|
| `AE_TEAM_NAME` | `Sales (AE)` | HubSpot team. Add or remove AEs in HubSpot; no change is needed here. As of 2026-11-12 it holds Sean Baron, Iain Foshay, Tal Ben Bassat and Jaime Alfaro Sevilla. |
| `EXTRA_AES` | `kit@sayanchor.com` | AEs included even if HubSpot's team data doesn't list them (Kit Reynolds; keitany@sayanchor.com is an alias of the same calendar). Remove someone once the team data shows them. |
| `INTERNAL_DOMAIN` | `sayanchor.com` | Attendees on this domain are internal. |
| `TIMEZONE` | `Asia/Jerusalem` | |
| `SCHEDULE` | Sunday–Friday, 20:00 | The schedule is set where the routine is scheduled; this row is for reference. The AEs are US-based, so many meetings end after the run and are checked on the next run. |
| `LOOKBACK_DAYS` | `7` | Every run checks all meetings from the last 7 days that weren't checked yet. This covers weekends and catches up after failed runs. |
| `RECENT_BUFFER_MINUTES` | `30` | Meetings that ended in the last 30 minutes wait for the next run, so Avoma has time to upload. |
| `MATCH_TOLERANCE_MINUTES` | `15` | Start-time tolerance when matching a meeting across Calendar, HubSpot and Avoma. |
| `OUTCOME_PROPERTY` | `hs_meeting_outcome` (HubSpot's "Meeting outcome") | Written values: `COMPLETED`, `RESCHEDULED`, `NO_SHOW`, `CANCELED`. |
| `EXPLANATION_PROPERTY` | `meeting_outcome__avoma_explanation` (label "Meeting Outcome AI - Explanation") | Text on Meetings. When it's filled, the meeting counts as checked. |
| `HUBSPOT_PORTAL_ID` | `8391286` | Anchor's HubSpot account. `scripts/hubspot.py` refuses to run with a key for any other account. |
| `CALENDAR_ACCOUNT` | Anchor Marketing Google account (marketing@sayanchor.com) | Has read access to all AE calendars. |

## FREE_EMAIL_DOMAINS

Attendees on these domains get a contact but no company:

gmail.com, googlemail.com, outlook.com, hotmail.com, live.com, msn.com, yahoo.com, icloud.com, me.com, aol.com, proton.me, protonmail.com, walla.co.il, walla.com
