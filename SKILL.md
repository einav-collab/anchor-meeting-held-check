---
name: anchor-meeting-held-check
description: Daily routine for Anchor (sayanchor.com) that checks what happened in every external AE meeting. Reads the AE calendars, makes sure each meeting is logged in HubSpot (creating the meeting, contacts and company when missing), checks the Avoma recording and HubSpot activity, and sets HubSpot's own Meeting outcome to Completed, Rescheduled, No show or Canceled, with a one-line reason in "Meeting Outcome AI - Explanation". Also removes clear duplicate meeting records. Use this skill whenever the Anchor meeting-check routine runs, or when someone asks to "check if Anchor's meetings were held", "run the meeting check", "update meeting outcomes for Anchor", "בדוק אם הפגישות של אנקור התקיימו", or wants a dry run of it.
---

# Anchor: Meeting Check

Anchor's AEs book external meetings. Anchor needs to know, for every one of them, what really happened. This routine answers that and writes the answer on the meeting in HubSpot. HubSpot is the only output: no summary is sent anywhere.

All settings (team name, domain, timings, property names) are in `references/config.md`. Read it first. The rules below refer to those values by name.

## Ground rules

- **Each meeting is decided once.** A meeting whose `EXPLANATION_PROPERTY` already has text was checked before (by this routine or a person): skip it. To have a meeting checked again, clear that field.
- **The evidence wins over the AE.** `OUTCOME_PROPERTY` is HubSpot's own Meeting outcome, which AEs also set. The routine overwrites it, and the explanation always records what was there before, for example `(AE outcome was Completed)`.
- **Decide only on full data.** If Calendar, HubSpot or Avoma can't be reached, or a lookup fails for a meeting, write nothing for that meeting. It stays unchecked and the next run picks it up through the lookback window. A wrong outcome is worse than a late one.
- **Avoma is read-only.** The routine only reads meetings and transcripts from Avoma; all results go to HubSpot.
- **Dry run.** If the run is started as a dry run ("dry run", "test", "בלי לעדכן"), do every step but make no writes, creates or deletes in HubSpot. Print what would have been done instead.

## Allowed actions (security layer)

| System | How | Allowed | Never |
|---|---|---|---|
| Google Calendar | Calendar connector (MCP), signed in as `CALENDAR_ACCOUNT` | Read calendars and events | Create, change, delete or respond to events |
| Avoma | `scripts/avoma.py` (key in `AVOMA_API_KEY`) | Read meetings and transcripts (GET only) | Any change in Avoma |
| HubSpot | `scripts/hubspot.py` (key in `HUBSPOT_API_KEY`) | Read records and activity; set `OUTCOME_PROPERTY` and `EXPLANATION_PROPERTY` on meetings; create a missing meeting, contact or company (Step 2); delete a clear duplicate meeting (Step 5) | Change any other property, change associations on existing records, delete anything else |
| Everything else | — | — | Other connectors, editing files, web access |

`security/guard.py` enforces this list: it checks every action before it runs and blocks anything not listed (`security/policy.json` holds the list). The HubSpot script also checks, on every run, that its key belongs to Anchor's portal (`HUBSPOT_PORTAL_ID`), and only accepts the four outcome values. If an action is blocked, don't look for a way around it; record it under Errors in the run log.

**Running commands under the guard.** The guard only accepts the two scripts by their real path, worked out from the session's current folder. A scheduled run starts in the routine's folder, so either call them by their full relative path (`python3 .claude/skills/anchor-meeting-held-check/scripts/hubspot.py check`), or first run `cd .claude/skills/anchor-meeting-held-check` as a command of its own and then use `scripts/…` as written below. `cd … && python3 scripts/…` in one command is blocked. The guard also blocks `>` anywhere in a command (including inside `jq` filters: flip comparisons to use `<`), `$(…)`, backticks and redirection.

## Step 0: Preflight

1. Check the connections: `python3 scripts/hubspot.py check`, `python3 scripts/avoma.py check`, and one `list_calendars` call on the Calendar connector. If any of them fails, stop and print which one. The lookback window makes a skipped run safe.
2. Work out the time window in `TIMEZONE`:
   - **Start:** now minus `LOOKBACK_DAYS`
   - **End:** now minus `RECENT_BUFFER_MINUTES`. A meeting that ended after this point is left for the next run, because Avoma may not have uploaded the recording yet.

   All script times are ISO 8601 in UTC (for example `2026-11-01T00:00:00Z`).

### Keep the run fast

Read each source once for the whole window, then match in memory. Don't look things up meeting by meeting.

