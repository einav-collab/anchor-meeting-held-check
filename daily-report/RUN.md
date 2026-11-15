# Daily AE meetings Slack report

A weekday Slack message with the previous business day's external AE meetings: planned, attended,
rescheduled, canceled, no-show, not logged, show rate and no-show rate, plus a line per AE.

All data comes from **Beacon** (BigQuery project `production-275007`, table
`hubspot.engagement_meeting`, synced hourly). Nothing is read from or written to HubSpot directly.

## When

- Monday to Friday only, never on weekends.
- The report day is the **previous business day** in US Eastern time: Monday reports Friday,
  Tuesday to Friday report the day before.

## Steps

1. Work out the report day: today's date in `America/New_York`; on Monday go back 3 days,
   otherwise 1 day. If today is Saturday or Sunday, stop and send nothing.
2. Take `daily-report/meetings_daily.sql`, replace `@report_day` with `DATE 'YYYY-MM-DD'`, drop the
   comment lines, and run it with the BigQuery connector (`execute_sql_readonly`,
   project `production-275007`). The row where `ae` is NULL is the total; the other rows are per AE.
3. Send the message below to the Slack recipient (now: a DM to Einav, Slack user `U0C002S4160`).
   Percentages are rounded to whole numbers. List AEs in the order the query returns them. If
   `planned` is 0, send one line: "No external AE meetings on <day>."

```
📅 **AE meetings: <Weekday, Mon D>**

**Planned: <planned>**
✅ Attended: <attended>
🔁 Rescheduled: <rescheduled>
🚫 Canceled: <canceled>
👻 No-show: <no_show>
❔ No outcome logged yet: <not_logged>

**Show rate: <show_rate>%** (<attended> attended ÷ <date_passed> meetings whose date passed)
**No-show rate: <no_show_rate>%** (<no_show> no-show + <canceled> canceled ÷ <date_passed>)

**By AE** (attended / date passed · not logged)
• <AE>: <attended>/<date_passed> (<show_rate>%) · <not_logged> not logged

_Show rate = Meeting attended ÷ Meeting date passed. Meetings with no outcome logged stay in the base, so they count as not attended until a rep logs them. Rescheduled meetings are left out of the base. Source: Beacon (HubSpot meetings), external AE meetings only._
```

## Definitions (same as the Anchor Marketing Report)

- **Planned:** external meetings owned by an AE (Sean, Iain, Tal, Jaime, Kit) that started on the
  report day. Zoom-integration copies, meetings with no contact outside sayanchor.com, and interviews
  are left out; duplicate records of one meeting count once.
- **Meeting date passed** = Attended + No-show + Canceled + Outcome not logged. Rescheduled is left out.
- **Show rate** = Attended ÷ Meeting date passed.
- **No-show rate** = (No-show + Canceled) ÷ Meeting date passed.
- **Not logged:** outcome blank or still "Scheduled". Counts as not attended until a rep logs it.
