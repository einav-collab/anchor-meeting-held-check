#!/usr/bin/env python3
"""Turns on guard.py for the scheduled cloud run only.

The repo's .claude/settings.json runs this before every tool call in every
session on this repo. A session whose opening prompt contains ROUTINE_MARKER
(the scheduled task's prompt does) gets the full guard: every call is checked
by guard.py against policy.json. Any other session, such as one opened to
maintain the skill, is left alone.

If the session's transcript can't be read, the guard is applied anyway, so
the routine can never run unguarded by mistake.
"""
import json
import os
import subprocess
import sys

ROUTINE_MARKER = "[anchor-meeting-check-routine]"
GUARD = os.path.join(os.path.dirname(os.path.abspath(__file__)), "guard.py")
SCAN_LINES = 300


def opening_prompt(path):
    """Text of the first real user message, or None if it can't be found."""
    with open(path, encoding="utf-8") as f:
        for i, line in enumerate(f):
            if i >= SCAN_LINES:
                return None
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if entry.get("type") != "user" or entry.get("isMeta"):
                continue
            content = (entry.get("message") or {}).get("content")
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text = "\n".join(b.get("text", "") for b in content
                                 if isinstance(b, dict) and b.get("type") == "text")
            else:
                text = ""
            if text.strip():
                return text
    return None


def main():
    raw = sys.stdin.read()
    try:
        prompt = opening_prompt(json.loads(raw).get("transcript_path") or "")
    except Exception:
        prompt = None
    if prompt is not None and ROUTINE_MARKER not in prompt:
        sys.exit(0)  # not the routine: normal permission flow
    result = subprocess.run([sys.executable, GUARD], input=raw, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
