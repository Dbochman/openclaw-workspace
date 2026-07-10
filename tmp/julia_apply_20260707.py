#!/usr/bin/env python3
import json
import os
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-07"
ENV = dict(os.environ, GOOGLE_WORKSPACE_CLI_ACCOUNT=ACCOUNT)
ERRORS = []


def gws(parts, params=None, body=None, retry=True):
    params = dict(params or {})
    params.setdefault("userId", "me")
    cmd = ["gws", "gmail"] + parts + ["--params", json.dumps(params, separators=(",", ":"))]
    if body is not None:
        cmd += ["--json", json.dumps(body, separators=(",", ":"))]
    p = subprocess.run(cmd, env=ENV, text=True, capture_output=True)
    combined = ((p.stdout or "") + "\n" + (p.stderr or "")).strip()
    if p.returncode and retry and '"Failed to get token"' in combined:
        time.sleep(5)
        return gws(parts, params, body, retry=False)
    if p.returncode:
        raise RuntimeError(combined[:500] or "gws command failed")
    out = json.loads(p.stdout or "{}")
    if isinstance(out, dict) and out.get("error"):
        raise RuntimeError(str(out["error"])[:500])
    return out


def list_all(parts, q=None, key="messages"):
    items, token = [], None
    while True:
        params = {"userId": "me", "maxResults": 100}
        if q is not None:
            params["q"] = q
        if token:
            params["pageToken"] = token
        out = gws(parts, params)
        items.extend(out.get(key, []) or [])
        token = out.get("nextPageToken")
        if not token:
            return items


def get_full(mid):
    return gws(["users", "messages", "get"], {"userId": "me", "id": mid, "format": "full"})


def headers(msg):
    return {h.get("name", "").lower(): h.get("value", "") for h in msg.get("payload", {}).get("headers", []) or []}


def modify_independent(ids, add, remove, stage):
    ok = []
    for pos in range(0, len(ids), 1000):
        chunk = ids[pos:pos + 1000]
        if not chunk:
            continue
        body = {"ids": chunk}
        if add:
            body["addLabelIds"] = add
        if remove:
            body["removeLabelIds"] = remove
        try:
            gws(["users", "messages", "batchModify"], {"userId": "me"}, body)
            ok.extend(chunk)
        except Exception:
            for mid in chunk:
                try:
                    gws(["users", "messages", "modify"], {"userId": "me", "id": mid}, {
                        "addLabelIds": add, "removeLabelIds": remove,
                    })
                    ok.append(mid)
                except Exception as exc:
                    ERRORS.append({"stage": stage, "messageId": mid, "message": str(exc)[:160]})
    return ok


required = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI",
    "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]

labels_data = gws(["users", "labels", "list"], {"userId": "me"})
label_map = {x.get("name"): x.get("id") for x in labels_data.get("labels", [])}
for name in required:
    if not label_map.get(name):
        made = gws(["users", "labels", "create"], {"userId": "me"}, {
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show",
        })
        label_map[name] = made.get("id")
primary_ids = [label_map[x] for x in required]

# Every ID below was fetched in full and reviewed before this mutation pass.
classes = {
    "OpenClaw/Urgent": [
        "19f3a06a2a0638d7", "19f37807ec7978c2", "19f34c10e273e93f",
        "19f32d374b1b34c7", "19f287e45f40d0ce", "19f25448aa5e0cd8",
        "19f2543c03a30ea5",
    ],
    "OpenClaw/Action": ["19f22c6173725c36"],
    "OpenClaw/FYI": [],
    "OpenClaw/Financial": ["19f38f9a8f0e8e0c", "19f389cc9433ed1f"],
    "OpenClaw/Shopping": ["19f3a0e39da50fc5", "19f396cde06f284d", "19f2a1bb930ca236"],
    "OpenClaw/Newsletters": [
        "19f3801ad3695de5", "19f37f190892d4b6", "19f3789635e3bf73",
        "19f378949da1f36e", "19f372720c230e6c",
    ],
    "OpenClaw/Social": ["19f3c05526b3cdbf", "19f37686083619de", "19f374954003200b"],
}
keep_unread = {
    "19f3a06a2a0638d7", "19f37807ec7978c2", "19f34c10e273e93f",
    "19f32d374b1b34c7", "19f287e45f40d0ce", "19f25448aa5e0cd8",
    "19f2543c03a30ea5", "19f22c6173725c36", "19f389cc9433ed1f",
    "19f2a1bb930ca236",
}

# Snapshot the complete unread inbox immediately before changing it.
snapshot = [x["id"] for x in list_all(["users", "messages", "list"], "is:unread in:inbox")]
planned = set().union(*(set(v) for v in classes.values()))
for mid in snapshot:
    if mid not in planned:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "No confident classification; left unread"})
