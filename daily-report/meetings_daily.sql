-- Daily AE meetings report (Beacon / BigQuery project production-275007).
-- Replace @report_day with the day to report on, e.g. DATE '2026-11-13' (US Eastern time).
--
-- Scope: external meetings owned by an AE (Sean, Iain, Tal, Jaime, Kit), the same
-- meetings the meeting-held check scores. Left out: Zoom-integration copies
-- (hs_meeting_source = INTEGRATION: support sessions, internal calls), meetings with no
-- contact outside sayanchor.com, and recruiting interviews. Duplicate records of the same
-- meeting (a shared contact and a start within 15 minutes) count once, keeping the record
-- that has an outcome.
--
-- Definitions (same as the Anchor Marketing Report):
--   Meeting date passed = Attended + No-show + Canceled + Outcome not logged
--                         (Rescheduled is left out of the base)
--   Show rate           = Attended / Meeting date passed. Meetings with no outcome logged
--                         stay in the base, so they count as not attended until a rep logs them.
--   No-show rate        = (No-show + Canceled) / Meeting date passed
WITH m AS (
  SELECT
    m.engagement_id AS id,
    o.first_name AS ae,
    m.property_hs_meeting_start_time AS st,
    UPPER(COALESCE(m.property_hs_meeting_outcome, '')) AS outcome
  FROM `production-275007.hubspot.engagement_meeting` m
  JOIN `production-275007.hubspot.owner` o
    ON CAST(o.owner_id AS STRING) = CAST(m.property_hubspot_owner_id AS STRING)
  WHERE NOT COALESCE(m._fivetran_deleted, FALSE)
    AND DATE(m.property_hs_meeting_start_time, 'America/New_York') = @report_day
    AND LOWER(o.email) IN ('sean@sayanchor.com', 'iain@sayanchor.com', 'tal@sayanchor.com',
                           'jaime@sayanchor.com', 'kit@sayanchor.com')
    AND COALESCE(m.property_hs_meeting_source, '') != 'INTEGRATION'
    AND NOT REGEXP_CONTAINS(LOWER(COALESCE(m.property_hs_meeting_title, '')), r'interview')
),
mc AS (  -- external contacts on each meeting
  SELECT DISTINCT m.id, LOWER(c.property_email) AS email
  FROM m
  JOIN `production-275007.hubspot.engagement_contact` ec ON ec.engagement_id = m.id
  JOIN `production-275007.hubspot.contact` c ON c.id = ec.contact_id
  WHERE c.property_email IS NOT NULL AND NOT ENDS_WITH(LOWER(c.property_email), '@sayanchor.com')
),
ext AS (
  SELECT m.*,
    CASE WHEN outcome IN ('COMPLETED', 'NO_SHOW', 'CANCELED', 'RESCHEDULED') THEN 0 ELSE 1 END AS unlogged_rank
  FROM m WHERE id IN (SELECT id FROM mc)
),
dupes AS (  -- a record is a duplicate when a better-ranked record shares a contact and starts within 15 min
  SELECT DISTINCT a.id
  FROM ext a JOIN mc ca ON ca.id = a.id
  JOIN mc cb ON cb.email = ca.email AND cb.id != a.id
  JOIN ext b ON b.id = cb.id
  WHERE ABS(TIMESTAMP_DIFF(a.st, b.st, MINUTE)) <= 15
    AND (b.unlogged_rank < a.unlogged_rank OR (b.unlogged_rank = a.unlogged_rank AND b.id < a.id))
),
mtg AS (
  SELECT ae,
    CASE outcome
      WHEN 'COMPLETED' THEN 'attended' WHEN 'NO_SHOW' THEN 'no_show'
      WHEN 'CANCELED' THEN 'canceled' WHEN 'RESCHEDULED' THEN 'rescheduled'
      ELSE 'not_logged' END AS status
  FROM ext WHERE id NOT IN (SELECT id FROM dupes)
)
SELECT
  ae,  -- NULL on the ROLLUP row = all AEs (the total)
  COUNT(*) AS planned,
  COUNTIF(status = 'attended') AS attended,
  COUNTIF(status = 'rescheduled') AS rescheduled,
  COUNTIF(status = 'canceled') AS canceled,
  COUNTIF(status = 'no_show') AS no_show,
  COUNTIF(status = 'not_logged') AS not_logged,
  COUNTIF(status != 'rescheduled') AS date_passed,
  SAFE_DIVIDE(COUNTIF(status = 'attended'), COUNTIF(status != 'rescheduled')) AS show_rate,
  SAFE_DIVIDE(COUNTIF(status IN ('no_show', 'canceled')), COUNTIF(status != 'rescheduled')) AS no_show_rate
FROM mtg
GROUP BY ROLLUP(ae)
ORDER BY ae IS NULL DESC, attended DESC, planned DESC;
