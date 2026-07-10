#!/usr/bin/env python3
import json
import os
import subprocess
import time

ACCOUNT = "julia.joy.jennings@gmail.com"
TODAY = "2026-07-09"
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
    succeeded = []
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
            succeeded.extend(chunk)
        except Exception as exc:
            ERRORS.append({"stage": stage, "message": "batch failed; tried messages independently: " + str(exc)[:100]})
            for mid in chunk:
                try:
                    gws(["users", "messages", "modify"], {"userId": "me", "id": mid}, {
                        "addLabelIds": add, "removeLabelIds": remove,
                    })
                    succeeded.append(mid)
                except Exception as inner:
                    ERRORS.append({"stage": stage, "messageId": mid, "message": str(inner)[:160]})
    return succeeded


required = [
    "OpenClaw/Urgent", "OpenClaw/Action", "OpenClaw/FYI",
    "OpenClaw/Financial", "OpenClaw/Shopping",
    "OpenClaw/Newsletters", "OpenClaw/Social",
]

# Ensure all primary labels and build their IDs.
labels_data = gws(["users", "labels", "list"], {"userId": "me"})
label_map = {x.get("name"): x.get("id") for x in labels_data.get("labels", [])}
for name in required:
    if not label_map.get(name):
        made = gws(["users", "labels", "create"], {"userId": "me"}, {
            "name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show",
        })
        label_map[name] = made.get("id")
primary_ids = [label_map[x] for x in required]

# The promotion and unread result sets were fully paginated and snapshotted,
# and all 29 unread messages were fetched in full before this mutation pass.
collected = json.load(open("tmp/julia_collect_20260709.json"))
snapshot = [x["id"] for x in collected["unread"]]
draft_threads = {
    (x.get("message") or {}).get("threadId")
    for x in collected["drafts"]
    if (x.get("message") or {}).get("threadId")
}
full_by_id = {
    x["message"]["id"]: x["message"]
    for x in collected["full"] if x.get("ok")
}
for mid in ("19f22c6173725c36", "19f4522f19698f63", "19f43c405cfd4552"):
    full_by_id[mid] = json.load(open(f"tmp/msg_{mid}_20260709.json"))

classes = {
    "OpenClaw/Urgent": [
        "19f3ece52d4decdd", "19f3a06a2a0638d7", "19f37807ec7978c2",
        "19f34c10e273e93f", "19f287e45f40d0ce", "19f25448aa5e0cd8",
        "19f2543c03a30ea5",
    ],
    "OpenClaw/Action": ["19f22c6173725c36"],
    "OpenClaw/FYI": [],
    "OpenClaw/Financial": [
        "19f442cd4ac82bfd", "19f417d2227ac47b", "19f389cc9433ed1f",
    ],
    "OpenClaw/Shopping": [
        "19f2a1bb930ca236", "19f43597ee5add2e", "19f432797b1b54ad",
        "19f419f00f2fe46e", "19f41783c20c8966",
    ],
    "OpenClaw/Newsletters": [
        "19f458c94591148c", "19f4522f19698f63", "19f44397b496053d",
        "19f43efbfc7e1ce7", "19f43c405cfd4552", "19f4368731aec54e",
        "19f4356a4dbd9fdd", "19f42d42a318c7ab", "19f423e02eda84d0",
        "19f423cb64112e56", "19f420ce344ec4b7", "19f41e333250eabb",
    ],
    "OpenClaw/Social": ["19f4209e0c3907f3"],
}

keep_unread = {
    "19f2a1bb930ca236", "19f22c6173725c36", "19f3ece52d4decdd",
    "19f3a06a2a0638d7", "19f389cc9433ed1f", "19f37807ec7978c2",
    "19f34c10e273e93f", "19f287e45f40d0ce", "19f25448aa5e0cd8",
    "19f2543c03a30ea5",
}

planned = set().union(*(set(v) for v in classes.values()))
for mid in snapshot:
    if mid not in planned:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "No confident classification; left unread"})
for mid in planned:
    if mid not in snapshot:
        ERRORS.append({"stage": "classification", "messageId": mid, "message": "Message absent from unread snapshot"})
for mid in snapshot:
    if mid not in full_by_id:
        ERRORS.append({"stage": "fetch", "messageId": mid, "message": "Full message unavailable; left unread"})

# None of the Action items is a reply request. The treatment-plan email needs a
# medical review in the provider workflow, so no reply thread or draft is made.
successful = set()
marked_read_ids = set()
for name, ids in classes.items():
    current = [mid for mid in ids if mid in snapshot and mid in full_by_id]
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

# No message was downgraded from OpenClaw/Urgent today, so no automation star
# is removed. Existing user stars are otherwise preserved.

attention_specs = {
    "19f2a1bb930ca236": ("Review the delivered refill's possibly changed dose concentration and refrigerate the medication.", "Upon receipt"),
    "19f22c6173725c36": ("Review the doctor's updated treatment plan for any dosing-schedule changes.", ""),
    "19f3ece52d4decdd": ("Confirm the Find My sound played on Julia's iPhone was expected.", ""),
    "19f3a06a2a0638d7": ("Confirm the Peacock sign-in from Hyde Park was authorized and secure the account if not.", ""),
    "19f389cc9433ed1f": ("Check the TreasuryDirect Investor InBox for the important account message.", ""),
    "19f37807ec7978c2": ("Confirm the Shareworks phone-number change was authorized.", ""),
    "19f34c10e273e93f": ("Confirm the Peacock sign-in from Atlanta was authorized and secure the account if not.", ""),
    "19f287e45f40d0ce": ("Review passwords Google says appeared in a data breach and change affected credentials.", ""),
    "19f25448aa5e0cd8": ("Confirm the alternate-login access to the T. Rowe Price account was authorized.", ""),
    "19f2543c03a30ea5": ("T. Rowe Price says account access was suspended; review and reset the password if needed.", ""),
}
attention = []
for mid, (reason, deadline) in attention_specs.items():
    if mid not in snapshot or mid not in full_by_id:
        continue
    msg = full_by_id[mid]
    h = headers(msg)
    attention.append({
        "messageId": mid, "threadId": msg.get("threadId", ""),
        "from": h.get("from", ""), "subject": h.get("subject", ""),
        "reason": reason, "deadline": deadline, "draftStatus": "none",
    })

# Archive stale read inbox mail after snapshotting the complete result set.
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