for mid in planned:
    if mid not in snapshot:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "Message absent from unread snapshot"})

# The full drafts list was paginated before this pass. None of today's actionable
# messages calls for an email reply; each is a click/account/medical action.
successful = set()
marked_read_ids = set()
for name, ids in classes.items():
    current = [mid for mid in ids if mid in snapshot]
    read_ids = [mid for mid in current if mid not in keep_unread]
    unread_ids = [mid for mid in current if mid in keep_unread]
    add = [label_map[name]] + (["STARRED"] if name == "OpenClaw/Urgent" else [])
    remove_primary = [lid for lid in primary_ids if lid != label_map[name]]
    if read_ids:
        ok = modify_independent(read_ids, add, remove_primary + ["UNREAD"], "classify_and_read")
        successful.update(ok)
        marked_read_ids.update(ok)
    if unread_ids:
        ok = modify_independent(unread_ids, add, remove_primary, "classify")
        successful.update(ok)

# Remove a stale automation star only when a formerly Urgent message was
# confidently downgraded. None in today's snapshot matches that condition.

attention_specs = {
    "19f3a06a2a0638d7": ("Review the new Peacock sign-in from Hyde Park and secure the account if it was not authorized.", ""),
    "19f37807ec7978c2": ("Confirm the phone-number change on the Shareworks account was authorized.", ""),
    "19f34c10e273e93f": ("Review the new Peacock sign-in from Atlanta and secure the account if it was not authorized.", ""),
    "19f32d374b1b34c7": ("Confirm today's Parkway Veterinary appointments for Potato and Coconut.", "Today at 11:00 AM"),
    "19f287e45f40d0ce": ("Review passwords Google says appeared in a data breach and change any affected credentials.", ""),
    "19f25448aa5e0cd8": ("Confirm the alternate-login access to the T. Rowe Price account was authorized.", ""),
    "19f2543c03a30ea5": ("T. Rowe Price says account access was suspended; review and reset the password if needed.", ""),
    "19f22c6173725c36": ("Review the doctor's updated treatment plan for any dosing-schedule changes.", ""),
    "19f389cc9433ed1f": ("Check the TreasuryDirect Investor InBox for the important account message.", ""),
    "19f2a1bb930ca236": ("Verify the medication dose concentration and refrigerate the delivered refill.", "Upon receipt"),
}
attention = []
full_by_id = {}
for entry in json.load(open("tmp/julia_collect_20260707.json"))["full"]:
    if entry.get("ok"):
        full_by_id[entry["message"]["id"]] = entry["message"]
for path in ("tmp/msg_19f3c055.json", "tmp/msg_19f38f9a.json"):
    if os.path.exists(path):
        message = json.load(open(path))
        full_by_id[message["id"]] = message
for mid, (reason, deadline) in attention_specs.items():
    if mid not in snapshot or mid not in successful:
        continue
    msg = full_by_id[mid]
    h = headers(msg)
    attention.append({
        "messageId": mid, "threadId": msg.get("threadId", ""),
        "from": h.get("from", ""), "subject": h.get("subject", ""),
        "reason": reason, "deadline": deadline, "draftStatus": "none",
    })

# Archive stale read inbox mail only after the read-state pass. Snapshot all IDs
# first, then fetch every candidate in full to verify attention labels.
archive_snapshot = [x["id"] for x in list_all(["users", "messages", "list"], "is:read in:inbox older_than:1d")]
archive_eligible = []
for mid in archive_snapshot:
    try:
        msg = get_full(mid)
        labs = set(msg.get("labelIds", []) or [])
        if "STARRED" in labs or label_map["OpenClaw/Urgent"] in labs or label_map["OpenClaw/Action"] in labs:
            continue
        archive_eligible.append(mid)
    except Exception as exc:
        ERRORS.append({"stage": "archive_fetch", "messageId": mid, "message": str(exc)[:160]})
archived_ids = modify_independent(archive_eligible, [], ["INBOX"], "archive")

unread_after = [x["id"] for x in list_all(["users", "messages", "list"], "is:unread in:inbox")]
result = {
    "schemaVersion": 1,
    "status": "partial" if ERRORS else "ok",
    "date": TODAY,
    "processed": len(snapshot),
    "markedRead": len(marked_read_ids),
    "leftUnread": sum(1 for mid in snapshot if mid in unread_after),
    "draftsCreated": 0,
    "draftsExisting": 0,
    "archived": len(archived_ids),
    "trashed": 0,
    "unreadAfter": unread_after,
    "attention": attention,
    "errors": ERRORS,
}
print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