- **Calendar:** one `list_events` call per AE for the window. Keep the full list, including declined and cancelled events: Steps 2b and 3 use it. Large results are saved to a file: filter them with `jq` instead of reading them whole.
- **HubSpot meetings:** one `hubspot.py meetings --from --to` call for the window (all owners). Then one `hubspot.py assoc --ids <id,id,…> --to contacts` call, and `hubspot.py contacts --ids <id,id,…>` for the contacts' emails. IDs are always one comma-separated value, with no spaces.
- **Avoma:** one `avoma.py meetings --from --to` call for the window (chunks of at most 7 days), matched in memory. Fetch a transcript only for a meeting that still needs a decision and that Avoma shows as recorded.
- **Skip early:** drop meetings whose `EXPLANATION_PROPERTY` is already filled before any Avoma or activity lookup.
- **Activity (`hubspot.py activity`):** only for meetings with no usable recording.
- **Writes:** one `hubspot.py set-outcome` call with all the decided meetings (it batches and reads back by itself).

## Step 1: Collect the meetings from the AE calendars

1. `python3 scripts/hubspot.py aes --team "<AE_TEAM_NAME>" --extra "<EXTRA_AES>"` returns the AE list: email, owner ID and name.
2. For each AE, read the calendar events in the window through the Calendar connector (`calendarId` = the AE's email). If one AE's calendar can't be read, skip that AE, list it under Errors in the run log, and continue with the others.
3. Keep an event as a meeting only if **all** of these are true:
   - At least one attendee's email is **not** on `INTERNAL_DOMAIN`
   - It has a video link (Zoom, Google Meet, Teams or similar), in the conferencing data, location or description. Anchor's Zoom links usually appear in the conferencing data, either as a Zoom solution or as joining notes that start with "Meeting host: …@sayanchor.com"
   - It's a regular event (not out-of-office or focus time) and not all-day
   - It isn't a recruiting interview (Comeet "Interview" events)
4. Events the AE declined or that were cancelled are **not** dropped: they are meetings that didn't happen, decided in Step 3.
5. **Remove duplicates.** When two AEs are on the same event, it's one meeting (match by the event's iCalUID). The owner is the AE who organized it; if no AE organized it, use the first AE attendee.
6. For each meeting, keep: owner AE (email + owner ID), title, start and end time, external attendees (email, display name and response status), and the calendar event ID / iCalUID.

## Step 2: Make sure the meeting is in HubSpot

**Find it** in the HubSpot meeting list from the fast-run reads: a meeting that starts within `MATCH_TOLERANCE_MINUTES` and has at least one of the external attendees as an associated contact, **whatever its owner**. A meeting an AE attended may be owned in HubSpot by someone else (for example Customer Success): use it and keep its owner, so no duplicate is created under the AE.

| Found | Action |
|---|---|
| Once | Use it. If its `EXPLANATION_PROPERTY` is filled, skip the meeting entirely. |
| More than once | Use the record linked to Avoma: the one whose internal notes have the Avoma notes link (`app.avoma.com/meetings`), or else the one Avoma created (`hs_object_source_detail_1` = "Avoma - AI Meeting Assistant"), or else the one with the most data. The others are duplicates, handled in Step 5. |
| Not found | Create it, as below. |

**Create a missing meeting:**
1. **Contacts.** For each external attendee, `hubspot.py find-contact --email`. Use the contact if it exists. If not, `hubspot.py create-contact --email --owner <AE owner ID> --first --last` (names from the calendar display name, when there is one).
2. **Company.** For each attendee's email domain, `hubspot.py find-company --domain`. Use it if it exists, or `hubspot.py create-company --domain --owner`. Skip this step for domains on `FREE_EMAIL_DOMAINS`: a "Gmail" company is noise.
3. **Meeting.** `hubspot.py create-meeting --owner --title --start --end --contacts <ids> --companies <ids>`.

Records created here are the routine's own work. Don't count them as "activity" in Step 3.

## Step 2b: HubSpot meetings that aren't on the calendar

A meeting that is in HubSpot but not on the AE's calendar was usually cancelled or removed. Take the meetings from the HubSpot list you already pulled that:
- are owned by an AE from the AE list
- have at least one associated contact whose email isn't on `INTERNAL_DOMAIN`
- weren't logged by the Zoom integration (`hs_meeting_source` is not `INTEGRATION`): those are support sessions, internal calls and copies of real meetings
- don't have "Interview" in the title
- have an empty `EXPLANATION_PROPERTY`
- didn't match any calendar meeting in Step 2 (check against the calendar events already read in Step 1; don't read the calendar again)

