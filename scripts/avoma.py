#!/usr/bin/env python3
"""Read-only Avoma API helper for the Anchor meeting held check.

The API key is read from the AVOMA_API_KEY environment variable (set in the
Claude app's environment variables for the Anchor folder), falling back to the
macOS Keychain (service "avoma-api-key"). It never appears in the skill, in
arguments or in output. Only GET requests to
allow-listed paths are sent.

Usage:
  avoma.py check
  avoma.py meetings --from 2026-10-26T00:00:00Z --to 2026-11-02T00:00:00Z [--attendees a@x.com,b@y.com]
  avoma.py meeting <meeting_uuid>
  avoma.py transcript <meeting_uuid>
  avoma.py recording <meeting_uuid>
  avoma.py notes <meeting_uuid> --from ... --to ...
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.avoma.com"
KEYCHAIN_SERVICE = "avoma-api-key"
ALLOWED_PREFIXES = ("/v1/meetings/", "/v1/transcriptions/", "/v1/recordings/", "/v1/notes/", "/v1/users/")
RETRIES = 4


def api_key():
    if os.environ.get("AVOMA_API_KEY"):
        return os.environ["AVOMA_API_KEY"].strip()
    try:
        return subprocess.run(
            ["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-w"],
            check=True, capture_output=True, text=True,
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        sys.exit(f"Avoma key not found (AVOMA_API_KEY or Keychain service '{KEYCHAIN_SERVICE}').")


def get(path, params=None):
    if not path.startswith(ALLOWED_PREFIXES):
        sys.exit(f"Path not allowed: {path}")
    url = BASE + path
    if params:
        url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
    results, key = [], api_key()
    while url:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
        for attempt in range(RETRIES + 1):
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                # Rate limit (429) and server errors are temporary: wait and retry.
                if e.code in (429, 500, 502, 503, 504) and attempt < RETRIES:
                    wait = e.headers.get("Retry-After")
                    time.sleep(min(int(wait), 60) if wait and wait.isdigit() else 2 ** (attempt + 1))
                    continue
                sys.exit(f"Avoma API error {e.code} on {path}: {e.read()[:300].decode(errors='replace')}")
        if isinstance(data, dict) and "results" in data:
            results.extend(data["results"])
            url = data.get("next")
            if url and not url.startswith(BASE + "/v1/"):
                sys.exit("Unexpected pagination URL from Avoma.")
        else:
            return data
    return results


def main():
    p = argparse.ArgumentParser()
    p.add_argument("cmd", choices=["check", "meetings", "meeting", "transcript", "recording", "notes"])
    p.add_argument("uuid", nargs="?")
    p.add_argument("--from", dest="from_date")
    p.add_argument("--to", dest="to_date")
    p.add_argument("--attendees")
    a = p.parse_args()

    if a.cmd == "check":
        from datetime import datetime, timedelta, timezone
        now = datetime.now(timezone.utc)
        data = get("/v1/meetings/", {"from_date": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                                     "to_date": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "page_size": 10})
        print(f"OK: Avoma API reachable, {len(data)} meetings in the last 24 hours.")
        return
    if a.cmd == "meetings":
        out = get("/v1/meetings/", {"from_date": a.from_date, "to_date": a.to_date,
                                    "attendee_emails": a.attendees, "page_size": 100})
    elif a.cmd == "meeting":
        out = get(f"/v1/meetings/{a.uuid}/")
    elif a.cmd == "transcript":
        out = get("/v1/transcriptions/", {"meeting_uuid": a.uuid, "from_date": a.from_date or "2000-01-01T00:00:00Z",
                                          "to_date": a.to_date or "2100-01-01T00:00:00Z"})
    elif a.cmd == "recording":
        out = get("/v1/recordings/", {"meeting_uuid": a.uuid})
    else:
        out = get("/v1/notes/", {"meeting_uuid": a.uuid, "from_date": a.from_date, "to_date": a.to_date})
    json.dump(out, sys.stdout, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    main()
