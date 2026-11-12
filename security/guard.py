#!/usr/bin/env python3
"""PreToolUse guard for the Anchor meeting held check.

Claude Code runs this before every tool call (see security/settings.json).
It reads the call from stdin and denies anything that policy.json doesn't
allow: no deletes, no writes outside the two meeting properties and the
Step 2 creates, no other connectors, no file edits, no web access.
"""
import json
import os
import re
import shlex
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
with open(os.path.join(HERE, "policy.json")) as f:
    POLICY = json.load(f)


def deny(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": f"Blocked by the Anchor meeting check security layer: {reason}",
    }}))
    sys.exit(0)


def allow():
    sys.exit(0)  # no output: normal permission flow continues


def canonical_type(t):
    t = str(t or "").strip().lower()
    for name, aliases in POLICY["object_type_aliases"].items():
        if t in aliases:
            return name
    return None


def check_hubspot_write(inp):
    extra = set(inp) - {"createRequest", "updateRequest", "confirmationStatus"}
    if extra:
        deny(f"unexpected fields {sorted(extra)}")
    for obj in (inp.get("createRequest") or {}).get("objects", []):
        kind = canonical_type(obj.get("objectType"))
        if kind not in POLICY["hubspot_create"]:
            deny(f"creating '{obj.get('objectType')}' isn't allowed")
        bad = set(obj.get("properties") or {}) - set(POLICY["hubspot_create"][kind])
        if bad:
            deny(f"creating {kind} with properties {sorted(bad)} isn't allowed")
        check_status_value(obj.get("properties") or {})
        for a in obj.get("associations") or []:
            if canonical_type(a.get("targetObjectType")) not in POLICY["hubspot_create_association_targets"]:
                deny(f"association to '{a.get('targetObjectType')}' isn't allowed")
    for obj in (inp.get("updateRequest") or {}).get("objects", []):
        kind = canonical_type(obj.get("objectType"))
        if kind not in POLICY["hubspot_update"]:
            deny(f"updating '{obj.get('objectType')}' isn't allowed (only meetings)")
        props = obj.get("properties") or {}
        if not props:
            deny("updates without properties (association-only) aren't allowed")
        bad = set(props) - set(POLICY["hubspot_update"][kind])
        if bad:
            deny(f"updating meeting properties {sorted(bad)} isn't allowed")
        if obj.get("associations"):
            deny("changing associations on an update isn't allowed")
        check_status_value(props)
    allow()


def check_status_value(props):
    key = POLICY["status_property"]
    if key in props and props[key] not in POLICY["status_values"]:
        deny(f"'{props[key]}' isn't a valid value for {key}")


def check_bash(cmd):
    if re.search(r"[`>]|\$\(|<\(|\bsudo\b", cmd):
        deny("command substitution, redirection and sudo aren't allowed")
    try:
        lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=";&|")
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        deny("couldn't parse the command")
    segments, current = [], []
    for tok in tokens:
        if tok and set(tok) <= set(";&|"):
            if tok not in (";", "|", "||", "&&"):
                deny(f"operator '{tok}' isn't allowed")
            segments.append(current)
            current = []
        else:
            current.append(tok)
    segments.append(current)
    for words in segments:
        if not words:
            continue
        if words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            deny("setting environment variables isn't allowed")
        if words and words[0] == "cd" and len(words) <= 2:
            continue
        name = os.path.basename(words[0]) if words else ""
        if name in POLICY["bash_commands_allowed"]:
            continue
        if name in ("python3", "python") and len(words) >= 2:
            allowed = {os.path.realpath(os.path.join(SKILL_DIR, s)) for s in POLICY["bash_python_scripts_allowed"]}
            if os.path.realpath(os.path.join(call_cwd, words[1])) in allowed:
                continue
        deny(f"shell command '{name}' isn't allowed")
    allow()


call_cwd = os.getcwd()


def main():
    global call_cwd
    call = json.load(sys.stdin)
    call_cwd = call.get("cwd") or call_cwd
    tool = call.get("tool_name", "")
    inp = call.get("tool_input") or {}

    if tool in POLICY["builtin_tools_allowed"]:
        allow()
    if tool == "Bash":
        check_bash(inp.get("command", ""))
    if tool.startswith("mcp__"):
        if any(tool.startswith(p) for p in POLICY["mcp_tool_prefixes_allowed"]):
            allow()
        short = tool.split("__", 2)[-1]
        if short in POLICY["calendar_read_tools"] or short in POLICY["hubspot_read_tools"]:
            allow()
        if short == POLICY["hubspot_write_tool"]:
            check_hubspot_write(inp)
    deny(f"the tool '{tool}' isn't on the allowed list")


if __name__ == "__main__":
    main()