Decide each one with Step 3, like any other meeting. The explanation says the meeting wasn't on the calendar, for example `Canceled: not on Sean's calendar; Avoma shows the booking cancelled by the prospect on 2 Nov.`

## Step 3: Decide the outcome

Go through these in order and take the **first** one that fits.

### 1. Completed: the meeting happened

Either of these:
- **An Avoma recording where the AE had a real conversation with at least one person from outside Anchor.** Length doesn't matter: a 3-minute call where the prospect says "this isn't relevant for us" happened. An unnamed speaker (for example "Speaker 2", someone who dialed in by phone) counts as external when the AE is clearly talking *with* them. A prospect who joined only to say "let's reschedule" does **not** count: that meeting didn't happen.
- **No usable recording, but HubSpot activity that is certainly about this meeting and shows it happened.** Read it with `hubspot.py activity --since <meeting start> --contact <id> --company <id>`. Counts: a note the AE logged about the call, a follow-up email about what was discussed, a logged call with the contact, a deal created or moved because of the meeting. The activity has to be clearly tied to this meeting; company-level activity about someone else or another meeting doesn't count. If you can't tell for sure, ignore it.

Find the recording in the Avoma list by AE as host, start time within `MATCH_TOLERANCE_MINUTES` and attendee emails, then read the transcript with `avoma.py transcript <uuid>`. A recording with no external participant (the AE alone, only Anchor people, the bot in an empty room, silence) means the meeting didn't happen. A recording that stops abruptly well before the scheduled end, with no external participant, can't be trusted: treat it as no recording.

### 2. Rescheduled: it didn't happen, but there is a later meeting

The meeting didn't happen, and HubSpot has a **later** meeting with the same prospect: `hubspot.py meetings --contact <id> --from <this meeting's end> --to <now + 60 days>`, ignoring duplicate records of this same meeting. A later meeting logged without the contact (for example a contact-less Zoom record) counts only when the emails clearly tie it to this prospect.

### 3. Canceled: it didn't happen, and the prospect told us beforehand

The meeting didn't happen, and the prospect told us **before the start time** that they wouldn't join. Look at everything from the day the meeting was booked (`hs_createdate`) until the start time:
- the prospect declined the calendar event, and the event was last changed before the start time
- an email, call or note from or about the prospect saying they can't make it, want to reschedule or are cancelling
- Avoma shows the booking cancelled before the start

There is no minimum notice: a decline 5 minutes before the start still counts. If the event was moved to a new time after the prospect declined, and the prospect never accepted the new time, the decline still counts.

### 4. No show: it didn't happen, and the prospect didn't tell us

Everything else: no real conversation, no later meeting, and no notice before the start. Messages the prospect sent **after** the start ("sorry, I missed it") don't change this.

**These are never evidence:** marketing emails and newsletters, automated sequence steps, enrichment or integration updates (Apollo, ZoomInfo and similar), Avoma's automatic notes, tasks created automatically, and anything this routine created in Step 2.

## Step 4: Write to HubSpot

Write all decided meetings in one call:

```
python3 scripts/hubspot.py set-outcome --json '[{"id":"<meeting id>","outcome":"NO_SHOW","explanation":"..."}]'
```

- `outcome` is the stored value: `COMPLETED`, `RESCHEDULED`, `NO_SHOW` or `CANCELED`.
- `explanation` is one short line in English: the value, the evidence, and the AE's previous outcome. Name people by first name, never by email address. Examples:
  - `Completed: 42-min recording, Dana in two-way conversation with Sean. (AE outcome was Scheduled)`
  - `Completed: no recording; Sean logged a note and sent a follow-up about the pricing they discussed. (AE outcome was Completed)`
  - `Rescheduled: silent recording; Megan met Jaime later on 22 Oct. (AE outcome was Completed)`
  - `Canceled: no recording; Jeff declined the invite on 12 Oct. (AE outcome was Scheduled)`
  - `No show: silent recording; Rita never declined or wrote; no later meeting. (AE outcome was Completed)`
- Inside the JSON, write an apostrophe as `'\''` (the shell command is wrapped in single quotes). Don't use `>` anywhere in the text: the guard blocks it.

The script writes both fields together, reads them back, and exits with an error listing any meeting that wasn't saved. Record those under Errors.

## Step 5: Delete duplicate meetings

For each meeting with more than one HubSpot record (Step 2), keep the record linked to Avoma and delete the others, but only when they're clearly copies.

1. **Delete only a clear copy:** same contacts as the kept record (and at least one), start within 15 minutes, and the same video link or none. A copy with no contacts, different contacts or a different link is **not** deleted: list it under "Duplicates to review" in the run log.
2. **Keep the outcome.** Write the outcome on the kept record first (Step 4).
3. **Delete:** `python3 scripts/hubspot.py delete-duplicate <copy_id> --keep <kept_id>`. The script checks the copy rules again itself, saves a backup in `backups/`, deletes the copy (HubSpot moves it to the recycling bin) and confirms it's gone. If it refuses, list the record for review; never delete another way.
4. In a dry run, don't delete: list what would have been deleted.

## End of run: run log

There's no summary to send, but print a short log at the end so the run history shows what happened:

```
Anchor meeting check: <date> 20:00
Window: <start> → <end>
Meetings found: N | already checked (skipped): N | created in HubSpot: N (contacts +N, companies +N)
Completed: N | Rescheduled: N | Canceled: N | No show: N | Deferred (no data or error): N
Not on the calendar (Step 2b): N
Changed the AE's outcome: N
Duplicates: deleted N | to review N (<meeting IDs>)
Errors: <one line each, or "none">
```

In a dry run, also list each meeting with the outcome and explanation it would have received.
