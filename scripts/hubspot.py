#!/usr/bin/env python3
"""HubSpot API helper for the Anchor meeting held check.

All HubSpot reads and writes in the skill go through this script. Every run
first checks that the key belongs to Anchor's portal. The only writes it can
make are:
  - set-outcome: HubSpot's Meeting outcome (hs_meeting_outcome) and the
    explanation (meeting_outcome__avoma_explanation) on existing meetings,
    with the outcome limited to Completed / Rescheduled / No show / Canceled
  - create-contact / create-company / create-meeting: a missing record, with a
    fixed set of properties, associated to the new meeting
  - delete-duplicate: one duplicate meeting, only after the script checks itself
    that it is a clear copy of the meeting being kept (same contacts, start
    within 15 minutes, same video link or none). A backup is saved to backups/
    first; HubSpot moves the deleted meeting to its recycling bin.

The key is read from the HUBSPOT_API_KEY environment variable (a HubSpot
private-app key for Anchor's portal), falling back to the macOS Keychain
(service "hubspot-anchor-token"). It never appears in arguments or output.

Usage (times are ISO 8601 UTC, e.g. 2026-11-01T00:00:00Z):
  hubspot.py check
  hubspot.py aes --team "Sales (AE)" [--extra kit@sayanchor.com,...]
  hubspot.py meetings --from T --to T [--owners id,id] [--contact ID]
  hubspot.py assoc --ids id,id --to contacts|companies|deals
  hubspot.py contacts --ids id,id
  hubspot.py find-contact --email x@y.com
  hubspot.py find-company --domain y.com
  hubspot.py activity --since T [--contact ID] [--company ID]
  hubspot.py set-outcome --json '[{"id": "...", "outcome": "NO_SHOW", "explanation": "..."}]'
  hubspot.py create-contact --email x@y.com --owner ID [--first F] [--last L]
  hubspot.py create-company --domain y.com --owner ID [--name N]
  hubspot.py create-meeting --owner ID --title T --start T --end T [--contacts id,id] [--companies id,id]
  hubspot.py delete-duplicate <copy_meeting_id> --keep <kept_meeting_id>
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://api.hubapi.com"
PORTAL_ID = 8391286
KEYCHAIN_SERVICE = "hubspot-anchor-token"
TOLERANCE_MINUTES = 15
RETRIES = 4
OUTCOMES = {"COMPLETED", "RESCHEDULED", "NO_SHOW", "CANCELED"}
EXPLANATION = "meeting_outcome__avoma_explanation"
MEETING_PROPS = ["hs_meeting_title", "hs_meeting_start_time", "hs_meeting_end_time", "hubspot_owner_id",
                 "hs_meeting_outcome", "hs_meeting_source", "hs_object_source_detail_1", "hs_video_conference_url",
                 "hs_internal_meeting_notes", "hs_createdate", "hs_activity_type", EXPLANATION]
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")
_key = None


def token():
    global _key
    if _key:
        return _key
    if os.environ.get("HUBSPOT_API_KEY"):
        _key = os.environ["HUBSPOT_API_KEY"].strip()
        return _key
    try:
        _key = subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
        return _key
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit(f"HubSpot key not found (HUBSPOT_API_KEY or Keychain service '{KEYCHAIN_SERVICE}').")


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Authorization": f"Bearer {token()}", "Accept": "application/json",
                                          "Content-Type": "application/json"})
    for attempt in range(RETRIES + 1):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            # Rate limit (429) and server errors are temporary: wait and retry.
            if e.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                wait = e.headers.get("Retry-After")
                time.sleep(min(int(wait), 60) if wait and wait.isdigit() else 2 ** (attempt + 1))
                continue
            if e.code == 404 and method == "GET":
                return None
            sys.exit(f"HubSpot API error {e.code} on {method} {path}: {e.read()[:400].decode(errors='replace')}")


def check_portal():
    info = call("GET", "/account-info/v3/details")
    if not info or info.get("portalId") != PORTAL_ID:
        sys.exit(f"HubSpot key is not for Anchor's portal {PORTAL_ID} (got {info and info.get('portalId')}).")


def ids(arg):
    out = [i.strip() for i in (arg or "").split(",") if i.strip()]
    if not all(i.isdigit() for i in out):
        sys.exit("IDs must be numbers, separated by commas.")
    return out


def search(object_type, filters, properties, sorts=None):
    """CRM search with paging (HubSpot returns at most 200 per page and 10,000 in total)."""
    results, after = [], None
    while True:
        body = {"filterGroups": [{"filters": filters}], "properties": properties, "limit": 200}
        if sorts:
            body["sorts"] = sorts
        if after:
            body["after"] = after
        page = call("POST", f"/crm/v3/objects/{object_type}/search", body)
        results += [{"id": r["id"], **r["properties"]} for r in page.get("results", [])]
        after = page.get("paging", {}).get("next", {}).get("after")
        if not after:
            return results


def out(data):
    json.dump(data, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    print()


# ---------- reads ----------

def cmd_aes(team, extra):
    teams = call("GET", "/settings/v3/users/teams").get("results", [])
    match = [t for t in teams if t.get("name", "").strip().lower() == team.strip().lower()]
    if not match:
        sys.exit(f"Team '{team}' not found. Teams: {', '.join(t.get('name', '') for t in teams)}")
    user_ids = {str(u) for t in match for u in (t.get("userIds", []) + t.get("secondaryUserIds", []))}
    owners, after = [], None
    while True:
        page = call("GET", "/crm/v3/owners?limit=500&archived=false" + (f"&after={after}" if after else ""))
        owners += page.get("results", [])
        after = page.get("paging", {}).get("next", {}).get("after")
        if not after:
            break
    extra_emails = {e.strip().lower() for e in (extra or "").split(",") if e.strip()}
    aes, seen = [], set()
    for o in owners:
        email = (o.get("email") or "").lower()
        if (str(o.get("userId")) in user_ids or email in extra_emails) and email not in seen:
            seen.add(email)
            aes.append({"email": email, "owner_id": o["id"],
                        "name": f"{o.get('firstName', '')} {o.get('lastName', '')}".strip()})
    out(aes)


def cmd_meetings(start, end, owners, contact):
    filters = [{"propertyName": "hs_meeting_start_time", "operator": "BETWEEN", "value": start, "highValue": end}]
    if owners:
        filters.append({"propertyName": "hubspot_owner_id", "operator": "IN", "values": ids(owners)})
    if contact:
        filters.append({"propertyName": "associations.contact", "operator": "EQ", "value": ids(contact)[0]})
    out(search("meetings", filters, MEETING_PROPS, [{"propertyName": "hs_meeting_start_time", "direction": "ASCENDING"}]))


def cmd_assoc(meeting_ids, to):
    if to not in ("contacts", "companies", "deals"):
        sys.exit("--to must be contacts, companies or deals.")
    result = {}
    mids = ids(meeting_ids)
    for i in range(0, len(mids), 100):
        page = call("POST", f"/crm/v4/associations/meetings/{to}/batch/read",
                    {"inputs": [{"id": m} for m in mids[i:i + 100]]})
        for r in page.get("results", []):
            result[str(r["from"]["id"])] = [str(t["toObjectId"]) for t in r.get("to", [])]
    out({m: result.get(m, []) for m in mids})


def cmd_contacts(contact_ids):
    cids, rows = ids(contact_ids), []
    for i in range(0, len(cids), 100):
        page = call("POST", "/crm/v3/objects/contacts/batch/read",
                    {"inputs": [{"id": c} for c in cids[i:i + 100]], "properties": ["email", "firstname", "lastname"]})
        rows += [{"id": r["id"], **r["properties"]} for r in page.get("results", [])]
    out(rows)


def cmd_find_contact(email):
    out(search("contacts", [{"propertyName": "email", "operator": "EQ", "value": email.strip().lower()}],
               ["email", "firstname", "lastname", "hubspot_owner_id"]))


def cmd_find_company(domain):
    out(search("companies", [{"propertyName": "domain", "operator": "EQ", "value": domain.strip().lower()}],
               ["domain", "name", "hubspot_owner_id"]))


def cmd_activity(since, contact, company):
    """Emails, notes, calls and deals on a contact and/or company since a time, newest first."""
    if not (contact or company):
        sys.exit("Give --contact and/or --company.")
    specs = {
        "emails": (["hs_timestamp", "hs_email_subject", "hs_email_text", "hs_email_direction",
                    "hs_email_from_email", "hs_email_to_email", "hubspot_owner_id"], "hs_timestamp"),
        "notes": (["hs_timestamp", "hs_note_body", "hubspot_owner_id"], "hs_timestamp"),
        "calls": (["hs_timestamp", "hs_call_title", "hs_call_body", "hs_call_duration", "hs_call_disposition",
                   "hubspot_owner_id"], "hs_timestamp"),
        "deals": (["dealname", "dealstage", "createdate", "hs_lastmodifieddate", "hubspot_owner_id"],
                  "hs_lastmodifieddate"),
    }
    result = {}
    for obj, (props, time_prop) in specs.items():
        rows = []
        for assoc, oid in (("contact", contact), ("company", company)):
            if oid:
                rows += search(obj, [{"propertyName": f"associations.{assoc}", "operator": "EQ", "value": ids(oid)[0]},
                                     {"propertyName": time_prop, "operator": "GTE", "value": since}],
                               props, [{"propertyName": time_prop, "direction": "DESCENDING"}])
        unique = {r["id"]: r for r in rows}.values()
        for r in unique:
            for long_field in ("hs_email_text", "hs_note_body", "hs_call_body"):
                if r.get(long_field):
                    r[long_field] = r[long_field][:600]
        result[obj] = list(unique)
    out(result)


# ---------- writes ----------

def cmd_set_outcome(raw):
    try:
        items = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit("--json must be a JSON list.")
    if not isinstance(items, list) or not items:
        sys.exit("--json must be a non-empty list.")
    inputs = []
    for it in items:
        mid, outcome, why = str(it.get("id", "")), it.get("outcome"), (it.get("explanation") or "").strip()
        if not mid.isdigit() or outcome not in OUTCOMES or not why or set(it) - {"id", "outcome", "explanation"}:
            sys.exit(f"Invalid item {it}: needs id, outcome ({', '.join(sorted(OUTCOMES))}) and explanation only.")
        inputs.append({"id": mid, "properties": {"hs_meeting_outcome": outcome, EXPLANATION: why[:1000]}})
    for i in range(0, len(inputs), 100):
        call("POST", "/crm/v3/objects/meetings/batch/update", {"inputs": inputs[i:i + 100]})
    # Read back and confirm both values were saved.
    check = call("POST", "/crm/v3/objects/meetings/batch/read",
                 {"inputs": [{"id": x["id"]} for x in inputs], "properties": ["hs_meeting_outcome", EXPLANATION]})
    saved = {r["id"]: r["properties"] for r in check.get("results", [])}
    bad = [x["id"] for x in inputs
           if saved.get(x["id"], {}).get("hs_meeting_outcome") != x["properties"]["hs_meeting_outcome"]
           or saved.get(x["id"], {}).get(EXPLANATION) != x["properties"][EXPLANATION]]
    out({"updated": len(inputs) - len(bad), "not_saved": bad})
    if bad:
        sys.exit(1)


def create(object_type, properties):
    return call("POST", f"/crm/v3/objects/{object_type}", {"properties": properties})["id"]


def cmd_create_contact(email, owner, first, last):
    props = {"email": email.strip().lower(), "hubspot_owner_id": ids(owner)[0]}
    if first:
        props["firstname"] = first
    if last:
        props["lastname"] = last
    out({"contact_id": create("contacts", props)})


def cmd_create_company(domain, owner, name):
    props = {"domain": domain.strip().lower(), "hubspot_owner_id": ids(owner)[0], "name": name or domain}
    out({"company_id": create("companies", props)})


def cmd_create_meeting(owner, title, start, end, contacts, companies):
    mid = create("meetings", {"hs_timestamp": start, "hs_meeting_title": title, "hs_meeting_start_time": start,
                              "hs_meeting_end_time": end, "hubspot_owner_id": ids(owner)[0]})
    for kind, oids in (("contacts", ids(contacts)), ("companies", ids(companies))):
        for oid in oids:
            call("PUT", f"/crm/v4/objects/meetings/{mid}/associations/default/{kind}/{oid}")
    out({"meeting_id": mid})


def meeting_record(mid):
    rec = call("GET", f"/crm/v3/objects/meetings/{mid}?properties={','.join(MEETING_PROPS)}"
                      "&associations=contacts,companies,deals")
    if not rec:
        sys.exit(f"Meeting {mid} not found.")
    return rec


def cmd_delete_duplicate(copy_id, keep_id):
    if copy_id == keep_id:
        sys.exit("The copy and the kept meeting are the same record.")
    copy, keep = meeting_record(copy_id), meeting_record(keep_id)
    start = lambda r: datetime.fromisoformat(r["properties"]["hs_meeting_start_time"].replace("Z", "+00:00"))
    contacts = lambda r: {a["id"] for a in r.get("associations", {}).get("contacts", {}).get("results", [])}
    url = lambda r: (r["properties"].get("hs_video_conference_url") or "").split("?")[0]
    problems = []
    if abs((start(copy) - start(keep)).total_seconds()) > TOLERANCE_MINUTES * 60:
        problems.append("start times differ by more than 15 minutes")
    if not contacts(copy):
        problems.append("the copy has no contacts")
    elif contacts(copy) != contacts(keep):
        problems.append("the contacts differ")
    if url(copy) and url(keep) and url(copy) != url(keep):
        problems.append("the video links differ")
    if problems:
        sys.exit(f"Not deleted: {copy_id} is not a clear copy of {keep_id} ({'; '.join(problems)}).")

    os.makedirs(BACKUP_DIR, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = os.path.join(BACKUP_DIR, f"meeting-{copy_id}-{stamp}.json")
    with open(path, "w") as f:
        json.dump({"deleted": copy, "kept_meeting_id": keep_id, "deleted_at": stamp}, f, ensure_ascii=False, indent=1)
    call("DELETE", f"/crm/v3/objects/meetings/{copy_id}")
    if call("GET", f"/crm/v3/objects/meetings/{copy_id}"):
        sys.exit(f"Delete of {copy_id} did not take effect.")
    # The full record is also printed, so the backup survives in the run log on machines that
    # are wiped after each run (cloud routines).
    out({"deleted": copy_id, "kept": keep_id, "backup": f"backups/{os.path.basename(path)}", "backup_record": copy})


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["check", "aes", "meetings", "assoc", "contacts", "find-contact", "find-company",
                                   "activity", "set-outcome", "create-contact", "create-company", "create-meeting",
                                   "delete-duplicate"])
    p.add_argument("meeting_id", nargs="?")
    for flag in ("team", "extra", "from", "to", "owners", "contact", "ids", "email", "domain", "since", "company",
                 "json", "owner", "first", "last", "name", "title", "start", "end", "contacts", "companies", "keep"):
        p.add_argument(f"--{flag}", dest=flag.replace("-", "_") if flag != "from" else "start_from")
    a = p.parse_args()
    check_portal()
    c = a.cmd
    if c == "check":
        print(f"OK: HubSpot key works for Anchor's portal {PORTAL_ID}.")
    elif c == "aes":
        cmd_aes(a.team or "Sales (AE)", a.extra)
    elif c == "meetings":
        if not (a.start_from and a.to):
            sys.exit("meetings needs --from and --to.")
        cmd_meetings(a.start_from, a.to, a.owners, a.contact)
    elif c == "assoc":
        cmd_assoc(a.ids, a.to)
    elif c == "contacts":
        cmd_contacts(a.ids)
    elif c == "find-contact":
        cmd_find_contact(a.email or sys.exit("--email is required."))
    elif c == "find-company":
        cmd_find_company(a.domain or sys.exit("--domain is required."))
    elif c == "activity":
        cmd_activity(a.since or sys.exit("--since is required."), a.contact, a.company)
    elif c == "set-outcome":
        cmd_set_outcome(a.json or sys.exit("--json is required."))
    elif c == "create-contact":
        cmd_create_contact(a.email or sys.exit("--email is required."), a.owner, a.first, a.last)
    elif c == "create-company":
        cmd_create_company(a.domain or sys.exit("--domain is required."), a.owner, a.name)
    elif c == "create-meeting":
        if not all((a.owner, a.title, a.start, a.end)):
            sys.exit("create-meeting needs --owner, --title, --start and --end.")
        cmd_create_meeting(a.owner, a.title, a.start, a.end, a.contacts, a.companies)
    else:
        if not (a.meeting_id and a.keep and a.meeting_id.isdigit() and a.keep.isdigit()):
            sys.exit("Usage: hubspot.py delete-duplicate <copy_meeting_id> --keep <kept_meeting_id>")
        cmd_delete_duplicate(a.meeting_id, a.keep)


if __name__ == "__main__":
    main()
