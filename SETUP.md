# Anchor Meeting Check: Setup Guide

Every evening, Sunday to Friday at 20:00 Israel time, this routine checks each external AE meeting from the last 7 days that it hasn't checked yet. It sets HubSpot's own **Meeting outcome** to Completed, Rescheduled, No show or Canceled, and writes a one-line reason in **Meeting Outcome AI - Explanation**. It also creates meetings that are missing from HubSpot and removes clear duplicate meeting records.

It reads Google Calendar and Avoma and never changes them. In HubSpot it changes only those two meeting fields, creates missing meetings, contacts and companies, and deletes clear duplicate meetings (after saving a backup).

**Needs:** Claude Desktop (the Code tab), a Mac or PC that's on at 20:00 Israel time, and `python3`.

---

## 1. Create the routine's folder

1. Create a dedicated folder, for example `Anchor Meeting Check`. Use it only for this routine.
2. Inside it, create `.claude/skills/` and unzip the skill there, so you get:
   `Anchor Meeting Check/.claude/skills/anchor-meeting-held-check/SKILL.md`
3. Copy `anchor-meeting-held-check/security/settings.json` to `Anchor Meeting Check/.claude/settings.json`. This turns on the security guard, which blocks any action other than the allowed ones.

## 2. Connect Google Calendar (Claude → Settings → Connectors)

Connect **Google Calendar**, signed in as **marketing@sayanchor.com**. That account needs read access to every AE's calendar.

No HubSpot or Avoma connector is needed: both are reached with API keys (steps 3 and 4).

## 3. Create the HubSpot key

1. In HubSpot, make sure you're in the **Anchor** account (8391286): check the account switcher in the top-right corner.
2. Go to **Settings → Integrations → Private Apps** (called **Service Keys** in some accounts) and create one, for example "Meeting Check".
3. Give it these scopes:
   - `crm.objects.contacts.read`, `crm.objects.contacts.write`
   - `crm.objects.companies.read`, `crm.objects.companies.write`
   - `crm.objects.deals.read`
   - `crm.objects.owners.read`, `crm.objects.users.read`
   - `settings.users.teams.read`
   - `sales-email-read`
   - if HubSpot also lists them: `crm.objects.meetings.read` and `crm.objects.meetings.write`
4. Create it and copy the key (it starts with `pat-`).

## 4. Create the Avoma key

In Avoma (as an admin), go to **Settings → Organization → Developer → Add API Key**. Set the scope to **Organization limited**, then copy the key.

## 5. Save both keys in the folder

In Claude Desktop, open the folder's **Environment variables** and add two lines:

```
HUBSPOT_API_KEY=<the HubSpot key>
AVOMA_API_KEY=<the Avoma key>
```

Never put the keys in a file or a chat. Then quit and reopen Claude Desktop: sessions only read environment variables when they start.

## 6. Check the connections

Open a new session in the folder and type:
> Run the anchor meeting check preflight only.

All three must pass: HubSpot ("OK: HubSpot key works for Anchor's portal 8391286"), Avoma ("OK: Avoma API reachable") and Google Calendar. If HubSpot says the key isn't for Anchor's portal, the key was created in another HubSpot account: redo step 3 in the Anchor account.

## 7. Test it (nothing is written)

In the same session, type:
> Run the anchor meeting check as a dry run.

You should get a table of last week's meetings with the outcome and explanation each would get, and the run log should show no errors.

## 8. Schedule it

In Claude Desktop's **Code tab**, open a session **in this folder** and type:
> Create a scheduled task in this folder: Sunday to Friday at 20:00 Israel time, prompt "Run the anchor-meeting-held-check skill."

Check the time it uses: scheduled tasks run on **the computer's local time**. On a US computer, 20:00 Israel time is midday (for example about 12:00 Chicago time), and the gap moves by an hour for a few weeks a year when Israel and the US change clocks on different dates. Scheduled tasks run while Claude Desktop is open; if it's closed at run time, the task runs the next time it opens.

In the task's settings, use a permission mode that doesn't prompt, so the run doesn't wait for approvals. The security guard still blocks everything outside the allowed list.

## 9. After the first real run

Open a few meetings in HubSpot and check **Meeting outcome** and **Meeting Outcome AI - Explanation**. The run log at the end of the task shows the counts, any duplicates it deleted or left for review, and any errors. Backups of deleted duplicates are in the skill's `backups/` folder.

---

**Changing settings:** the AE list, timings and property names are in `references/config.md`. AEs come from the HubSpot team **Sales (AE)**. Anyone the team data misses goes under `EXTRA_AES` (Kit is there today).

**Re-checking a meeting:** clear its **Meeting Outcome AI - Explanation**. The next run (within 7 days of the meeting) checks it again.

**If a run fails:** nothing is written for meetings it couldn't check, and the next run catches up, because it always looks back 7 days.
