#!/usr/bin/env python3
import json
import os
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-04"
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
    try:
        out = json.loads(p.stdout or "{}")
    except Exception:
        raise RuntimeError("invalid JSON from gws")
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
        body = {"ids": chunk, "addLabelIds": add, "removeLabelIds": remove}
        try:
            gws(["users", "messages", "batchModify"], {"userId": "me"}, body)
            ok.extend(chunk)
        except Exception:
            for mid in chunk:
                try:
                    gws(["users", "messages", "modify"], {"userId": "me", "id": mid}, {"addLabelIds": add, "removeLabelIds": remove})
                    ok.append(mid)
                except Exception as exc:
                    ERRORS.append({"stage": stage, "messageId": mid, "message": str(exc)[:160]})
    return ok


def auth_error(message):
    return {
        "schemaVersion": 1, "status": "auth_error", "date": TODAY,
        "processed": 0, "markedRead": 0, "leftUnread": 0,
        "draftsCreated": 0, "draftsExisting": 0, "archived": 0,
        "trashed": 0, "unreadAfter": [], "attention": [],
        "errors": [{"stage": "auth", "message": message}],
    }


try:
    gws(["users", "messages", "list"], {"userId": "me", "q": "is:unread in:inbox", "maxResults": 1})
except Exception as exc:
    print(json.dumps(auth_error("Gmail authentication failed"), separators=(",", ":")))
    raise SystemExit(0)

labels_data = gws(["users", "labels", "list"], {"userId": "me"})
label_map = {x.get("name"): x.get("id") for x in labels_data.get("labels", [])}
required = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI",
    "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]
for name in required:
    if not label_map.get(name):
        made = gws(["users", "labels", "create"], {"userId": "me"}, {
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"
        })
        label_map[name] = made.get("id")
primary_ids = [label_map[x] for x in required]

classes = {
    "OpenClaw/Shopping": [
        "19f2a829a49fffc6", "19f2a4a2cf0801d7", "19f2a1ec329ca781",
        "19f2a1bb930ca236", "19f29743ce875db4", "19f28e2c4b765526",
        "19f28547ada92dbd", "19f27ef1865caaca",
    ],
    "OpenClaw/Newsletters": [
        "19f295f568792f1f", "19f287e05ad08171", "19f282e96fe62894", "19f27c862ad9d792",
    ],
    "OpenClaw/Financial": ["19f2935ab26d578d", "19f27ef35081edac"],
    "OpenClaw/Social": ["19f27fbac18668ba", "19f27fbab43fda4e"],
    "OpenClaw/FYI": ["19f28457794a3bd5", "19f282e7d380bf08"],
    "OpenClaw/Action": ["19f2a40131056724", "19f22c6173725c36"],
    "OpenClaw/Urgent": ["19f287e45f40d0ce", "19f25448aa5e0cd8", "19f2543c03a30ea5"],
}
keep_unread = {
    "19f2a40131056724", "19f2a1bb930ca236", "19f287e45f40d0ce",
    "19f25448aa5e0cd8", "19f2543c03a30ea5", "19f22c6173725c36",
}

snapshot = [x["id"] for x in list_all(["users", "messages", "list"], "is:unread in:inbox")]
planned = set().union(*(set(v) for v in classes.values()))
for mid in snapshot:
    if mid not in planned:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "No confident classification; left unread"})
for mid in planned:
    if mid not in snapshot:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "Message absent from unread snapshot"})

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

attention_specs = {
    "19f2a40131056724": ("Choose 3:30 PM or 5:00 PM for Kyuri's longer spa treatment and reply; availability may change.", ""),
    "19f2a1bb930ca236": ("Medication was delivered; verify the dose concentration and refrigerate it promptly.", "Upon receipt"),
    "19f287e45f40d0ce": ("Review passwords Google says appeared in a data breach and change any affected credentials.", ""),
    "19f25448aa5e0cd8": ("Confirm the alternate-login access to the T. Rowe Price account was authorized.", ""),
    "19f2543c03a30ea5": ("T. Rowe Price says account access was suspended; review and reset the password if needed.", ""),
    "19f22c6173725c36": ("Review the doctor's updated treatment plan for any dosing-schedule changes.", ""),
}
attention = []
by_id = {m["id"]: m for m in json.load(open("tmp/julia_unread_full.json"))}
for mid, (reason, deadline) in attention_specs.items():
    if mid not in snapshot or mid not in successful:
        continue
    msg = by_id[mid]
    h = headers(msg)
    attention.append({
        "messageId": mid, "threadId": msg.get("threadId", ""),
        "from": h.get("from", ""), "subject": h.get("subject", ""),
        "reason": reason, "deadline": deadline, "draftStatus": "none",
    })

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
processed = len(snapshot)
result = {
    "schemaVersion": 1,
    "status": "partial" if ERRORS else "ok",
    "date": TODAY,
    "processed": processed,
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
